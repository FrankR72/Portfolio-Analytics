
from fastapi import HTTPException, status

from sqlalchemy.ext.asyncio import AsyncSession

import models

from sqlalchemy import select, func

from market_data_service import get_current_stock_price


class HoldingService:
    def __init__(self, session: AsyncSession):
        self.db = session
        
        
    def summarize_holdings(self, transactions):
        pass
    
    
    def get_portfolio_holdings(self, portfolio_id: int , user_id: int):
        result = self.db.execute(
            select(models.Transaction)
            .join(models.Portfolio,
                  models.Portfolio.id == models.Transaction.portfolio_id)
            .where(models.Portfolio.id == portfolio_id,
                   models.Portfolio.user_id == user_id)
            .order_by(models.Transaction.transaction_date,
                      models.Transaction.id)
        )
        list_of_transactions = result.scalars().all()
        return list_of_transactions
    
    
    def form_holdings_dictionary(self, transactions):
        pass