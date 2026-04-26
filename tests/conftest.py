import os
import sys
import tempfile

# Permet aux tests d'importer app.py / summary.py depuis la racine du projet
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# DB temporaire pour ne pas polluer l'environnement de dev
_tmp_db = os.path.join(tempfile.gettempdir(), "ml_info_tests_summaries.db")
if os.path.exists(_tmp_db):
    os.remove(_tmp_db)
os.environ.setdefault("SUMMARY_DB_URL", f"file:{_tmp_db}")
