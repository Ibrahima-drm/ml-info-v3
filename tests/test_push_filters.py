"""Tests de la logique de filtrage du trigger push :
score ≥ 10, pas déjà notifié, dernier push > 30 min."""

import time

import pytest

from push import select_article_to_push, STORE


def make_article(
    cat_score=12,
    categorie="politique",
    lien="https://example.com/a",
    titre="Article test",
    score=None,
):
    """Mini Article-like object (juste les attributs lus par le trigger).

    Par défaut on simule un article catégorie 'politique' (seuil push 10),
    avec cat_score=12 → éligible. Le score total est aligné si non précisé.
    """
    class A:
        pass
    a = A()
    a.cat_score = cat_score
    a.categorie = categorie
    a.score = cat_score if score is None else score
    a.lien = lien
    a.titre = titre
    a.source = "Test Source"
    a.timestamp = time.time()
    return a


class TestFilters:
    def test_no_articles_returns_none(self):
        assert select_article_to_push([]) is None

    def test_politique_below_threshold_skipped(self):
        # politique seuil = 10, cat_score 9 → rejeté
        a = make_article(cat_score=9, categorie="politique")
        assert select_article_to_push([a]) is None

    def test_politique_above_threshold_passes(self):
        a = make_article(cat_score=10, categorie="politique")
        assert select_article_to_push([a]) is a

    def test_securite_lower_threshold(self):
        # sécurité seuil = 8 (plus bas que politique)
        a = make_article(cat_score=8, categorie="securite")
        assert select_article_to_push([a]) is a

    def test_sport_higher_threshold(self):
        # sport seuil = 15. cat_score 12 (qui passerait pour politique) rejeté.
        a = make_article(cat_score=12, categorie="sport")
        assert select_article_to_push([a]) is None

    def test_already_notified_skipped(self):
        a = make_article(cat_score=15, lien="https://example.com/already")
        STORE.mark_notified(a.lien)
        assert select_article_to_push([a]) is None

    def test_recent_push_blocks_all(self, monkeypatch):
        monkeypatch.setattr(STORE, "last_push_at", lambda: time.time() - 5 * 60)
        a = make_article(cat_score=15)
        assert select_article_to_push([a]) is None

    def test_old_push_does_not_block(self, monkeypatch):
        monkeypatch.setattr(STORE, "last_push_at", lambda: time.time() - 31 * 60)
        a = make_article(cat_score=15)
        assert select_article_to_push([a]) is a

    def test_picks_highest_margin_above_threshold(self):
        # Margin = cat_score - seuil. On veut le plus "fort" relativement.
        # securite cat_score 12 → margin 4
        # politique cat_score 18 → margin 8 (gagne)
        # economie cat_score 11 → margin 1
        sec = make_article(cat_score=12, categorie="securite",
                           lien="https://example.com/sec")
        pol = make_article(cat_score=18, categorie="politique",
                           lien="https://example.com/pol")
        eco = make_article(cat_score=11, categorie="economie",
                           lien="https://example.com/eco")
        assert select_article_to_push([sec, pol, eco]) is pol

    def test_skips_below_threshold_keeps_above(self):
        low = make_article(cat_score=8, categorie="politique",
                           lien="https://example.com/low")
        ok = make_article(cat_score=11, categorie="politique",
                          lien="https://example.com/ok")
        assert select_article_to_push([low, ok]) is ok


class TestDelivery:
    """Tests du dispatcher : on mocke webpush() pour vérifier le routing
    sans envoyer de vraies notifs."""

    def test_send_to_all_subscriptions(self, monkeypatch):
        from push import send_push_to_all, STORE

        sent = []
        def fake_webpush(subscription_info, data, vapid_private_key,
                         vapid_claims, **kwargs):
            sent.append(subscription_info["endpoint"])
            class R:
                status_code = 201
            return R()

        monkeypatch.setattr("push.webpush", fake_webpush)

        STORE.add_subscription("https://fcm.example/a", "p1", "a1")
        STORE.add_subscription("https://fcm.example/b", "p2", "a2")

        n_sent, n_dead = send_push_to_all({"title": "T", "body": "B", "url": "/x"})
        assert n_sent == 2
        assert n_dead == 0
        assert sorted(sent) == [
            "https://fcm.example/a",
            "https://fcm.example/b",
        ]

    def test_dead_subscription_removed(self, monkeypatch):
        from push import send_push_to_all, STORE
        from pywebpush import WebPushException

        def fake_webpush(subscription_info, *a, **kw):
            class FakeResp:
                status_code = 410
                text = "Gone"
            raise WebPushException("gone", response=FakeResp())

        monkeypatch.setattr("push.webpush", fake_webpush)

        STORE.add_subscription("https://fcm.example/dead", "p", "a")

        n_sent, n_dead = send_push_to_all({"title": "T", "body": "B", "url": "/x"})
        assert n_sent == 0
        assert n_dead == 1
        assert STORE.list_subscriptions() == []

    def test_transient_error_keeps_subscription(self, monkeypatch):
        from push import send_push_to_all, STORE
        from pywebpush import WebPushException

        def fake_webpush(subscription_info, *a, **kw):
            class FakeResp:
                status_code = 500
                text = "boom"
            raise WebPushException("server error", response=FakeResp())

        monkeypatch.setattr("push.webpush", fake_webpush)

        STORE.add_subscription("https://fcm.example/temp", "p", "a")

        n_sent, n_dead = send_push_to_all({"title": "T", "body": "B", "url": "/x"})
        assert n_sent == 0
        assert n_dead == 0
        assert len(STORE.list_subscriptions()) == 1


class TestTrigger:
    def test_full_flow_eligible_article(self, monkeypatch):
        from push import trigger_push_for_new_articles, STORE

        sent = []
        def fake_webpush(subscription_info, data, **kw):
            sent.append((subscription_info["endpoint"], data))
            class R:
                status_code = 201
            return R()
        monkeypatch.setattr("push.webpush", fake_webpush)

        STORE.add_subscription("https://fcm.example/a", "p", "a")

        a = make_article(cat_score=15, lien="https://example.com/big-news",
                         titre="Big news")
        a.source = "Test"

        result = trigger_push_for_new_articles([a])
        assert result == "https://example.com/big-news"
        assert STORE.is_already_notified("https://example.com/big-news") is True
        assert len(sent) == 1

    def test_full_flow_no_eligible_article(self, monkeypatch):
        from push import trigger_push_for_new_articles

        def boom(*a, **k):
            raise AssertionError("webpush should not be called")
        monkeypatch.setattr("push.webpush", boom)

        a = make_article(cat_score=5)
        result = trigger_push_for_new_articles([a])
        assert result is None

    def test_full_flow_no_subscriptions(self, monkeypatch):
        from push import trigger_push_for_new_articles, STORE

        def boom(*a, **k):
            raise AssertionError("webpush should not be called")
        monkeypatch.setattr("push.webpush", boom)

        a = make_article(cat_score=12, lien="https://example.com/x")
        result = trigger_push_for_new_articles([a])
        assert result == "https://example.com/x"
        assert STORE.is_already_notified("https://example.com/x") is True
