# Multi-pays Afrique de l'Ouest — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer ml-info de "agrégateur Mali" en agrégateur Afrique de l'Ouest couvrant 15 pays, avec sélection du pays dans l'interface (Mali par défaut).

**Architecture:** Chaque article reçoit un champ `pays`. Les sources locales (Seneweb → senegal, etc.) sont taguées directement via `SOURCE_PAYS`. Les sources pan-africaines (RFI, France 24, etc.) sont attribuées par détection d'ancres géographiques dans le titre via `detect_pays()`. Le filtre pays est appliqué côté API (`?pays=mali`) et côté frontend (chips défilantes).

**Tech Stack:** Flask, Python 3, feedparser, pytest, vanilla JS

**Spec :** `docs/superpowers/specs/2026-06-06-multi-pays-design.md`

---

## Fichiers touchés

| Fichier | Action |
|---------|--------|
| `app.py` | Modifier : Article.pays, PAYS_ANCHORS, SOURCE_PAYS, detect_pays(), _ALL_ANCHORS, parse_one_feed(), /api/articles, /api/countries (nouveau), SOURCES |
| `templates/index.html` | Modifier : chips pays, JS country switcher |
| `tests/test_detect_pays.py` | Créer : tests de detect_pays() |
| `tests/test_score_article.py` | Modifier : 3 tests devenus stale |
| `tests/test_api_pays.py` | Créer : tests des endpoints pays |

---

## Task 1 : PAYS_ANCHORS + SOURCE_PAYS + detect_pays()

**Files:**
- Modify: `app.py` (après CATEGORY_ANCHORS, avant _ALL_ANCHORS)
- Create: `tests/test_detect_pays.py`

- [ ] **Étape 1 : Écrire les tests (tests/test_detect_pays.py)**

