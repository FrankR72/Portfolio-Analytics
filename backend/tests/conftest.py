import os

# config.py builds Settings() on import and needs SECRET_KEY. It reads
# app/.env relative to the current directory, which only works when pytest
# is run from backend/. Setting it here makes the tests work from anywhere.
os.environ.setdefault("SECRET_KEY", "test-secret-key")
