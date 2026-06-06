# Design : Agrégateur multi-pays Afrique de l'Ouest

**Date** : 2026-06-06  
**Projet** : ml-info-v3  
**Statut** : approuvé

---

## Objectif

Transformer ml-info (actuellement centré Mali) en agrégateur panafricain Afrique de l'Ouest couvrant 15 pays, avec sélection du pays dans l'interface. Mali reste le pays par défaut.

---

## Architecture

### Approche retenue : sources taguées + détection par ancres

Chaque article reçoit un champ `pays: str`. L'attribution se fait en deux temps :

1. **Source locale connue** → pays attribué directement via `SOURCE_PAYS` (ex. `"Mali Actu" → "mali"`)
2. **Source pan-africaine** (RFI, France 24, BBC Afrique…) → détection par correspondance d'ancres géographiques dans le titre de l'article via `PAYS_ANCHORS`
3. **Aucun match** → article écarté

Le filtre `_ALL_ANCHORS` actuel est remplacé par cette logique de détection.

---

## Modèle de données

### Article (dataclass)

Ajout d'un champ :
```python
pays: str  # ex. "mali", "senegal", "cote_ivoire"
```

### PAYS_ANCHORS

```python
PAYS_ANCHORS: dict[str, set[str]] = {
    "mali": {
        "mali", "malien", "malienne", "maliens", "maliennes",
        "bamako", "kidal", "gao", "tombouctou", "mopti", "ségou",
        "sikasso", "kayes", "koulikoro", "taoudéni", "ménaka",
        "azawad", "fama", "goïta", "assimi", "choguel", "edm",
        "niono", "douentza", "tessalit", "ansongo", "bourem",
        "diré", "nioro", "kati",
    },
    "senegal": {
        "sénégal", "sénégalais", "sénégalaise", "dakar", "thiès",
        "saint-louis", "ziguinchor", "kaolack", "touba", "diourbel",
        "tambacounda", "kolda", "matam", "kédougou", "fatick",
        "louga", "mbour", "rufisque", "sonko", "faye", "bassirou",
        "macky sall", "apr", "pastef", "casamance", "mfdc",
        "senelec", "petrosen",
    },
    "cote_ivoire": {
        "côte d'ivoire", "ivoirien", "ivoirienne", "abidjan",
        "yamoussoukro", "bouaké", "daloa", "san pédro", "korhogo",
        "man", "gagnoa", "odienné", "ouattara", "alassane", "gbagbo",
        "tidjane", "rhdp", "fpi", "pdci", "bédié", "cie", "petroci",
        "port d'abidjan",
    },
    "burkina": {
        "burkina", "burkina faso", "burkinabè", "ouagadougou",
        "bobo-dioulasso", "koudougou", "banfora", "ouahigouya",
        "tenkodogo", "dori", "fada", "ibrahim traoré", "anfb",
        "aib", "sonabhy", "koglweogo", "vdp",
        "volontaires pour la défense de la patrie",
    },
    "niger": {
        "niger", "nigérien", "nigérienne", "niamey", "zinder",
        "maradi", "tahoua", "agadez", "diffa", "dosso", "tillabéri",
        "tiani", "cnsp", "mnj", "pnds", "mnsd", "sonidep",
        "nigelec", "arlit", "azawak",
    },
    "guinee": {
        "guinée", "guinéen", "guinéenne", "conakry", "kankan",
        "kindia", "labé", "nzérékoré", "mamou", "boké", "faranah",
        "mamadi doumbouya", "cnrd", "rpg", "ufdg", "cellou dalein",
        "friguia", "cbg", "simandou",
    },
    "togo": {
        "togo", "togolais", "togolaise", "lomé", "sokodé",
        "kpalimé", "atakpamé", "dapaong", "tsévié", "gnassingbé",
        "faure", "unir", "arc", "togotelecom", "ceet", "port de lomé",
    },
    "benin": {
        "bénin", "béninois", "béninoise", "cotonou", "porto-novo",
        "parakou", "abomey", "natitingou", "bohicon", "kandi",
        "talon", "patrice talon", "soneb", "sbee", "port de cotonou",
    },
    "mauritanie": {
        "mauritanie", "mauritanien", "mauritanienne", "nouakchott",
        "nouadhibou", "rosso", "kaédi", "kiffa", "atar", "néma",
        "ghazouani", "tewfik", "prds", "ufp", "snim", "aziz", "ould",
    },
    "gambie": {
        "gambie", "gambien", "gambienne", "banjul", "serekunda",
        "kanifing", "barrow", "adama barrow", "grts", "gamtel", "nawec",
    },
    "sierra_leone": {
        "sierra leone", "sierra-léone", "freetown", "kenema", "bo",
        "makeni", "bio", "julius maada bio", "slpp", "apc", "nassit",
    },
    "liberia": {
        "liberia", "libérien", "libérienne", "monrovia", "gbarnga",
        "buchanan", "weah", "george weah", "cdc", "unity party",
        "lprc", "lec",
    },
    "ghana": {
        "ghana", "ghanéen", "ghanéenne", "accra", "kumasi", "tamale",
        "sekondi", "akufo-addo", "mahama", "ndc", "npp", "gnpc",
        "ashanti", "tema",
    },
    "nigeria": {
        "nigeria", "nigérian", "nigériane", "abuja", "lagos", "kano",
        "ibadan", "port harcourt", "kaduna", "tinubu", "bola tinubu",
        "nnpc", "boko haram", "iswap",
    },
    "cap_vert": {
        "cap-vert", "cap vert", "capverdien", "capverdienne", "praia",
        "mindelo", "electra", "tacv", "paicv", "mpd",
    },
    "guinee_bissau": {
        "guinée-bissau", "guinéen-bissauien", "bissau", "bafatá",
        "gabu", "embalo", "umaro", "paigc", "madem", "prs",
    },
}
```

