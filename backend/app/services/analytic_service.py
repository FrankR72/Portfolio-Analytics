from database import get_db

from sqlalchemy import select, func

from .market_data_service import get_current_stock_price

from .holding_service import HoldingService


class AnalyticService:
    def __init__(self, session):
        self.db = session
        self.holding_service = HoldingService(session)

    async def get_portfolio_distribution(self, user_id: int, portfolio_id: int):
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
            
            current_price = get_current_stock_price(symbol)
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
            
            
