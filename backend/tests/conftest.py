"""Shared pytest setup for the backend tests.

pytest loads this file before any test module, so the environment set here
is in place before the app modules are imported.
"""

import os

# config.py builds Settings() on import and needs SECRET_KEY and DATABASE_URL.
# CI has no app/.env, so they are set here. Environment variables win over
# app/.env, so local runs use these dummies too, not the real key or Postgres.
# The tests never connect with this URL: each one builds its own in-memory
# SQLite engine.
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-bytes-long")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# Empty REDIS_URL turns the price cache off (redis_client is None), so local
# runs never read or write the real Redis from app/.env: the tests would
# otherwise store their fake prices there and read each other's. The cache
# tests put in a fakeredis client themselves.
os.environ.setdefault("REDIS_URL", "")
