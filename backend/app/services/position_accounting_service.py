"""Position accounting with the average cost method.

Single source of the rules for replaying a portfolio's transactions into
per-symbol positions: a BUY adds shares and cost, a SELL removes shares at
the current average cost and realizes the difference as gain or loss.

Used by HoldingService.build_holdings_dictionary and
TransactionService.build_closed_transactions.

Known issues (pending refactor):
    TransactionService._validate_sell and
    AnalyticService.get_portfolio_performance still replay transactions
    with their own code instead of this module, so a rule change here must
    be mirrored there by hand until they are migrated.
"""

from dataclasses import dataclass

from models import Transaction

@dataclass
class Position:
    """Running state of one symbol while transactions are replayed.

    Attributes:
        shares: Shares currently held.
        cost_basis: Total purchase cost of the shares currently held
            (not of every share ever bought).
    """
    shares: int = 0
    cost_basis: float = 0.0

    @property
    def average_cost(self) ->float:
        """Cost per held share, or 0.0 when no shares are held."""
        return self.cost_basis / self.shares if self.shares else 0.0


def apply_transaction(position: Position, transaction: Transaction) -> dict | None:
    """Apply one transaction to a position, modifying it in place.

    The caller keeps one Position per symbol and must pass transactions in
    (transaction_date, id) order, otherwise sells can be matched against
    shares that were not held yet.

    Args:
        position: Position of the transaction's symbol. Updated in place.
        transaction: BUY or SELL transaction to apply.

    Returns:
        None for a BUY. For a SELL, a dict with the fields of
        schemas.ClosedTransaction describing the realized sale.

    Raises:
        ValueError: If the quantity is not positive, the transaction type
            is not BUY/SELL, or a SELL exceeds the shares held. Callers
            translate it into an HTTP error.
    """
    # transaction_type is normally the TransactionType enum, but accept a
    # plain string too.
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
    
    # Clear the float rounding residue left after selling every share, so a
    # later BUY starts from a clean cost basis.
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
        