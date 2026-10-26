"""Measure how long the price-heavy screens take, and how often they call yfinance.

Runs the real app in-process (httpx + ASGITransport, like the API tests, no
server needed) against the real database in backend/app/.env and the real
Yahoo Finance.

Each "round" replays, in this order, what a user does on one portfolio:

    Holdings tab        GET /api/holdings/{id}
    Analytics tab       GET /distribution, /unrealized_gains_distribution,
                        /performance and /stocks_performance (default "3M")
    AI summary          POST /summary with a fake LLM: only the price part is
                        measured, no model quota is used
    Add a transaction   the ticker check for one held symbol, called directly
                        (no HTTP request, nothing is saved)

Round 2 repeats round 1 right away. Without a cache it costs the same; with
the price cache it should drop to almost no history() calls. That difference
is the before/after of the caching work.

What the numbers mean
---------------------
- "history() calls" counts how often OUR app calls yfinance's
  Ticker.history(). It is not the number of network requests yfinance sends
  to Yahoo: one call can make several requests (for example, the very first
  call of a process also sets up a session with Yahoo).
- "time inside history()" is the wall-clock time spent in that function: the
  waiting for Yahoo plus whatever processing yfinance does with the answer.
- "total time" of a scenario is everything the backend does for it: database
  queries, our calculations and the price lookups.
- The script calls the backend directly, so Streamlit is not included: not
  its caches (performance_cache, summary_cache) and not drawing the page.
- Today the price calls run one after another, so "time inside history()"
  can be read as a share of the total time. If the calls overlap in the
  future (asyncio.gather), their durations add up to more than the time that
  actually passed, and the sum must no longer be read as a percentage.

Run from Portfolio-Analytics/ with Postgres started:

    uv run python backend/benchmarks/measure_price_calls.py --list
    uv run python backend/benchmarks/measure_price_calls.py --portfolio-id 1 --label baseline

Results are saved to backend/benchmarks/results/<timestamp>_<label>.json.
They hold timings and counts only: no symbols, names or ids.
"""

import argparse
import asyncio
import json
import sys
import tempfile
import threading
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "app"))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from ai import request_log
from ai.client import LLMResult
from core.config import settings
from db.database import AsyncSessionLocal, engine
from main import app
from models import models
from routers.auth import get_current_user
from services import market_data_service
from services.holding_service import HoldingService


RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# Counting history() calls
# ---------------------------------------------------------------------------

class HistoryCallCounter:
    """Stands in for the `yf` module inside market_data_service.

    market_data_service only uses `yf.Ticker(symbol).history(...)`, so this
    class offers the same `Ticker` method. It returns a CountedTicker that
    forwards every history() call to the real yfinance and reports back here.

    The price lookups run in threads (asyncio.to_thread), so the counters are
    updated under a lock.
    """

    def __init__(self, real_yf):
        self.real_yf = real_yf
        self.lock = threading.Lock()
        self.calls = 0
        self.seconds = 0.0

    def reset(self):
        with self.lock:
            self.calls = 0
            self.seconds = 0.0

    def record(self, seconds):
        with self.lock:
            self.calls += 1
            self.seconds += seconds

    def Ticker(self, symbol):  # same name as yfinance's, so the app can't tell
        return CountedTicker(self.real_yf.Ticker(symbol), self)


class CountedTicker:
    """A real yfinance Ticker whose history() calls are timed and counted."""

    def __init__(self, real_ticker, counter):
        self.real_ticker = real_ticker
        self.counter = counter

    def history(self, *args, **kwargs):
        start = time.perf_counter()
        try:
            return self.real_ticker.history(*args, **kwargs)
        finally:
            # Counted even when it fails: a failed call still took time.
            self.counter.record(time.perf_counter() - start)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def three_months_ago(today: date) -> date:
    """Start of the Analytics tab's default "3M" period, as the frontend computes it."""
    return (pd.Timestamp(today) - pd.DateOffset(months=3)).date()


def http_screens(portfolio_id: int) -> list[tuple[str, list[tuple[str, str, dict | None]]]]:
    """The screens measured through the API: (name, [(method, path, query params)])."""
    today = date.today()
    period = {"start_date": three_months_ago(today).isoformat(), "end_date": today.isoformat()}
    base = f"/api/portfolios/{portfolio_id}"
    return [
        ("Holdings tab", [
            ("GET", f"/api/holdings/{portfolio_id}", None),
        ]),
        ("Analytics tab", [
            ("GET", f"{base}/distribution", None),
            ("GET", f"{base}/unrealized_gains_distribution", None),
            ("GET", f"{base}/performance", period),
            ("GET", f"{base}/stocks_performance", period),
        ]),
        ("AI summary (prices only)", [
            ("POST", f"{base}/summary", None),
        ]),
    ]


async def measure_http_screen(client, counter, name, requests_to_send) -> dict:
    """Send a screen's requests one after another and measure the whole screen."""
    counter.reset()
    statuses = []
    start = time.perf_counter()
    for method, path, params in requests_to_send:
        response = await client.request(method, path, params=params)
        statuses.append(response.status_code)
    return make_row(name, time.perf_counter() - start, counter, statuses)


async def measure_ticker_check(counter, symbol) -> dict:
    """Call the ticker check directly, as POST /api/transactions does before saving."""
    counter.reset()
    start = time.perf_counter()
    await asyncio.to_thread(market_data_service.ticker_validation, symbol)
    return make_row("Add a transaction (ticker check)", time.perf_counter() - start, counter, [])


