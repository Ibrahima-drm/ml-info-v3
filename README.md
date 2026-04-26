# ML Info

Agrégateur d'actualités basé sur des flux RSS, avec scoring de pertinence,
catégorisation automatique, synthèses d'articles et **PWA installable** sur
mobile.

## Fonctionnalités

- Agrégation parallèle de flux RSS (configurable dans `app.py`)
- Scoring par mots-clés pondérés et catégorisation auto
- Synthèses d'articles à la volée, deux modes :
  - **Extractif** (gratuit) — extraction du contenu via `trafilatura`
  - **Claude** (optionnel) — résumé naturel via l'API Anthropic, activé
    automatiquement si `ANTHROPIC_API_KEY` est défini
- PWA installable (iOS / Android), service worker, mode hors ligne basique
- Filtres, recherche live, favoris locaux, partage natif

## Stack

Flask · feedparser · trafilatura · gunicorn · Anthropic SDK (optionnel)

## Lancer en local

```bash
pip install -r requirements.txt
python app.py
```

→ `http://localhost:5000`

## Déploiement Render

Le repo contient un `render.yaml` prêt à l'emploi :

1. Sur [render.com](https://render.com) → **New + → Blueprint**
2. Sélectionner ce repo
3. Render lit `render.yaml` et crée le service automatiquement

Pour activer les résumés Claude, ajouter `ANTHROPIC_API_KEY` dans
**Environment** et décommenter `anthropic>=0.39` dans `requirements.txt`.

> Plan free Render : mise en veille après 15 min d'inactivité. Un ping
> régulier (UptimeRobot, cron Render) sur `/health` permet de garder
> l'app éveillée.

## API

| Route | Description |
|---|---|
| `GET /` | Page web |
| `GET /api/articles` | JSON des articles |
| `GET /api/articles?refresh=1` | Force le rafraîchissement |
| `GET /api/summary?url=<URL>` | Synthèse d'un article |
| `GET /health` | Statut du service |

## Structure

```
app.py              Backend Flask (routes, agrégation, scoring)
summary.py          Génération des synthèses
templates/          UI mobile-first
static/             PWA assets (manifest, service worker, icônes)
render.yaml         Config Render (Infrastructure as Code)
Procfile            Commande de démarrage
```

## Licence

MIT
