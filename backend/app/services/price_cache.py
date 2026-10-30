"""Read and write cached market prices in Redis.

Used only by market_data_service, which checks the cache before calling
yfinance and saves what it fetched. Only valid prices are saved: failed
lookups are never cached, so they are retried on the next request.

Keys (symbol stripped and uppercased, dates in ISO format):
    prices:v1:current:AAPL                           current price
    prices:v1:historical:AAPL:2026-07-20:2026-10-28  closes from start to
                                                     end (end exclusive)

"v1" is the format version: if the stored format changes, bump it and the
old keys are simply never read again (they expire on their own).

TTLs come from settings: ttl_price_cache_current_prices_seconds (5 min) and
ttl_price_cache_historical_prices_seconds (1 h).

The cache never breaks a price lookup. With no REDIS_URL every function
does nothing (reads return None), and any Redis error (container stopped,
timeout) is logged as a warning and treated as a miss, so the caller
fetches from yfinance as if there were no cache.
"""

import io
import logging

import pandas as pd
import redis

from core.config import settings
from db.redis_client import redis_client

logger = logging.getLogger(__name__)


# Redis key generation functions
def create_redis_current_price_key(symbol: str) -> str:
    symbol = symbol.strip().upper()
    return f"prices:v1:current:{symbol}"

def create_redis_historical_price_key(symbol: str, start_date, end_date) -> str:
    symbol = symbol.strip().upper()
    start = start_date.isoformat()
    end = end_date.isoformat()
    return f"prices:v1:historical:{symbol}:{start}:{end}"



# Redis fetching functions
def fetch_current_price_from_cache(symbol: str) -> float | None:
    """Return the cached current price, or None on a miss."""
    if redis_client is None:
        return None  # Redis is not configured
    key = create_redis_current_price_key(symbol)
    try:
        price = redis_client.get(key)
    except redis.RedisError as exc:
        logger.warning("Redis read failed for %s: %s", key, exc)
        return None
    if price is None:
        return None  # Not found in cache
    try:
        return float(price)
    except ValueError:
        return None  # Invalid cached value

def fetch_historical_prices_from_cache(symbol: str, start_date, end_date) -> pd.Series | None:
    """Return the cached closes (Series indexed by date), or None on a miss."""
    if redis_client is None:
        return None  # Redis is not configured
    key = create_redis_historical_price_key(symbol, start_date, end_date)
    try:
        prices = redis_client.get(key)
    except redis.RedisError as exc:
        logger.warning("Redis read failed for %s: %s", key, exc)
        return None
    if prices is None:
        return None  # Not found in cache
    try:
        # StringIO: pandas would read a plain string as a file path.
        # typ="series": what is stored is a Series, not a DataFrame.
        return pd.read_json(io.StringIO(prices), typ="series")
    except ValueError:
        return None  # Invalid cached value



# Redis caching functions
def cache_current_price(symbol: str, price: float, ttl_seconds: int | None = None) -> None:
    """Save a current price for ttl_seconds (default from settings)."""
    if redis_client is None:
        return  # Redis is not configured
    ttl_seconds = ttl_seconds or settings.ttl_price_cache_current_prices_seconds
    key = create_redis_current_price_key(symbol)
    try:
        redis_client.set(key, price, ex=ttl_seconds)
    except redis.RedisError as exc:
        logger.warning("Redis write failed for %s: %s", key, exc)

def cache_historical_prices(
    symbol: str,
    start_date,
    end_date,
    prices: pd.Series,
    ttl_seconds: int | None = None,
) -> None:
    """Save the closes Series for ttl_seconds (default from settings)."""
    if redis_client is None:
        return  # Redis is not configured
    ttl_seconds = ttl_seconds or settings.ttl_price_cache_historical_prices_seconds
    key = create_redis_historical_price_key(symbol, start_date, end_date)
    try:
        # to_json keeps only 10 decimals by default; 15 (the maximum) gives
        # back exactly the closes yfinance returned.
        redis_client.set(key, prices.to_json(double_precision=15), ex=ttl_seconds)
    except redis.RedisError as exc:
        logger.warning("Redis write failed for %s: %s", key, exc)
