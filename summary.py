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
from collections import OrderedDict
from typing import Optional

log = logging.getLogger("ml_info.summary")

# ----------------------------------------------------------------------
# Cache LRU thread-safe (URL → résumé)
# ----------------------------------------------------------------------

class LRUCache:
    def __init__(self, capacity: int = 500):
        self.capacity = capacity
        self._d: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            if key not in self._d:
                return None
            self._d.move_to_end(key)
            return self._d[key]

    def set(self, key: str, value: str) -> None:
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
            self._d[key] = value
            if len(self._d) > self.capacity:
                self._d.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)

CACHE = LRUCache(capacity=500)

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
    # Réseaux sociaux (boutons partage qui finissent dans le texte)
    re.compile(r"^(partager|tweeter|facebook|whatsapp|linkedin)\b", re.I),
]

# Détection plus globale : si le texte ENTIER ressemble à un mur de
# consentement/paywall, on le rejette (return "" → fallback RSS).
_consent_signals = re.compile(
    r"(accepter\s+(les\s+)?cookies?|consentement|réservé\s+aux\s+abonnés|"
    r"pour\s+afficher\s+ce\s+contenu|required\s+part\s+of\s+this\s+site|"
    r"désactivez?\s+votre\s+(bloqueur|adblock)|javascript)",
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
    except ImportError:
        log.warning("Module anthropic non installé, fallback extractif.")
        return None

    if not text:
        return None

    # Tronque le texte pour éviter de payer trop de tokens
    text_trim = text[:4000]

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
        return " ".join(parts).strip() or None
    except Exception as e:
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

        if summary:
            CACHE.set(url, summary)

    return {"summary": summary, "source": mode}
