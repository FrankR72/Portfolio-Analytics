"""Market prices from Yahoo Finance.

The only module that calls yfinance. Every function here is synchronous and
does network I/O, so async code must call it through asyncio.to_thread.

Prices are cached in Redis (see price_cache): each function checks the
cache first and calls yfinance only on a miss, then saves the result.
Current prices are kept 5 minutes and histories 1 hour. Only valid results
are cached; failures are never saved, so they are retried on the next
request. With no REDIS_URL, or with Redis down, every lookup goes to
yfinance as before.

Known issues (pending refactor):
    Symbols are still fetched one at a time; the services don't fetch them
    in parallel yet.
"""

import yfinance as yf
import pandas as pd
import math
from services.price_cache import (
    fetch_current_price_from_cache,
    fetch_historical_prices_from_cache,
    cache_current_price,
    cache_historical_prices
)


def get_current_stock_price(symbol: str) -> float:
    """Return the most recent closing price for a ticker.

    This is the last close within the past 5 days, not a live quote. A
    cached price can be up to 5 minutes old.

    Args:
        symbol: Ticker. Stripped and uppercased before the lookup.

    Returns:
        A finite, positive price.

    Raises:
        ValueError: On any failure (empty ticker, no data, invalid price or
            a yfinance/network error). It never returns None.
    """
    symbol = symbol.strip().upper()

    try:
        if not symbol:
            raise ValueError("Empty ticker")

        price = fetch_current_price_from_cache(symbol)
        if price is not None:
            return price

        history = yf.Ticker(symbol).history(
            period="5d",
            auto_adjust=False,
            timeout=10,
        )
        if history.empty or "Close" not in history.columns:
            raise ValueError("No price history")

        prices = history["Close"].dropna()
        if prices.empty:
            raise ValueError("No usable closing prices")

        price = float(prices.iloc[-1])
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid price")

        # Only after every check passed, so a bad price is never cached.
        cache_current_price(symbol, price)
        return price
    except Exception as exc:
        raise ValueError(
            f"Could not verify a usable price for {symbol}"
        ) from exc



def get_historical_stock_prices(symbol, start_date, end_date):
    """Return daily closing prices for a ticker.

    Prices are not split-adjusted (auto_adjust=False), so they match the
    prices users enter in their transactions. Cached per symbol and date
    range for up to 1 hour.

    Args:
        symbol: Ticker. Stripped and uppercased before the lookup.
        start_date: First day to include.
        end_date: Exclusive upper bound; pass the day after the last day
            you need.

    Returns:
        pandas Series of closes indexed by date (timezone and time of day
        removed). Days without trading are missing, not filled.

    Raises:
        ValueError: If there is no data (empty ticker, unknown symbol, no
            trading days in the range or a yfinance/network error).
    """
    symbol = symbol.strip().upper()

    try:
        if not symbol:
            raise ValueError("Empty ticker")

        prices = fetch_historical_prices_from_cache(symbol, start_date, end_date)
        if prices is not None:
            return prices

        history = yf.Ticker(symbol).history(
            start=start_date,
            end=end_date,  # Exclusive upper bound
            auto_adjust=False,
            actions=True,
        )

        if history.empty:
            raise ValueError(f"No historical prices available for {symbol}")

        prices = history["Close"].copy()
        prices.index = pd.to_datetime(history.index.date)
        # Only after the checks above, so an empty history is never cached.
        cache_historical_prices(symbol, start_date, end_date, prices)
        return prices
    except Exception as exc:
        raise ValueError(
            f"Could not verify a usable price for {symbol}"
        ) from exc



def ticker_validation(symbol: str) -> bool:
    """Return True if a usable current price can be fetched for the ticker.

    Makes a network call, unless the price is already cached. False can
    also mean yfinance is unreachable, not only that the ticker doesn't
    exist.
    """
    try:
        get_current_stock_price(symbol)
        return True
    except ValueError:
        return False