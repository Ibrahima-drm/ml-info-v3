"""Tests du scoring d'articles : anchor-check Afrique de l'Ouest
(_ALL_ANCHORS) et choix de catégorie par poids dominant."""

import pytest

from app import score_article


# ----------------------------------------------------------------------
# Filtre Mali strict : sans ancre Mali, score = 0
# ----------------------------------------------------------------------

class TestMaliAnchorRequired:
    def test_non_west_african_title_scores_zero(self):
        score, cat, cat_score = score_article(
            "Accord commercial États-Unis — Union Européenne",
            "Washington et Bruxelles finalisent un traité tarifaire majeur."
        )
        assert score == 0
        assert cat == ""
        assert cat_score == 0

    def test_sahel_without_mali_returns_zero(self):
        score, cat, cat_score = score_article(
            "Le Sahel face à la menace terroriste",
            "Niger et Burkina Faso renforcent leur coopération."
        )
        assert score == 0

    def test_mali_anchor_in_title_passes(self):
        score, cat, _ = score_article(
            "Attaque djihadiste au Mali",
            "L'armée a riposté."
        )
        assert score > 0

    def test_anchor_in_description_only_scores_zero(self):
        # Since e3478f7, the anchor must appear in the TITLE, not just the description.
        score, cat, _ = score_article(
            "Nouvelle attaque dans le Sahel",
            "L'événement s'est produit au Mali, près de Mopti."
        )
        assert score == 0

    def test_bamako_anchor_passes(self):
        score, cat, _ = score_article("Manifestation à Bamako", "Des milliers de personnes")
        assert score > 0

    def test_fama_anchor_passes(self):
        score, cat, _ = score_article("Communiqué des FAMa", "Les forces ont riposté.")
        assert score > 0

    def test_mali_in_title_with_keyword_passes(self):
        score, cat, _ = score_article(
            "Femafoot : la fédération malienne annonce le calendrier",
            "La fédération malienne de football a publié le programme."
        )
        assert score > 0


# ----------------------------------------------------------------------
# Word boundaries : "Mali" ne doit pas matcher "Malicious"
# ----------------------------------------------------------------------

class TestWordBoundaries:
    def test_mali_does_not_match_malicious(self):
        score, cat, _ = score_article(
            "Malicious software attack",
            "A malicious actor attacked the system."
        )
        assert score == 0

    def test_mali_does_not_match_somalia(self):
        score, cat, _ = score_article(
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
        score, cat, cat_score = score_article(
            "Attentat à Bamako : JNIM revendique",
            "Une attaque djihadiste a frappé la capitale malienne."
        )
        assert cat == "securite"
        assert score > 0
        assert cat_score > 0

    def test_politics_dominant(self):
        score, cat, _ = score_article(
            "Goïta annonce un référendum constitutionnel au Mali",
            "Le président de transition Assimi Goïta a fait une déclaration."
        )
        assert cat == "politique"

    def test_economy_dominant(self):
        score, cat, _ = score_article(
            "Crise économique au Mali : orpaillage et franc CFA en chute",
            "L'inflation grimpe et l'orpaillage clandestin progresse."
        )
        assert cat == "economie"

    def test_cat_score_is_dominant_only(self):
        # cat_score = score de la cat dominante (pas le total).
        score, cat, cat_score = score_article(
            "Attentat à Bamako : JNIM revendique",
            "Une attaque djihadiste a frappé la capitale malienne."
        )
        assert cat_score <= score
        assert cat_score > 0


# ----------------------------------------------------------------------
# Insensibilité accents et casse
# ----------------------------------------------------------------------

class TestNormalization:
    def test_case_insensitive(self):
        s1, _, _ = score_article("attaque au mali", "")
        s2, _, _ = score_article("ATTAQUE AU MALI", "")
        assert s1 == s2 > 0

    def test_accent_insensitive_anchor(self):
        # "ménaka" doit matcher "menaka" et inversement
        s_with_accent, _, _ = score_article("Tensions à Ménaka", "Affrontements signalés.")
        s_without_accent, _, _ = score_article("Tensions a Menaka", "Affrontements signales.")
        assert s_with_accent > 0
        assert s_without_accent > 0


# ----------------------------------------------------------------------
# Cas dégénérés
# ----------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_input(self):
        assert score_article("", "") == (0, "", 0)

    def test_only_whitespace(self):
        assert score_article("   ", "  \t ") == (0, "", 0)
