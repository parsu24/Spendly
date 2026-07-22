"""Shared pytest setup.

app.py calls init_db() and seed_db() at import time, so any test module that
imports app would build and seed a real database as a side effect. Pointing
SPENDLY_DB at a scratch file here — before database.db is ever imported —
keeps that side effect away from the development data in spendly.db.

conftest.py is imported before the test modules themselves, which is what
makes setting the variable at module level early enough.
"""

import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.gettempdir()) / "spendly-test.db"
os.environ.setdefault("SPENDLY_DB", str(_TEST_DB))

# Start every run from a clean slate rather than inheriting the previous one.
_TEST_DB.unlink(missing_ok=True)