```python
"""Tests de la fonction detect_pays() et de la config associée."""
import pytest
from app import detect_pays, SOURCE_PAYS, PAYS_ANCHORS


class TestSourceLocale:
    def test_mali_actu_tagged_mali(self):
        assert detect_pays("Mali Actu", "Titre quelconque") == "mali"

    def test_seneweb_tagged_senegal(self):
        assert detect_pays("Seneweb", "N'importe quel titre") == "senegal"

    def test_lefaso_tagged_burkina(self):
        assert detect_pays("Lefaso.net", "Actualité du jour") == "burkina"

    def test_source_pays_covers_all_local_sources(self):
        # Toutes les sources locales doivent avoir un pays déclaré.
        local_sources = [
            "Mali Actu", "Studio Tamani", "Bamada", "Journal du Mali",
            "Seneweb", "Dakaractu", "SenePlus", "Actusen",
            "Abidjan.net", "Fratmat", "Koaci",
            "Lefaso.net", "Burkina24", "Faso7",
            "Tamtaminfo", "Niger Express",
            "Guineematin", "Mosaiqueguinee",
            "Togoweb", "Togo Tribune",
            "Benin Web TV", "La Nation Bénin",
            "Alakhbar", "Cridem",
            "Wakat Séra", "ActuNiger",
        ]
        for src in local_sources:
            assert src in SOURCE_PAYS, f"{src!r} absent de SOURCE_PAYS"


class TestDetectionParAncres:
    def test_titre_senegal_detecte(self):
        assert detect_pays("RFI Afrique", "Élections au Sénégal : Dakar vote") == "senegal"

    def test_titre_cote_ivoire_detecte(self):
        assert detect_pays("France 24 Afrique", "Abidjan accueille le sommet de l'UA") == "cote_ivoire"

    def test_titre_burkina_detecte(self):
        assert detect_pays("RFI Afrique", "Ouagadougou : nouveau bilan des affrontements") == "burkina"

    def test_titre_niger_detecte(self):
        assert detect_pays("BBC Afrique", "Niamey annonce la fin du CNSP") == "niger"

    def test_titre_aucun_match_retourne_vide(self):
        assert detect_pays("RFI Afrique", "Résultats de la Ligue des Champions") == ""

    def test_titre_usa_europe_retourne_vide(self):
        assert detect_pays("France 24 Afrique", "Accord commercial Washington Bruxelles") == ""


class TestMultiPays:
    def test_mali_gagne_si_plus_danchres(self):
        # "mali" + "bamako" vs "senegal" → mali gagne
        result = detect_pays(
            "RFI Afrique",
            "Au Mali, les forces à Bamako face à la question sénégalaise"
        )
        assert result == "mali"

    def test_pays_avec_un_seul_match_detecte(self):
        result = detect_pays("France 24 Afrique", "Lomé accueille la médiation")
        assert result == "togo"
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```
pytest tests/test_detect_pays.py -v
```
Résultat attendu : `ImportError: cannot import name 'detect_pays' from 'app'`

- [ ] **Étape 3 : Ajouter PAYS_ANCHORS dans app.py**

Dans `app.py`, après le bloc `CATEGORY_ANCHORS` (ligne ~238) et avant `_ALL_ANCHORS`, ajouter :

```python
# Ancres géographiques par pays.
# Normalisées à la lecture (sans accents, minuscules) via normalize().
PAYS_ANCHORS: dict[str, set[str]] = {
    "mali": {
        "mali", "malien", "malienne", "maliens", "maliennes",
        "bamako", "kidal", "gao", "tombouctou", "mopti", "segou",
        "sikasso", "kayes", "koulikoro", "taoudeni", "menaka",
        "azawad", "fama", "forces armees maliennes",
        "goita", "assimi", "choguel", "edm", "energie du mali",
        "niono", "douentza", "tessalit", "ansongo", "bourem",
        "dire", "nioro", "kati",
    },
    "senegal": {
        "senegal", "senegalais", "senegalaise",
        "dakar", "thies", "saint-louis", "ziguinchor", "kaolack",
        "touba", "diourbel", "tambacounda", "kolda", "matam",
        "kedougou", "fatick", "louga", "mbour", "rufisque",
        "sonko", "faye", "bassirou", "macky sall", "apr", "pastef",
        "casamance", "mfdc", "senelec", "petrosen",
    },
    "cote_ivoire": {
        "cote d'ivoire", "cote divoire", "ivoirien", "ivoirienne",
        "abidjan", "yamoussoukro", "bouake", "daloa", "san pedro",
        "korhogo", "man", "gagnoa", "odiénne",
        "ouattara", "alassane", "gbagbo", "tidjane",
        "rhdp", "fpi", "pdci", "bedie", "cie", "petroci",
        "port d'abidjan",
    },
    "burkina": {
        "burkina", "burkina faso", "burkinabe",
        "ouagadougou", "bobo-dioulasso", "koudougou",
        "banfora", "ouahigoua", "tenkodogo", "dori", "fada",
        "ibrahim traore", "anfb", "aib", "sonabhy",
        "koglweogo", "vdp", "volontaires pour la defense de la patrie",
    },
    "niger": {
        "niger", "nigerien", "nigerienne",
        "niamey", "zinder", "maradi", "tahoua",
        "agadez", "diffa", "dosso", "tillaberi",
        "tiani", "cnsp", "pnds", "mnsd", "sonidep",
        "nigelec", "arlit", "azawak",
    },
    "guinee": {
        "guinee", "guineen", "guineenne",
        "conakry", "kankan", "kindia", "labe",
        "nzerekore", "mamou", "boke", "faranah",
        "mamadi doumbouya", "cnrd", "rpg", "ufdg",
        "cellou dalein", "friguia", "cbg", "simandou",
    },
    "togo": {
        "togo", "togolais", "togolaise",
        "lome", "sokode", "kpalime", "atakpame",
        "dapaong", "tsevie", "gnassingbe", "faure",
        "unir", "arc", "togotelecom", "ceet", "port de lome",
    },
    "benin": {
        "benin", "beninois", "beninoise",
        "cotonou", "porto-novo", "parakou",
        "abomey", "natitingou", "bohicon", "kandi",
        "talon", "patrice talon", "soneb", "sbee",
        "port de cotonou",
    },
    "mauritanie": {
        "mauritanie", "mauritanien", "mauritanienne",
        "nouakchott", "nouadhibou", "rosso",
        "kaedi", "kiffa", "atar", "nema",
        "ghazouani", "tewfik", "prds", "ufp", "snim",
        "aziz", "ould",
    },
    "gambie": {
        "gambie", "gambien", "gambienne",
        "banjul", "serekunda", "kanifing",
        "barrow", "adama barrow", "grts", "gamtel", "nawec",
    },
    "sierra_leone": {
        "sierra leone", "sierra-leone",
        "freetown", "kenema", "bo", "makeni",
        "bio", "julius maada bio", "slpp", "nassit",
    },
    "liberia": {
        "liberia", "liberien", "liberienne",
        "monrovia", "gbarnga", "buchanan",
        "weah", "george weah", "cdc", "unity party", "lec",
    },
    "ghana": {
        "ghana", "ghaneen", "ghaneenne",
        "accra", "kumasi", "tamale", "sekondi",
        "akufo-addo", "mahama", "ndc", "npp", "gnpc",
        "ashanti", "tema",
    },
    "nigeria": {
        "nigeria", "nigerian", "nigeriane",
        "abuja", "lagos", "kano", "ibadan",
        "port harcourt", "kaduna",
        "tinubu", "bola tinubu", "nnpc",
        "boko haram", "iswap",
    },
    "cap_vert": {
        "cap-vert", "cap vert", "capverdien", "capverdienne",
        "praia", "mindelo", "electra", "tacv", "paicv", "mpd",
    },
    "guinee_bissau": {
        "guinee-bissau", "guinee bissau",
        "bissau", "bafata", "gabu",
        "embalo", "umaro", "paigc", "madem", "prs",
    },
}

