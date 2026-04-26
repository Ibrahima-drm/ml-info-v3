# Push notifications design

Date : 2026-04-26
Auteur : ML_INFO project
Statut : approuvé en brainstorming, en attente du plan d'implémentation

## Contexte

L'app ML_INFO agrège l'actualité Mali via flux RSS et la sert en PWA installée
sur l'écran d'accueil iOS / Android. Elle ne notifie pas l'utilisateur des
événements importants — il doit ouvrir l'app pour vérifier. Pour des sujets
sensibles (attaques armées, annonces politiques, événements régionaux à fort
impact), le vrai usage est d'être *alerté* dès qu'un fait nouveau apparaît.

Cible : un utilisateur unique connu, qui suit l'actualité malienne quotidiennement
sur iPhone (iOS 26.4, PWA installée). Pas de comptes multi-utilisateurs prévus.

## Décisions de cadrage

Issues du brainstorming :

| Choix | Valeur |
|---|---|
| Mode de notification | Real-time, dès qu'un article éligible est ingéré |
| Seuil score | ≥ 10 (sélectif, attaques + actu chaude) |
| Cap anti-spam | 1 push max toutes les 30 minutes (global, pas par utilisateur) |
| Catégories | Toutes (sécurité + politique + économie + régions) |
| Format titre | Titre de l'article |
| Format body | `Source • il y a X min` |
| Action au tap | Ouvre l'URL source dans le navigateur |
| Bouton UI | 🔔 / 🔕 dans le header, à droite de "dernière maj" |
| Plateforme cible | iOS PWA installée (homescreen), Android, desktop Chrome/Firefox |

## Architecture

```
┌──────────────────┐
│ fetch_all() RSS  │  (toutes les ~3 min, cache 180s + stale-while-revalidate)
└────────┬─────────┘
         │ liste articles fraîche
         ▼
┌──────────────────────────────────────────┐
│ trigger_push(articles)                   │
│ • filtre : score ≥ 10 ?                  │
│ • filtre : URL absente de               │
│            notified_articles ?           │
│ • filtre : dernier push > 30 min ?       │
│ • prend l'article le plus haut score     │
│   restant, break après 1                 │
└────────┬─────────────────────────────────┘
         │ 1 article élu
         ▼
┌──────────────────────────────────────────┐
│ SELECT * FROM push_subscriptions          │
│ for each subscription:                    │
│   pywebpush.send(...)                     │
│   if 410/404 → DELETE subscription        │
│ INSERT INTO notified_articles             │
└──────────────────────────────────────────┘
         │ via FCM / Apple Push
         ▼
┌──────────────────────────────────────────┐
│ Service worker (sw.js)                    │
│ self.addEventListener('push', e => …)     │
│ self.registration.showNotification(…)     │
│ click → clients.openWindow(url)           │
└──────────────────────────────────────────┘
```

La pipeline push se branche en queue du `_do_fetch()` existant et tourne dans
le `_prefetch_pool` (`ThreadPoolExecutor` déjà présent dans `app.py`). Pas de
scheduler séparé.

## Data model

Deux nouvelles tables Turso, gérées par un nouveau module `push.py` à créer :

```sql
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint    TEXT PRIMARY KEY,   -- URL unique du navigateur (FCM/Apple)
    p256dh      TEXT NOT NULL,      -- clé publique du navigateur (b64)
    auth        TEXT NOT NULL,      -- secret partagé (b64)
    created_at  REAL,               -- unix timestamp
    last_seen_at REAL               -- mis à jour à chaque push réussi
);

CREATE TABLE IF NOT EXISTS notified_articles (
    url         TEXT PRIMARY KEY,
    notified_at REAL                -- unix timestamp
);
```

`notified_articles` ne stocke pas le contenu de la notif (titre, source) —
juste un set d'URLs déjà pushées pour la déduplication. Pas de TTL : la
table grossit linéairement avec les articles. Si elle dépasse 10 000 lignes
on ajoutera une purge (out of scope ici).

## Frontend

