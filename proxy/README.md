# Proxy de génération pour le site GitHub Pages

Le site [fkp-codes.github.io/FKP-Codes](https://fkp-codes.github.io/FKP-Codes/) est statique : il ne peut pas
contenir de clé API. Ce Cloudflare Worker (`worker.js`, un seul fichier, aucune dépendance) fait l'intermédiaire.

```
Navigateur (chiffres calculés) ──► Worker (clé API secrète, prompt côté serveur) ──► API Claude
                               ◄── texte du commentaire en streaming ◄──
```

## Garde-fous

- **Clé API** stockée comme secret Cloudflare, jamais envoyée au navigateur.
- **Prompt construit côté serveur** : le navigateur n'envoie que des nombres, le public cible, la longueur, la
  langue et le contexte du gérant (800 caractères max). Les noms des lignes sont fixés dans le Worker : le proxy
  ne peut pas servir d'accès gratuit et générique à Claude.
- **Origine** : seules les origines listées dans `ALLOWED_ORIGINS` sont acceptées (CORS).
- **Débit** : 5 générations par heure et par IP (au mieux, par instance), plafond quotidien global optionnel via KV.
- **Coût** : Claude Haiku 4.5, `max_tokens` = 1500, et limite de dépenses mensuelle sur la console Anthropic.

## Déploiement depuis GitHub (recommandé)

Le fichier `wrangler.jsonc` à la racine du dépôt décrit le Worker (`financial-commentary`, point d'entrée
`proxy/worker.js`, origine autorisée). Si le Worker est relié au dépôt (**Workers & Pages → Create → Import a
repository**), chaque push sur `main` le redéploie automatiquement. Seul le secret `ANTHROPIC_API_KEY` est à
renseigner dans **Settings → Variables and Secrets** (type **Secret**) ; il n'est pas écrasé par les déploiements.

## Déploiement manuel (sans lien GitHub)

1. Sur [dash.cloudflare.com](https://dash.cloudflare.com) : **Workers & Pages → Create → Create Worker**, nommé
   `financial-commentary`, puis **Edit code** → collez `worker.js` → **Deploy**.
2. **Settings → Variables and Secrets** : `ANTHROPIC_API_KEY` (type **Secret**) et `ALLOWED_ORIGINS`
   (`https://fkp-codes.github.io`).

## Options

- `CLAUDE_MODEL` (défaut `claude-haiku-4-5`) et `HOURLY_LIMIT_PER_IP` (défaut `5`), en variables.
- Plafond quotidien global : créez un espace KV, liez-le au Worker sous le nom `USAGE` et ajoutez `DAILY_LIMIT`.
- Diagnostic : les erreurs de l'API Claude sont journalisées dans **Workers → financial-commentary → Logs** ; le
  site n'affiche que leur type.

Le Worker ne contient aucun secret : son code peut rester public.
