"""Tests du résumé extractif : filtrage du boilerplate et respect de
la limite de mots."""

import pytest

from summary import extractive_summary, _is_boilerplate


class TestEmptyAndTooShort:
    def test_empty_input(self):
        assert extractive_summary("") == ""

    def test_too_short_returns_empty(self):
        # < 25 mots après extraction → on rend la main au fallback
        assert extractive_summary("Phrase trop courte.") == ""


class TestBoilerplateDetection:
    @pytest.mark.parametrize("phrase", [
        "Lire aussi : un autre article",
        "À lire également",
        "Voir aussi notre dossier",
        "Abonnez-vous à notre newsletter",
        "Inscrivez-vous gratuitement",
        "Publié le 12 mars 2024",
        "Mis à jour il y a 2 heures",
        "© Tous droits réservés",
        "Crédit photo : AFP",
        "",
        "...",
        "Accepter les cookies",
        "Pour afficher ce contenu, accepter",
        "Partager sur Twitter",
    ])
    def test_boilerplate_filtered(self, phrase):
        assert _is_boilerplate(phrase) is True

    def test_real_sentence_kept(self):
        sentence = (
            "L'armée malienne a annoncé hier soir avoir mené une opération "
            "de grande envergure contre des groupes armés à Ménaka."
        )
        assert _is_boilerplate(sentence) is False


class TestMaxWords:
    def test_respects_max_words(self):
        # Texte de ~200 mots, limite à 50
        text = " ".join([
            "L'armée malienne a annoncé hier soir avoir mené une opération "
            "de grande envergure contre des groupes armés à Ménaka."
        ] * 10)
        result = extractive_summary(text, max_words=50)
        # Tolérance : on autorise un dépassement d'une phrase
        assert len(result.split()) <= 70

    def test_default_returns_substantial_text(self):
        text = (
            "Une attaque djihadiste a frappé hier soir une position de "
            "l'armée malienne à Ménaka. "
            "Les FAMa ont riposté pendant plusieurs heures avant de "
            "reprendre le contrôle de la zone. "
            "Le bilan provisoire fait état de plusieurs blessés selon "
            "une source militaire proche du dossier. "
            "Une enquête a été ouverte ce matin par les autorités. "
            "Les habitants de la zone ont fui vers des localités plus "
            "au sud du pays."
        )
        result = extractive_summary(text)
        assert len(result) > 50
        assert "Ménaka" in result


class TestBoilerplateStripped:
    def test_lire_aussi_dropped_from_real_article(self):
        text = (
            "L'armée malienne a annoncé une opération à Ménaka contre "
            "les groupes armés actifs dans la région. "
            "Lire aussi : Mali, la situation à Kidal s'aggrave de jour en jour. "
            "Plusieurs combattants ont été neutralisés selon le communiqué officiel. "
            "Une enquête a été ouverte ce matin par les autorités compétentes. "
            "Les habitants ont fui vers le sud en quête de sécurité."
        )
        result = extractive_summary(text)
        assert "Lire aussi" not in result
        assert "Ménaka" in result

    def test_cookie_banner_dropped(self):
        text = (
            "Accepter les cookies pour poursuivre la lecture du site. "
            "L'armée malienne a mené une opération contre les groupes armés "
            "à Ménaka pendant plusieurs heures hier soir. "
            "Plusieurs combattants ont été neutralisés selon les autorités. "
            "Une enquête a été ouverte ce matin par les services compétents. "
            "Les habitants ont fui vers le sud du pays par convois."
        )
        result = extractive_summary(text)
        assert "Accepter les cookies" not in result
