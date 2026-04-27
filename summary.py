"""
Génération de synthèses pour les articles.

Deux modes :
  - "extractive" (par défaut, gratuit) :
      Récupère le contenu via trafilatura, garde les premières
      phrases significatives, retourne un résumé propre de ~150 mots.
  - "claude" (si ANTHROPIC_API_KEY est défini) :
      Demande à Claude Haiku une synthèse en français de 3-4 phrases.

Cache LRU en mémoire pour éviter de re-fetch à chaque appel.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Optional

log = logging.getLogger("ml_info.summary")

# ----------------------------------------------------------------------
# SummaryStore : cache 2 niveaux (LRU mémoire L1 + libsql/Turso L2)
# ----------------------------------------------------------------------
#
# L1 = OrderedDict en RAM, ~200 entrées, sert les résumés "chauds" en O(1)
#      sans round-trip réseau.
# L2 = base libsql persistante. URL via SUMMARY_DB_URL :
#        - "file:summaries.db" (défaut, dev local) → SQLite local
#        - "libsql://xxx.turso.io" + SUMMARY_DB_AUTH_TOKEN → Turso (prod)
#      Survit aux redémarrages du process Render et au sleep/wake.
#
# Toutes les opérations L2 sont enveloppées dans un try/except : si la
# DB est indisponible, on retombe sur L1 sans planter le service.

class SummaryStore:
    def __init__(self, capacity: int = 200):
        self._mem_capacity = capacity
        self._mem: OrderedDict[str, str] = OrderedDict()
        self._mem_lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._client = None

        url = os.environ.get("SUMMARY_DB_URL", "file:summaries.db")
        token = os.environ.get("SUMMARY_DB_AUTH_TOKEN") or None
        # libsql:// fait du WebSocket (wss://) qui plante en 505 sur Turso
        # depuis certaines versions ; on force le transport HTTP.
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        try:
            import libsql_client
            self._client = libsql_client.create_client_sync(
                url=url, auth_token=token
            )
            self._client.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    url TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    source TEXT,
                    created_at REAL
                )
            """)
            log.info("SummaryStore L2 prêt (%s)", url.split("?")[0])
        except Exception as e:
            log.warning("SummaryStore L2 indisponible (%s) — mémoire seule", e)
            self._client = None

    def _mem_get(self, key: str) -> Optional[str]:
        with self._mem_lock:
            if key not in self._mem:
                return None
            self._mem.move_to_end(key)
            return self._mem[key]

    def _mem_set(self, key: str, value: str) -> None:
        with self._mem_lock:
            if key in self._mem:
                self._mem.move_to_end(key)
            self._mem[key] = value
            if len(self._mem) > self._mem_capacity:
                self._mem.popitem(last=False)

    def get(self, key: str) -> Optional[str]:
        v = self._mem_get(key)
        if v is not None:
            return v
        if self._client is None:
            return None
        try:
            with self._db_lock:
                rs = self._client.execute(
                    "SELECT summary FROM summaries WHERE url = ?", (key,)
                )
            if rs.rows:
                summary = rs.rows[0][0]
                self._mem_set(key, summary)
                return summary
        except Exception as e:
            log.warning("SummaryStore L2 read KO : %s", e)
        return None

    def set(self, key: str, value: str, source: str = "") -> None:
        self._mem_set(key, value)
        if self._client is None:
            return
        try:
            with self._db_lock:
                self._client.execute(
                    "INSERT OR REPLACE INTO summaries(url, summary, source, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (key, value, source, time.time()),
                )
        except Exception as e:
            log.warning("SummaryStore L2 write KO : %s", e)

    def clear(self) -> int:
        with self._mem_lock:
            self._mem.clear()
        if self._client is None:
            return 0
        try:
            with self._db_lock:
                rs = self._client.execute("SELECT COUNT(*) FROM summaries")
                n = int(rs.rows[0][0]) if rs.rows else 0
                self._client.execute("DELETE FROM summaries")
            return n
        except Exception as e:
            log.warning("SummaryStore L2 clear KO : %s", e)
            return 0

    def __len__(self) -> int:
        if self._client is None:
            with self._mem_lock:
                return len(self._mem)
        try:
            with self._db_lock:
                rs = self._client.execute("SELECT COUNT(*) FROM summaries")
            return int(rs.rows[0][0]) if rs.rows else 0
        except Exception:
            with self._mem_lock:
                return len(self._mem)

CACHE = SummaryStore(capacity=200)

# Diagnostic Claude : on retient le dernier statut/erreur pour /health
LAST_CLAUDE_STATUS: dict = {"called": False, "ok": False, "error": None}

# Verrous par URL pour éviter de générer le même résumé deux fois
# en parallèle (évite des fetchs HTTP doublonnés).
_url_locks: dict[str, threading.Lock] = {}
_url_locks_master = threading.Lock()

