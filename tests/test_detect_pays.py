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
        result = detect_pays(
            "RFI Afrique",
            "Au Mali, les forces à Bamako face à la question sénégalaise"
        )
        assert result == "mali"

    def test_pays_avec_un_seul_match_detecte(self):
        result = detect_pays("France 24 Afrique", "Lomé accueille la médiation")
        assert result == "togo"