# Pays par défaut pour les sources locales.
# Les sources absentes de ce dict sont pan-africaines
# et seront attribuées par détection d'ancres dans le titre.
SOURCE_PAYS: dict[str, str] = {
    # Mali
    "Studio Tamani":    "mali",
    "Mali Web":         "mali",
    "Journal du Mali":  "mali",
    "Bamada":           "mali",
    "MaliJet":          "mali",
    "Mali Actu":        "mali",
    "22 Septembre":     "mali",
    "Nord Sud Journal": "mali",
    "Phileingora":      "mali",
    "Sahel Intelligence": "mali",
    # Sahel existants
    "Wakat Séra":       "burkina",
    "ActuNiger":        "niger",
    # Sénégal
    "Seneweb":          "senegal",
    "Dakaractu":        "senegal",
    "SenePlus":         "senegal",
    "Actusen":          "senegal",
    # Côte d'Ivoire
    "Abidjan.net":      "cote_ivoire",
    "Fratmat":          "cote_ivoire",
    "Koaci":            "cote_ivoire",
    # Burkina Faso
    "Lefaso.net":       "burkina",
    "Burkina24":        "burkina",
    "Faso7":            "burkina",
    # Niger
    "Tamtaminfo":       "niger",
    "Niger Express":    "niger",
    # Guinée
    "Guineematin":      "guinee",
    "Mosaiqueguinee":   "guinee",
    # Togo
    "Togoweb":          "togo",
    "Togo Tribune":     "togo",
    # Bénin
    "Benin Web TV":     "benin",
    "La Nation Bénin":  "benin",
    # Mauritanie
    "Alakhbar":         "mauritanie",
    "Cridem":           "mauritanie",
}
```

- [ ] **Étape 4 : Ajouter detect_pays() dans app.py**

Ajouter la fonction juste après le bloc `SOURCE_PAYS`, avant `_ALL_ANCHORS` :

```python
def detect_pays(source: str, title: str) -> str:
    """Retourne le pays (slug) associé à un article, ou '' si aucun match.

    1. Source locale → pays fixe via SOURCE_PAYS.
    2. Source pan-africaine → on compte les ancres qui matchent dans le
       titre par pays et on retourne celui qui en a le plus.
       En cas d'égalité, le premier dans l'itération dict gagne.
    """
    if source in SOURCE_PAYS:
        return SOURCE_PAYS[source]

    title_norm = normalize(title)
    scores: dict[str, int] = {}
    for pays, anchors in PAYS_ANCHORS.items():
        for anchor in anchors:
            pattern = r"\b" + re.escape(normalize(anchor)) + r"\b"
            if re.search(pattern, title_norm):
                scores[pays] = scores.get(pays, 0) + 1

    if not scores:
        return ""
    return max(scores, key=lambda p: scores[p])
```

- [ ] **Étape 5 : Lancer les tests**

```
pytest tests/test_detect_pays.py -v
```
Résultat attendu : tous PASS.

- [ ] **Étape 6 : Commit**

```bash
git add app.py tests/test_detect_pays.py
git commit -m "feat: add PAYS_ANCHORS, SOURCE_PAYS and detect_pays() for 15 West African countries"
```

---

## Task 2 : Article.pays + _ALL_ANCHORS + parse_one_feed

**Files:**
- Modify: `app.py` (Article dataclass, _ALL_ANCHORS, parse_one_feed)
- Modify: `tests/test_score_article.py` (3 tests stale)

- [ ] **Étape 1 : Écrire le test pour Article.pays**

Ajouter dans `tests/test_detect_pays.py` une nouvelle classe à la fin du fichier :

```python
class TestArticlePays:
    def test_article_has_pays_field(self):
        from app import Article
        a = Article(
            source="Test", titre="Titre", lien="http://x", description="",
            date_iso="2026-01-01T00:00:00+00:00",
            date_affichee="01/01/2026 • 00:00",
            timestamp=0.0, categorie="", score=0, cat_score=0,
        )
        # Le champ pays doit exister avec valeur par défaut vide.
        assert hasattr(a, "pays")
        assert a.pays == ""
