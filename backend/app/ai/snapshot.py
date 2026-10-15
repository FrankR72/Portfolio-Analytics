"""The portfolio data the LLM receives, and the pure function that builds it.

build_snapshot takes what the services already return (holdings, closed
transactions, performance) and produces a PortfolioSnapshot: no database,
no network, so it is easy to test and the evals can reuse it.

Three jobs:
- Do the math (allocation, totals, realized gain per symbol) so the model
  never has to calculate anything.
- Format every number as text ("1,234.56", "+12.5%"), so the model can
  copy numbers exactly and the evals can check them by exact string match.
- Keep only safe fields. Nothing typed by the user (portfolio name,
  description) and nothing personal (username, email, ids) is included,
  which protects privacy and closes the prompt-injection path.
  extra="forbid" makes adding an unknown field an error.

Amounts carry no currency: the app doesn't store one (yfinance prices are
in each stock's trading currency, usually USD).
"""

from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from db.schemas import ClosedTransaction, HoldingBase


# ---------------------------------------------------------------------------
# Snapshot shape
# ---------------------------------------------------------------------------

class PositionSnapshot(BaseModel):
    """One open position. Price-based fields are None if the price lookup failed."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    shares: int
    cost_basis: str
    price_available: bool
    current_value: str | None
    allocation: str | None
    unrealized_gain: str | None
    unrealized_return: str | None


class RealizedSnapshot(BaseModel):
    """Realized gain of all the sales of one symbol, added together."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    shares_sold: int
    realized_gain: str
    realized_return: str


class PerformanceSnapshot(BaseModel):
    """Portfolio return over a period."""

    model_config = ConfigDict(extra="forbid")

    start_date: str
    end_date: str
    return_percentage: str
    # True when the portfolio is younger than the requested period, so the
    # return covers less time than asked.
    history_limited: bool


class PortfolioSnapshot(BaseModel):
    """Everything the LLM is told about a portfolio."""

    model_config = ConfigDict(extra="forbid")

    # Largest position first, positions without a price last.
    positions: list[PositionSnapshot]
    positions_without_price: list[str]
    # Totals cover only positions with a price; None when there are none.
    total_value: str | None
    total_cost: str | None
    total_unrealized_gain: str | None
    total_unrealized_return: str | None
    realized: list[RealizedSnapshot]
    total_realized_gain: str | None
    # None when the return couldn't be calculated (no data, stock split...).
    performance: PerformanceSnapshot | None


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------

def _format(value: float, decimals: int, signed: bool) -> str:
    value = round(value, decimals)
    # Rounding can leave -0.0, which would print as "-0.00".
    if value == 0:
        value = 0.0
    sign = "-" if value < 0 else ("+" if signed and value > 0 else "")
    return sign + f"{abs(value):,.{decimals}f}"


def format_money(value: float, signed: bool = False) -> str:
    """1234.5 -> "1,234.50". With signed=True, gains get a "+"."""
    return _format(value, 2, signed)


def format_percent(value: float, signed: bool = False) -> str:
    """12.345 -> "12.3%". With signed=True, gains get a "+"."""
    return _format(value, 1, signed) + "%"


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_snapshot(
    holdings: list[HoldingBase],
    closed_transactions: list[ClosedTransaction],
    performance: dict | None = None,
) -> PortfolioSnapshot:
    """Turn the services' results into the snapshot sent to the LLM.

    Args:
        holdings: From HoldingService.summarize_holdings (open positions,
            price fields None when the lookup failed).
        closed_transactions: From TransactionService.get_closed_transactions.
        performance: From AnalyticService.get_portfolio_performance, or None
            if it wasn't available.
    """
    priced = [h for h in holdings if h.current_value is not None]
    unpriced = [h for h in holdings if h.current_value is None]

    total_value = sum(h.current_value for h in priced)
    total_cost = sum(h.cost_bases for h in priced)
    total_gain = sum(h.unrealized_gain_loss for h in priced)

    positions = [
        PositionSnapshot(
            symbol=h.symbol,
            shares=h.number_current_shares,
            cost_basis=format_money(h.cost_bases),
            price_available=True,
            current_value=format_money(h.current_value),
            allocation=format_percent(h.current_value / total_value * 100),
            unrealized_gain=format_money(h.unrealized_gain_loss, signed=True),
            unrealized_return=format_percent(h.return_percentage, signed=True),
        )
        for h in sorted(priced, key=lambda h: h.current_value, reverse=True)
    ] + [
        PositionSnapshot(
            symbol=h.symbol,
            shares=h.number_current_shares,
            cost_basis=format_money(h.cost_bases),
            price_available=False,
            current_value=None,
            allocation=None,
            unrealized_gain=None,
            unrealized_return=None,
        )
        for h in sorted(unpriced, key=lambda h: h.symbol)
    ]

    return PortfolioSnapshot(
        positions=positions,
        positions_without_price=sorted(h.symbol for h in unpriced),
        total_value=format_money(total_value) if priced else None,
        total_cost=format_money(total_cost) if priced else None,
        total_unrealized_gain=format_money(total_gain, signed=True) if priced else None,
        total_unrealized_return=(
            format_percent(total_gain / total_cost * 100, signed=True) if priced else None
        ),
        realized=_realized_by_symbol(closed_transactions),
        total_realized_gain=(
            format_money(sum(c.realized_gain_loss for c in closed_transactions), signed=True)
            if closed_transactions else None
        ),
        performance=_performance(performance),
    )


def _realized_by_symbol(closed_transactions: list[ClosedTransaction]) -> list[RealizedSnapshot]:
    """Add up the sales of each symbol (one line per symbol, not per sale)."""
    shares = defaultdict(int)
    cost = defaultdict(float)
    gain = defaultdict(float)
    for c in closed_transactions:
        shares[c.symbol] += c.number_shares_sold
        cost[c.symbol] += c.total_cost_of_shares_sold
        gain[c.symbol] += c.realized_gain_loss

    return [
        RealizedSnapshot(
            symbol=symbol,
            shares_sold=shares[symbol],
            realized_gain=format_money(gain[symbol], signed=True),
            # Return on what the sold shares cost (cost is always > 0).
            realized_return=format_percent(gain[symbol] / cost[symbol] * 100, signed=True),
        )
        for symbol in sorted(shares)
    ]


def _performance(performance: dict | None) -> PerformanceSnapshot | None:
    """Keep only the final return of the series; the model doesn't need every day."""
    if not performance or not performance.get("points"):
        return None
    return PerformanceSnapshot(
        start_date=performance["start_date"],
        end_date=performance["end_date"],
        return_percentage=format_percent(
            performance["points"][-1]["return_percentage"], signed=True,
        ),
        history_limited=performance.get("history_limited", False),
    )