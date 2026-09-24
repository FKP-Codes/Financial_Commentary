"""Construction du contexte chiffré et appel à l'API Claude."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import anthropic

SYSTEM_PROMPT = """Tu es gérant de portefeuille multi-actifs dans une société de gestion française.
Tu rédiges le commentaire de gestion mensuel ou périodique destiné aux clients.

Règles impératives :
- Rédige en français professionnel, sobre et factuel, dans le style des reportings de sociétés de gestion.
- Appuie-toi EXCLUSIVEMENT sur les données chiffrées fournies et sur le contexte éventuellement donné par le gérant.
- N'invente AUCUN événement de marché, décision de banque centrale, statistique macroéconomique
  ou chiffre absent des données.
  Si le contexte de marché n'est pas fourni, décris les mouvements observés sans leur attribuer de cause précise.
- Cite les chiffres clés avec 1 ou 2 décimales et le signe (ex. +3,42 %, -1,10 %). Utilise la virgule décimale.
- Explique la performance relative par les effets d'allocation (sur/sous-pondérations vs l'allocation stratégique)
  et par la contribution de chaque ligne.
- Ne donne aucune recommandation d'investissement personnalisée ni promesse de performance future.
- N'utilise ni emojis ni formules marketing.

Structure attendue (titres en gras Markdown, sans titre général) :
**Environnement de marché** — ce que les données disent de chaque classe d'actifs.
**Performance du portefeuille** — performance absolue et relative, volatilité, drawdown, Sharpe.
**Analyse des contributions** — lignes moteurs et détractrices, effet des écarts d'allocation.
**Positionnement et perspectives** — allocation actuelle (après dérive), points de vigilance, sans prédiction chiffrée.
"""

LENGTH_GUIDE = {
    "Court": "Environ 150 mots au total.",
    "Standard": "Environ 300 mots au total.",
    "Détaillé": "Environ 500 mots au total.",
}

AUDIENCE_GUIDE = {
    "Investisseurs institutionnels": (
        "Public expert : vocabulaire technique assumé (tracking error, allocation tactique)."
    ),
    "Clientèle privée": "Public averti mais non spécialiste : explique brièvement les notions techniques.",
}


def build_context(
    *,
    period_start: str,
    period_end: str,
    portfolio_metrics: dict[str, float],
    benchmark_metrics: dict[str, float],
    tracking_error: float,
    assets: list[dict[str, Any]],
    monthly: dict[str, float],
) -> dict[str, Any]:
    """Payload JSON compact : c'est la seule source de vérité transmise au LLM."""

    def pct(x: float) -> float:
        return round(x * 100, 2)

    return {
        "periode": {"debut": period_start, "fin": period_end},
        "portefeuille": {k: (round(v, 2) if k == "Ratio de Sharpe" else pct(v)) for k, v in portfolio_metrics.items()},
        "allocation_strategique_benchmark": {
            k: (round(v, 2) if k == "Ratio de Sharpe" else pct(v)) for k, v in benchmark_metrics.items()
        },
        "surperformance_relative_pts": pct(
            portfolio_metrics["Performance cumulée"] - benchmark_metrics["Performance cumulée"]
        ),
        "tracking_error_annualisee": pct(tracking_error),
        "lignes": assets,
        "performances_mensuelles_portefeuille": {k: pct(v) for k, v in monthly.items()},
        "unite": "Valeurs en %, sauf ratio de Sharpe. Portefeuille buy-and-hold, dividendes réinvestis, en EUR.",
    }


def build_user_prompt(context: dict[str, Any], audience: str, length: str, manager_notes: str) -> str:
    notes = manager_notes.strip() or "Aucun contexte fourni : ne pas attribuer de causes externes aux mouvements."
    return (
        f"Public cible : {AUDIENCE_GUIDE[audience]}\n"
        f"Longueur : {LENGTH_GUIDE[length]}\n\n"
        f"<donnees_portefeuille>\n{json.dumps(context, ensure_ascii=False, indent=2)}\n</donnees_portefeuille>\n\n"
        f"<contexte_gerant>\n{notes}\n</contexte_gerant>\n\n"
        "Rédige le commentaire de gestion."
    )


def stream_commentary(api_key: str, model: str, user_prompt: str) -> Iterator[str]:
    """Génère le commentaire en streaming (affichage progressif dans Streamlit)."""
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        yield from stream.text_stream