```

- [ ] **Étape 2 : Vérifier que le test échoue**

```
pytest tests/test_detect_pays.py::TestArticlePays -v
```
Résultat attendu : `TypeError: Article.__init__() got an unexpected keyword argument 'pays'` ou similaire.

- [ ] **Étape 3 : Ajouter pays à la dataclass Article**

Dans `app.py`, modifier la dataclass `Article` (autour de la ligne 282) :

```python
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
    cat_score: int
    pays: str = ""
```

- [ ] **Étape 4 : Mettre à jour _ALL_ANCHORS**

Remplacer le bloc `_ALL_ANCHORS` existant (lignes ~242-244 dans app.py) :

Ancien code :
```python
_ALL_ANCHORS: set[str] = set(MALI_ANCHORS)
for _anchors in CATEGORY_ANCHORS.values():
    _ALL_ANCHORS.update(_anchors)
```

Nouveau code :
```python
# Union de toutes les ancres géographiques (15 pays) + ancres catégories.
# Sert à l'anchor-check dans score_article() : un article doit mentionner
# au moins un terme de cet ensemble dans son titre pour passer.
_ALL_ANCHORS: set[str] = set()
for _anchors in PAYS_ANCHORS.values():
    _ALL_ANCHORS.update(_anchors)
for _anchors in CATEGORY_ANCHORS.values():
    _ALL_ANCHORS.update(_anchors)
```

Note : `MALI_ANCHORS` peut rester dans le code (il est référencé nulle part ailleurs) ou être supprimé. Le plus propre est de le supprimer, mais le laisser n'a aucune conséquence fonctionnelle.

- [ ] **Étape 5 : Mettre à jour parse_one_feed pour utiliser detect_pays**

Dans `app.py`, dans la fonction `parse_one_feed()`, remplacer le bloc de scoring (après l'appel à `score_article`) :

Ancien code :
```python
score, categorie, cat_score = score_article(title, description)
if score < 4:
    diag["low_score"] += 1
    continue
```

Nouveau code :
```python
score, categorie, cat_score = score_article(title, description)
pays = detect_pays(source, title)

if not pays:
    diag["low_score"] += 1
    continue

# Sources locales (ex. Seneweb) : on garde même si score=0 (pas de mots-clés
# mali-centriques). Sources pan-africaines : on garde seulement si score >= 4.
is_local_source = source in SOURCE_PAYS
if not is_local_source and score < 4:
    diag["low_score"] += 1
    continue
```

- [ ] **Étape 6 : Ajouter pays à la construction de l'Article dans parse_one_feed**

Quelques lignes plus bas dans la même fonction, modifier le constructeur `Article(...)` pour y inclure `pays=pays` :

```python
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
    pays=pays,
))
```

- [ ] **Étape 7 : Mettre à jour 3 tests stale dans test_score_article.py**

Les 3 tests suivants ne sont plus valides après l'élargissement de `_ALL_ANCHORS` et la restriction de l'anchor-check au titre uniquement (commit `e3478f7`). Les remplacer :

**1. `test_no_anchor_returns_zero`** — "Burkina Faso" est maintenant dans `_ALL_ANCHORS` et "attaque" est dans KEYWORDS, donc score > 0. Remplacer par un titre vraiment hors Afrique de l'Ouest :

```python
def test_non_west_african_title_scores_zero(self):
    score, cat, cat_score = score_article(
        "Accord commercial États-Unis — Union Européenne",
        "Washington et Bruxelles finalisent un traité tarifaire majeur."
    )
    assert score == 0
    assert cat == ""
    assert cat_score == 0
```

**2. `test_mali_anchor_in_description_passes`** — depuis le commit `e3478f7`, l'anchor-check n'utilise que le titre. Si "Mali" n'est que dans la description, score = 0. Mettre à jour l'assertion :

```python
def test_anchor_in_description_only_scores_zero(self):
    # Depuis e3478f7, l'ancre doit figurer dans le TITRE, pas seulement la description.
    score, cat, _ = score_article(
        "Nouvelle attaque dans le Sahel",
        "L'événement s'est produit au Mali, près de Mopti."
    )
    assert score == 0
