/**
 * Cloudflare Worker: commentary proxy for the GitHub Pages portfolio site.
 *
 * The browser sends only the computed figures (the same payload as build_context() in
 * src/commentary.py) plus the audience, length, language and optional manager notes.
 * The worker validates them, rebuilds the prompt server-side, calls the Claude API with
 * the key stored as a Worker secret, and streams plain text back.
 *
 * Settings (Workers > your worker > Settings > Variables and Secrets):
 *   ANTHROPIC_API_KEY  secret, required
 *   ALLOWED_ORIGINS    comma-separated, e.g. "https://fkp-codes.github.io"
 *   CLAUDE_MODEL       optional, default "claude-haiku-4-5"
 *   HOURLY_LIMIT_PER_IP optional, default 5 (best effort, per Worker instance)
 * Optional KV binding USAGE: enables a global daily cap (DAILY_LIMIT, default 100).
 */

const DEFAULT_MODEL = "claude-haiku-4-5";

// Kept in sync with SYSTEM_PROMPT in src/commentary.py (language line added for the bilingual site).
const SYSTEM_PROMPT = `Tu es gérant de portefeuille multi-actifs dans une société de gestion française.
Tu rédiges le commentaire de gestion mensuel ou périodique destiné aux clients.

Règles impératives :
- Rédige dans un style professionnel, sobre et factuel, dans le style des reportings de sociétés de gestion.
- Appuie-toi EXCLUSIVEMENT sur les données chiffrées fournies et sur le contexte éventuellement donné par le gérant.
- N'invente AUCUN événement de marché, décision de banque centrale, statistique macroéconomique
  ou chiffre absent des données.
  Si le contexte de marché n'est pas fourni, décris les mouvements observés sans leur attribuer de cause précise.
- Cite les chiffres clés avec 1 ou 2 décimales et le signe (ex. +3,42 %, -1,10 %).
- Explique la performance relative par les effets d'allocation (sur/sous-pondérations vs l'allocation stratégique)
  et par la contribution de chaque ligne.
- Ne donne aucune recommandation d'investissement personnalisée ni promesse de performance future.
- N'utilise ni emojis ni formules marketing.

Structure attendue (titres en gras Markdown, sans titre général) :
**Environnement de marché** — ce que les données disent de chaque classe d'actifs.
**Performance du portefeuille** — performance absolue et relative, volatilité, drawdown, Sharpe.
**Analyse des contributions** — lignes moteurs et détractrices, effet des écarts d'allocation.
**Positionnement et perspectives** — allocation actuelle (après dérive), points de vigilance, sans prédiction chiffrée.
`;

const LANGUAGE_GUIDE = {
  fr: "Langue de rédaction : français. Utilise la virgule décimale.",
  en: "Langue de rédaction : anglais (English), avec le point décimal. Traduis les titres de section : "
    + "**Market environment**, **Portfolio performance**, **Contribution analysis**, **Positioning and outlook**.",
};
const LENGTH_GUIDE = {
  short: "Environ 150 mots au total.",
  standard: "Environ 300 mots au total.",
  detailed: "Environ 500 mots au total.",
};
const AUDIENCE_GUIDE = {
  institutional: "Public expert : vocabulaire technique assumé (tracking error, allocation tactique).",
  private: "Public averti mais non spécialiste : explique brièvement les notions techniques.",
};

// Fixed universe: names come from here, never from the request.
const ASSETS = [
  { nom: "iShares Core S&P 500 UCITS ETF", classe_actifs: "Actions US" },
  { nom: "iShares Core EURO STOXX 50 UCITS ETF", classe_actifs: "Actions zone euro" },
  { nom: "iShares Core Euro Government Bond UCITS ETF", classe_actifs: "Obligations souveraines zone euro" },
];
const METRIC_KEYS = ["Performance cumulée", "Performance annualisée", "Volatilité annualisée", "Drawdown maximum", "Ratio de Sharpe"];
const LINE_KEYS = ["Poids initial", "Poids actuel", "Poids benchmark", "Performance", "Volatilité", "Drawdown max", "Contribution"];
const MAX_NOTES = 800;

class BadRequest extends Error {}

function num(v, where) {
  if (typeof v !== "number" || !Number.isFinite(v) || Math.abs(v) > 1e6) throw new BadRequest(`invalid number: ${where}`);
  return Math.round(v * 100) / 100;
}
function isoDate(v, where) {
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(v)) throw new BadRequest(`invalid date: ${where}`);
  return v;
}
function metrics(obj, where) {
  if (!obj || typeof obj !== "object") throw new BadRequest(`missing ${where}`);
  return Object.fromEntries(METRIC_KEYS.map((k) => [k, num(obj[k], `${where}.${k}`)]));
}

/** Rebuilds the payload from numbers only, so no free text reaches the prompt through it. */
export function sanitizePayload(p) {
  if (!p || typeof p !== "object") throw new BadRequest("missing payload");
  if (!Array.isArray(p.lignes) || p.lignes.length !== ASSETS.length) throw new BadRequest("invalid lignes");
  const monthly = p.performances_mensuelles_portefeuille || {};
  const months = Object.keys(monthly);
  if (months.length > 60) throw new BadRequest("too many months");
  return {
    periode: { debut: isoDate(p.periode?.debut, "debut"), fin: isoDate(p.periode?.fin, "fin") },
    portefeuille: metrics(p.portefeuille, "portefeuille"),
    allocation_strategique_benchmark: metrics(p.allocation_strategique_benchmark, "benchmark"),
    surperformance_relative_pts: num(p.surperformance_relative_pts, "surperformance"),
    tracking_error_annualisee: num(p.tracking_error_annualisee, "tracking_error"),
    lignes: p.lignes.map((l, i) => ({
      ...ASSETS[i],
      ...Object.fromEntries(LINE_KEYS.map((k) => [k, num(l?.[k], `lignes[${i}].${k}`)])),
    })),
    performances_mensuelles_portefeuille: Object.fromEntries(
      months.map((m) => {
        if (!/^\d{4}-\d{2}$/.test(m)) throw new BadRequest("invalid month");
        return [m, num(monthly[m], `mois ${m}`)];
      }),
    ),
    unite: "Valeurs en %, sauf ratio de Sharpe. Portefeuille buy-and-hold, dividendes réinvestis, en EUR.",
  };
}