def _get_url_lock(url: str) -> threading.Lock:
    with _url_locks_master:
        lock = _url_locks.get(url)
        if lock is None:
            lock = threading.Lock()
            _url_locks[url] = lock
        return lock

# ----------------------------------------------------------------------
# Extraction et résumé extractif (mode gratuit)
# ----------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Découpage de phrases francophone simple
_sentence_split = re.compile(r"(?<=[\.!?…])\s+(?=[A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ])")

# Phrases à filtrer (boilerplate fréquent dans la presse)
_boilerplate_patterns = [
    re.compile(r"^lire\s+(aussi|également)\b", re.I),
    re.compile(r"^à\s+lire\b", re.I),
    re.compile(r"^voir\s+aussi\b", re.I),
    re.compile(r"^abonnez[- ]vous", re.I),
    re.compile(r"^(s')?inscri(re|vez)", re.I),
    re.compile(r"^par\s+\w+\s+\w+\s*[\-–]\s*\d", re.I),  # "Par Jean Dupont - 12..."
    re.compile(r"^publié\s+le", re.I),
    re.compile(r"^mis\s+à\s+jour", re.I),
    re.compile(r"©|tous droits réservés", re.I),
    re.compile(r"^crédit\s+(photo|image)", re.I),
    re.compile(r"^\W*$"),  # vide ou ponctuation
    # Bannières de cookies / consentement RGPD
    re.compile(r"accepter\s+(les\s+)?cookies?", re.I),
    re.compile(r"refuser\s+(les\s+)?cookies?", re.I),
    re.compile(r"gérer\s+(mes\s+|vos\s+)?(cookies|préférences|consentement)", re.I),
    re.compile(r"\bconsentement\b", re.I),
    re.compile(r"politique\s+de\s+(cookies|confidentialité)", re.I),
    re.compile(r"\bdonnées\s+personnelles\b.*\b(cookies?|partenaires?)\b", re.I),
    # Placeholders pour contenus tiers (YouTube, Twitter, Instagram…)
    re.compile(r"pour\s+afficher\s+ce\s+contenu", re.I),
    re.compile(r"required\s+part\s+of\s+this\s+site", re.I),
    re.compile(r"this\s+content\s+is\s+(currently\s+)?(unavailable|hosted)", re.I),
    re.compile(r"please\s+(enable|allow|accept|disable)", re.I),
    # Paywalls
    re.compile(r"réservé\s+aux\s+abonnés", re.I),
    re.compile(r"déjà\s+abonné", re.I),
    re.compile(r"poursuivez\s+votre\s+lecture", re.I),
    re.compile(r"créez\s+(un\s+|votre\s+)?compte", re.I),
    # Anti-adblock
    re.compile(r"désactivez?\s+votre\s+(bloqueur|adblock)", re.I),
    re.compile(r"javascript.*(désactivé|disabled|enabled|required)", re.I),
    re.compile(r"une\s+extension\s+de\s+votre\s+navigateur", re.I),
    re.compile(r"extension.*\bbloque(r|nt|)\b", re.I),
    re.compile(r"merci\s+de\s+(la\s+)?désactiver", re.I),
    re.compile(r"semble\s+bloquer", re.I),
    re.compile(r"bloqueur\s+de\s+publicit", re.I),
    re.compile(r"this\s+may\s+be\s+due\s+to\s+a\s+browser\s+extension", re.I),
    re.compile(r"browser\s+extension", re.I),
    re.compile(r"ad[\s-]?block(er)?", re.I),
    re.compile(r"network\s+issue", re.I),
    re.compile(r"\btry\s+(again|reloading)\b", re.I),
    # Réseaux sociaux (boutons partage qui finissent dans le texte)
    re.compile(r"^(partager|tweeter|facebook|whatsapp|linkedin)\b", re.I),
]

# Détection plus globale : si le texte ENTIER ressemble à un mur de
# consentement/paywall, on le rejette (return "" → fallback RSS).
_consent_signals = re.compile(
    r"(accepter\s+(les\s+)?cookies?|consentement|réservé\s+aux\s+abonnés|"
    r"pour\s+afficher\s+ce\s+contenu|required\s+part\s+of\s+this\s+site|"
    r"désactivez?\s+votre\s+(bloqueur|adblock)|javascript|"
    r"une\s+extension\s+de\s+votre\s+navigateur|semble\s+bloquer|"
    r"bloqueur\s+de\s+publicit|browser\s+extension|"
    r"this\s+may\s+be\s+due\s+to|ad[\s-]?block(er)?|network\s+issue)",
    re.I,
)

def _looks_like_consent_wall(text: str) -> bool:
    """True si le texte est trop court ou dominé par du consentement/paywall."""
    if not text:
        return True
    if len(text) < 200:
        # Trop court pour être un vrai article ; et si en plus on y voit un
        # signal de consentement, c'est foutu.
        return bool(_consent_signals.search(text))
    # Texte plus long : on rejette si > 25% des phrases sont du consentement
    matches = len(_consent_signals.findall(text))
    if matches >= 3:
        return True
    return False

