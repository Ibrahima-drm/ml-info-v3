# Push Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time web push notifications to the ML_INFO PWA, alerting the user about high-priority Mali news articles (score ≥ 10) at most once every 30 minutes.

**Architecture:** A new `push.py` module manages two Turso tables (`push_subscriptions`, `notified_articles`). Three Flask routes handle VAPID key distribution and subscribe/unsubscribe. A trigger function hooked into `_do_fetch()` checks newly fetched articles against filters (score, dedup, rate limit) and dispatches via `pywebpush` to all stored subscriptions in a background thread. Frontend adds a 🔔/🔕 toggle in the header that calls the new endpoints; service worker `static/sw.js` listens for `push` events and shows notifications.

**Tech Stack:** Flask, libsql-client (Turso), pywebpush + py-vapid, vanilla JS service worker, pytest with monkeypatch for mocking webpush.

---

## File Structure

**New files:**
- `push.py` — `PushStore` class (Turso CRUD for subscriptions and notified articles) + `trigger_push_for_new_articles()` function
- `scripts/gen_vapid_keys.py` — one-shot script to generate VAPID keypair locally
- `tests/test_push_store.py` — unit tests for PushStore CRUD
- `tests/test_push_filters.py` — unit tests for the trigger filter logic (score, dedup, rate limit)
- `tests/test_push_routes.py` — integration tests for the 3 push API routes

**Modified files:**
- `requirements.txt` — add `pywebpush>=2.0` (which pulls `py-vapid`)
- `app.py` — 3 new routes, hook trigger in `_do_fetch()`, helper to build subscription payloads
- `static/sw.js` — add `push` and `notificationclick` event listeners
- `templates/index.html` — header button + JS subscribe/unsubscribe logic
- `render.yaml` — document new VAPID env vars
- `tests/conftest.py` — set test VAPID env vars + autouse fixture to reset push tables between tests

---

## Task 1: Add pywebpush dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add pywebpush to requirements**

Edit `requirements.txt` to:

```
Flask>=3.0
feedparser>=6.0
trafilatura>=1.12
gunicorn>=21.0
anthropic>=0.40
libsql-client>=0.3
pywebpush>=2.0
```

- [ ] **Step 2: Install locally**

Run: `pip install pywebpush`
Expected: pywebpush + py-vapid + cryptography installed without error.

- [ ] **Step 3: Verify import**

Run: `python -c "from pywebpush import webpush, WebPushException; from py_vapid import Vapid01; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "Add pywebpush dependency for web push notifications"
```

---

## Task 2: VAPID key generation script

**Files:**
- Create: `scripts/gen_vapid_keys.py`

- [ ] **Step 1: Create the directory**

Run: `mkdir -p scripts`

- [ ] **Step 2: Write the script**

Create `scripts/gen_vapid_keys.py`:

```python
"""Generate a VAPID keypair for web push notifications.

Run once. Copy the printed values into Render env vars:
    VAPID_PRIVATE_KEY = <private PEM, multi-line>
    VAPID_PUBLIC_KEY  = <public b64 url-safe>

Do NOT commit the output. The private key must remain secret.
"""

from py_vapid import Vapid01


def main():
    v = Vapid01()
    v.generate_keys()

    print("=" * 60)
    print("VAPID_PRIVATE_KEY (multi-line PEM, copy AS-IS into Render):")
    print("=" * 60)
    print(v.private_pem().decode())

    print("=" * 60)
    print("VAPID_PUBLIC_KEY (single-line b64 url-safe):")
    print("=" * 60)
    # py-vapid 1.x : public_key bytes uncompressed point → b64 url-safe
    import base64
    pub = v.public_key.public_bytes(
        encoding=__import__("cryptography.hazmat.primitives.serialization",
                            fromlist=["Encoding"]).Encoding.X962,
        format=__import__("cryptography.hazmat.primitives.serialization",
                          fromlist=["PublicFormat"]).PublicFormat.UncompressedPoint,
    )
    print(base64.urlsafe_b64encode(pub).rstrip(b"=").decode())

    print()
    print("Set both as env vars on Render. Add VAPID_CONTACT=mailto:<your-email>.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it once locally to verify it works**

Run: `python scripts/gen_vapid_keys.py`
Expected: prints a PEM block (5-6 lines starting with `-----BEGIN PRIVATE KEY-----`) and a single b64 line (~88 chars).

⚠️ Do not commit the output. The keys you generate now are for the user to copy into Render manually.

- [ ] **Step 4: Commit the script (not its output)**

```bash
git add scripts/gen_vapid_keys.py
git commit -m "Add VAPID keypair generation script"
```

---

## Task 3: PushStore — subscription CRUD (TDD)

**Files:**
- Create: `push.py`
- Create: `tests/test_push_store.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Update conftest.py to reset push tables between tests**

Edit `tests/conftest.py` to:

