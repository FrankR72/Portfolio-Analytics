"""Shared pytest setup for the backend tests.

pytest loads this file before any test module, so the environment set here
is in place before the app modules are imported.
"""

import os

# config.py builds Settings() on import and needs SECRET_KEY. It reads
# app/.env relative to the current directory, which only works when pytest
# is run from backend/. Setting it here makes the tests work from anywhere.
os.environ.setdefault("SECRET_KEY", "test-secret-key")
