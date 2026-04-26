"""Tests des routes push : vapid-public-key, subscribe (POST/DELETE)."""

import pytest

import app as app_mod
import push


@pytest.fixture
def client():
    return app_mod.app.test_client()


class TestVapidPublicKey:
    def test_returns_key(self, client):
        r = client.get("/api/push/vapid-public-key")
        assert r.status_code == 200
        d = r.get_json()
        assert "key" in d
        assert d["key"] == "BP-test-public-key"


class TestSubscribe:
    def test_post_valid_payload_creates_subscription(self, client):
        body = {
            "endpoint": "https://fcm.example/abc",
            "keys": {"p256dh": "p256-val", "auth": "auth-val"},
        }
        r = client.post("/api/push/subscribe", json=body)
        assert r.status_code == 201
        subs = push.STORE.list_subscriptions()
        assert len(subs) == 1
        assert subs[0]["endpoint"] == "https://fcm.example/abc"
        assert subs[0]["p256dh"] == "p256-val"
        assert subs[0]["auth"] == "auth-val"

    def test_post_missing_endpoint(self, client):
        r = client.post("/api/push/subscribe", json={"keys": {"p256dh": "x", "auth": "y"}})
        assert r.status_code == 400

    def test_post_missing_keys(self, client):
        r = client.post("/api/push/subscribe",
                        json={"endpoint": "https://fcm.example/x"})
        assert r.status_code == 400

    def test_post_partial_keys(self, client):
        r = client.post("/api/push/subscribe", json={
            "endpoint": "https://fcm.example/x",
            "keys": {"p256dh": "only-this"}
        })
        assert r.status_code == 400


class TestUnsubscribe:
    def test_delete_removes_subscription(self, client):
        push.STORE.add_subscription("https://fcm.example/zzz", "p", "a")
        r = client.delete("/api/push/subscribe",
                          json={"endpoint": "https://fcm.example/zzz"})
        assert r.status_code == 204
        assert push.STORE.list_subscriptions() == []

    def test_delete_missing_endpoint(self, client):
        r = client.delete("/api/push/subscribe", json={})
        assert r.status_code == 400

    def test_delete_unknown_endpoint_is_204(self, client):
        r = client.delete("/api/push/subscribe",
                          json={"endpoint": "https://fcm.example/never-existed"})
        assert r.status_code == 204