```

**3. `test_category_anchor_alone_is_enough`** — "malienne" est dans la description, pas dans le titre, donc anchor-check sur le titre échoue → score = 0. Mettre à jour :

```python
def test_mali_in_title_with_keyword_passes(self):
    score, cat, _ = score_article(
        "Femafoot : la fédération malienne annonce le calendrier",
        "La fédération malienne de football a publié le programme."
    )
    assert score > 0
```

- [ ] **Étape 8 : Lancer tous les tests**

```
pytest tests/ -v
```
Résultat attendu : tous PASS (en particulier test_detect_pays.py et test_score_article.py).

- [ ] **Étape 9 : Commit**

```bash
git add app.py tests/test_detect_pays.py tests/test_score_article.py
git commit -m "feat: wire detect_pays into parse_one_feed, add Article.pays, update _ALL_ANCHORS"
```

---

## Task 3 : Nouvelles sources Afrique de l'Ouest

**Files:**
- Modify: `app.py` (dict SOURCES)

Pas de tests automatiques : les flux RSS sont externes et peuvent être cassés. On documente les FIXME comme pour les sources maliennes existantes.

- [ ] **Étape 1 : Ajouter les nouvelles sources dans SOURCES**

Dans `app.py`, dans le dict `SOURCES`, ajouter une section après les sources existantes :

```python
    # ---- Sénégal ----
    "Seneweb":          "https://www.seneweb.com/news/rss.php",
    "Dakaractu":        "https://www.dakaractu.com/feed/",
    "SenePlus":         "https://www.seneplus.com/rss.xml",
    "Actusen":          "https://actusen.sn/feed/",
    # ---- Côte d'Ivoire ----
    "Abidjan.net":      "https://news.abidjan.net/rss/",
    "Fratmat":          "https://www.fratmat.info/feed/",
    "Koaci":            "https://koaci.com/feed/",
    # ---- Burkina Faso ----
    "Lefaso.net":       "https://lefaso.net/spip.php?page=backend",
    "Burkina24":        "https://burkina24.com/feed/",
    "Faso7":            "https://faso7.com/feed/",
    # ---- Niger ----
    "Tamtaminfo":       "https://www.tamtaminfo.com/feed/",
    "Niger Express":    "https://nigerexpress.info/feed/",
    # ---- Guinée ----
    "Guineematin":      "https://guineematin.com/feed/",
    "Mosaiqueguinee":   "https://mosaiqueguinee.com/feed/",
    # ---- Togo ----
    "Togoweb":          "https://www.togoweb.net/feed/",
    "Togo Tribune":     "https://togotribune.com/feed/",
    # ---- Bénin ----
    "Benin Web TV":     "https://beninwebtv.com/feed/",
    "La Nation Bénin":  "https://www.lanation.bj/feed/",
    # ---- Mauritanie ----
    "Alakhbar":         "https://alakhbar.info/feed/",
    "Cridem":           "https://www.cridem.org/rss/",
```

> Certains flux peuvent répondre avec du HTML ou être bloqués (Cloudflare, DNS). Documenter les résultats dans `/admin/sources/diag?token=...` après déploiement. Les sources qui échouent recevront un commentaire FIXME comme les sources maliennes existantes.

- [ ] **Étape 2 : Augmenter le pool de workers si besoin**

Dans `app.py`, vérifier la ligne `with ThreadPoolExecutor(max_workers=20)`. Avec ~50 sources au total, passer à `max_workers=25` pour ne pas allonger trop le fetch.

Rechercher dans app.py :
```python
    with ThreadPoolExecutor(max_workers=20) as pool:
```

Remplacer par :
```python
    with ThreadPoolExecutor(max_workers=25) as pool:
