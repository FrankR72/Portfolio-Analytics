"""Portfolio analytics: allocation, unrealized gains and return over time.

Builds on HoldingService for loading and replaying transactions, and on
market_data_service for current and historical prices.

Unlike the other services, errors here are raised as ValueError, not
HTTPException. The /performance route turns them into 422; the
/distribution and /unrealized_gains_distribution routes don't catch them,
so they become 500.

Known issues (pending refactor):
    - A failed price lookup in the two distribution methods returns 500.
      get_current_stock_price raises ValueError and never returns None, so
      their `if current_price is None` checks never run.
    - get_portfolio_performance replays transactions with its own code
      instead of position_accounting_service.
    - Raises ValueError instead of the HTTPException used elsewhere.
"""

from datetime import date, timedelta

import math

from database import get_db

from sqlalchemy import select, func

from .market_data_service import get_current_stock_price, get_historical_stock_prices

from .holding_service import HoldingService

import asyncio

import pandas as pd

class AnalyticService:
    def __init__(self, session):
        self.db = session
        self.holding_service = HoldingService(session)

    async def get_portfolio_distribution(self, user_id: int, portfolio_id: int):
        """Return the market value of each open position and its weight.

        Returns:
            (total_portfolio_value, {symbol: {"current_value",
            "distribution_percentage"}}). Percentages are 0.0 when the
            total value is 0.

        Raises:
            HTTPException: 404 if the portfolio isn't the user's, 400 if its
                transaction history is invalid.
            ValueError: If a current price can't be fetched (becomes 500).
        """
        transactions = await self.holding_service.get_portfolio_transactions(
            portfolio_id=portfolio_id,
            user_id=user_id,
        )
        holdings = self.holding_service.build_holdings_dictionary(transactions)

        total_portfolio_value = 0.0
        holdings_distribution = {}
        for symbol, data in holdings.items():
            shares = data["number_current_shares"]
            if shares == 0:
                continue
            
            current_price = await asyncio.to_thread(get_current_stock_price, symbol)
            # Known issue: never true, the call above raises instead.
            if current_price is None:
                raise ValueError(f"No current price available for {symbol}")
            current_value = shares * current_price
            total_portfolio_value += current_value
            holdings_distribution[symbol] = {
                "current_value": current_value,
            }
        for data in holdings_distribution.values():
            data["distribution_percentage"] = (
                data["current_value"] / total_portfolio_value * 100
                if total_portfolio_value > 0
                else 0.0
            )
        return total_portfolio_value, holdings_distribution
    
    
    async def get_portfolio_unrealized_gains_distribution(self, user_id: int, portfolio_id: int):
        """Return the unrealized gain or loss of each open position.

        Returns:
            {symbol: {"unrealized_gain_loss"}}, computed as current market
            value minus cost basis.

        Raises:
            HTTPException: 404 if the portfolio isn't the user's, 400 if its
                transaction history is invalid.
            ValueError: If a current price can't be fetched (becomes 500).
        """
        transactions = await self.holding_service.get_portfolio_transactions(
            portfolio_id=portfolio_id,
            user_id=user_id,
        )
        holdings = self.holding_service.build_holdings_dictionary(transactions)
        
        holdings_unrealized_gains_distribution = {}
        for symbol, data in holdings.items():
            shares = data["number_current_shares"]
            if shares == 0:
                continue
            
            current_price =  await asyncio.to_thread(get_current_stock_price, symbol)
            # Known issue: never true, the call above raises instead.
            if current_price is None:
                raise ValueError(f"No current price available for {symbol}")
            current_value = shares * current_price
            unrealized_gain_loss = current_value - data["cost_bases"]
            holdings_unrealized_gains_distribution[symbol] = {
                "unrealized_gain_loss": unrealized_gain_loss,
            }
        return holdings_unrealized_gains_distribution
            
        
        
        
    async def get_portfolio_performance(
            self, user_id: int, portfolio_id: int,
            start_date: date, end_date: date,
        ):
            """Return the portfolio's daily return series between two dates.

            Approximate time-weighted return with end-of-day flows. Each
            day's growth factor is (value - net flow of that day) / previous
            value, so buying or selling doesn't count as gain or loss. The
            factors are chained into a cumulative return. On the portfolio's
            first day, the return is value / net investment, so the gap
            between purchase price and that day's close is included. Prices
            are forward-filled over weekends and holidays, and dividends are
            ignored.

            If start_date is before the first transaction, the series starts
            at the first transaction instead ("history_limited" is True).

            Returns:
                A dict with "method" and "points", a list of {"date",
                "holdings_value", "return_percentage"}. When there is data
                it also has "start_date", "end_date",
                "requested_start_date", "history_limited", "provisional"
                (True when end_date is today, since today's close may not be
                final) and "price_dates" (the date of the last available
                price of each symbol still held). "points" is empty when no
                transactions fall in the range.

            Raises:
                HTTPException: 404 if the portfolio isn't the user's.
                ValueError: The /performance route turns it into 422. Raised
                    for an invalid date range, a stock split or missing
                    price in the window, a negative share count, a first
                    day without a positive net investment, or a period where
                    the portfolio is emptied and restarted.
            """
            if start_date > end_date or end_date > date.today():
                raise ValueError("Use start <= end, with end no later than today")

            transactions = await self.holding_service.get_portfolio_transactions(
                portfolio_id=portfolio_id, user_id=user_id,
            )
            transactions = sorted(
                (t for t in transactions if t.transaction_date.date() <= end_date),
                key=lambda t: (t.transaction_date, t.id),
            )
            if not transactions:
                return {"method": "daily_end_of_day_flow", "points": []}

            first_date = transactions[0].transaction_date.date()
            baseline_date = max(start_date, first_date)
            if baseline_date > end_date:
                return {"method": "daily_end_of_day_flow", "points": []}

            days = pd.date_range(baseline_date, end_date, freq="D")
            prices = {}
            price_dates = {}
            for symbol in sorted({t.symbol for t in transactions}):
                history = await asyncio.to_thread(
                    get_historical_stock_prices,
                    symbol,
                    first_date - timedelta(days=7),
                    end_date + timedelta(days=1),
                )
                available = history.loc[history.index <= pd.Timestamp(end_date)].dropna()
                price_dates[symbol] = available.index[-1].date().isoformat() if not available.empty else None
                # Carry the last known close over weekends and market holidays.
                prices[symbol] = history.reindex(
                    history.index.union(days)
                ).sort_index().ffill().reindex(days)

            shares = {}
            position = 0
            previous_value = None
            growth = 1.0
            points = []

            for timestamp in days:
                day = timestamp.date()
                # Net money put in today: positive for buys, negative for sells.
                flow = 0.0

                # Apply every transaction up to and including today. Only
                # today's transactions count as flow; earlier ones (before
                # the baseline) just set the starting share counts.
                while position < len(transactions):
                    transaction = transactions[position]
                    transaction_day = transaction.transaction_date.date()
                    if transaction_day > day:
                        break
                    
                    side = getattr(
                        transaction.transaction_type, "value",
                        transaction.transaction_type,
                    )
                    if side not in ("BUY", "SELL"):
                        raise ValueError(f"Unsupported transaction type: {side}")

                    sign = 1 if side == "BUY" else -1
                    symbol = transaction.symbol
                    shares[symbol] = shares.get(symbol, 0) + (
                        sign * transaction.quantity_actions
                    )
                    if shares[symbol] < 0:
                        raise ValueError(f"Negative holdings for {symbol}")

                    if transaction_day == day:
                        flow += sign * float(transaction.total_value)
                    position += 1

                value = 0.0
                for symbol, quantity in shares.items():
                    if quantity == 0:
                        continue
                    price = float(prices[symbol].loc[timestamp])
                    if not math.isfinite(price) or price <= 0:
                        raise ValueError(f"Missing valid price for {symbol} on {day}")
                    value += quantity * price

                if previous_value is None and baseline_date == first_date:
                    # Include the initial purchase-to-market gain or loss.
                    if flow <= 0:
                        raise ValueError(
                            "Initial-day return requires a positive net investment"
                        )
                    growth = value / flow
                elif previous_value is not None:
                    if previous_value > 0:
                        daily_factor = (value - flow) / previous_value
                        if not math.isfinite(daily_factor) or daily_factor <= 0:
                            raise ValueError(
                                "Daily approximation is unsuitable for this period"
                            )
                        growth *= daily_factor
                    elif value > 0 or flow != 0:
                        raise ValueError(
                            "Choose a period without restarting an empty portfolio"
                        )

                points.append({
                    "date": day.isoformat(),
                    "holdings_value": value,
                    "return_percentage": (growth - 1) * 100,
                })
                previous_value = value

            return {
                "method": "daily_end_of_day_flow",
                "start_date": baseline_date.isoformat(),
                "end_date": end_date.isoformat(),
                "requested_start_date": start_date.isoformat(),
                "history_limited": baseline_date > start_date,
                "provisional": end_date == date.today(),
                "price_dates": {symbol: price_dates[symbol] for symbol, quantity in shares.items() if quantity > 0},
                "points": points,
            }
            
