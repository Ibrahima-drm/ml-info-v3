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