def _is_boilerplate(sentence: str) -> bool:
    s = sentence.strip()
    if len(s) < 25:  # phrase trop courte = souvent du bruit
        return True
    if len(s) > 600:  # phrase improbablement longue (souvent un paragraphe non-segmenté)
        return False  # on la garde quand même
    for pat in _boilerplate_patterns:
        if pat.search(s):
            return True
    return False

def _extract_main_text(url: str) -> Optional[str]:
    """Récupère le contenu propre d'une page web. Lazy import de trafilatura."""
    try:
        import trafilatura
    except ImportError:
        log.warning("trafilatura non installé, mode résumé extractif indisponible.")
        return None

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            deduplicate=True,
        )
        if text and _looks_like_consent_wall(text):
            log.info("Mur de consentement/paywall détecté pour %s", url)
            return None
        return text
    except Exception as e:
        log.warning("Échec d'extraction pour %s : %s", url, e)
        return None

def extractive_summary(text: str, max_words: int = 150) -> str:
    """Construit un résumé extractif simple à partir d'un texte.

    Stratégie : on garde les premières phrases substantielles, en filtrant
    le boilerplate, jusqu'à atteindre `max_words` environ. Les articles de
    presse suivent généralement la structure de la pyramide inversée donc
    le lead contient l'essentiel.
    """
    if not text:
        return ""

    # Découpe en phrases
    sentences = _sentence_split.split(text.strip())
    kept: list[str] = []
    word_count = 0

    for s in sentences:
        s = s.strip()
        if _is_boilerplate(s):
            continue
        words = len(s.split())
        if word_count + words > max_words and kept:
            break
        kept.append(s)
        word_count += words
        if word_count >= max_words:
            break

    result = " ".join(kept).strip()
    # Trop court pour être un vrai résumé ? On rend la main au fallback.
    if len(result.split()) < 25:
        return ""
    return result

# ----------------------------------------------------------------------
# Résumé via Claude (mode optionnel)
# ----------------------------------------------------------------------

def _claude_summary(title: str, text: str, source: str) -> Optional[str]:
    """Résume via l'API Anthropic si la clé est disponible."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError as e:
        LAST_CLAUDE_STATUS.update({"called": True, "ok": False,
                                   "error": f"import anthropic: {e}"})
        log.warning("Module anthropic non installé, fallback extractif.")
        return None

    if not text:
        return None

    # Tronque le texte pour éviter de payer trop de tokens
    text_trim = text[:4000]

    LAST_CLAUDE_STATUS["called"] = True
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=(
                "Tu es un assistant de veille spécialisé sur le Mali et le "
                "Sahel. Tu rédiges des synthèses factuelles, neutres, en "
                "français, en 3 à 4 phrases (≈80 mots). Tu mentionnes les "
                "acteurs, lieux et faits clés. Tu n'inventes rien. Tu "
                "n'utilises pas de formules introductives (« cet article "
                "explique que… »)."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Source : {source}\n"
                    f"Titre : {title}\n\n"
                    f"Article :\n{text_trim}\n\n"
                    "Rédige la synthèse."
                ),
            }],
        )
        # Concatène les blocs de texte retournés
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        result = " ".join(parts).strip() or None
        LAST_CLAUDE_STATUS.update({"ok": True, "error": None})
        return result
    except Exception as e:
        LAST_CLAUDE_STATUS.update({"ok": False, "error": f"{type(e).__name__}: {e}"})
        log.warning("Échec Claude pour résumé : %s", e)
        return None

# ----------------------------------------------------------------------
# API publique
# ----------------------------------------------------------------------

def get_summary(url: str, title: str = "", source: str = "",
                fallback_desc: str = "") -> dict:
    """
    Retourne un résumé pour l'URL donnée.
    Réponse : {"summary": str, "source": "cache|claude|extractive|fallback"}
    """
    if not url:
        return {"summary": fallback_desc, "source": "fallback"}

    # Cache hit
    cached = CACHE.get(url)
    if cached is not None:
        return {"summary": cached, "source": "cache"}

    # Verrou pour éviter le doublon de fetch
    lock = _get_url_lock(url)
    with lock:
        # Re-check après acquisition du verrou
        cached = CACHE.get(url)
        if cached is not None:
            return {"summary": cached, "source": "cache"}

        text = _extract_main_text(url)

        # Tentative Claude
        summary = _claude_summary(title, text or "", source)
        mode = "claude"

        # Fallback extractif
        if not summary and text:
            summary = extractive_summary(text)
            mode = "extractive"

        # Fallback ultime : description RSS
        if not summary:
            summary = fallback_desc or ""
            mode = "fallback"

        # On ne persiste pas le fallback "description RSS brute" :
        # ce n'est pas un vrai résumé, et il a déjà l'air dans l'article.
        if summary and mode != "fallback":
            CACHE.set(url, summary, source=mode)

    return {"summary": summary, "source": mode}
