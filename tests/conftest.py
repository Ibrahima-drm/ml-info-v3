import os
import sys
import tempfile

# Permet aux tests d'importer app.py / summary.py / push.py depuis la racine
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# DB temporaire pour ne pas polluer l'environnement de dev
_tmp_db = os.path.join(tempfile.gettempdir(), "ml_info_tests_summaries.db")
if os.path.exists(_tmp_db):
    os.remove(_tmp_db)
os.environ.setdefault("SUMMARY_DB_URL", f"file:{_tmp_db}")

# VAPID test keys (factices, suffisent pour les tests qui ne font pas de vrai send)
os.environ.setdefault("VAPID_PUBLIC_KEY", "BP-test-public-key")
os.environ.setdefault("VAPID_PRIVATE_KEY", "test-private-key")
os.environ.setdefault("VAPID_CONTACT", "mailto:test@example.com")


import pytest


@pytest.fixture(autouse=True)
def _reset_push_tables():
    """Vide les tables push_subscriptions et notified_articles avant chaque test."""
    try:
        import push
        push.STORE.clear_all()
    except Exception:
        # Module pas encore créé ou DB pas encore initialisée
        pass
    yield