### Header (templates/index.html)

Ajout d'un bouton à droite de l'horloge "dernière maj" :

```html
<button id="pushToggle" class="btn-icon" aria-label="Notifications">🔕</button>
```

État :
- 🔕 (gris) : non abonné ou refusé par le navigateur
- 🔔 (bleu) : abonné

Persistance de l'état d'affichage via `localStorage["push_subscribed"]` pour
éviter un flicker au chargement, mais la vérité reste côté backend.

### Logique JS (templates/index.html, `<script>`)

Au chargement :
1. Si `'serviceWorker' in navigator && 'PushManager' in window` → bouton actif
2. Sinon → bouton caché (plateforme non compatible, ex: Safari iOS hors PWA)
3. Lit `Notification.permission` :
   - `'granted'` + abonné côté backend → 🔔
   - sinon → 🔕

Au tap :
- Si non abonné :
  1. `await Notification.requestPermission()` — si refusé, message d'erreur discret
  2. `await registration.pushManager.subscribe({applicationServerKey: VAPID_PUBLIC, userVisibleOnly: true})`
  3. `POST /api/push/subscribe` avec `{endpoint, keys: {p256dh, auth}}`
  4. État → 🔔

- Si déjà abonné :
  1. `await sub.unsubscribe()`
  2. `DELETE /api/push/subscribe` avec `{endpoint}`
  3. État → 🔕

### Service worker (static/sw.js)

Ajout de deux event listeners :

```javascript
self.addEventListener('push', (event) => {
    const data = event.data ? event.data.json() : {};
    event.waitUntil(
        self.registration.showNotification(data.title || 'Mali Info', {
            body: data.body || '',
            icon: '/static/icon-192.png',
            badge: '/static/icon-192.png',
            data: { url: data.url },
            tag: data.tag,         // dédup côté navigateur
        })
    );
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const url = event.notification.data.url;
    if (url) {
        event.waitUntil(clients.openWindow(url));
    }
});
```

## Backend

### Nouvelles routes (app.py)

| Route | Méthode | Auth | Rôle |
|---|---|---|---|
| `/api/push/vapid-public-key` | GET | Public | Retourne `{"key": "<b64-public-key>"}` |
| `/api/push/subscribe` | POST | Public | Enregistre `{endpoint, keys: {p256dh, auth}}` dans Turso |
| `/api/push/subscribe` | DELETE | Public | Supprime l'abonnement par endpoint |

