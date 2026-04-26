"""Tests de la logique de filtrage du trigger push :
score ≥ 10, pas déjà notifié, dernier push > 30 min."""

import time

import pytest

from push import select_article_to_push, STORE


def make_article(score=12, lien="https://example.com/a", titre="Article test"):
    """Mini Article-like object (juste les attributs lus par le trigger)."""
    class A:
        pass
    a = A()
    a.score = score
    a.lien = lien
    a.titre = titre
    a.source = "Test Source"
    a.timestamp = time.time()
    return a


class TestFilters:
    def test_no_articles_returns_none(self):
        assert select_article_to_push([]) is None

    def test_score_below_threshold_skipped(self):
        a = make_article(score=9)
        assert select_article_to_push([a]) is None

    def test_score_above_threshold_passes(self):
        a = make_article(score=10)
        result = select_article_to_push([a])
        assert result is a

    def test_already_notified_skipped(self):
        a = make_article(score=15, lien="https://example.com/already")
        STORE.mark_notified(a.lien)
        assert select_article_to_push([a]) is None

    def test_recent_push_blocks_all(self, monkeypatch):
        monkeypatch.setattr(STORE, "last_push_at", lambda: time.time() - 5 * 60)
        a = make_article(score=15)
        assert select_article_to_push([a]) is None

    def test_old_push_does_not_block(self, monkeypatch):
        monkeypatch.setattr(STORE, "last_push_at", lambda: time.time() - 31 * 60)
        a = make_article(score=15)
        assert select_article_to_push([a]) is a

    def test_picks_highest_score(self):
        low = make_article(score=10, lien="https://example.com/low")
        high = make_article(score=18, lien="https://example.com/high")
        mid = make_article(score=12, lien="https://example.com/mid")
        result = select_article_to_push([low, high, mid])
        assert result is high

    def test_skips_below_threshold_keeps_above(self):
        low = make_article(score=8, lien="https://example.com/low")
        ok = make_article(score=11, lien="https://example.com/ok")
        result = select_article_to_push([low, ok])
        assert result is ok