### SOURCE_PAYS

Sources locales taguées directement (pas de détection nécessaire) :

```python
SOURCE_PAYS: dict[str, str] = {
    # Mali (sources existantes)
    "Studio Tamani":      "mali",
    "Mali Web":           "mali",
    "Journal du Mali":    "mali",
    "Bamada":             "mali",
    "MaliJet":            "mali",
    "Mali Actu":          "mali",
    "22 Septembre":       "mali",
    "Nord Sud Journal":   "mali",
    "Phileingora":        "mali",
    "Sahel Intelligence": "mali",
    # Nouvelles sources locales
    "Seneweb":            "senegal",
    "Dakaractu":          "senegal",
    "SenePlus":           "senegal",
    "Actusen":            "senegal",
    "Abidjan.net":        "cote_ivoire",
    "Fratmat":            "cote_ivoire",
    "Koaci":              "cote_ivoire",
    "Lefaso.net":         "burkina",
    "Burkina24":          "burkina",
    "Faso7":              "burkina",
    "Tamtaminfo":         "niger",
    "Niger Express":      "niger",
    "Guineematin":        "guinee",
    "Mosaiqueguinee":     "guinee",
    "Togoweb":            "togo",
    "Togo Tribune":       "togo",
    "Benin Web TV":       "benin",
    "La Nation Bénin":    "benin",
    "Alakhbar":           "mauritanie",
    "Cridem":             "mauritanie",
    # Sources Sahel existantes
    "Wakat Séra":         "burkina",
    "ActuNiger":          "niger",
    # Sources pan-africaines → détection par ancres (pas dans SOURCE_PAYS)
    # RFI, France 24, BBC Afrique, Al Jazeera, Crisis Group, etc. → idem
}
```

---

## Logique de détection pays

Dans `parse_one_feed`, après le scoring de l'article :

```python
def detect_pays(source: str, title: str) -> str:
    # 1. Source locale connue
    if source in SOURCE_PAYS:
        return SOURCE_PAYS[source]
    # 2. Détection par ancres dans le titre : on compte les matches par pays
    #    et on retourne celui qui en a le plus (gère les titres multi-pays).
    title_norm = normalize(title)
    scores: dict[str, int] = {}
    for pays, anchors in PAYS_ANCHORS.items():
        for anchor in anchors:
            if re.search(r"\b" + re.escape(normalize(anchor)) + r"\b", title_norm):
                scores[pays] = scores.get(pays, 0) + 1
    if not scores:
        return ""  # article écarté
    return max(scores, key=lambda p: scores[p])
```