```

- [ ] **Étape 3 : Ajuster MAX_ARTICLES**

Avec 15 pays et ~50 sources, le cache peut contenir plus d'articles utiles. Dans app.py :

```python
MAX_ARTICLES = 200  # était 80
```

- [ ] **Étape 4 : Commit**

```bash
git add app.py
git commit -m "feat: add 20 West African sources (Senegal, CI, Burkina, Niger, Guinea, Togo, Benin, Mauritania)"
```

---

## Task 4 : API — /api/articles?pays + /api/countries

**Files:**
- Modify: `app.py` (/api/articles, home, + nouvelle route /api/countries)
- Create: `tests/test_api_pays.py`

- [ ] **Étape 1 : Écrire les tests (tests/test_api_pays.py)**

```python
"""Tests des endpoints pays : /api/articles?pays= et /api/countries."""
import pytest
import json
from app import app as flask_app, Article, CACHE
from dataclasses import asdict


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def seed_cache():
    """Peuple le cache avec quelques articles pour les tests."""
    CACHE["data"] = [
        Article(
            source="Mali Actu", titre="Événement à Bamako", lien="http://mali/1",
            description="desc", date_iso="2026-06-06T10:00:00+00:00",
            date_affichee="06/06/2026 • 10:00", timestamp=1000.0,
            categorie="politique", score=10, cat_score=8, pays="mali",
        ),
        Article(
            source="Seneweb", titre="Résultat sénégalais", lien="http://sn/1",
            description="desc", date_iso="2026-06-06T09:00:00+00:00",
            date_affichee="06/06/2026 • 09:00", timestamp=900.0,
            categorie="politique", score=8, cat_score=6, pays="senegal",
        ),
        Article(
            source="Lefaso.net", titre="Sécurité à Ouagadougou", lien="http://bf/1",
            description="desc", date_iso="2026-06-06T08:00:00+00:00",
            date_affichee="06/06/2026 • 08:00", timestamp=800.0,
            categorie="securite", score=12, cat_score=10, pays="burkina",
        ),
    ]
    CACHE["timestamp"] = 9e9  # cache jamais expiré pendant les tests
    yield
    CACHE["data"] = []
    CACHE["timestamp"] = 0.0


class TestApiArticlesPays:
    def test_default_returns_mali(self, client):
        r = client.get("/api/articles")
        data = r.get_json()
        assert r.status_code == 200
        assert data["count"] == 1
        assert data["articles"][0]["pays"] == "mali"

    def test_pays_senegal_filtre(self, client):
        r = client.get("/api/articles?pays=senegal")
        data = r.get_json()
        assert data["count"] == 1
        assert data["articles"][0]["pays"] == "senegal"

    def test_pays_all_retourne_tout(self, client):
        r = client.get("/api/articles?pays=all")
        data = r.get_json()
        assert data["count"] == 3

    def test_pays_inexistant_retourne_vide(self, client):
        r = client.get("/api/articles?pays=zzzz")
        data = r.get_json()
        assert data["count"] == 0

    def test_articles_ont_champ_pays(self, client):
        r = client.get("/api/articles?pays=all")
        for art in r.get_json()["articles"]:
            assert "pays" in art


class TestApiCountries:
    def test_countries_endpoint_existe(self, client):
        r = client.get("/api/countries")
        assert r.status_code == 200

    def test_countries_retourne_liste(self, client):
        data = client.get("/api/countries").get_json()
        assert "countries" in data
        assert isinstance(data["countries"], list)

    def test_countries_contient_mali(self, client):
        data = client.get("/api/countries").get_json()
        ids = [c["id"] for c in data["countries"]]
        assert "mali" in ids

    def test_countries_count_correct(self, client):
        data = client.get("/api/countries").get_json()
        mali = next(c for c in data["countries"] if c["id"] == "mali")
        assert mali["count"] == 1

    def test_countries_has_label(self, client):
        data = client.get("/api/countries").get_json()
        for c in data["countries"]:
            assert "label" in c
            assert "id" in c
            assert "count" in c
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```
pytest tests/test_api_pays.py -v
```
Résultat attendu : plusieurs FAIL (endpoint manquant, champ pays absent, etc.)

- [ ] **Étape 3 : Modifier /api/articles pour supporter ?pays=**

Dans `app.py`, remplacer la route `api_articles()` :

```python
@app.route("/api/articles")
def api_articles():
    force = request.args.get("refresh") == "1"
    pays_filter = request.args.get("pays", "mali")
    articles = fetch_all(force=force)
    if pays_filter != "all":
        articles = [a for a in articles if a.pays == pays_filter]
    return jsonify({
        "count": len(articles),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "articles": [asdict(a) for a in articles],
    })
```

- [ ] **Étape 4 : Ajouter la route /api/countries**

Ajouter après `api_articles()` dans `app.py` :

