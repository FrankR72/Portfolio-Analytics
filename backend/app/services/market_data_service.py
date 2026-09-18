
import yfinance as yf



def get_current_stock_price(symbol: str) -> float:
    """
    Get the current stock price for a given symbol using yfinance.
    """
    try:
        stock = yf.Ticker(symbol)
        current_price = stock.history(period="1d")["Close"].iloc[-1]
        return current_price
    except Exception as e:
        raise ValueError(f"Could not fetch stock price for symbol {symbol}: {e}")