import os
import tempfile
import pathlib

# main.py raises at import if MAM_COOKIE is unset, and opens a SQLite DB at
# import time. Provide safe test values before any test imports `main`.
os.environ.setdefault("MAM_COOKIE", "test-cookie")

# Always OVERRIDE the database URL — never setdefault. `main` runs
# ensure_history_schema() at import, which mutates rows, so an inherited
# HISTORY_DB_URL would let a test run rewrite a real database.
_test_db = pathlib.Path(tempfile.gettempdir()) / "mam_audiofinder_test_history.db"
os.environ["HISTORY_DB_URL"] = f"sqlite:///{_test_db}"