def make_row(name, elapsed, counter, statuses) -> dict:
    """One result row, in the format of the saved JSON files."""
    return {
        "screen": name,
        "seconds": round(elapsed, 2),
        "yfinance_calls": counter.calls,
        "yfinance_seconds": round(counter.seconds, 2),
        "statuses": statuses,
    }


async def run_round(client, counter, portfolio_id, symbol) -> list[dict]:
    """One pass through the four screens, in order. One row per screen."""
    rows = []
    for name, requests_to_send in http_screens(portfolio_id):
        rows.append(await measure_http_screen(client, counter, name, requests_to_send))
    rows.append(await measure_ticker_check(counter, symbol))
    return rows


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def list_portfolios() -> None:
    """Print each portfolio with its owner and how many symbols it holds."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                models.Portfolio.id, models.Portfolio.name, models.Portfolio.user_id,
                func.count(func.distinct(models.Transaction.symbol)),
            )
            .outerjoin(models.Transaction)
            .group_by(models.Portfolio.id)
            .order_by(models.Portfolio.id)
        )
        rows = result.all()
    if not rows:
        print("No portfolios in the database yet.")
    for portfolio_id, name, user_id, symbols in rows:
        print(f"  id {portfolio_id:<4} user {user_id:<4} symbols {symbols:<3} {name}")


async def load_portfolio(portfolio_id: int) -> tuple[models.User, list[str]]:
    """The portfolio's owner and its distinct symbols (oldest first)."""
    async with AsyncSessionLocal() as session:
        portfolio = await session.get(models.Portfolio, portfolio_id)
        if portfolio is None:
            raise SystemExit(f"Portfolio {portfolio_id} not found (use --list).")
        user = await session.get(models.User, portfolio.user_id)
        transactions = await HoldingService(session).get_portfolio_transactions(portfolio_id, user.id)
    symbols = list(dict.fromkeys(t.symbol for t in transactions))
    if not symbols:
        raise SystemExit(f"Portfolio {portfolio_id} has no transactions: nothing to measure.")
    return user, symbols


async def fake_generate_text(system_prompt: str, user_prompt: str) -> LLMResult:
    """Instant fake answer, so the summary measures only its price lookups."""
    return LLMResult(text="(benchmark)", model="benchmark", latency_seconds=0.0)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def describe_statuses(statuses: list[int]) -> str:
    if not statuses:
        return "no HTTP request"
    text = "HTTP " + ", ".join(str(s) for s in statuses)
    failed = sum(1 for s in statuses if s >= 400)
    if failed:
        text += f"  <-- {failed} failed (still measured)"
    return text


def print_report(rounds: list[list[dict]]) -> None:
    total_calls = 0
    total_history_seconds = 0.0

    for number, rows in enumerate(rounds, start=1):
        print(f"\nRound {number}")
        for row in rows:
            print(f"  {row['screen']}")
            print(f"      total time:            {row['seconds']:.2f} s")
            print(f"      history() calls:       {row['yfinance_calls']}")
            print(f"      time inside history(): {row['yfinance_seconds']:.2f} s")
            print(f"      {describe_statuses(row['statuses'])}")
            total_calls += row["yfinance_calls"]
            total_history_seconds += row["yfinance_seconds"]

        round_seconds = sum(row["seconds"] for row in rows)
        round_calls = sum(row["yfinance_calls"] for row in rows)
        print(f"  Round {number} total: {round_seconds:.2f} s, {round_calls} history() calls")

    # One average over every call: total time / total calls. (Averaging each
    # screen's average would give Holdings' 6 calls the same weight as
    # Analytics' 24.)
    if total_calls:
        print(f"\nAverage history() call: {total_history_seconds / total_calls:.3f} s "
              f"({total_calls} calls in {total_history_seconds:.2f} s)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--list", action="store_true", help="List portfolios and exit")
    parser.add_argument("--portfolio-id", type=int)
    parser.add_argument("--rounds", type=int, default=2, help="Repeat the screens N times (default 2)")
    parser.add_argument("--label", default="run", help="Name for the results file, e.g. baseline")
    args = parser.parse_args()

    try:
        if args.list:
            await list_portfolios()
            return
        if args.portfolio_id is None:
            raise SystemExit("Pass --portfolio-id (see --list).")

        user, symbols = await load_portfolio(args.portfolio_id)

        # Changes made only inside this process; nothing is written to .env
        # or the database.
        # 1. Every request is made as the portfolio's owner, without a token.
        app.dependency_overrides[get_current_user] = lambda: user
        # 2. Count and time every history() call.
        counter = HistoryCallCounter(market_data_service.yf)
        market_data_service.yf = counter
        # 3. The summary gets an instant fake LLM, so no quota is used...
        import ai.portfolio_summary as portfolio_summary
        portfolio_summary.generate_text = fake_generate_text
        # ...and must look "configured", or it would stop before the prices.
        settings.llm_base_url = settings.llm_base_url or "http://benchmark"
        settings.llm_model = settings.llm_model or "benchmark"
        # 4. Keep the fake calls out of the real LLM request log.
        request_log.LOG_FILE = Path(tempfile.gettempdir()) / "benchmark_llm_requests.jsonl"

        rounds = []
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://benchmark") as client:
            for number in range(1, args.rounds + 1):
                print(f"round {number}/{args.rounds}...", flush=True)
                rounds.append(await run_round(client, counter, args.portfolio_id, symbols[0]))
    finally:
        await engine.dispose()

    print_report(rounds)

    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{args.label}.json"
    path.write_text(json.dumps({
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "label": args.label,
        "symbols_in_portfolio": len(symbols),
        "analytics_period": "3M",
        "rounds": rounds,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved to {path.relative_to(BACKEND.parent)}")


if __name__ == "__main__":
    asyncio.run(main())
