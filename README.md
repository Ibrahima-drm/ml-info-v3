# ML Info — Veille Mali

Agrégateur d'actualité sur le Mali avec catégorisation automatique,
synthèses d'articles et **PWA installable** sur iPhone et Android.

---

## Fonctionnalités

- **12 sources RSS** francophones et internationales (RFI, France 24,
  Le Monde Afrique, Jeune Afrique, BBC Afrique, Studio Tamani, Mali Web,
  MaliJet, Maliactu, Bamada, Journal du Mali, Al Jazeera).
- **Filtrage intelligent** par mots-clés pondérés et ancrage géographique.
- **4 catégories** auto : sécurité, politique, économie, régions.
- **Synthèses d'articles** générées à la volée — plus besoin d'aller
  sur le site. Deux modes :
    - **Extractif** (par défaut, gratuit) : extraction du contenu via
      `trafilatura` puis sélection des phrases significatives.
    - **Claude** (optionnel) : résumé naturel en 3-4 phrases via l'API
      Anthropic. Activé automatiquement si `ANTHROPIC_API_KEY` est
      présent dans l'environnement.
- **PWA cross-platform** : installable comme une vraie app sur iOS et
  Android (icône, plein écran, fonctionne hors ligne).
- **Filtres**, recherche live, favoris locaux, partage natif,
  pull-to-refresh.

---

## Lancer en local

```bash
git clone <ton-repo>
cd ML_INFO_v3
pip install -r requirements.txt
python app.py
```

Ouvre `http://localhost:5000` dans ton navigateur.

Pour tester depuis ton téléphone sur le même Wi-Fi, utilise l'IP locale
de ton ordi : `http://192.168.x.x:5000`.

---

## Déploiement sur Render (recommandé)

> **Pourquoi pas Vercel ?** Vercel est conçu pour du frontend statique
> ou des fonctions serverless. Pour un Flask classique avec cache mémoire
> et tâches en arrière-plan (préchargement des résumés), Render est
> bien plus adapté : process long-running, HTTPS gratuit, déploiement
> direct depuis GitHub.

### Méthode 1 — Bouton "Connect Repo" (le plus rapide)

1. Va sur [render.com](https://render.com) et connecte ton compte GitHub.
2. **New + → Web Service** → choisis ton repo `ML_INFO`.
3. Render détecte automatiquement le `render.yaml` ou tu peux remplir
   manuellement :
    - **Build command** : `pip install -r requirements.txt`
    - **Start command** : `gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`
    - **Plan** : Free
4. Clique **Create Web Service**.
5. Attends 2-3 min, puis ton app est en ligne sur
   `https://ml-info.onrender.com` (ou similaire).

### Méthode 2 — render.yaml (Infrastructure as Code)

Le fichier `render.yaml` est déjà inclus. Il suffit de :

1. Push le repo sur GitHub.
2. Sur Render : **New + → Blueprint** → sélectionne ton repo.
3. Render lit `render.yaml` et crée le service automatiquement.

### Activer les résumés Claude (optionnel mais recommandé)

1. Décommente la ligne `anthropic>=0.39` dans `requirements.txt`.
2. Sur Render → ton service → **Environment** → ajoute :
    - Clé : `ANTHROPIC_API_KEY`
    - Valeur : ta clé d'API
3. Redéploie. Les nouveaux résumés seront générés par Claude Haiku.

### Limitation du plan gratuit

Le plan free de Render met l'app en veille après 15 min d'inactivité
(le premier chargement après veille peut prendre 30-60 s). Solutions :

- **Upgrade** au plan Starter ($7/mois) pour de l'always-on.
- **Keep-alive** : configure un ping toutes les 10 min via
  [UptimeRobot](https://uptimerobot.com) (gratuit) pointant sur
  `https://ton-app.onrender.com/health`.

---

## Installation comme app sur ton téléphone

### iPhone (Safari)
1. Ouvre l'URL Render dans **Safari** (pas Chrome — l'install ne marche
   que dans Safari sur iOS).
2. Bouton **Partager** (carré avec flèche) → **Sur l'écran d'accueil**.
3. L'app s'ouvre désormais en plein écran depuis ton home screen.

### Android (Chrome)
1. Ouvre l'URL Render dans Chrome.
2. Un bandeau "Installer ML Info" apparaît automatiquement après
   quelques secondes (ou Menu ⋮ → **Installer l'application**).
3. Confirme. L'app apparaît dans le tiroir d'applications.

---

## API

| Route                              | Description                                |
| ---------------------------------- | ------------------------------------------ |
| `GET /`                            | Page web (HTML)                            |
| `GET /api/articles`                | JSON de tous les articles                  |
| `GET /api/articles?refresh=1`      | Force un rafraîchissement                  |
| `GET /api/summary?url=<URL>`       | Synthèse d'un article (cache si déjà fait) |
| `GET /health`                      | État du service (cache, mode Claude…)      |

---

## Structure du projet

```
ML_INFO_v3/
├── app.py                  # Backend Flask : routes, agrégation, scoring
├── summary.py              # Module de génération de synthèses
├── requirements.txt
├── Procfile                # Commande de démarrage Render/Heroku
├── render.yaml             # Config Render (IaC)
├── runtime.txt             # Version Python pour Render
├── .gitignore
├── README.md
├── static/
│   ├── manifest.json       # Manifest PWA
│   ├── sw.js               # Service Worker (cache + offline)
│   ├── icon-192.png
│   └── icon-512.png
└── templates/
    └── index.html          # UI mobile-first
```

---

## Idées d'évolution

- Notifications push (nécessite VAPID + Web Push API + opt-in user)
- Géolocalisation des évènements sur une carte (Leaflet + OSM)
- Alertes personnalisées par mots-clés (ex. "Ménaka", "Kidal")
- Historique consultable (persistance SQLite + Postgres sur Render)
- Sentiment analysis pour identifier les articles à forte tension
- Sources additionnelles : ACLED (API), Sahel-Intelligence, RFI Sahel

---

**Auteur** : Ibrahima A. DIAROUMBA
