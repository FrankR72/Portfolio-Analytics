from dataclasses import dataclass

@dataclass
class Position:
    shares: int = 0
    cost_basis: float = 0.0
    
    @property
    def average_cost(self) ->float:
        return self.cost_basis / self.shares if self.shares else 0.0
    

def apply_transaction(position: Position):
    pass