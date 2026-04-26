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
        """Timestamp du dernier mark_notified, ou 0.0 si jamais notifié.
        Sert au cap anti-spam (1 push toutes les 30 min)."""
        if self._client is None:
            return 0.0
        with self._lock:
            rs = self._client.execute(
                "SELECT MAX(notified_at) FROM notified_articles"
            )
        v = rs.rows[0][0] if rs.rows else None
        return float(v) if v is not None else 0.0

    def clear_all(self) -> None:
        """Test helper : vide les deux tables."""
        if self._client is None:
            return
        with self._lock:
            self._client.execute("DELETE FROM push_subscriptions")
            self._client.execute("DELETE FROM notified_articles")


# Instance globale, créée au load
STORE = PushStore()


# ----------------------------------------------------------------------
# Trigger : filtres + sélection de l'article à pousser
# ----------------------------------------------------------------------

PUSH_SCORE_THRESHOLD = 10
PUSH_MIN_INTERVAL_SEC = 30 * 60  # 1 push max toutes les 30 min


def select_article_to_push(articles: list) -> Optional[object]:
    """Retourne l'article éligible avec le plus haut score, ou None.

    Filtres dans cet ordre :
      1. liste vide → None
      2. dernier push global < PUSH_MIN_INTERVAL_SEC → None (cap anti-spam)
      3. score ≥ PUSH_SCORE_THRESHOLD
      4. URL pas déjà dans notified_articles
      5. parmi les survivants, prend le score max
    """
    if not articles:
        return None

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

    Returns (nombre envoyés OK, nombre subscriptions mortes supprimées).
    Une subscription qui répond 404/410 est supprimée définitivement.
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
