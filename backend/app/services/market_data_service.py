"""Market prices from Yahoo Finance.

The only module that calls yfinance. Every function here is synchronous and
does network I/O, so async code must call it through asyncio.to_thread.

Known issues (pending refactor):
    There is no caching. Every holdings, distribution, unrealized-gains and
    performance request fetches prices again, one symbol at a time.
"""

import yfinance as yf
import pandas as pd
import math


def get_current_stock_price(symbol: str) -> float:
    """Return the most recent closing price for a ticker.

    This is the last close within the past 5 days, not a live quote.

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

        return price
    except Exception as exc:
        raise ValueError(
            f"Could not verify a usable price for {symbol}"
        ) from exc
    
    
    
def get_historical_stock_prices(symbol, start_date, end_date):
    """Return daily closing prices for a ticker.

    Prices are not split-adjusted (auto_adjust=False), so they match the
    prices users enter in their transactions.

    Args:
        symbol: Ticker, used as given.
        start_date: First day to include.
        end_date: Exclusive upper bound; pass the day after the last day
            you need.

    Returns:
        pandas Series of closes indexed by date (timezone and time of day
        removed). Days without trading are missing, not filled.

    Raises:
        ValueError: If there is no data, or if a stock split happened in the
            window, because user-entered prices are not split-adjusted and
            the returns would be wrong.
    """
    history = yf.Ticker(symbol).history(
        start=start_date,
        end=end_date,  # Exclusive upper bound
        auto_adjust=False,
        actions=True,
    )

    if history.empty:
        raise ValueError(f"No historical prices available for {symbol}")

    if (history["Stock Splits"].fillna(0) != 0).any():
        raise ValueError(f"Split handling is required for {symbol}")

    prices = history["Close"].copy()
    prices.index = pd.to_datetime(history.index.date)
    return prices

def ticker_validation(symbol: str) -> bool:
    """Return True if a usable current price can be fetched for the ticker.

    Makes a network call. False can also mean yfinance is unreachable, not
    only that the ticker doesn't exist.
    """
    try:
        get_current_stock_price(symbol)
        return True
    except ValueError:
        return False