Le filtre `_ALL_ANCHORS` est supprimé. `score_article()` ne change pas (catégories universelles).

---

## Nouvelles sources RSS

| Pays | Source | URL RSS |
|------|--------|---------|
| Sénégal | Seneweb | https://www.seneweb.com/news/rss.php |
| Sénégal | Dakaractu | https://www.dakaractu.com/feed/ |
| Sénégal | SenePlus | https://www.seneplus.com/rss.xml |
| Sénégal | Actusen | https://actusen.sn/feed/ |
| Côte d'Ivoire | Abidjan.net | https://news.abidjan.net/rss/ |
| Côte d'Ivoire | Fratmat | https://www.fratmat.info/feed/ |
| Côte d'Ivoire | Koaci | https://koaci.com/feed/ |
| Burkina Faso | Lefaso.net | https://lefaso.net/spip.php?page=backend |
| Burkina Faso | Burkina24 | https://burkina24.com/feed/ |
| Burkina Faso | Faso7 | https://faso7.com/feed/ |
| Niger | Tamtaminfo | https://www.tamtaminfo.com/feed/ |
| Niger | Niger Express | https://nigerexpress.info/feed/ |
| Guinée | Guineematin | https://guineematin.com/feed/ |
| Guinée | Mosaiqueguinee | https://mosaiqueguinee.com/feed/ |
| Togo | Togoweb | https://www.togoweb.net/feed/ |
| Togo | Togo Tribune | https://togotribune.com/feed/ |
| Bénin | Benin Web TV | https://beninwebtv.com/feed/ |
| Bénin | La Nation Bénin | https://www.lanation.bj/feed/ |
| Mauritanie | Alakhbar | https://alakhbar.info/feed/ |
| Mauritanie | Cridem | https://www.cridem.org/rss/ |

> Certains flux peuvent être cassés à la vérification — documenter en FIXME comme les sources maliennes existantes.

---

## API

### Modification de `/api/articles`

```
GET /api/articles?pays=mali       → articles Mali uniquement
GET /api/articles?pays=senegal    → articles Sénégal uniquement
GET /api/articles                 → par défaut : mali
GET /api/articles?pays=all        → tous pays confondus (admin/debug)
```

Le paramètre `pays` filtre côté serveur avant de renvoyer le JSON.

### Modification de `/`

La route home passe `pays` au template (défaut `mali`), le template lit `?pays=` depuis l'URL ou `localStorage`.

### `/api/countries`

Nouvel endpoint qui renvoie la liste des pays disponibles avec leur nombre d'articles dans le cache courant :

```json
{
  "countries": [
    {"id": "mali", "label": "Mali", "count": 47},
    {"id": "senegal", "label": "Sénégal", "count": 12},
    ...
  ]
}
```

---

## Interface utilisateur

### Sélecteur de pays

Barre de chips défilable horizontalement, au-dessus des filtres catégorie existants :

```
🌍 [Mali 47] [Sénégal 12] [Côte d'Ivoire 8] [Burkina Faso 6] ...
```

- Mali sélectionné par défaut
- Un seul pays actif à la fois
- Choix sauvegardé en `localStorage` sous la clé `mlinfo_pays`
- Scroll horizontal natif sur mobile
- Badge avec nombre d'articles par pays (chargé via `/api/countries`)

### Comportement

- Clic pays → `fetch('/api/articles?pays=X')` → remplace la liste
- Les filtres catégorie existants s'appliquent en plus du filtre pays
- Le titre de la page et le `<h1>` restent "ML Info" (pas de rename par pays)

---

## Ce qui ne change pas

- Logique de scoring (`score_article`) — universelle, inchangée
- Push notifications — continuent sur Mali uniquement pour l'instant
- Catégories (`KEYWORDS`, `CATEGORY_PRIORITY`) — universelles
- Cache (`CACHE_DURATION`, `MAX_ARTICLES`) — inchangés
- Résumés et traductions — inchangés
- Déduplication — inchangée
