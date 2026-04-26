"""Tests CRUD du PushStore (table push_subscriptions)."""

from push import PushStore


def make_sub(endpoint="https://fcm.example/abc"):
    return {
        "endpoint": endpoint,
        "p256dh": "BP-fake-p256dh",
        "auth": "fake-auth-secret",
    }


class TestSubscriptionCRUD:
    def test_empty_store(self):
        store = PushStore()
        assert store.list_subscriptions() == []

    def test_add_then_list(self):
        store = PushStore()
        s = make_sub()
        store.add_subscription(**s)
        rows = store.list_subscriptions()
        assert len(rows) == 1
        assert rows[0]["endpoint"] == s["endpoint"]
        assert rows[0]["p256dh"] == s["p256dh"]
        assert rows[0]["auth"] == s["auth"]

    def test_add_is_idempotent(self):
        store = PushStore()
        s = make_sub()
        store.add_subscription(**s)
        store.add_subscription(**s)  # second call must not raise / not duplicate
        assert len(store.list_subscriptions()) == 1

    def test_remove(self):
        store = PushStore()
        s = make_sub()
        store.add_subscription(**s)
        store.remove_subscription(s["endpoint"])
        assert store.list_subscriptions() == []

    def test_remove_nonexistent_is_noop(self):
        store = PushStore()
        # Doesn't raise
        store.remove_subscription("https://nonexistent.example/xyz")
