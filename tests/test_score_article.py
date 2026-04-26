"""Tests du scoring d'articles : on vérifie le filtre Mali strict
(MALI_ANCHORS) et le choix de catégorie par poids dominant."""

import pytest

from app import score_article


# ----------------------------------------------------------------------
# Filtre Mali strict : sans ancre Mali, score = 0
# ----------------------------------------------------------------------

class TestMaliAnchorRequired:
    def test_no_mali_anchor_returns_zero(self):
        score, cat = score_article(
            "Attaque djihadiste au Burkina Faso",
            "Une attaque a frappé Ouagadougou hier soir."
        )
        assert score == 0
        assert cat == ""

    def test_sahel_without_mali_returns_zero(self):
        score, cat = score_article(
            "Le Sahel face à la menace terroriste",
            "Niger et Burkina Faso renforcent leur coopération."
        )
        assert score == 0

    def test_mali_anchor_in_title_passes(self):
        score, cat = score_article(
            "Attaque djihadiste au Mali",
            "L'armée a riposté."
        )
        assert score > 0

    def test_mali_anchor_in_description_passes(self):
        score, cat = score_article(
            "Nouvelle attaque dans le Sahel",
            "L'événement s'est produit au Mali, près de Mopti."
        )
        assert score > 0

    def test_bamako_anchor_passes(self):
        score, cat = score_article("Manifestation à Bamako", "Des milliers de personnes")
        assert score > 0

    def test_fama_anchor_passes(self):
        score, cat = score_article("Communiqué des FAMa", "Les forces ont riposté.")
        assert score > 0


# ----------------------------------------------------------------------
# Word boundaries : "Mali" ne doit pas matcher "Malicious"
# ----------------------------------------------------------------------

class TestWordBoundaries:
    def test_mali_does_not_match_malicious(self):
        score, cat = score_article(
            "Malicious software attack",
            "A malicious actor attacked the system."
        )
        assert score == 0

    def test_mali_does_not_match_somalia(self):
        score, cat = score_article(
            "Crisis in Somalia",
            "The situation in Somalia remains tense."
        )
        # "Somalia" contient "mali" mais pas comme mot autonome
        assert score == 0


# ----------------------------------------------------------------------
# Catégorisation : la catégorie avec le score max gagne
# ----------------------------------------------------------------------

class TestCategorisation:
    def test_security_dominant(self):
        score, cat = score_article(
            "Attentat à Bamako : JNIM revendique",
            "Une attaque djihadiste a frappé la capitale malienne."
        )
        assert cat == "securite"
        assert score > 0

    def test_politics_dominant(self):
        score, cat = score_article(
            "Goïta annonce un référendum constitutionnel au Mali",
            "Le président de transition Assimi Goïta a fait une déclaration."
        )
        assert cat == "politique"

    def test_economy_dominant(self):
        # Une seule ancre Mali (regions=5) mais plusieurs mots économie
        # (orpaillage 3 + franc cfa 3 + inflation 2 = 8) → economie l'emporte.
        score, cat = score_article(
            "Crise économique : orpaillage et franc CFA en chute",
            "Au Mali, l'inflation grimpe et l'orpaillage clandestin progresse."
        )
        assert cat == "economie"


# ----------------------------------------------------------------------
# Insensibilité accents et casse
# ----------------------------------------------------------------------

class TestNormalization:
    def test_case_insensitive(self):
        s1, _ = score_article("attaque au mali", "")
        s2, _ = score_article("ATTAQUE AU MALI", "")
        assert s1 == s2 > 0

    def test_accent_insensitive_anchor(self):
        # "ménaka" doit matcher "menaka" et inversement
        s_with_accent, _ = score_article("Tensions à Ménaka", "Affrontements signalés.")
        s_without_accent, _ = score_article("Tensions a Menaka", "Affrontements signales.")
        assert s_with_accent > 0
        assert s_without_accent > 0


# ----------------------------------------------------------------------
# Cas dégénérés
# ----------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_input(self):
        assert score_article("", "") == (0, "")

    def test_only_whitespace(self):
        assert score_article("   ", "  \t ") == (0, "")