```python
_PAYS_LABELS: dict[str, str] = {
    "mali":         "Mali",
    "senegal":      "Sénégal",
    "cote_ivoire":  "Côte d'Ivoire",
    "burkina":      "Burkina Faso",
    "niger":        "Niger",
    "guinee":       "Guinée",
    "togo":         "Togo",
    "benin":        "Bénin",
    "mauritanie":   "Mauritanie",
    "gambie":       "Gambie",
    "sierra_leone": "Sierra Leone",
    "liberia":      "Liberia",
    "ghana":        "Ghana",
    "nigeria":      "Nigeria",
    "cap_vert":     "Cap-Vert",
    "guinee_bissau":"Guinée-Bissau",
}

@app.route("/api/countries")
def api_countries():
    """Renvoie la liste des pays avec leur nombre d'articles dans le cache."""
    articles = fetch_all()
    from collections import Counter
    counts = Counter(a.pays for a in articles if a.pays)
    countries = [
        {
            "id": pays,
            "label": _PAYS_LABELS.get(pays, pays),
            "count": count,
        }
        for pays, count in sorted(counts.items(), key=lambda x: -x[1])
    ]
    return jsonify({"countries": countries})
```

- [ ] **Étape 5 : Lancer les tests**

```
pytest tests/test_api_pays.py -v
```
Résultat attendu : tous PASS.

- [ ] **Étape 6 : Lancer tous les tests**

```
pytest tests/ -v
```
Résultat attendu : tous PASS.

- [ ] **Étape 7 : Commit**

```bash
git add app.py tests/test_api_pays.py
git commit -m "feat: add pays filter to /api/articles and new /api/countries endpoint"
```

---

## Task 5 : Frontend — sélecteur de pays

**Files:**
- Modify: `templates/index.html`

Pas de tests automatiques — vérification visuelle dans le navigateur.

- [ ] **Étape 1 : Ajouter le CSS pour la barre pays**

Dans `templates/index.html`, dans le bloc `<style>`, ajouter après la règle `.chip.active` (environ ligne 179) :

```css
/* ========================== SÉLECTEUR PAYS ========================== */
.pays-bar {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    padding: 8px 0 0;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
}
.pays-bar::-webkit-scrollbar { display: none; }

.pays-chip {
    flex-shrink: 0;
    padding: 5px 11px;
    border-radius: 999px;
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--muted);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
    font-family: inherit;
}
.pays-chip:active { transform: scale(0.95); }
.pays-chip.active {
    background: #1e40af;
    border-color: #3b82f6;
    color: #bfdbfe;
    font-weight: 600;
}
.pays-badge {
    display: inline-block;
    background: rgba(255,255,255,0.15);
    border-radius: 999px;
    padding: 0 5px;
    font-size: 0.68rem;
    margin-left: 3px;
    font-weight: 600;
}
```

- [ ] **Étape 2 : Ajouter le HTML du sélecteur pays dans le header**

Dans `templates/index.html`, dans `<header>`, juste avant la fermeture `</header>` (après le div `.title-bar`), ajouter :

```html
    <div class="pays-bar" id="paysBar">
        <!-- Chips injectés par JS via /api/countries -->
        <button class="pays-chip active" data-pays="mali">Mali</button>
    </div>
```

- [ ] **Étape 3 : Ajouter le JS du sélecteur pays**

Dans `templates/index.html`, dans le bloc `<script>`, ajouter **avant** la fermeture `</script>` :

```javascript
// ============================================================
// Sélecteur de pays
// ============================================================
const PAYS_LABELS = {
    mali: 'Mali', senegal: 'Sénégal', cote_ivoire: "Côte d'Ivoire",
    burkina: 'Burkina Faso', niger: 'Niger', guinee: 'Guinée',
    togo: 'Togo', benin: 'Bénin', mauritanie: 'Mauritanie',
    gambie: 'Gambie', sierra_leone: 'Sierra Leone', liberia: 'Liberia',
    ghana: 'Ghana', nigeria: 'Nigeria', cap_vert: 'Cap-Vert',
    guinee_bissau: 'Guinée-Bissau',
};

let currentPays = localStorage.getItem('mlinfo_pays') || 'mali';

function renderArticleCard(a) {
    const dateRel = relativeDate(a.date_iso);
    const catBadge = a.categorie
        ? `<span class="cat-badge cat-${a.categorie}">${a.categorie}</span>`
        : '';
    return `
<article class="card"
    data-link="${a.lien}"
    data-cat="${a.categorie}"
    data-source="${a.source}"
    data-iso="${a.date_iso}"
    data-title="${a.titre.replace(/"/g, '&quot;')}">
    <div class="card-meta">
        <div>
            <span class="source-tag">${a.source}</span>
            ${catBadge}
        </div>
        <span class="date-rel" data-iso="${a.date_iso}">${dateRel}</span>
    </div>
    <h2 class="card-title">${a.titre}</h2>
    <div class="summary-wrap">
        <div class="summary collapsed">
            <div class="skeleton"></div>
            <div class="skeleton"></div>
            <div class="skeleton"></div>
        </div>
        <div class="summary-source"></div>
    </div>
    <div class="card-actions">
        <button class="btn summary-toggle" style="display:none">Voir plus</button>
        <a class="btn" href="${a.lien}" target="_blank" rel="noopener">Source ↗</a>
        <button class="btn-icon share-btn" title="Partager" aria-label="Partager">⇪</button>
    </div>
