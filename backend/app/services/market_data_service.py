
import yfinance as yf
import pandas as pd
import math


def get_current_stock_price(symbol: str) -> float:
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
    """
    Get historical stock prices for a given symbol using yfinance.
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
    try:
        get_current_stock_price(symbol)
        return True
    except ValueError:
        return False