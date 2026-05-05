"""
Traduction EN → FR des articles servis par les sources anglophones.

Périmètre actuel : Al Jazeera Africa et Crisis Group (les autres flux
"africains" servent en fait du français).

Architecture :
  - Cache LRU mémoire 200 entrées indexée par URL article ; un article
    n'est traduit qu'une seule fois sur la durée de vie du process.
  - Pas de persistance L2 : libsql/Turso est cassé sur Render free
    actuellement (cf. PushStore / SummaryStore qui retombent en mémoire).
    Render fait un cold start toutes les ~15 min d'inactivité, on
    accepte de retraduire après reboot.
  - Si la clé ANTHROPIC_API_KEY manque ou si l'appel échoue, on
    renvoie le couple original (titre EN, desc EN) — l'article passe
    quand même, juste pas traduit.

Modèle : Claude Haiku 4.5 (claude-haiku-4-5-20251001).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import OrderedDict
from typing import Optional

log = logging.getLogger("ml_info.translate")

LAST_CLAUDE_STATUS: dict = {"called": False, "ok": None, "error": None}


class TranslationStore:
    def __init__(self, capacity: int = 200):
        self._cap = capacity
        self._mem: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, url: str) -> Optional[tuple[str, str]]:
        with self._lock:
            v = self._mem.get(url)
            if v is not None:
                self._mem.move_to_end(url)
            return v

    def put(self, url: str, title_fr: str, desc_fr: str) -> None:
        with self._lock:
            self._mem[url] = (title_fr, desc_fr)
            self._mem.move_to_end(url)
            while len(self._mem) > self._cap:
                self._mem.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._mem)


STORE = TranslationStore()


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _claude_translate(title_en: str, desc_en: str) -> Optional[tuple[str, str]]:
    """Demande à Claude Haiku titre + description en FR. None si échec."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError as e:
        LAST_CLAUDE_STATUS.update({"called": True, "ok": False,
                                   "error": f"import anthropic: {e}"})
        return None

    desc_trim = desc_en[:1500] if desc_en else ""
    LAST_CLAUDE_STATUS["called"] = True
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=(
                "Tu traduis des articles d'actualité de l'anglais vers le "
                "français pour un agrégateur d'infos sur le Mali. Style "
                "journalistique sobre. Tu conserves les noms propres, "
                "lieux et acronymes (FAMA, JNIM, EIGS, AES…) tels quels. "
                "Tu réponds UNIQUEMENT avec un objet JSON de la forme "
                '{"titre": "...", "description": "..."} — aucun texte avant '
                "ou après, pas de bloc markdown."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Titre anglais : {title_en}\n\n"
                    f"Description anglaise : {desc_trim}\n\n"
                    "Traduis."
                ),
            }],
        )
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        raw = " ".join(parts).strip()
        if not raw:
            LAST_CLAUDE_STATUS.update({"ok": False, "error": "empty response"})
            return None
        # Au cas où Claude colle le JSON dans un bloc ``` ou ajoute du préambule
        m = _JSON_BLOCK_RE.search(raw)
        if not m:
            LAST_CLAUDE_STATUS.update({"ok": False, "error": "no JSON in response"})
            return None
        data = json.loads(m.group(0))
        title_fr = (data.get("titre") or "").strip()
        desc_fr = (data.get("description") or "").strip()
        if not title_fr:
            LAST_CLAUDE_STATUS.update({"ok": False, "error": "missing titre"})
            return None
        LAST_CLAUDE_STATUS.update({"ok": True, "error": None})
        return title_fr, desc_fr
    except Exception as e:
        LAST_CLAUDE_STATUS.update({"ok": False, "error": f"{type(e).__name__}: {e}"})
        log.warning("Échec traduction Claude : %s", e)
        return None


def translate_en_to_fr(url: str, title_en: str, desc_en: str) -> tuple[str, str]:
    """Renvoie (titre_fr, description_fr). Cache par URL ; fallback EN
    si Claude indisponible ou en erreur."""
    cached = STORE.get(url)
    if cached is not None:
        return cached

    result = _claude_translate(title_en, desc_en)
    if result is None:
        # Fallback : on retourne l'original. On ne met PAS en cache pour
        # ré-essayer au prochain fetch.
        return title_en, desc_en

    STORE.put(url, *result)
    return result