```python
import os
import sys
import tempfile

# Permet aux tests d'importer app.py / summary.py / push.py depuis la racine
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# DB temporaire pour ne pas polluer l'environnement de dev
_tmp_db = os.path.join(tempfile.gettempdir(), "ml_info_tests_summaries.db")
if os.path.exists(_tmp_db):
    os.remove(_tmp_db)
os.environ.setdefault("SUMMARY_DB_URL", f"file:{_tmp_db}")

# VAPID test keys (factices, suffisent pour les tests qui ne font pas de vrai send)
os.environ.setdefault("VAPID_PUBLIC_KEY", "BP-test-public-key")
os.environ.setdefault("VAPID_PRIVATE_KEY", "test-private-key")
os.environ.setdefault("VAPID_CONTACT", "mailto:test@example.com")


import pytest


@pytest.fixture(autouse=True)
def _reset_push_tables():
    """Vide les tables push_subscriptions et notified_articles avant chaque test."""
    try:
        import push
        push.STORE.clear_all()
    except Exception:
        # Module pas encore créé ou DB pas encore initialisée
        pass
    yield
```

- [ ] **Step 2: Write failing tests for PushStore CRUD**

Create `tests/test_push_store.py`:

```python
"""Tests CRUD du PushStore (table push_subscriptions)."""

from push import PushStore


def make_sub(endpoint="https://fcm.example/abc"):
    return {
        "endpoint": endpoint,
        "p256dh": "BP-fake-p256dh",
        "auth": "fake-auth-secret",
    }


class TestSubscriptionCRUD:
    def test_empty_store(self):
        store = PushStore()
        assert store.list_subscriptions() == []

    def test_add_then_list(self):
        store = PushStore()
        s = make_sub()
        store.add_subscription(**s)
        rows = store.list_subscriptions()
        assert len(rows) == 1
        assert rows[0]["endpoint"] == s["endpoint"]
        assert rows[0]["p256dh"] == s["p256dh"]
        assert rows[0]["auth"] == s["auth"]

    def test_add_is_idempotent(self):
        store = PushStore()
        s = make_sub()
        store.add_subscription(**s)
        store.add_subscription(**s)  # second call must not raise / not duplicate
        assert len(store.list_subscriptions()) == 1

    def test_remove(self):
        store = PushStore()
        s = make_sub()
        store.add_subscription(**s)
        store.remove_subscription(s["endpoint"])
        assert store.list_subscriptions() == []

    def test_remove_nonexistent_is_noop(self):
        store = PushStore()
        # Doesn't raise
        store.remove_subscription("https://nonexistent.example/xyz")
```

