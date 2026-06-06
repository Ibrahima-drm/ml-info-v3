"""Tests des endpoints pays : /api/articles?pays= et /api/countries."""
import pytest
from app import app as flask_app, Article, CACHE


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