Pas d'auth admin sur ces routes : un attaquant pourrait spammer la table mais
pas reçevoir les pushs (l'endpoint cible son propre navigateur). Risque limité.

### Module push.py (nouveau)

Pattern parallèle au `SummaryStore` :

```python
class PushStore:
    def __init__(self): ...
    def add_subscription(self, endpoint, p256dh, auth): ...
    def remove_subscription(self, endpoint): ...
    def list_subscriptions(self) -> list[dict]: ...
    def mark_notified(self, url): ...
    def is_already_notified(self, url) -> bool: ...
    def last_push_at(self) -> float: ...   # max(notified_at) global
```

Et une fonction côté pipeline :

```python
def trigger_push_for_new_articles(articles: list[Article]) -> Optional[str]:
    """Évalue les filtres et envoie le push si éligible.
    Retourne l'URL pushée ou None."""
```

### Hook dans fetch_all

À la fin de `_do_fetch()`, juste après `_prefetch_summaries(all_articles)`,
ajouter (dans le pool background) :

```python
_prefetch_pool.submit(lambda: trigger_push_for_new_articles(all_articles))
```

Non bloquant pour la requête HTTP en cours.

### Library : pywebpush

Ajout à `requirements.txt` : `pywebpush>=2.0`. Cette lib gère le chiffrement
WebPush (ECDH + AES-GCM) et l'envoi HTTP au push service du navigateur.

Gestion des erreurs :
- HTTP 201/202/204 → succès, on update `last_seen_at`
- HTTP 404/410 → endpoint mort → DELETE subscription de Turso
- Autre → log warning, ne pas DELETE (pourrait être transitoire)

## Variables d'environnement (à ajouter sur Render)

| Var | Valeur |
|---|---|
| `VAPID_PRIVATE_KEY` | Clé privée PEM (à générer une fois, jamais partagée) |
| `VAPID_PUBLIC_KEY` | Clé publique au format b64 uncompressed point |
| `VAPID_CONTACT` | `mailto:ibrahimadiaroumba@gmail.com` |

Génération de clés (script one-shot dans `scripts/gen_vapid_keys.py`) :

```python
from py_vapid import Vapid01
v = Vapid01()
v.generate_keys()
print("Private:", v.private_key_pem())
print("Public:", v.public_key_b64)
```

## Tests

### Unit tests (pytest)

- `test_push_filters.py`
  - score < 10 → skip
  - score ≥ 10 mais URL déjà dans notified_articles → skip
  - score ≥ 10, jamais notifié, mais dernier push < 30 min → skip
  - tous filtres OK → push, mark_notified appelé
- `test_push_store.py`
  - add/list/remove subscription round-trip
  - is_already_notified retourne True après mark_notified
  - last_push_at retourne le bon timestamp

### Tests d'intégration

- `POST /api/push/subscribe` avec payload valide → 201 + ligne en DB
- `POST /api/push/subscribe` payload invalide → 400
- `DELETE /api/push/subscribe` → 204 + ligne supprimée
- `GET /api/push/vapid-public-key` → 200 + clé non vide

### Test manuel (post-déploiement)

1. Sur iPhone, ouvrir la PWA installée → tap 🔕
2. Accepter la permission iOS
3. Vérifier que 🔔 apparaît
4. Attendre un article score ≥ 10 (ou injecter via SQL `INSERT INTO notified_articles`
   avec `notified_at` ancien pour permettre un nouveau push immédiatement)
5. Vérifier la notif sur le lock screen
6. Tap → l'article s'ouvre dans Safari

## Hors scope (YAGNI)

Décisions explicites de NE PAS faire :

- Quiet hours côté serveur — iOS Focus mode et Android DND s'en chargent
- Filtres par catégorie côté utilisateur — single-user, toutes catégories OK
- Comptes / authentification — pas de modèle multi-tenant
- Historique des notifications envoyées (contenu) — `notified_articles` stocke
  juste l'URL+date pour dédupliquer, pas le contenu
- Analytics de delivery (taux d'ouverture, taux d'erreur) — overkill personnel
- Bouton "test push" caché — pas la peine, le test manuel ci-dessus suffit
- Multi-langue des notifs — l'app est francophone uniquement
- Notifications groupées (digest) — explicitement écarté en faveur du temps réel

## Risques connus

- **Latence iOS** : Apple Push Notification service peut introduire 30-60s de
  délai. Acceptable pour de l'actu ; ne pas promettre du < 5s.
- **Subscriptions zombies** : un utilisateur qui désinstalle la PWA sans
  cliquer 🔕 laisse une subscription orpheline. Le push retournera 410, on la
  supprime à ce moment-là. Ok.
- **Rate limit FCM/APNS** : à très faible volume (1 user × 1 push / 30 min),
  largement sous les limites. Pas un sujet.
- **VAPID keys leak** : si la clé privée fuit, un attaquant peut envoyer des
  pushs. Mitigations : env var Render, jamais committée, rotation possible
  (les abonnés devraient se ré-abonner — c'est OK pour un user solo).

## Plan de déploiement

1. Implémenter selon le plan (issu de la prochaine étape `writing-plans`)
2. Tester en local : `pip install pywebpush`, générer VAPID, lancer Flask, tester
   sur Chrome desktop d'abord (plus simple à debug)
3. Push les changements sur GitHub → Render redéploie
4. Ajouter les 3 env vars VAPID + le pywebpush dans requirements.txt
5. Sur iPhone, ouvrir la PWA, tap 🔕 → 🔔
6. Attendre / injecter un article éligible, vérifier la notif