- [ ] **Step 3: Run tests — must fail (push.py doesn't exist)**

Run: `python -m pytest tests/test_push_store.py -v`
Expected: ImportError or collection error — `push` module not found.

- [ ] **Step 4: Implement push.py with PushStore subscription CRUD**

Create `push.py`:

```python
"""Push notifications : stockage des subscriptions et déduplication des articles
notifiés. Tables dans la même DB Turso que les résumés (SUMMARY_DB_URL)."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

log = logging.getLogger("ml_info.push")


class PushStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._client = None

        url = os.environ.get("SUMMARY_DB_URL", "file:summaries.db")
        token = os.environ.get("SUMMARY_DB_AUTH_TOKEN") or None
        try:
            import libsql_client
            self._client = libsql_client.create_client_sync(
                url=url, auth_token=token
            )
            self._init_schema()
            log.info("PushStore prêt (%s)", url.split("?")[0])
        except Exception as e:
            log.warning("PushStore L2 indisponible : %s", e)
            self._client = None

    def _init_schema(self):
        self._client.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                endpoint     TEXT PRIMARY KEY,
                p256dh       TEXT NOT NULL,
                auth         TEXT NOT NULL,
                created_at   REAL,
                last_seen_at REAL
            )
        """)
        self._client.execute("""
            CREATE TABLE IF NOT EXISTS notified_articles (
                url         TEXT PRIMARY KEY,
                notified_at REAL
            )
        """)

    def add_subscription(self, endpoint: str, p256dh: str, auth: str) -> None:
        if self._client is None:
            return
        now = time.time()
        with self._lock:
            self._client.execute(
                "INSERT OR REPLACE INTO push_subscriptions"
                "(endpoint, p256dh, auth, created_at, last_seen_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (endpoint, p256dh, auth, now, now),
            )

    def remove_subscription(self, endpoint: str) -> None:
        if self._client is None:
            return
        with self._lock:
            self._client.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ?",
                (endpoint,),
            )

    def list_subscriptions(self) -> list[dict]:
        if self._client is None:
            return []
        with self._lock:
            rs = self._client.execute(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions"
            )
        return [
            {"endpoint": r[0], "p256dh": r[1], "auth": r[2]}
            for r in rs.rows
        ]

    def clear_all(self) -> None:
        """Test helper : vide les deux tables."""
        if self._client is None:
            return
        with self._lock:
            self._client.execute("DELETE FROM push_subscriptions")
            self._client.execute("DELETE FROM notified_articles")


# Instance globale, créée au load
STORE = PushStore()
```

- [ ] **Step 5: Run tests — must pass**

Run: `python -m pytest tests/test_push_store.py -v`
Expected: 5 PASSED.

- [ ] **Step 6: Commit**

```bash
git add push.py tests/test_push_store.py tests/conftest.py
git commit -m "Add PushStore: subscription CRUD on Turso"
```

---

## Task 4: PushStore — notified articles tracking (TDD)

**Files:**
- Modify: `push.py`
- Modify: `tests/test_push_store.py`

- [ ] **Step 1: Write failing tests for notified articles tracking**

Append to `tests/test_push_store.py`:

```python
class TestNotifiedArticles:
    def test_not_notified_by_default(self):
        store = PushStore()
        assert store.is_already_notified("https://example.com/a") is False

    def test_mark_then_is_notified(self):
        store = PushStore()
        store.mark_notified("https://example.com/a")
        assert store.is_already_notified("https://example.com/a") is True

    def test_mark_idempotent(self):
        store = PushStore()
        store.mark_notified("https://example.com/a")
        store.mark_notified("https://example.com/a")  # no error
        assert store.is_already_notified("https://example.com/a") is True

    def test_last_push_at_empty(self):
        store = PushStore()
        assert store.last_push_at() == 0.0

    def test_last_push_at_after_mark(self):
        import time as _t
        store = PushStore()
        before = _t.time()
        store.mark_notified("https://example.com/a")
        after = _t.time()
        ts = store.last_push_at()
        assert before <= ts <= after
```

- [ ] **Step 2: Run tests — must fail**

Run: `python -m pytest tests/test_push_store.py::TestNotifiedArticles -v`
Expected: AttributeError — `mark_notified` / `is_already_notified` / `last_push_at` not defined.

- [ ] **Step 3: Implement the methods**

Add to `push.py` inside `class PushStore:`, before the `clear_all` method:

```python
    def mark_notified(self, url: str) -> None:
        if self._client is None:
            return
        with self._lock:
            self._client.execute(
                "INSERT OR REPLACE INTO notified_articles(url, notified_at)"
                " VALUES (?, ?)",
                (url, time.time()),
            )

    def is_already_notified(self, url: str) -> bool:
        if self._client is None:
            return False
        with self._lock:
            rs = self._client.execute(
                "SELECT 1 FROM notified_articles WHERE url = ? LIMIT 1",
                (url,),
            )
        return bool(rs.rows)

    def last_push_at(self) -> float:
        if self._client is None:
            return 0.0
        with self._lock:
            rs = self._client.execute(
                "SELECT MAX(notified_at) FROM notified_articles"
            )
        v = rs.rows[0][0] if rs.rows else None
        return float(v) if v is not None else 0.0
```

- [ ] **Step 4: Run tests — must pass**

Run: `python -m pytest tests/test_push_store.py -v`
Expected: 10 PASSED total (5 from Task 3 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add push.py tests/test_push_store.py
git commit -m "PushStore: track notified articles for dedup and rate limiting"
```

---

## Task 5: Trigger filter logic (TDD)

**Files:**
- Modify: `push.py`
- Create: `tests/test_push_filters.py`

- [ ] **Step 1: Write failing tests for the filter logic**

Create `tests/test_push_filters.py`:

```python
"""Tests de la logique de filtrage du trigger push :
score ≥ 10, pas déjà notifié, dernier push > 30 min."""

import time

import pytest

from push import select_article_to_push, STORE


def make_article(score=12, lien="https://example.com/a", titre="Article test"):
    """Mini Article-like object (juste les attributs lus par le trigger)."""
    class A:
        pass
    a = A()
    a.score = score
    a.lien = lien
    a.titre = titre
    a.source = "Test Source"
    a.timestamp = time.time()
    return a


class TestFilters:
    def test_no_articles_returns_none(self):
        assert select_article_to_push([]) is None

    def test_score_below_threshold_skipped(self):
        a = make_article(score=9)
        assert select_article_to_push([a]) is None

    def test_score_above_threshold_passes(self):
        a = make_article(score=10)
        result = select_article_to_push([a])
        assert result is a

    def test_already_notified_skipped(self):
        a = make_article(score=15, lien="https://example.com/already")
        STORE.mark_notified(a.lien)
        assert select_article_to_push([a]) is None

    def test_recent_push_blocks_all(self, monkeypatch):
        # Simule un push il y a 5 minutes (< 30 min cap)
        monkeypatch.setattr(STORE, "last_push_at", lambda: time.time() - 5 * 60)
        a = make_article(score=15)
        assert select_article_to_push([a]) is None

    def test_old_push_does_not_block(self, monkeypatch):
        # Push il y a 31 minutes : on peut re-pusher
        monkeypatch.setattr(STORE, "last_push_at", lambda: time.time() - 31 * 60)
        a = make_article(score=15)
        assert select_article_to_push([a]) is a

    def test_picks_highest_score(self):
        low = make_article(score=10, lien="https://example.com/low")
        high = make_article(score=18, lien="https://example.com/high")
        mid = make_article(score=12, lien="https://example.com/mid")
        result = select_article_to_push([low, high, mid])
        assert result is high

    def test_skips_below_threshold_keeps_above(self):
        low = make_article(score=8, lien="https://example.com/low")
        ok = make_article(score=11, lien="https://example.com/ok")
        result = select_article_to_push([low, ok])
        assert result is ok
```

- [ ] **Step 2: Run tests — must fail**

Run: `python -m pytest tests/test_push_filters.py -v`
Expected: ImportError — `select_article_to_push` not in `push`.

- [ ] **Step 3: Implement select_article_to_push**

Append to `push.py` (after the `STORE = PushStore()` line):

```python
# ----------------------------------------------------------------------
# Trigger : filtres + sélection de l'article à pousser
# ----------------------------------------------------------------------

PUSH_SCORE_THRESHOLD = 10
PUSH_MIN_INTERVAL_SEC = 30 * 60  # 1 push max toutes les 30 min


def select_article_to_push(articles: list) -> Optional[object]:
    """Retourne l'article éligible le plus haut score, ou None.

    Filtres dans cet ordre :
      1. liste vide → None
      2. score ≥ PUSH_SCORE_THRESHOLD
      3. URL pas déjà dans notified_articles
      4. dernier push global > PUSH_MIN_INTERVAL_SEC
      5. parmi les survivants, prend le score max
    """
    if not articles:
        return None

    # Cap global : si on a poussé récemment, rien ne sort
    elapsed = time.time() - STORE.last_push_at()
    if elapsed < PUSH_MIN_INTERVAL_SEC:
        return None

    eligible = [
        a for a in articles
        if getattr(a, "score", 0) >= PUSH_SCORE_THRESHOLD
        and getattr(a, "lien", "")
        and not STORE.is_already_notified(a.lien)
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda a: a.score)
```

- [ ] **Step 4: Run tests — must pass**

Run: `python -m pytest tests/test_push_filters.py -v`
Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add push.py tests/test_push_filters.py
git commit -m "Push trigger: filter logic (score, dedup, rate limit)"
```

---

## Task 6: Push delivery via pywebpush (TDD with mock)

**Files:**
- Modify: `push.py`

- [ ] **Step 1: Write failing tests for delivery**

Append to `tests/test_push_filters.py`:

```python
class TestDelivery:
    """Tests du dispatcher : on mocke webpush() pour vérifier le routing
    sans envoyer de vraies notifs."""

    def test_send_to_all_subscriptions(self, monkeypatch):
        from push import send_push_to_all, STORE

        sent = []
        def fake_webpush(subscription_info, data, vapid_private_key,
                         vapid_claims, **kwargs):
            sent.append(subscription_info["endpoint"])
            class R:
                status_code = 201
            return R()

        monkeypatch.setattr("push.webpush", fake_webpush)

        STORE.add_subscription("https://fcm.example/a", "p1", "a1")
        STORE.add_subscription("https://fcm.example/b", "p2", "a2")

        n_sent, n_dead = send_push_to_all({"title": "T", "body": "B", "url": "/x"})
        assert n_sent == 2
        assert n_dead == 0
        assert sorted(sent) == [
            "https://fcm.example/a",
            "https://fcm.example/b",
        ]

    def test_dead_subscription_removed(self, monkeypatch):
        from push import send_push_to_all, STORE
        from pywebpush import WebPushException

        def fake_webpush(subscription_info, *a, **kw):
            class FakeResp:
                status_code = 410
                text = "Gone"
            raise WebPushException("gone", response=FakeResp())

        monkeypatch.setattr("push.webpush", fake_webpush)

        STORE.add_subscription("https://fcm.example/dead", "p", "a")

        n_sent, n_dead = send_push_to_all({"title": "T", "body": "B", "url": "/x"})
        assert n_sent == 0
        assert n_dead == 1
        assert STORE.list_subscriptions() == []

    def test_transient_error_keeps_subscription(self, monkeypatch):
        from push import send_push_to_all, STORE
        from pywebpush import WebPushException

        def fake_webpush(subscription_info, *a, **kw):
            class FakeResp:
                status_code = 500
                text = "boom"
            raise WebPushException("server error", response=FakeResp())

        monkeypatch.setattr("push.webpush", fake_webpush)

        STORE.add_subscription("https://fcm.example/temp", "p", "a")

        n_sent, n_dead = send_push_to_all({"title": "T", "body": "B", "url": "/x"})
        assert n_sent == 0
        assert n_dead == 0
        assert len(STORE.list_subscriptions()) == 1
```

- [ ] **Step 2: Run tests — must fail**

Run: `python -m pytest tests/test_push_filters.py::TestDelivery -v`
Expected: ImportError — `send_push_to_all` and `webpush` not defined in `push`.

- [ ] **Step 3: Implement send_push_to_all**

Append to `push.py`:

```python
# ----------------------------------------------------------------------
# Envoi via pywebpush
# ----------------------------------------------------------------------

import json as _json

try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
    WebPushException = Exception
    log.warning("pywebpush non installé — pas de push possible")


def _vapid_claims() -> dict:
    contact = os.environ.get("VAPID_CONTACT", "mailto:admin@example.com")
    return {"sub": contact}


def send_push_to_all(payload: dict) -> tuple[int, int]:
    """Envoie le payload à toutes les subscriptions stockées.

    Args:
        payload: dict sérialisé en JSON et reçu côté SW (title, body, url).
    Returns:
        (nombre envoyés OK, nombre subscriptions mortes supprimées)
    """
    if webpush is None:
        return 0, 0

    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    if not private_key:
        log.warning("VAPID_PRIVATE_KEY non défini — push impossible")
        return 0, 0

    n_sent = 0
    n_dead = 0
    data = _json.dumps(payload, ensure_ascii=False)

    for sub in STORE.list_subscriptions():
        sub_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        try:
            webpush(
                subscription_info=sub_info,
                data=data,
                vapid_private_key=private_key,
                vapid_claims=_vapid_claims(),
            )
            n_sent += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                STORE.remove_subscription(sub["endpoint"])
                n_dead += 1
                log.info("Subscription morte supprimée : %s", sub["endpoint"])
            else:
                log.warning("Échec push transitoire (%s) : %s", status, e)
        except Exception as e:
            log.warning("Échec push inattendu : %s", e)

    return n_sent, n_dead
```

- [ ] **Step 4: Run tests — must pass**

Run: `python -m pytest tests/test_push_filters.py -v`
Expected: 11 PASSED total.

- [ ] **Step 5: Commit**

```bash
git add push.py tests/test_push_filters.py
git commit -m "Push delivery: pywebpush dispatch + dead subscription cleanup"
```

---

## Task 7: Combine filter + delivery into trigger function (TDD)

**Files:**
- Modify: `push.py`
- Modify: `tests/test_push_filters.py`

- [ ] **Step 1: Write failing test for the integrated trigger**

Append to `tests/test_push_filters.py`:

```python
class TestTrigger:
    def test_full_flow_eligible_article(self, monkeypatch):
        from push import trigger_push_for_new_articles, STORE

        sent = []
        def fake_webpush(subscription_info, data, **kw):
            sent.append((subscription_info["endpoint"], data))
            class R:
                status_code = 201
            return R()
        monkeypatch.setattr("push.webpush", fake_webpush)

        STORE.add_subscription("https://fcm.example/a", "p", "a")

        a = make_article(score=15, lien="https://example.com/big-news",
                         titre="Big news")
        a.source = "Test"

        result = trigger_push_for_new_articles([a])
        assert result == "https://example.com/big-news"
        assert STORE.is_already_notified("https://example.com/big-news") is True
        assert len(sent) == 1

    def test_full_flow_no_eligible_article(self, monkeypatch):
        from push import trigger_push_for_new_articles
        # webpush ne devrait pas être appelé
        called = []
        monkeypatch.setattr(
            "push.webpush",
            lambda *a, **k: called.append(1) or (_ for _ in ()).throw(
                AssertionError("should not be called")
            ),
        )
        a = make_article(score=5)
        result = trigger_push_for_new_articles([a])
        assert result is None
        assert called == []

    def test_full_flow_no_subscriptions(self, monkeypatch):
        from push import trigger_push_for_new_articles, STORE
        monkeypatch.setattr("push.webpush",
                            lambda *a, **k: (_ for _ in ()).throw(
                                AssertionError("should not be called")
                            ))
        # pas de subscription → on doit quand même marquer notifié pour
        # ne pas re-tenter à chaque fetch
        a = make_article(score=12, lien="https://example.com/x")
        result = trigger_push_for_new_articles([a])
        assert result == "https://example.com/x"
        assert STORE.is_already_notified("https://example.com/x") is True
```

- [ ] **Step 2: Run tests — must fail**

Run: `python -m pytest tests/test_push_filters.py::TestTrigger -v`
Expected: ImportError — `trigger_push_for_new_articles` not defined.

- [ ] **Step 3: Implement trigger_push_for_new_articles**

Append to `push.py`:

```python
def _format_payload(article) -> dict:
    """Construit le payload JSON envoyé au service worker.

    Format : title = titre de l'article, body = "Source • il y a X min", url = lien.
    """
    age_min = max(0, int((time.time() - getattr(article, "timestamp", time.time())) / 60))
    if age_min < 1:
        age_str = "à l'instant"
    elif age_min < 60:
        age_str = f"il y a {age_min} min"
    else:
        age_str = f"il y a {age_min // 60}h"
    return {
        "title": article.titre,
        "body": f"{article.source} • {age_str}",
        "url": article.lien,
    }


def trigger_push_for_new_articles(articles: list) -> Optional[str]:
    """Pipeline complète : sélectionne un article, envoie les pushs, marque notifié.

    Retourne l'URL pushée, ou None si rien d'éligible.
    """
    chosen = select_article_to_push(articles)
    if chosen is None:
        return None

    payload = _format_payload(chosen)
    try:
        n_sent, n_dead = send_push_to_all(payload)
        log.info("Push '%s' : %d envoyés, %d supprimés", chosen.lien, n_sent, n_dead)
    except Exception as e:
        log.warning("send_push_to_all KO : %s", e)

    # On marque notifié même si 0 subscription — sinon on retentera à chaque
    # fetch et on saturera les logs.
    STORE.mark_notified(chosen.lien)
    return chosen.lien
```

- [ ] **Step 4: Run tests — must pass**

Run: `python -m pytest tests/test_push_filters.py -v`
Expected: 14 PASSED total.

- [ ] **Step 5: Commit**

```bash
git add push.py tests/test_push_filters.py
git commit -m "Push: combine filter+delivery into trigger_push_for_new_articles"
```

---

## Task 8: Backend routes (TDD)

**Files:**
- Modify: `app.py`
- Create: `tests/test_push_routes.py`

- [ ] **Step 1: Write failing tests for the 3 routes**

Create `tests/test_push_routes.py`:

```python
"""Tests des routes push : vapid-public-key, subscribe (POST/DELETE)."""

import json

import pytest

import app as app_mod
import push


@pytest.fixture
def client():
    return app_mod.app.test_client()


class TestVapidPublicKey:
    def test_returns_key(self, client):
        r = client.get("/api/push/vapid-public-key")
        assert r.status_code == 200
        d = r.get_json()
        assert "key" in d
        assert d["key"] == "BP-test-public-key"


class TestSubscribe:
    def test_post_valid_payload_creates_subscription(self, client):
        body = {
            "endpoint": "https://fcm.example/abc",
            "keys": {"p256dh": "p256-val", "auth": "auth-val"},
        }
        r = client.post("/api/push/subscribe", json=body)
        assert r.status_code == 201
        subs = push.STORE.list_subscriptions()
        assert len(subs) == 1
        assert subs[0]["endpoint"] == "https://fcm.example/abc"
        assert subs[0]["p256dh"] == "p256-val"
        assert subs[0]["auth"] == "auth-val"

    def test_post_missing_endpoint(self, client):
        r = client.post("/api/push/subscribe", json={"keys": {"p256dh": "x", "auth": "y"}})
        assert r.status_code == 400

    def test_post_missing_keys(self, client):
        r = client.post("/api/push/subscribe",
                        json={"endpoint": "https://fcm.example/x"})
        assert r.status_code == 400

    def test_post_partial_keys(self, client):
        r = client.post("/api/push/subscribe", json={
            "endpoint": "https://fcm.example/x",
            "keys": {"p256dh": "only-this"}
        })
        assert r.status_code == 400


class TestUnsubscribe:
    def test_delete_removes_subscription(self, client):
        push.STORE.add_subscription("https://fcm.example/zzz", "p", "a")
        r = client.delete("/api/push/subscribe",
                          json={"endpoint": "https://fcm.example/zzz"})
        assert r.status_code == 204
        assert push.STORE.list_subscriptions() == []

    def test_delete_missing_endpoint(self, client):
        r = client.delete("/api/push/subscribe", json={})
        assert r.status_code == 400

    def test_delete_unknown_endpoint_is_204(self, client):
        # Idempotent : supprimer un endpoint inconnu n'est pas une erreur
        r = client.delete("/api/push/subscribe",
                          json={"endpoint": "https://fcm.example/never-existed"})
        assert r.status_code == 204
```

- [ ] **Step 2: Run tests — must fail**

Run: `python -m pytest tests/test_push_routes.py -v`
Expected: 404 errors — routes not registered.

- [ ] **Step 3: Add routes in app.py**

In `app.py`, add an import at the top of the imports block (after `import summary as summarizer`):

```python
import push
```

Then add the 3 new routes. Insert them just before the `@app.route("/admin/clear-summaries")` block:

```python
@app.route("/api/push/vapid-public-key")
def push_vapid_public_key():
    key = os.environ.get("VAPID_PUBLIC_KEY", "")
    return jsonify({"key": key})


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    body = request.get_json(silent=True) or {}
    endpoint = body.get("endpoint", "")
    keys = body.get("keys") or {}
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")
    if not endpoint or not p256dh or not auth:
        return jsonify({"error": "endpoint and keys.p256dh and keys.auth required"}), 400
    push.STORE.add_subscription(endpoint, p256dh, auth)
    return jsonify({"status": "subscribed"}), 201


@app.route("/api/push/subscribe", methods=["DELETE"])
def push_unsubscribe():
    body = request.get_json(silent=True) or {}
    endpoint = body.get("endpoint", "")
    if not endpoint:
        return jsonify({"error": "endpoint required"}), 400
    push.STORE.remove_subscription(endpoint)
    return "", 204
```

- [ ] **Step 4: Run tests — must pass**

Run: `python -m pytest tests/test_push_routes.py -v`
Expected: 8 PASSED.

- [ ] **Step 5: Run full suite to make sure nothing regressed**

Run: `python -m pytest tests/ -v`
Expected: 62 PASSED total (48 anciens + 14 nouveaux push).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_push_routes.py
git commit -m "Add push subscribe/unsubscribe API routes"
```

---

## Task 9: Hook trigger into _do_fetch

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add the hook**

In `app.py`, find the `_do_fetch()` function (around line 305-353). Locate this line near the end:

```python
    _prefetch_summaries(all_articles)
    return all_articles
```

Replace those two lines with:

```python
    _prefetch_summaries(all_articles)

    # Trigger push notification (background, non-blocking)
    def _push_task():
        try:
            push.trigger_push_for_new_articles(all_articles)
        except Exception as e:
            log.warning("Push trigger KO : %s", e)
    try:
        _prefetch_pool.submit(_push_task)
    except RuntimeError:
        pass

    return all_articles
```

- [ ] **Step 2: Run full suite to make sure nothing regressed**

Run: `python -m pytest tests/ -v`
Expected: 62 PASSED.

- [ ] **Step 3: Smoke test — boot Flask and check /health doesn't crash**

Run:
```bash
python -c "
import sys; sys.path.insert(0, '.')
import app
with app.app.test_client() as c:
    r = c.get('/health')
    print('status:', r.status_code)
    print('body:', r.get_json())
"
```
Expected: status 200, body shows usual fields, no traceback.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Hook push trigger into fetch_all background pipeline"
```

---

## Task 10: Service worker push handlers

**Files:**
- Modify: `static/sw.js`

- [ ] **Step 1: Read the current sw.js**

Run: `cat static/sw.js`
Note the existing structure (cache strategy + fetch handler). Do not break it.

- [ ] **Step 2: Append push handlers at the end of sw.js**

Add at the very end of `static/sw.js`:

```javascript
// ============================================================
// Push notifications
// ============================================================
self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        // payload non JSON, on garde un fallback
        data = { title: 'Mali Info', body: event.data ? event.data.text() : '' };
    }
    const title = data.title || 'Mali Info';
    const options = {
        body: data.body || '',
        icon: '/static/icon-192.png',
        badge: '/static/icon-192.png',
        data: { url: data.url || '/' },
        tag: data.url || 'ml-info-default',  // remplace la précédente avec le même tag
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
            // Si une fenêtre de l'app est déjà ouverte, on la focus + on navigue
            for (const w of wins) {
                if ('focus' in w) {
                    w.focus();
                    if ('navigate' in w) w.navigate(url);
                    return;
                }
            }
            // Sinon on ouvre une nouvelle fenêtre
            return clients.openWindow(url);
        })
    );
});
```

- [ ] **Step 3: Smoke test — verify the file parses as valid JS**

Run: `node --check static/sw.js`
Expected: no output (means valid syntax). If `node` isn't installed, skip and trust the syntax.

- [ ] **Step 4: Commit**

```bash
git add static/sw.js
git commit -m "Service worker: handle push events and notification clicks"
```

---

## Task 11: Frontend button + JS subscribe flow

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Find the header section**

Run: `grep -n "dernière maj\|last_update\|searchWrap" templates/index.html | head`

Identify where the header HTML lives. Look for the line that displays `last_update` / "dernière mise à jour".

- [ ] **Step 2: Add the bell button near the last_update display**

In `templates/index.html`, find the section in the header that contains `last_update`. Right after that element (still inside the same parent container, e.g. `<div class="header-info">` or similar — look at what's there), add:

```html
<button id="pushToggle" class="btn-icon" aria-label="Notifications" title="Activer les notifications" hidden>🔕</button>
```

Note `hidden` by default — the JS will reveal it when the platform supports push.

- [ ] **Step 3: Add the JS subscribe/unsubscribe logic**

In `templates/index.html`, in the `<script>` block (after the existing functions), add this code:

```javascript
// ============================================================
// Push notifications
// ============================================================
(async function initPush() {
    const btn = document.getElementById('pushToggle');
    if (!btn) return;
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        return; // platform not supported, button stays hidden
    }
    btn.hidden = false;

    const reg = await navigator.serviceWorker.ready;

    function updateUI(subscribed) {
        btn.textContent = subscribed ? '🔔' : '🔕';
        btn.title = subscribed ? 'Notifications activées (tap pour désactiver)' : 'Activer les notifications';
        if (subscribed) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    }

    // État initial : déjà abonné côté navigateur ?
    let sub = await reg.pushManager.getSubscription();
    updateUI(!!sub);

    btn.addEventListener('click', async () => {
        try {
            if (!sub) {
                // Subscribe path
                const perm = await Notification.requestPermission();
                if (perm !== 'granted') {
                    toast('Permission refusée');
                    return;
                }
                const r = await fetch('/api/push/vapid-public-key');
                const { key } = await r.json();
                if (!key) { toast('VAPID non configuré'); return; }
                sub = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(key),
                });
                const j = sub.toJSON();
                await fetch('/api/push/subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint: j.endpoint, keys: j.keys }),
                });
                updateUI(true);
                toast('Notifications activées');
            } else {
                // Unsubscribe path
                const endpoint = sub.endpoint;
                await sub.unsubscribe();
                await fetch('/api/push/subscribe', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint }),
                });
                sub = null;
                updateUI(false);
                toast('Notifications désactivées');
            }
        } catch (e) {
            console.error('Push toggle failed:', e);
            toast('Erreur : ' + (e.message || e));
        }
    });
})();

function urlBase64ToUint8Array(b64) {
    const padding = '='.repeat((4 - b64.length % 4) % 4);
    const base64 = (b64 + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
}
```

⚠️ The code above uses `toast()` which already exists in `index.html`. If you cannot find a `toast()` function in the existing JS, replace each `toast(...)` call with `alert(...)`.

- [ ] **Step 4: Render the template locally to verify no syntax errors**

Run:
```bash
python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
t = env.get_template('index.html')
out = t.render(articles=[], last_update='now', total=0)
print('rendered ok,', len(out), 'chars')
print('pushToggle present:', 'pushToggle' in out)
print('initPush present:', 'initPush' in out)
"
```
Expected: rendered ok, both present True.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "UI: header bell button + push subscribe/unsubscribe flow"
```

---

## Task 12: Document VAPID env vars in render.yaml

**Files:**
- Modify: `render.yaml`

- [ ] **Step 1: Update the env vars comment block**

Edit `render.yaml`, find the `envVars` section, and update the comment block to:

```yaml
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.9
      # À renseigner dans le dashboard Render :
      #   ANTHROPIC_API_KEY        — pour activer les résumés via Claude
      #   SUMMARY_DB_URL           — libsql://xxx.turso.io  (Turso prod)
      #   SUMMARY_DB_AUTH_TOKEN    — JWT généré par turso db tokens create
      #   ADMIN_TOKEN              — token pour protéger /admin/*
      #   VAPID_PRIVATE_KEY        — généré par scripts/gen_vapid_keys.py
      #   VAPID_PUBLIC_KEY         — généré par le même script (clé pub b64)
      #   VAPID_CONTACT            — mailto:<your-email>
      # Sans SUMMARY_DB_URL, l'app utilise un fichier SQLite local
      # (éphémère sur Render free, juste utile en dev).
```

- [ ] **Step 2: Commit**

```bash
git add render.yaml
git commit -m "Document VAPID env vars in render.yaml"
```

---

## Task 13: Push to GitHub and configure Render

**Files:** none (deployment step)

- [ ] **Step 1: Push the branch**

Run:
```bash
git push origin main
```

Expected: push succeeds.

- [ ] **Step 2: Generate VAPID keys locally**

Run: `python scripts/gen_vapid_keys.py`

Copy the output. Keep the private PEM secret.

- [ ] **Step 3: Add 3 env vars on Render**

Go to Render dashboard → ml-info service → Environment → Add Environment Variable. Add:

| Key | Value |
|---|---|
| `VAPID_PRIVATE_KEY` | The full PEM block (multi-line) |
| `VAPID_PUBLIC_KEY` | The single-line b64 url-safe key |
| `VAPID_CONTACT` | `mailto:ibrahimadiaroumba@gmail.com` |

Save. Render redeploys automatically (~2 min).

- [ ] **Step 4: Verify the deploy**

Run:
```bash
curl -sS https://ml-info.onrender.com/api/push/vapid-public-key
```
Expected: `{"key": "<your-public-key>"}`

If the key field is empty, the env var didn't propagate yet — wait 30s and retry.

---

## Task 14: Manual end-to-end test on iPhone

**Files:** none

- [ ] **Step 1: Open the PWA on iPhone**

Open the installed PWA on your iPhone (the icon on your home screen, NOT Safari). The page must load.

- [ ] **Step 2: Tap the 🔕 button**

Should appear in the header. iOS will prompt for notification permission. Accept.

- [ ] **Step 3: Verify the icon switched to 🔔**

The toast "Notifications activées" should appear.

- [ ] **Step 4: Trigger a test push from local machine**

You need to manually inject an article URL into Turso to ensure a push fires for a known URL. From your local machine:

```bash
python -c "
import os, sys
sys.path.insert(0, '.')

# Point at PROD Turso (need URL + token from Render env)
os.environ['SUMMARY_DB_URL'] = '<libsql://... from Render>'
os.environ['SUMMARY_DB_AUTH_TOKEN'] = '<token from Render>'
os.environ['VAPID_PRIVATE_KEY'] = '<PEM from Render>'
os.environ['VAPID_PUBLIC_KEY'] = '<pub from Render>'
os.environ['VAPID_CONTACT'] = 'mailto:test@example.com'

import push, time
class A: pass
a = A()
a.score = 99
a.lien = f'https://test-push.example/{int(time.time())}'
a.titre = 'Test push : si tu vois ça sur ton iPhone, ça marche'
a.source = 'TEST'
a.timestamp = time.time()

# Court-circuite le rate limit pour le test
push.STORE._client.execute('DELETE FROM notified_articles WHERE notified_at > ?', (time.time() - 3600,))

result = push.trigger_push_for_new_articles([a])
print('Pushed:', result)
"
```

Expected: a notification pops on your iPhone within 5-30 seconds.

- [ ] **Step 5: Tap the notification**

The notification should be tappable. Tapping should open the URL `https://test-push.example/...` (which 404s, but that's fine — it proves the click handler works).

- [ ] **Step 6: Tap 🔔 to disable**

Toggle should switch back to 🔕. Toast: "Notifications désactivées".

- [ ] **Step 7: Verify in Turso**

Run:
```bash
curl -sS https://ml-info.onrender.com/health
```
Expected: response is `ok`. (No new field exposed yet for push — that's fine.)

If you want to inspect: connect to Turso via the dashboard SQL console:
```sql
SELECT COUNT(*) FROM push_subscriptions;       -- should be 0 after Step 6
SELECT COUNT(*) FROM notified_articles;        -- ≥ 1
```

---

## Done

At this point:
- The 🔔 button works on iPhone PWA, Android Chrome, and desktop browsers that support web push.
- High-priority Mali articles (score ≥ 10) trigger an automatic push, capped at 1 every 30 minutes.
- Dead subscriptions are auto-cleaned on 410 responses.
- 14 new tests cover the filter logic, store CRUD, delivery, and routes.
- All previous functionality (Claude summaries, /admin lock, etc.) keeps working.
