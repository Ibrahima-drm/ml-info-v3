"""
ML_INFO — Backend Flask agrégeant des flux RSS avec scoring de pertinence,
catégorisation, récupération parallèle et synthèses d'articles.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Iterable

import feedparser
from flask import Flask, jsonify, render_template, request, send_from_directory

import summary as summarizer
import push
import translate

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
    "Le Monde Sahel":     "https://www.lemonde.fr/sahel/rss_full.xml",
    "Jeune Afrique":      "https://www.jeuneafrique.com/feed/",  # /rss/afrique/ retournait 404
    "BBC Afrique":        "https://www.bbc.com/afrique/index.xml",
    # Maliens
    "Studio Tamani":      "https://www.studiotamani.org/feed/",
    "Mali Web":           "https://www.maliweb.net/feed/",        # FIXME feed sert du HTML, à retravailler (scrape ou RSSHub)
    "Journal du Mali":    "https://www.journaldumali.com/feed/",
    "Bamada":             "https://bamada.net/feed",
    "MaliJet":            "https://malijet.com/feed",             # FIXME idem Mali Web : HTML servi à la place du RSS
    "Mali Actu":          "https://maliactu.net/feed/",
    "22 Septembre":       "https://www.22septembre.com/feed/",    # FIXME DNS ne résout pas (Errno -2)
    "Nord Sud Journal":   "https://nordsudjournal.com/feed/",     # FIXME Errno 101 Network unreachable
    "Phileingora":        "https://phileingora.com/feed/",        # FIXME DNS ne résout pas
    # L'Essor (lessormali.com) retiré : serveur injoignable depuis Render.
    # Régionaux / Sahel (transfrontalier AES)
    "Sahel Intelligence": "https://sahel-intelligence.com/feed/",
    "Wakat Séra":         "https://www.wakatsera.com/feed/",
    "ActuNiger":          "https://www.actuniger.com/feed/",      # FIXME feedburner brisé (titres sans nom de feed)
    "Crisis Group":       "https://www.crisisgroup.org/rss",
    # Agences internationales
    "VOA Afrique":        "https://www.voaafrique.com/api/epiqq",  # ancienne URL "zmgqoe$omv" était 404
    "DW Afrique":         "https://rss.dw.com/rdf/rss-fr-afri",   # FIXME "no feed by that name", DW a renommé tous ses flux
    "TV5 Monde Afrique":  "https://information.tv5monde.com/rss.xml",  # global (afrique-only retourne 404), keywords filtrent
    "APA News":           "https://apanews.net/feed/",            # FIXME bloqué par Cloudflare (challenge anti-bot)
    "Anadolu Afrique":    "https://www.aa.com.tr/fr/rss/default?cat=afrique",
    # International (panafricain anglo)
    "Al Jazeera Africa":  "https://www.aljazeera.com/xml/rss/all.xml",  # africa.xml retourne 404, all.xml est filtré par keywords
    "Africanews":         "https://fr.africanews.com/feed/rss",
}

# Sources servies en anglais : on traduit titre + description avant
# scoring/affichage. Les autres flux internationaux (BBC Afrique,
# Africanews, Anadolu, Crisis Group fr, etc.) sont déjà en français.
SOURCES_EN: set[str] = {
    "Al Jazeera Africa",
    "Crisis Group",
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
        # Chefs jihadistes
        ("iyad ag ghali", 5), ("amadou koufa", 5),
        ("abou oubeida", 4), ("abou houzeifa", 4),
        # Groupes / mouvements
        ("macina", 4), ("katiba macina", 5), ("ansar dine", 4),
        ("mnla", 4), ("cma", 4), ("gatia", 3), ("plateforme", 3), ("dna", 3),
        # Lieux de conflit
        ("tinzaouatène", 5), ("in-khalil", 5), ("anefis", 4), ("agouni", 4),
        ("andéramboukane", 4), ("farabougou", 5), ("ogossagou", 4),
        ("moura", 4), ("diallassagou", 4), ("bounti", 4),
        # Opérations militaires
        ("opération maliko", 4), ("opération keletigui", 4),
        # Matériel
        ("drone bayraktar", 3), ("akinci", 3), ("su-25", 3), ("hélicoptère", 2),
        # Acteurs externes
        ("russe", 2), ("russie", 2), ("turc", 2), ("iranien", 3),
        # Exactions / droits humains
        ("exaction", 4), ("charnier", 5), ("civils tués", 4),
        ("hrw", 3), ("human rights watch", 3), ("amnesty", 3), ("fidh", 3),
    ],
    "politique": [
        ("goita", 3), ("assimi", 3), ("transition", 2),
        ("cnt", 2), ("conseil national de transition", 3),
        ("élection", 3), ("présidentielle", 3),
        ("constitution", 2), ("référendum", 3),
        ("cedeao", 3), ("ecowas", 3), ("uemoa", 2),
        ("ambassadeur", 2), ("diplomatie", 2),
        # Figures du gouvernement
        ("choguel maïga", 3), ("abdoulaye maïga", 3), ("sadio camara", 2),
        ("ismaël wagué", 3), ("abdoulaye diop", 3), ("alousseni sanou", 3),
        # Opposition / société politique
        ("mahmoud dicko", 4), ("oumar mariko", 3), ("modibo sidibé", 3),
        ("soumeylou boubèye", 3), ("m5-rfp", 3), ("moussa mara", 3),
        # Institutions
        ("aige", 3), ("autorité indépendante de gestion des élections", 4),
        ("haut conseil islamique", 3), ("hci", 3),
        # Concepts processus de transition
        ("refondation", 3), ("charte de la transition", 3),
        ("recensement électoral", 3), ("rave", 2),
        ("fichier électoral", 3), ("assises nationales", 3),
        # Diplomatie
        ("niamey", 2), ("ouagadougou", 2), ("conakry", 2),
        ("abuja", 2), ("addis-abeba", 2),
        ("lavrov", 3), ("poutine", 2), ("erdogan", 2),
        # Sanctions / institutions financières
        ("sanctions", 3), ("embargo", 3), ("fmi", 2), ("banque mondiale", 2),
    ],
    "economie": [
        ("économie", 2), ("franc cfa", 3), ("eco", 1),
        ("inflation", 2), ("budget", 2), ("dette", 2),
        ("or", 1), ("orpaillage", 3), ("mine", 2),
        ("coton", 2), ("agriculture", 1),
        ("électricité", 2), ("edm", 3), ("carburant", 3),
        # Mines / matières premières
        ("barrick", 4), ("b2gold", 4), ("allied gold", 3), ("hummingbird", 3),
        ("fékola", 4), ("loulo", 4), ("gounkoto", 4), ("syama", 4), ("morila", 4),
        ("prix de l'or", 3), ("lithium", 3),
        # Énergie
        ("manantali", 4), ("sotuba", 3), ("kayo", 3),
        # Télécoms
        ("orange mali", 2), ("malitel", 3), ("moov africa", 2), ("sotelma", 2),
        # Banques
        ("bms", 2), ("bdm", 2), ("bnda", 2),
        ("ecobank mali", 2), ("bsic", 2),
        # Transport
        ("aéroport modibo keita", 3), ("sénou", 2), ("dakar-bamako rail", 3),
        # Agriculture
        ("office du niger", 4), ("mil", 1), ("sorgho", 1), ("bétail", 1),
    ],
    "regions": [
        ("mali", 5), ("malien", 4), ("malienne", 4),
        ("bamako", 5), ("kidal", 5), ("gao", 5),
        ("tombouctou", 5), ("mopti", 5), ("ségou", 4), ("sikasso", 4),
        ("kayes", 4), ("koulikoro", 3), ("taoudéni", 4), ("ménaka", 5),
        ("azawad", 5),
        # Cercles supplémentaires
        ("nara", 4), ("bandiagara", 5), ("niono", 4), ("koutiala", 4),
        ("bougouni", 4), ("kati", 4), ("kolokani", 3), ("dioïla", 3),
        ("banamba", 3), ("koro", 4), ("douentza", 5), ("tessalit", 5),
        ("abeibara", 4), ("achouratt", 4), ("ber", 4),
        # Ethnies / communautés linguistiques
        ("dogon", 3), ("peulh", 3), ("touareg", 3),
        ("songhaï", 3), ("bambara", 2), ("sonrhaï", 3),
    ],
    "societe_civile": [
        ("ong", 2), ("société civile", 3), ("syndicat", 2),
        ("untm", 3), ("grève", 3), ("manifestation", 3),
    ],
    "education": [
        ("bac", 2), ("baccalauréat", 3),
        ("def", 3), ("diplôme d'études fondamentales", 3),
        ("université", 2), ("usttb", 3), ("ulshb", 3),
        ("grève des enseignants", 4), ("syndicat enseignant", 3),
        ("untm-éducation", 3),
        ("rentrée scolaire", 3), ("année scolaire", 2),
    ],
    "climat_environnement": [
        ("sécheresse", 3), ("inondation", 4),
        ("crue du niger", 4), ("fleuve niger", 2), ("bani", 2),
        ("déforestation", 2), ("désertification", 3),
        ("changement climatique", 2), ("cop", 1),
    ],
    "infrastructure_quotidien": [
        ("délestage", 4), ("pénurie carburant", 4), ("gaz domestique", 3),
        ("aéroport modibo keita", 3), ("sénou", 2),
        ("bitumage", 2), ("route bamako", 2), ("pont", 1),
        ("sotrama", 2), ("transport urbain", 2),
    ],
}

# Termes "ancres" : un article est gardé UNIQUEMENT si au moins une
# ancre matche. Le filtre garantit que l'article parle bien du Mali et
# pas seulement du Sahel ou d'un pays voisin.
#
# Deux niveaux : MALI_ANCHORS (géographiques, valides pour toutes les
# catégories) et CATEGORY_ANCHORS (spécifiques — ex. "fékola" ancre
# un article économie sans qu'il ait à mentionner "Mali" en clair).
MALI_ANCHORS: set[str] = {
    "mali", "malien", "malienne", "maliens", "maliennes",
    "bamako", "kidal", "gao", "tombouctou", "mopti", "segou",
    "sikasso", "kayes", "koulikoro", "taoudeni", "menaka",
    "azawad", "fama", "forces armees maliennes",
    "goita", "assimi goita", "edm", "energie du mali",
}

CATEGORY_ANCHORS: dict[str, set[str]] = {
    "politique": {
        "choguel maïga", "abdoulaye maïga", "sadio camara",
        "mahmoud dicko", "moussa mara", "soumeylou boubèye",
        "modibo sidibé", "oumar mariko", "m5-rfp",
    },
    "economie": {
        "fékola", "loulo", "gounkoto", "syama", "morila",
        "office du niger", "manantali", "edm",
    },
    "societe_civile": {"untm"},
    "education": {"usttb", "ulshb", "def", "untm-éducation"},
    "infrastructure_quotidien": {"edm", "sénou", "sotrama"},
    "climat_environnement": {"crue du niger", "fleuve niger", "bani"},
}

# Set aplati de toutes les ancres acceptables (géo + toutes catégories),
# normalisé une seule fois au load.
_ALL_ANCHORS: set[str] = set(MALI_ANCHORS)
for _anchors in CATEGORY_ANCHORS.values():
    _ALL_ANCHORS.update(_anchors)

# Ordre de priorité pour départager les égalités sur la catégorie dominante.
# Les catégories en tête ont priorité quand deux scores sont identiques.
CATEGORY_PRIORITY: list[str] = [
    "securite", "politique", "economie",
    "societe_civile", "infrastructure_quotidien", "education",
    "climat_environnement", "regions",
]

CACHE: dict = {"data": [], "timestamp": 0.0}
CACHE_DURATION = 180
MAX_AGE_DAYS = 7
MAX_ARTICLES = 80
REQUEST_TIMEOUT = 8
USER_AGENT = "Mozilla/5.0 (compatible; ML-Info/3.0; +https://ml-info.onrender.com)"

# Borne tous les appels urllib (utilisés par feedparser) à REQUEST_TIMEOUT secondes
# pour éviter qu'une source hang fasse traîner tout le pool.
socket.setdefaulttimeout(REQUEST_TIMEOUT)

PREFETCH_TOP = 4
PREFETCH_WORKERS = 2

# Verrou pour éviter qu'un refresh forcé soit lancé plusieurs fois
# en parallèle (déclencheur stale-while-revalidate)
_refresh_lock = threading.Lock()
_refreshing = {"flag": False}

# Diagnostic du dernier fetch, par source : status, raw_entries, kept, error.
# Mis à jour par parse_one_feed() et _do_fetch(). Exposé via /admin/sources/diag.
_LAST_FETCH_DIAG: dict[str, dict] = {}
_LAST_FETCH_DIAG_LOCK = threading.Lock()

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
    cat_score: int  # score de la catégorie dominante (utilisé par PUSH_THRESHOLDS)

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

def score_article(title: str, desc: str) -> tuple[int, str, int]:
    """Renvoie (score_total, catégorie_dominante, score_catégorie_dominante).

    Filtre d'ancrage : le **titre** de l'article doit matcher au moins un
    terme dans `_ALL_ANCHORS`. On ignore le corps pour ce check parce que
    certains agrégateurs (ex. Mali Actu) collent "Mali" dans les tags
    de fin d'article même quand le sujet est ailleurs (UEMOA, Trump…),
    ce qui faisait passer des articles hors-sujet.
    Le scoring lui-même continue d'utiliser titre + description.
    """
    title_norm = normalize(title)
    text = normalize(f"{title} {desc}")
    if not text:
        return 0, "", 0

    has_anchor = any(
        re.search(r"\b" + re.escape(normalize(a)) + r"\b", title_norm)
        for a in _ALL_ANCHORS
    )
    if not has_anchor:
        return 0, "", 0

    cat_scores: dict[str, int] = {}
    for cat, kws in KEYWORDS.items():
        s = 0
        for kw, weight in kws:
            kw_n = normalize(kw)
            pattern = r"\b" + re.escape(kw_n) + r"\b"
            occurrences = len(re.findall(pattern, text))
            if occurrences:
                s += weight * occurrences
        if s:
            cat_scores[cat] = s

    if not cat_scores:
        return 0, "", 0

    total = sum(cat_scores.values())
    # Tie-break : score le plus haut, puis ordre dans CATEGORY_PRIORITY.
    # Une cat absente de la liste tombe en queue (index = len(priority)).
    def _prio(c: str) -> int:
        try:
            return CATEGORY_PRIORITY.index(c)
        except ValueError:
            return len(CATEGORY_PRIORITY)
    cat = max(cat_scores, key=lambda c: (cat_scores[c], -_prio(c)))
    return total, cat, cat_scores[cat]

def parse_one_feed(source: str, url: str) -> list[Article]:
    out: list[Article] = []
    t0 = time.time()
    diag: dict = {"raw": 0, "low_score": 0, "too_old": 0, "no_title": 0, "error": None}
    try:
        flux = feedparser.parse(
            url,
            agent=USER_AGENT,
            request_headers={"User-Agent": USER_AGENT},
        )
        if flux.bozo and not flux.entries:
            log.warning("Flux invalide %s : %s", source, flux.bozo_exception)
            diag["error"] = f"bozo: {flux.bozo_exception}"
            return out

        diag["raw"] = len(flux.entries)
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        is_en_source = source in SOURCES_EN
        for entry in flux.entries[:80]:
            title = getattr(entry, "title", "").strip()
            if not title:
                diag["no_title"] += 1
                continue

            description = clean_text(
                getattr(entry, "summary", "") or getattr(entry, "description", "")
            )

            # Pour les sources EN, le score est calculé sur le texte original
            # car les ancres "Mali"/"Bamako"/"Goïta" et les noms propres
            # s'écrivent pareil en EN. Ça évite de payer Claude pour 95%
            # d'articles qu'on filtrera ensuite.
            score, categorie, cat_score = score_article(title, description)
            if score < 4:
                diag["low_score"] += 1
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
                diag["too_old"] += 1
                continue

            link = getattr(entry, "link", "")
            if is_en_source:
                # Fallback transparent : si Claude rate, translate_en_to_fr
                # renvoie l'original — l'article passe quand même.
                title, description = translate.translate_en_to_fr(
                    link, title, description
                )

            out.append(Article(
                source=source,
                titre=title,
                lien=link,
                description=description[:400],
                date_iso=dt.isoformat(),
                date_affichee=dt.astimezone().strftime("%d/%m/%Y • %H:%M"),
                timestamp=dt.timestamp(),
                categorie=categorie,
                score=score,
                cat_score=cat_score,
            ))
    except Exception as e:
        log.exception("Erreur sur %s : %s", source, e)
        diag["error"] = f"{type(e).__name__}: {e}"
    finally:
        diag["kept"] = len(out)
        diag["elapsed_ms"] = int((time.time() - t0) * 1000)
        with _LAST_FETCH_DIAG_LOCK:
            _LAST_FETCH_DIAG[source] = diag
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

def _do_fetch() -> list[Article]:
    """Effectue le fetch parallèle, met à jour le cache, déclenche la précharge."""
    global CACHE

    log.info("Récupération de %d flux en parallèle...", len(SOURCES))
    t0 = time.time()
    all_articles: list[Article] = []

    with _LAST_FETCH_DIAG_LOCK:
        _LAST_FETCH_DIAG.clear()

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(parse_one_feed, name, url): name
            for name, url in SOURCES.items()
        }
        # Timeout global : on attend max GLOBAL_TIMEOUT puis on prend ce qu'on a.
        # Si as_completed lève TimeoutError, on récupère quand même les futures
        # qui ont fini, et on jette les autres.
        global_timeout = REQUEST_TIMEOUT * 4
        try:
            for fut in as_completed(futures, timeout=global_timeout):
                try:
                    all_articles.extend(fut.result(timeout=REQUEST_TIMEOUT))
                except Exception as e:
                    log.warning("Timeout/erreur %s : %s", futures[fut], e)
        except TimeoutError:
            log.warning(
                "Timeout global atteint, on continue avec %d sources OK",
                sum(1 for f in futures if f.done()),
            )
            for fut in futures:
                if fut.done() and not fut.cancelled():
                    try:
                        all_articles.extend(fut.result(timeout=0.1))
                    except Exception:
                        pass
                else:
                    fut.cancel()
                    name = futures[fut]
                    with _LAST_FETCH_DIAG_LOCK:
                        if name not in _LAST_FETCH_DIAG:
                            _LAST_FETCH_DIAG[name] = {
                                "raw": 0, "kept": 0, "low_score": 0,
                                "too_old": 0, "no_title": 0,
                                "error": "global_timeout",
                                "elapsed_ms": int((time.time() - t0) * 1000),
                            }

    all_articles = dedup(all_articles)
    all_articles.sort(key=lambda x: (x.timestamp, x.score), reverse=True)
    all_articles = all_articles[:MAX_ARTICLES]

    CACHE = {"data": all_articles, "timestamp": time.time()}
    log.info(
        "→ %d articles retenus en %.2fs",
        len(all_articles), time.time() - t0,
    )

    _prefetch_summaries(all_articles)

    # Trigger push notification (background, non-bloquant) — un seul article
    # poussé par cycle de fetch, filtré par score / dedup / cap 30 min.
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

def _trigger_background_refresh() -> bool:
    """Lance un refresh en tâche de fond si aucun n'est déjà en cours.
    Retourne True si un refresh a été déclenché."""
    with _refresh_lock:
        if _refreshing["flag"]:
            return False
        _refreshing["flag"] = True

    def task():
        try:
            _do_fetch()
        except Exception as e:
            log.warning("Background refresh KO : %s", e)
        finally:
            with _refresh_lock:
                _refreshing["flag"] = False

    try:
        _prefetch_pool.submit(task)
        return True
    except RuntimeError:
        with _refresh_lock:
            _refreshing["flag"] = False
        return False

def fetch_all(force: bool = False) -> list[Article]:
    """Renvoie les articles en cache (ou les récupère si vide).

    - `force=False` : cache valide < CACHE_DURATION → renvoyé direct ; sinon fetch synchrone.
    - `force=True`  : stale-while-revalidate. Si on a déjà des articles en cache,
      on les renvoie immédiatement et on déclenche un refresh en arrière-plan.
      Si le cache est totalement vide, on fait un fetch synchrone (1re visite).
    """
    cache_age = time.time() - CACHE["timestamp"]
    has_cache = bool(CACHE["data"])

    if force and has_cache:
        _trigger_background_refresh()
        return CACHE["data"]

    if not force and cache_age < CACHE_DURATION and has_cache:
        return CACHE["data"]

    return _do_fetch()

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
    # Vérifie si le SDK anthropic est installé (au-delà de la simple présence de la clé)
    try:
        import anthropic  # noqa: F401
        anthropic_sdk = True
    except ImportError:
        anthropic_sdk = False

    return jsonify({
        "status": "ok",
        "cached_articles": len(CACHE["data"]),
        "cached_summaries": len(summarizer.CACHE),
        "cache_age_s": int(time.time() - CACHE["timestamp"]),
        "claude_enabled": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "anthropic_sdk_installed": anthropic_sdk,
        "claude_last_call": summarizer.LAST_CLAUDE_STATUS,
        "cached_translations": len(translate.STORE),
        "translate_last_call": translate.LAST_CLAUDE_STATUS,
        "push_subscriptions": len(push.STORE.list_subscriptions()),
        "push_vapid_configured": bool(os.environ.get("VAPID_PRIVATE_KEY")),
    })

def _require_admin_token():
    """Retourne (response, status) si l'auth échoue, None si OK.

    Le token attendu est lu à chaque requête depuis ADMIN_TOKEN, donc
    une rotation côté Render ne nécessite pas de redéploiement.
    Comparaison constant-time pour éviter les timing attacks.
    """
    expected = os.environ.get("ADMIN_TOKEN", "").strip()
    if not expected:
        return jsonify({"error": "admin disabled (set ADMIN_TOKEN)"}), 503
    provided = (
        request.headers.get("X-Admin-Token", "").strip()
        or request.args.get("token", "").strip()
    )
    if not provided or not hmac.compare_digest(provided, expected):
        return jsonify({"error": "unauthorized"}), 401
    return None


# ----------------------------------------------------------------------
# Push notifications API
# ----------------------------------------------------------------------

@app.route("/api/push/vapid-public-key")
def push_vapid_public_key():
    """Expose la clé publique VAPID pour que le navigateur puisse subscribe()."""
    key = os.environ.get("VAPID_PUBLIC_KEY", "")
    return jsonify({"key": key})


_SUBSCRIBE_DIAG = {
    "post_count": 0,
    "last_body_shape": None,
    "last_endpoint_host": None,
    "last_error": None,
    "last_status": None,
}


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    _SUBSCRIBE_DIAG["post_count"] += 1
    raw = request.get_data(as_text=True) or ""
    try:
        body = request.get_json(silent=True) or {}
        keys = body.get("keys") or {}
        _SUBSCRIBE_DIAG["last_body_shape"] = {
            "endpoint_present": bool(body.get("endpoint")),
            "raw_len": len(raw),
            "top_keys": sorted(list(body.keys())) if isinstance(body, dict) else None,
            "keys_subkeys": sorted(list(keys.keys())) if isinstance(keys, dict) else None,
        }
        endpoint = body.get("endpoint", "")
        if endpoint:
            try:
                from urllib.parse import urlparse
                _SUBSCRIBE_DIAG["last_endpoint_host"] = urlparse(endpoint).hostname
            except Exception:
                _SUBSCRIBE_DIAG["last_endpoint_host"] = "unparseable"
        p256dh = keys.get("p256dh", "")
        auth = keys.get("auth", "")
        if not endpoint or not p256dh or not auth:
            _SUBSCRIBE_DIAG["last_status"] = 400
            _SUBSCRIBE_DIAG["last_error"] = "missing endpoint/p256dh/auth"
            return jsonify({"error": "endpoint and keys.p256dh and keys.auth required"}), 400
        push.STORE.add_subscription(endpoint, p256dh, auth)
        _SUBSCRIBE_DIAG["last_status"] = 201
        _SUBSCRIBE_DIAG["last_error"] = None
        return jsonify({"status": "subscribed"}), 201
    except Exception as e:
        _SUBSCRIBE_DIAG["last_status"] = 500
        _SUBSCRIBE_DIAG["last_error"] = f"{type(e).__name__}: {e}"
        log.exception("subscribe handler crashed")
        return jsonify({"error": "internal"}), 500


@app.route("/api/push/subscribe", methods=["DELETE"])
def push_unsubscribe():
    body = request.get_json(silent=True) or {}
    endpoint = body.get("endpoint", "")
    if not endpoint:
        return jsonify({"error": "endpoint required"}), 400
    push.STORE.remove_subscription(endpoint)
    return "", 204


@app.route("/admin/push/test", methods=["POST", "GET"])
def admin_push_test():
    """Envoie une notification de test à toutes les subscriptions enregistrées.
    Bypasse les filtres de score/dedup. Protégé par ADMIN_TOKEN."""
    auth_err = _require_admin_token()
    if auth_err is not None:
        return auth_err
    payload = {
        "title": "🇲🇱 ML Info — test",
        "body": "Si tu vois ça, les push notifications marchent.",
        "url": "/",
    }
    n_sent, n_dead = push.send_push_to_all(payload)

    # Round-trip storage test : on écrit une ligne, on la relit, on la
    # supprime. Permet de distinguer un PushStore._client = None d'un
    # INSERT silencieusement perdu.
    rt = {
        "client_alive": push.STORE._client is not None,
        "init_error": getattr(push.STORE, "init_error", "n/a"),
        "init_url": getattr(push.STORE, "init_url", "n/a"),
    }
    try:
        push.STORE.add_subscription("__roundtrip__", "rt-p", "rt-a")
        subs = push.STORE.list_subscriptions()
        rt["row_visible_after_insert"] = any(s["endpoint"] == "__roundtrip__" for s in subs)
        rt["total_after_insert"] = len(subs)
        push.STORE.remove_subscription("__roundtrip__")
        rt["error"] = None
    except Exception as e:
        rt["error"] = f"{type(e).__name__}: {e}"

    return jsonify({"sent": n_sent, "dead_removed": n_dead,
                    "total_subs": len(push.STORE.list_subscriptions()),
                    "subscribe_diag": _SUBSCRIBE_DIAG,
                    "store_roundtrip": rt,
                    "send_errors": list(push.LAST_SEND_ERRORS)})


@app.route("/admin/clear-summaries")
def clear_summaries():
    """Vide le cache des résumés (mémoire + DB persistante)."""
    auth_err = _require_admin_token()
    if auth_err is not None:
        return auth_err
    n = summarizer.CACHE.clear()
    return jsonify({"cleared": n})


@app.route("/admin/sources/diag")
def admin_sources_diag():
    """Renvoie le diag par source du dernier fetch.

    Pour chaque source : raw (entrées brutes), kept (gardées après filtres),
    low_score / too_old / no_title (drops), error, elapsed_ms.
    `?refresh=1` force un fetch synchrone neuf avant de renvoyer.
    """
    auth_err = _require_admin_token()
    if auth_err is not None:
        return auth_err
    if request.args.get("refresh") == "1":
        _do_fetch()
    with _LAST_FETCH_DIAG_LOCK:
        diag = dict(_LAST_FETCH_DIAG)
    silent = sorted(
        name for name in SOURCES if name not in diag
    )
    return jsonify({
        "sources_total": len(SOURCES),
        "sources_with_diag": len(diag),
        "never_returned": silent,
        "by_source": diag,
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
