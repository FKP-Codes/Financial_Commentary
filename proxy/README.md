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

## Déploiement (≈ 10 minutes, offre gratuite)

1. Créez un compte sur [dash.cloudflare.com](https://dash.cloudflare.com) (gratuit).
2. **Workers & Pages → Create → Create Worker** → nommez-le `commentary-proxy` → **Deploy**.
3. **Edit code** → remplacez tout le contenu par celui de `worker.js` → **Deploy**.
4. **Settings → Variables and Secrets** :
   - `ANTHROPIC_API_KEY` → type **Secret** → votre clé (idéalement une clé dédiée au site) ;
   - `ALLOWED_ORIGINS` → type **Text** → `https://fkp-codes.github.io` ;
   - optionnel : `CLAUDE_MODEL` (défaut `claude-haiku-4-5`), `HOURLY_LIMIT_PER_IP` (défaut `5`).
5. Optionnel, plafond global : **Storage & Databases → KV → Create** (`commentary-usage`), puis dans le Worker
   **Settings → Bindings → Add → KV namespace**, nom de variable `USAGE`, et une variable `DAILY_LIMIT` (ex. `100`).
6. Copiez l'URL du Worker (`https://commentary-proxy.<compte>.workers.dev`) et renseignez-la dans
   `assets/js/site.js` du dépôt FKP-Codes (`COMMENTARY_PROXY_URL`).

Le Worker ne contient aucun secret : son code peut rester public.