</article>`.trim();
}

function attachCardListeners(container) {
    container.querySelectorAll('.share-btn').forEach(btn => {
        btn.addEventListener('click', async e => {
            e.stopPropagation();
            const card = btn.closest('.card');
            const data = {
                title: card.dataset.title,
                text: card.dataset.title + ' — ' + card.dataset.source,
                url: card.dataset.link,
            };
            try {
                if (navigator.share) await navigator.share(data);
                else { await navigator.clipboard.writeText(data.url); toast('Lien copié'); }
            } catch(err) { if (err.name !== 'AbortError') console.warn(err); }
        });
    });
    container.querySelectorAll('.card').forEach(card => io.observe(card));
}

async function switchPays(pays) {
    currentPays = pays;
    localStorage.setItem('mlinfo_pays', pays);

    // Mettre à jour le chip actif
    document.querySelectorAll('.pays-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.pays === pays);
    });

    // Charger les articles du pays sélectionné
    const container = document.getElementById('container');
    container.innerHTML = '<div class="empty"><div class="empty-icon">⏳</div><div>Chargement…</div></div>';

    try {
        const r = await fetch(`/api/articles?pays=${pays}`);
        const data = await r.json();
        if (!data.articles || data.articles.length === 0) {
            container.innerHTML = '<div class="empty"><div class="empty-icon">📭</div><div>Aucun article disponible pour ce pays.</div><div style="margin-top:10px;font-size:0.8rem;">Réessaie dans quelques minutes.</div></div>';
            return;
        }
        container.innerHTML = data.articles.map(renderArticleCard).join('');
        attachCardListeners(container);
        refreshDates();
    } catch(err) {
        console.error('switchPays failed', err);
        toast('Erreur de chargement');
    }
}

async function loadPaysBar() {
    try {
        const r = await fetch('/api/countries');
        const { countries } = await r.json();
        const bar = document.getElementById('paysBar');

        const chips = countries.map(c => {
            const isActive = c.id === currentPays;
            return `<button class="pays-chip${isActive ? ' active' : ''}" data-pays="${c.id}">${c.label}<span class="pays-badge">${c.count}</span></button>`;
        }).join('');
        bar.innerHTML = chips;

        bar.querySelectorAll('.pays-chip').forEach(chip => {
            chip.addEventListener('click', () => switchPays(chip.dataset.pays));
        });

        // Si le pays sauvegardé en localStorage n'est pas Mali, charger ses articles
        if (currentPays !== 'mali') {
            switchPays(currentPays);
        }
    } catch(err) {
        console.warn('Impossible de charger la barre pays:', err);
    }
}

// Initialiser la barre pays au chargement
loadPaysBar();
```

- [ ] **Étape 4 : Mettre à jour le pull-to-refresh pour respecter le pays actif**

Dans `templates/index.html`, remplacer dans la section pull-to-refresh :

Ancien code :
```javascript
        fetch('/api/articles?refresh=1')
            .then(() => location.reload())
```

Nouveau code :
```javascript
        fetch(`/api/articles?refresh=1&pays=${currentPays}`)
            .then(() => switchPays(currentPays))
```

- [ ] **Étape 5 : Vérifier dans le navigateur**

Lancer le serveur localement :
```
python app.py
```
Ouvrir http://localhost:5000 et vérifier :
- La barre de pays s'affiche sous le titre
- Mali est sélectionné par défaut
- Cliquer sur un autre pays charge ses articles
- Le choix persiste après F5

- [ ] **Étape 6 : Commit**

```bash
git add templates/index.html
git commit -m "feat: add West African country selector in header (chips + localStorage persistence)"
```

---

## Vérification finale

- [ ] Lancer tous les tests :
  ```
  pytest tests/ -v
  ```
  Résultat attendu : tous PASS.

- [ ] Pousser sur GitHub et vérifier que Render redéploie sans erreur :
  ```
  git push origin main
  ```

- [ ] Après déploiement, consulter le diag des sources pour identifier les flux cassés :
  ```
  GET https://ml-info.onrender.com/admin/sources/diag?token=<ADMIN_TOKEN>
  ```
  Documenter les nouveaux FIXME dans `app.py`.
