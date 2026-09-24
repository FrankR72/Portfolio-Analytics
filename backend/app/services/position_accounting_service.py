from dataclasses import dataclass

from models import Transaction

@dataclass
class Position:
    shares: int = 0
    cost_basis: float = 0.0
    
    @property
    def average_cost(self) ->float:
        return self.cost_basis / self.shares if self.shares else 0.0
    

def apply_transaction(position: Position, transaction: Transaction) -> dict | None:
    side =getattr(
        transaction.transaction_type,
        "value",
        transaction.transaction_type
    )
    
    quantity = transaction.quantity_actions
    price = transaction.price
    
    if quantity <= 0:
        raise ValueError("Transaction quantity must be positive")
    
    if side == "BUY":
        position.shares += quantity
        position.cost_basis += quantity * price
        return None
    
    if side != "SELL":
        raise ValueError(f"Unsupported transaction type {side}")
    
    if quantity > position.shares:
        raise ValueError(f"Not enough shares to sell for {transaction.symbol}")

    average_cost = position.average_cost
    sold_cost = average_cost * quantity
    proceeds = price * quantity
    gain = proceeds - sold_cost
    
    position.shares -= quantity
    position.cost_basis -= sold_cost
    
    if position.shares == 0:
        position.cost_basis = 0.0
        
    return  {
        "transaction_date": transaction.transaction_date,
        "symbol": transaction.symbol,
        "number_shares_sold": quantity,
        "avg_cost_per_share": average_cost,
        "sold_price_per_share": price,
        "total_cost_of_shares_sold": sold_cost,
        "total_sold_price": proceeds,
        "realized_gain_loss": gain,
        "return_percentage": gain / sold_cost * 100 if sold_cost else 0.0,
    }
        