/** Same shape as build_user_prompt() in src/commentary.py. */
export function buildUserPrompt(context, audience, length, lang, notes) {
  const n = notes.trim() || "Aucun contexte fourni : ne pas attribuer de causes externes aux mouvements.";
  return (
    `Public cible : ${AUDIENCE_GUIDE[audience]}\n` +
    `Longueur : ${LENGTH_GUIDE[length]}\n` +
    `${LANGUAGE_GUIDE[lang]}\n\n` +
    `<donnees_portefeuille>\n${JSON.stringify(context, null, 2)}\n</donnees_portefeuille>\n\n` +
    `<contexte_gerant>\n${n}\n</contexte_gerant>\n\n` +
    "Rédige le commentaire de gestion."
  );
}

export function parseRequest(body) {
  const audience = body?.audience, length = body?.length, lang = body?.lang;
  if (!(audience in AUDIENCE_GUIDE)) throw new BadRequest("invalid audience");
  if (!(length in LENGTH_GUIDE)) throw new BadRequest("invalid length");
  if (!(lang in LANGUAGE_GUIDE)) throw new BadRequest("invalid lang");
  const notes = typeof body.notes === "string" ? body.notes : "";
  if (notes.length > MAX_NOTES) throw new BadRequest("notes too long");
  return buildUserPrompt(sanitizePayload(body.payload), audience, length, lang, notes);
}

/* ------------------------------------------------------------------ rate limiting */
const hits = new Map(); // ip -> timestamps (best effort: one map per Worker instance)
function allowIp(ip, limit) {
  const now = Date.now(), hour = 3600e3;
  const list = (hits.get(ip) || []).filter((t) => now - t < hour);
  if (list.length >= limit) return { ok: false, remaining: 0 };
  list.push(now);
  hits.set(ip, list);
  if (hits.size > 5000) hits.clear();
  return { ok: true, remaining: limit - list.length };
}
async function allowGlobal(env) {
  if (!env.USAGE) return true;
  const key = "day:" + new Date().toISOString().slice(0, 10);
  const used = parseInt((await env.USAGE.get(key)) || "0", 10);
  if (used >= parseInt(env.DAILY_LIMIT || "100", 10)) return false;
  await env.USAGE.put(key, String(used + 1), { expirationTtl: 172800 });
  return true;
}

/* ------------------------------------------------------------------ HTTP */
function corsHeaders(origin, env) {
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (!origin || !allowed.includes(origin)) return null;
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Expose-Headers": "X-Remaining",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}
function json(status, obj, headers) {
  return new Response(JSON.stringify(obj), { status, headers: { ...headers, "Content-Type": "application/json" } });
}

/** Converts the Messages API SSE stream into a plain UTF-8 text stream of the commentary. */
function sseToText(body) {
  const decoder = new TextDecoder(), encoder = new TextEncoder();
  let buffer = "";
  return body.pipeThrough(new TransformStream({
    transform(chunk, controller) {
      buffer += decoder.decode(chunk, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();
      for (const ev of events) {
        const data = ev.split("\n").find((l) => l.startsWith("data:"));
        if (!data) continue;
        let msg;
        try { msg = JSON.parse(data.slice(5)); } catch { continue; }
        if (msg.type === "content_block_delta" && msg.delta?.type === "text_delta") {
          controller.enqueue(encoder.encode(msg.delta.text));
        } else if (msg.type === "error") {
          controller.enqueue(encoder.encode("\n\n[error: generation interrupted]"));
        }
      }
    },
  }));
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request.headers.get("Origin"), env);
    if (!cors) return new Response("Forbidden", { status: 403 });
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (request.method !== "POST") return json(405, { error: "method_not_allowed" }, cors);
    if (!env.ANTHROPIC_API_KEY) return json(503, { error: "not_configured" }, cors);

    let prompt;
    try {
      const raw = await request.text();
      if (raw.length > 20000) throw new BadRequest("body too large");
      prompt = parseRequest(JSON.parse(raw));
    } catch (e) {
      return json(400, { error: "bad_request", detail: e instanceof BadRequest ? e.message : "invalid JSON" }, cors);
    }

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const quota = allowIp(ip, parseInt(env.HOURLY_LIMIT_PER_IP || "5", 10));
    if (!quota.ok) return json(429, { error: "rate_limited" }, cors);
    if (!(await allowGlobal(env))) return json(429, { error: "daily_limit" }, cors);

    const upstream = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: env.CLAUDE_MODEL || DEFAULT_MODEL,
        max_tokens: 1500,
        stream: true,
        system: SYSTEM_PROMPT,
        messages: [{ role: "user", content: prompt }],
      }),
    });
    if (!upstream.ok || !upstream.body) {
      // Error type only (e.g. authentication_error): never echoes the key or the request.
      let detail = "";
      try { detail = (await upstream.json())?.error?.type || ""; } catch { /* non-JSON body */ }
      return json(502, { error: "upstream_error", status: upstream.status, detail }, cors);
    }
    return new Response(sseToText(upstream.body), {
      headers: { ...cors, "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", "X-Remaining": String(quota.remaining) },
    });
  },
};
