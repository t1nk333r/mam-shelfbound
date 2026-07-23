import os
import tempfile
import pathlib

# main.py raises at import if MAM_COOKIE is unset, and opens a SQLite DB at
# import time. Provide safe test values before any test imports `main`.
os.environ.setdefault("MAM_COOKIE", "test-cookie")
_test_db = pathlib.Path(tempfile.gettempdir()) / "mam_audiofinder_test_history.db"
os.environ.setdefault("HISTORY_DB_URL", f"sqlite:///{_test_db}")
