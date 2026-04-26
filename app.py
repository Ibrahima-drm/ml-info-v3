"""
ML_INFO — Backend Flask agrégeant des flux RSS avec scoring de pertinence,
catégorisation, récupération parallèle et synthèses d'articles.
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Iterable

import feedparser
from flask import Flask, jsonify, render_template, request, send_from_directory

import summary as summarizer

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ml_info")

app = Flask(__name__)

SOURCES: dict[str, str] = {
    # Internationaux francophones
    "RFI Afrique":        "https://www.rfi.fr/fr/afrique/rss",
    "France 24 Afrique":  "https://www.france24.com/fr/afrique/rss",
    "Le Monde Afrique":   "https://www.lemonde.fr/afrique/rss_full.xml",
    "Jeune Afrique":      "https://www.jeuneafrique.com/rss/afrique/",
    "BBC Afrique":        "https://www.bbc.com/afrique/index.xml",
    # Maliens
    "Studio Tamani":      "https://www.studiotamani.org/feed/",
    "Mali Web":           "https://www.maliweb.net/feed/",
    "Journal du Mali":    "https://www.journaldumali.com/feed/",
    "Bamada":             "https://bamada.net/feed",
    "Maliactu":           "https://maliactu.net/feed/",
    "MaliJet":            "https://malijet.com/feed",
    # International
    "Al Jazeera Africa":  "https://www.aljazeera.com/xml/rss/africa.xml",
}

KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "securite": [
        ("jnim", 5), ("gsim", 5), ("eigs", 5), ("etat islamique", 5),
        ("daech", 5), ("aqmi", 5), ("katiba", 4), ("djihadiste", 4),
        ("terroriste", 4), ("terrorisme", 4), ("wagner", 4),
        ("africa corps", 4), ("africa korps", 4),
        ("fama", 4), ("forces armées maliennes", 4),
        ("aes", 3), ("alliance des etats du sahel", 4),
        ("minusma", 3), ("g5 sahel", 3),
        ("attaque", 3), ("attentat", 4), ("embuscade", 4),
        ("explosion", 3), ("ied", 4), ("kamikaze", 4),
        ("affrontement", 3), ("assaut", 3), ("frappe", 3),
        ("enlèvement", 3), ("kidnapping", 4), ("otage", 4),
        ("coup d'etat", 4), ("putsch", 4),
    ],
    "politique": [
        ("goita", 3), ("assimi", 3), ("transition", 2),
        ("cnt", 2), ("conseil national de transition", 3),
        ("élection", 3), ("présidentielle", 3),
        ("constitution", 2), ("référendum", 3),
        ("cedeao", 3), ("ecowas", 3), ("uemoa", 2),
        ("ambassadeur", 2), ("diplomatie", 2),
    ],
    "economie": [
        ("économie", 2), ("franc cfa", 3), ("eco", 1),
        ("inflation", 2), ("budget", 2), ("dette", 2),
        ("or", 1), ("orpaillage", 3), ("mine", 2),
        ("coton", 2), ("agriculture", 1),
        ("électricité", 2), ("edm", 3), ("carburant", 3),
    ],
    "geographie": [
        ("mali", 5), ("bamako", 5), ("kidal", 5), ("gao", 5),
        ("tombouctou", 5), ("mopti", 5), ("ségou", 4), ("sikasso", 4),
        ("kayes", 4), ("koulikoro", 3), ("taoudéni", 4), ("ménaka", 5),
        ("azawad", 5), ("liptako", 4), ("gourma", 3),
        ("sahel", 3), ("burkina faso", 2), ("niger", 1),
    ],
}

CACHE: dict = {"data": [], "timestamp": 0.0}
CACHE_DURATION = 180
MAX_AGE_DAYS = 7
MAX_ARTICLES = 80
REQUEST_TIMEOUT = 10
USER_AGENT = "ML_INFO/3.0"

PREFETCH_TOP = 4
PREFETCH_WORKERS = 2

# ----------------------------------------------------------------------
# Modèle
# ----------------------------------------------------------------------

@dataclass
class Article:
    source: str
    titre: str
    lien: str
    description: str
    date_iso: str
    date_affichee: str
    timestamp: float
    categorie: str
    score: int

# ----------------------------------------------------------------------
# Utilitaires texte
# ----------------------------------------------------------------------

_html_re = re.compile(r"<[^>]+>")
_ws_re = re.compile(r"\s+")

def clean_text(html: str) -> str:
    if not html:
        return ""
    txt = _html_re.sub(" ", html)
    txt = _ws_re.sub(" ", txt).strip()
    return txt

def normalize(s: str) -> str:
    s = s.lower()
    accents = (
        ("á", "a"), ("à", "a"), ("â", "a"), ("ä", "a"),
        ("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"),
        ("í", "i"), ("ì", "i"), ("î", "i"), ("ï", "i"),
        ("ó", "o"), ("ò", "o"), ("ô", "o"), ("ö", "o"),
        ("ú", "u"), ("ù", "u"), ("û", "u"), ("ü", "u"),
        ("ç", "c"), ("ñ", "n"),
    )
    for a, b in accents:
        s = s.replace(a, b)
    return s

def score_article(title: str, desc: str) -> tuple[int, str]:
    text = normalize(f"{title} {desc}")
    if not text:
        return 0, ""

    cat_scores: dict[str, int] = {}
    has_anchor = False

    for cat, kws in KEYWORDS.items():
        s = 0
        for kw, weight in kws:
            kw_n = normalize(kw)
            pattern = r"\b" + re.escape(kw_n) + r"\b"
            occurrences = len(re.findall(pattern, text))
            if occurrences:
                s += weight * occurrences
                if cat in ("geographie", "securite"):
                    has_anchor = True
        if s:
            cat_scores[cat] = s

    if not has_anchor:
        return 0, ""

    total = sum(cat_scores.values())
    priority = ["securite", "politique", "economie", "geographie"]
    cat = max(cat_scores, key=lambda c: (cat_scores[c], -priority.index(c)))
    return total, cat

def parse_one_feed(source: str, url: str) -> list[Article]:
    out: list[Article] = []
    try:
        flux = feedparser.parse(
            url,
            agent=USER_AGENT,
            request_headers={"User-Agent": USER_AGENT},
        )
        if flux.bozo and not flux.entries:
            log.warning("Flux invalide %s : %s", source, flux.bozo_exception)
            return out

        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        for entry in flux.entries[:30]:
            title = getattr(entry, "title", "").strip()
            if not title:
                continue

            description = clean_text(
                getattr(entry, "summary", "") or getattr(entry, "description", "")
            )

            score, categorie = score_article(title, description)
            if score < 4:
                continue

            ts_struct = (
                getattr(entry, "published_parsed", None)
                or getattr(entry, "updated_parsed", None)
            )
            if ts_struct:
                dt = datetime.fromtimestamp(mktime(ts_struct), tz=timezone.utc)
            else:
                dt = datetime.now(timezone.utc)

            if dt < cutoff:
                continue

            out.append(Article(
                source=source,
                titre=title,
                lien=getattr(entry, "link", ""),
                description=description[:400],
                date_iso=dt.isoformat(),
                date_affichee=dt.astimezone().strftime("%d/%m/%Y • %H:%M"),
                timestamp=dt.timestamp(),
                categorie=categorie,
                score=score,
            ))
    except Exception as e:
        log.exception("Erreur sur %s : %s", source, e)
    return out

def dedup(articles: Iterable[Article]) -> list[Article]:
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    out: list[Article] = []
    for a in articles:
        if a.lien and a.lien in seen_links:
            continue
        sig = normalize(a.titre)[:60]
        if sig in seen_titles:
            continue
        seen_links.add(a.lien)
        seen_titles.add(sig)
        out.append(a)
    return out

# ----------------------------------------------------------------------
# Précharge des résumés (fire-and-forget)
# ----------------------------------------------------------------------

_prefetch_pool = ThreadPoolExecutor(
    max_workers=PREFETCH_WORKERS, thread_name_prefix="summary"
)

def _prefetch_summaries(articles: list[Article]) -> None:
    for art in articles[:PREFETCH_TOP]:
        if not art.lien:
            continue
        if summarizer.CACHE.get(art.lien) is not None:
            continue

        def task(a=art):
            try:
                summarizer.get_summary(
                    a.lien,
                    title=a.titre,
                    source=a.source,
                    fallback_desc=a.description,
                )
            except Exception as e:
                log.warning("Préchargement résumé KO pour %s : %s", a.lien, e)

        try:
            _prefetch_pool.submit(task)
        except RuntimeError:
            pass

# ----------------------------------------------------------------------
# Cœur : récupération
# ----------------------------------------------------------------------

def fetch_all(force: bool = False) -> list[Article]:
    global CACHE

    if not force and (time.time() - CACHE["timestamp"] < CACHE_DURATION):
        return CACHE["data"]

    log.info("Récupération de %d flux en parallèle...", len(SOURCES))
    t0 = time.time()
    all_articles: list[Article] = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(parse_one_feed, name, url): name
            for name, url in SOURCES.items()
        }
        for fut in as_completed(futures, timeout=REQUEST_TIMEOUT * 2):
            try:
                all_articles.extend(fut.result(timeout=REQUEST_TIMEOUT))
            except Exception as e:
                log.warning("Timeout/erreur %s : %s", futures[fut], e)

    all_articles = dedup(all_articles)
    all_articles.sort(key=lambda x: (x.timestamp, x.score), reverse=True)
    all_articles = all_articles[:MAX_ARTICLES]

    CACHE = {"data": all_articles, "timestamp": time.time()}
    log.info(
        "→ %d articles retenus en %.2fs",
        len(all_articles), time.time() - t0,
    )

    _prefetch_summaries(all_articles)
    return all_articles

# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.route("/")
def home():
    articles = fetch_all()
    sources = sorted({a.source for a in articles})
    categories = sorted({a.categorie for a in articles if a.categorie})
    return render_template(
        "index.html",
        articles=articles,
        sources=sources,
        categories=categories,
        last_update=datetime.now().strftime("%H:%M"),
    )

@app.route("/api/articles")
def api_articles():
    force = request.args.get("refresh") == "1"
    articles = fetch_all(force=force)
    return jsonify({
        "count": len(articles),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "articles": [asdict(a) for a in articles],
    })

@app.route("/api/summary")
def api_summary():
    """
    GET /api/summary?url=<URL>
    Retourne un résumé pour l'article. Génère si absent du cache.
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "param 'url' requis"}), 400

    title = request.args.get("title", "")
    source = request.args.get("source", "")

    fallback = ""
    for art in CACHE.get("data", []):
        if art.lien == url:
            fallback = art.description
            if not title:
                title = art.titre
            if not source:
                source = art.source
            break

    result = summarizer.get_summary(
        url, title=title, source=source, fallback_desc=fallback
    )
    return jsonify(result)

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "cached_articles": len(CACHE["data"]),
        "cached_summaries": len(summarizer.CACHE),
        "cache_age_s": int(time.time() - CACHE["timestamp"]),
        "claude_enabled": bool(os.environ.get("ANTHROPIC_API_KEY")),
    })

# Service worker servi à la racine pour intercepter tout le scope.
@app.route("/sw.js")
def service_worker():
    response = send_from_directory("static", "sw.js")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
