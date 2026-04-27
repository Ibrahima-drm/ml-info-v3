"""Push notifications : stockage des subscriptions et déduplication des articles
notifiés. Tente Turso d'abord, fallback en mémoire si la connexion libsql
échoue (cas connu : libsql_client v0.3 qui plante en WS handshake 505).

Le fallback mémoire est volontairement simple : sur restart Render, les
subscriptions sont perdues et l'utilisateur doit re-tap la cloche. Pour un
usage perso, c'est acceptable."""

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
        self.init_error: Optional[str] = None
        self.init_url: Optional[str] = None

        # Fallback mémoire utilisé quand libsql est indisponible.
        self._mem_subs: dict[str, dict] = {}
        self._mem_notified: dict[str, float] = {}
        self._mem_last_push: float = 0.0

        url = os.environ.get("SUMMARY_DB_URL", "file:summaries.db")
        token = os.environ.get("SUMMARY_DB_AUTH_TOKEN") or None
        self.init_url = url.split("?")[0]
        try:
            import libsql_client
            self._client = libsql_client.create_client_sync(
                url=url, auth_token=token
            )
            self._init_schema()
            log.info("PushStore prêt (%s)", self.init_url)
        except Exception as e:
            self.init_error = f"{type(e).__name__}: {e}"
            log.warning("PushStore L2 indisponible (%s) — fallback mémoire", e)
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
        now = time.time()
        if self._client is None:
            with self._lock:
                self._mem_subs[endpoint] = {
                    "endpoint": endpoint,
                    "p256dh": p256dh,
                    "auth": auth,
                    "created_at": now,
                    "last_seen_at": now,
                }
            return
        with self._lock:
            self._client.execute(
                "INSERT OR REPLACE INTO push_subscriptions"
                "(endpoint, p256dh, auth, created_at, last_seen_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (endpoint, p256dh, auth, now, now),
            )

    def remove_subscription(self, endpoint: str) -> None:
        if self._client is None:
            with self._lock:
                self._mem_subs.pop(endpoint, None)
            return
        with self._lock:
            self._client.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ?",
                (endpoint,),
            )

    def list_subscriptions(self) -> list[dict]:
        if self._client is None:
            with self._lock:
                return [
                    {"endpoint": s["endpoint"], "p256dh": s["p256dh"], "auth": s["auth"]}
                    for s in self._mem_subs.values()
                ]
        with self._lock:
            rs = self._client.execute(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions"
            )
        return [
            {"endpoint": r[0], "p256dh": r[1], "auth": r[2]}
            for r in rs.rows
        ]

    def mark_notified(self, url: str) -> None:
        now = time.time()
        if self._client is None:
            with self._lock:
                self._mem_notified[url] = now
                self._mem_last_push = now
            return
        with self._lock:
            self._client.execute(
                "INSERT OR REPLACE INTO notified_articles(url, notified_at)"
                " VALUES (?, ?)",
                (url, now),
            )

    def is_already_notified(self, url: str) -> bool:
        if self._client is None:
            with self._lock:
                return url in self._mem_notified
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
            with self._lock:
                return self._mem_last_push
        with self._lock:
            rs = self._client.execute(
                "SELECT MAX(notified_at) FROM notified_articles"
            )
        v = rs.rows[0][0] if rs.rows else None
        return float(v) if v is not None else 0.0

    def clear_all(self) -> None:
        """Test helper : vide les deux tables (et le fallback mémoire)."""
        with self._lock:
            self._mem_subs.clear()
            self._mem_notified.clear()
            self._mem_last_push = 0.0
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


# Diagnostic : dernière erreur rencontrée par send_push_to_all, exposée via
# /admin/push/test pour faciliter le debug en prod.
LAST_SEND_ERRORS: list[dict] = []


def send_push_to_all(payload: dict) -> tuple[int, int]:
    """Envoie le payload à toutes les subscriptions stockées.

    Returns (nombre envoyés OK, nombre subscriptions mortes supprimées).
    Une subscription qui répond 404/410 est supprimée définitivement.
    """
    LAST_SEND_ERRORS.clear()
    if webpush is None:
        LAST_SEND_ERRORS.append({"global": "pywebpush not installed"})
        return 0, 0

    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    if not private_key:
        LAST_SEND_ERRORS.append({"global": "VAPID_PRIVATE_KEY not set"})
        log.warning("VAPID_PRIVATE_KEY non défini — push impossible")
        return 0, 0

    # Pré-flight : on tente de valider le PEM tout de suite pour ne pas
    # confondre "clé corrompue" et "endpoint mort".
    LAST_SEND_ERRORS.append({
        "vapid_key_len": len(private_key),
        "vapid_key_starts": private_key[:30],
        "vapid_key_has_newlines": "\n" in private_key,
        "vapid_contact": os.environ.get("VAPID_CONTACT", "<unset>"),
    })

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
            body = ""
            try:
                body = (getattr(e, "response", None).text or "")[:300]
            except Exception:
                pass
            LAST_SEND_ERRORS.append({
                "endpoint_host": sub["endpoint"].split("/")[2] if "//" in sub["endpoint"] else "?",
                "type": "WebPushException",
                "status": status,
                "body": body,
                "msg": str(e)[:300],
            })
            if status in (404, 410):
                STORE.remove_subscription(sub["endpoint"])
                n_dead += 1
                log.info("Subscription morte supprimée : %s", sub["endpoint"])
            else:
                log.warning("Échec push transitoire (%s) : %s", status, e)
        except Exception as e:
            LAST_SEND_ERRORS.append({
                "endpoint_host": sub["endpoint"].split("/")[2] if "//" in sub["endpoint"] else "?",
                "type": type(e).__name__,
                "msg": str(e)[:300],
            })
            log.warning("Échec push inattendu : %s", e)

    return n_sent, n_dead


# ----------------------------------------------------------------------
# Pipeline complète : sélection + envoi + marquage
# ----------------------------------------------------------------------

def _format_payload(article) -> dict:
    """Construit le payload JSON envoyé au service worker.

    Format : title = titre, body = "Source • il y a X min", url = lien.
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
    On marque notifié même si 0 subscription, pour ne pas retenter à chaque
    fetch et saturer les logs.
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

    STORE.mark_notified(chosen.lien)
    return chosen.lien
