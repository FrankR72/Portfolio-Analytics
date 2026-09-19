






# Gráfica 1. Pie chart   (valor actual de la acción / valor actual del portafolio)


import models

from database import get_db

from sqlalchemy import select, func

from holding_service import get_portfolio_transactions, build_holdings_dictionary


class AnalyticService():
    
    def __init__(self, session):
        self.db = session
        
        
        def get_portfolio_dsitribution(self, user_id: int, portfolio_id: int):
            
            list_of_transactions = get_portfolio_transactions()
