"""Tests for services/price_cache.py (the Redis price cache).

No real Redis: the `fake_redis` fixture replaces price_cache.redis_client
with a fakeredis client, an in-memory imitation of Redis that understands
the same commands (GET, SET with EX, TTL...). Each test gets a new, empty
one. `redis_down` is a fakeredis client whose server is "disconnected", so
every command raises redis.ConnectionError, like a stopped container.

The cache-off case (no REDIS_URL) sets redis_client to None, which is also
what every other test file runs with (conftest sets REDIS_URL to "").
"""

import logging
from datetime import date

import fakeredis
import pandas as pd
import pytest

from services import price_cache
from services.price_cache import (
    cache_current_price,
    cache_historical_prices,
    create_redis_current_price_key,
    create_redis_historical_price_key,
    fetch_current_price_from_cache,
    fetch_historical_prices_from_cache,
)


START = date(2026, 10, 20)
END = date(2026, 10, 23)  # Exclusive, like the callers pass it


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_redis(monkeypatch):
    """Empty fakeredis client in place of the real one. Returned so a test
    can look at the stored keys directly."""
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(price_cache, "redis_client", client)
    return client


@pytest.fixture
def redis_down(monkeypatch):
    """Client whose every command raises redis.ConnectionError."""
    server = fakeredis.FakeServer()
    server.connected = False
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr(price_cache, "redis_client", client)
    return client


@pytest.fixture
def cache_off(monkeypatch):
    """No REDIS_URL: redis_client is None."""
    monkeypatch.setattr(price_cache, "redis_client", None)


def closes():
    """Small closes Series shaped like get_historical_stock_prices' result.
    Long decimals on purpose: to_json would round them at its default
    precision (10 decimals)."""
    return pd.Series(
        [384.2799987792969, 386.1000061035156, 381.0],
        index=pd.to_datetime(["2026-10-20", "2026-10-21", "2026-10-22"]),
    )


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

# The symbol is stripped and uppercased, so " aapl " and "AAPL" share a key.
def test_current_price_key():
    assert create_redis_current_price_key(" aapl ") == "prices:v1:current:AAPL"


# Symbol plus both dates in ISO format, no trailing ":".
def test_historical_price_key():
    assert (
        create_redis_historical_price_key("msft", START, END)
        == "prices:v1:historical:MSFT:2026-10-20:2026-10-23"
    )


# ---------------------------------------------------------------------------
# Current price
# ---------------------------------------------------------------------------

# Nothing stored yet: a miss is None.
def test_current_price_miss(fake_redis):
    assert fetch_current_price_from_cache("AAPL") is None


# A saved price comes back as the same float, under the normalized key.
def test_current_price_saved_and_read(fake_redis):
    cache_current_price(" aapl ", 531.3300170898438)

    assert fake_redis.get("prices:v1:current:AAPL") == "531.3300170898438"
    assert fetch_current_price_from_cache("AAPL") == 531.3300170898438


# The key expires after the TTL from settings (300 s) unless one is passed.
def test_current_price_ttl(fake_redis):
    cache_current_price("AAPL", 150.0)
    cache_current_price("MSFT", 400.0, ttl_seconds=20)

    assert fake_redis.ttl("prices:v1:current:AAPL") == 300
    assert fake_redis.ttl("prices:v1:current:MSFT") == 20


# The TTL setting is read on every call, so a changed setting is used.
def test_current_price_ttl_follows_setting(fake_redis, monkeypatch):
    monkeypatch.setattr(price_cache.settings, "ttl_price_cache_current_prices_seconds", 42)

    cache_current_price("AAPL", 150.0)

    assert fake_redis.ttl("prices:v1:current:AAPL") == 42


# Something that isn't a number under the key counts as a miss, not an error.
def test_current_price_invalid_value_is_a_miss(fake_redis):
    fake_redis.set("prices:v1:current:AAPL", "not a number")
    assert fetch_current_price_from_cache("AAPL") is None


# ---------------------------------------------------------------------------
# Historical prices
# ---------------------------------------------------------------------------

def test_historical_prices_miss(fake_redis):
    assert fetch_historical_prices_from_cache("MSFT", START, END) is None


# Saved and read back: same dates and exactly the same values (no rounding).
def test_historical_prices_round_trip(fake_redis):
    cache_historical_prices("msft", START, END, closes())

    cached = fetch_historical_prices_from_cache("MSFT", START, END)

    assert isinstance(cached, pd.Series)
    assert cached.tolist() == closes().tolist()
    assert list(cached.index) == list(closes().index)


# Another date range is another key: a miss.
def test_historical_prices_other_range_is_a_miss(fake_redis):
    cache_historical_prices("MSFT", START, END, closes())
    assert fetch_historical_prices_from_cache("MSFT", START, date(2026, 10, 24)) is None


# The key expires after the TTL from settings (3600 s).
def test_historical_prices_ttl(fake_redis):
    cache_historical_prices("MSFT", START, END, closes())
    key = create_redis_historical_price_key("MSFT", START, END)
    assert fake_redis.ttl(key) == 3600


def test_historical_prices_invalid_value_is_a_miss(fake_redis):
    fake_redis.set(create_redis_historical_price_key("MSFT", START, END), "not json")
    assert fetch_historical_prices_from_cache("MSFT", START, END) is None


# ---------------------------------------------------------------------------
# Cache off (no REDIS_URL)
# ---------------------------------------------------------------------------

# Reads are misses and writes do nothing, without errors.
def test_cache_off(cache_off):
    cache_current_price("AAPL", 150.0)
    cache_historical_prices("MSFT", START, END, closes())

    assert fetch_current_price_from_cache("AAPL") is None
    assert fetch_historical_prices_from_cache("MSFT", START, END) is None


# ---------------------------------------------------------------------------
# Redis down
# ---------------------------------------------------------------------------

# Every Redis error becomes a miss (reads) or is skipped (writes), with a
# warning in the log; nothing is raised to the caller.
def test_redis_down_is_a_miss_with_a_warning(redis_down, caplog):
    with caplog.at_level(logging.WARNING, logger="services.price_cache"):
        cache_current_price("AAPL", 150.0)
        cache_historical_prices("MSFT", START, END, closes())
        assert fetch_current_price_from_cache("AAPL") is None
        assert fetch_historical_prices_from_cache("MSFT", START, END) is None

    # 2 writes + 2 reads, each logged once.
    assert len(caplog.records) == 4
    assert "Redis write failed for prices:v1:current:AAPL" in caplog.text
    assert "Redis read failed for prices:v1:historical:MSFT" in caplog.text
