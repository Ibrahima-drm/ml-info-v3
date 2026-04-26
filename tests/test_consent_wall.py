"""Tests de détection de murs de consentement / paywalls / anti-adblock.

Les bannières "Une extension de votre navigateur..." (France24) et
"This may be due to a browser extension" (Africanews EN) ne doivent
PAS être prises pour des résumés d'articles."""

import pytest

from summary import _looks_like_consent_wall


class TestEmptyAndShort:
    def test_empty_string_is_wall(self):
        assert _looks_like_consent_wall("") is True

    def test_short_with_signal_is_wall(self):
        assert _looks_like_consent_wall("Accepter les cookies") is True

    def test_short_without_signal_not_wall(self):
        # 50 chars, pas de signal — pas un mur
        assert _looks_like_consent_wall("Une nouvelle attaque a frappé hier.") is False


class TestCookieAndConsent:
    def test_cookies_banner_french(self):
        text = "Accepter les cookies pour continuer la navigation."
        assert _looks_like_consent_wall(text) is True

    def test_paywall_french(self):
        text = "Cet article est réservé aux abonnés du journal."
        assert _looks_like_consent_wall(text) is True

    def test_embed_placeholder(self):
        text = "Pour afficher ce contenu, veuillez accepter les cookies."
        assert _looks_like_consent_wall(text) is True


class TestAntiAdblock:
    def test_france24_extension_banner(self):
        text = (
            "Une extension de votre navigateur semble bloquer le chargement "
            "de la vidéo. Merci de la désactiver et de recharger la page."
        )
        assert _looks_like_consent_wall(text) is True

    def test_french_adblock_banner(self):
        text = "Pour visionner cette vidéo, votre bloqueur de publicité doit être désactivé."
        assert _looks_like_consent_wall(text) is True

    def test_english_browser_extension(self):
        text = (
            "This may be due to a browser extension, network issues, "
            "or browser settings. Please try the following solutions."
        )
        assert _looks_like_consent_wall(text) is True


class TestRealArticle:
    """Un vrai article doit passer même s'il mentionne en passant un mot
    qui pourrait alarmer (ex: 'cookies' dans un autre contexte)."""

    def test_real_article_passes(self):
        text = (
            "Une attaque djihadiste a frappé hier soir une position de "
            "l'armée malienne à Ménaka. Les FAMa ont riposté pendant "
            "plusieurs heures avant de reprendre le contrôle. Le bilan "
            "provisoire fait état de plusieurs blessés selon une source "
            "militaire. Une enquête sera ouverte dans les prochains jours "
            "pour identifier les responsables. Les habitants de la zone "
            "ont fui vers des localités plus au sud."
        )
        assert _looks_like_consent_wall(text) is False

    def test_long_article_with_one_consent_mention_passes(self):
        # Un article qui mentionne UNE FOIS "cookies" dans son contenu réel
        # ne doit pas être rejeté (seuil = 3 occurrences pour les textes longs)
        text = (
            "Le procès s'est ouvert ce matin à Bamako devant la chambre "
            "criminelle. L'accusation reproche au prévenu d'avoir contourné "
            "le système de cookies de plusieurs banques en ligne pour "
            "soustraire des fonds. La défense plaide la relaxe, arguant "
            "que les preuves numériques sont insuffisantes. L'audience "
            "s'est poursuivie jusqu'en début d'après-midi sans verdict. "
            "Les débats reprendront demain à neuf heures."
        )
        assert _looks_like_consent_wall(text) is False


class TestThreshold:
    """Texte long avec plusieurs signaux de consentement → rejeté."""

    def test_three_signals_triggers(self):
        text = (
            "Accepter les cookies. Pour afficher ce contenu, veuillez "
            "accepter les cookies. Réservé aux abonnés. Une extension "
            "de votre navigateur bloque cette page. Merci de désactiver "
            "votre adblock pour poursuivre. Politique de confidentialité "
            "et gestion du consentement disponibles dans le footer."
        )
        assert _looks_like_consent_wall(text) is True
