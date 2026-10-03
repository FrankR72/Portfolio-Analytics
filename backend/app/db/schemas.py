from pydantic import BaseModel, Field, ConfigDict, EmailStr, field_validator
from datetime import date, datetime
from models.models import TransactionType


# User schema
class UserBase(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=120)
    
class UserCreate(UserBase):
    password: str = Field(min_length=8)
    
class UserPublic(UserBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    username: str
    
class UserPrivate(UserPublic):
    email: EmailStr
    
class UserUpdate(UserBase):
    username: str | None = Field(min_length=1, max_length=100)
    email: EmailStr | None = Field(max_length=120)
    
    
# JWT token schema
class Token(BaseModel):
    access_token: str
    token_type: str



# Portfolio schema
def blank_to_none(value: str | None) -> str | None:
    """Strip a description and store an empty one as None, so "no
    description" has a single representation."""
    if value is None:
        return None
    return value.strip() or None


class PortfolioBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)

    _normalize_description = field_validator("description")(blank_to_none)

class PortfolioCreate(PortfolioBase):
    pass

class PortfolioPrivate(PortfolioBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int

class PortfolioUpdate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: str = Field(min_length=1, max_length=100)
    # PUT replaces both fields: leaving description out clears it.
    description: str | None = Field(default=None, max_length=255)

    _normalize_description = field_validator("description")(blank_to_none)


# Transaction schema
class TransactionBase(BaseModel):
    symbol: str = Field(min_length=1)
    transaction_type: TransactionType
    quantity_actions: int = Field(gt=0)
    price: float = Field(gt=0)


class TransactionCreate(TransactionBase):
    transaction_date: date | None = None


class TransactionPrivate(TransactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_date: datetime
    portfolio_id: int
    total_value: float = Field(gt=0)


class TransactionUpdate(BaseModel):
    symbol: str | None = Field(default=None, min_length=1)
    transaction_type: TransactionType | None = None
    quantity_actions: int | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, gt=0)


class ClosedTransaction(BaseModel):
    transaction_date: datetime
    symbol: str = Field(min_length=1)
    number_shares_sold: int = Field(gt=0)
    avg_cost_per_share: float = Field(gt=0)
    sold_price_per_share: float = Field(gt=0)
    total_cost_of_shares_sold: float = Field(gt=0)
    total_sold_price: float = Field(gt=0)
    realized_gain_loss: float
    return_percentage: float



# Holding schema
class HoldingBase(BaseModel):
    symbol: str = Field(min_length=1)
    number_current_shares: int = Field(gt=0)
    avg_cost_per_share: float = Field(gt=0)
    cost_bases: float = Field(gt=0) # total cost for all shares
    current_price_per_share: float | None = Field(default=None, gt=0)
    current_value: float | None = Field(default=None, gt=0) # current total value for all shares (yahoofinance)
    unrealized_gain_loss: float | None = Field(default=None)
    return_percentage: float | None = Field(default=None)
    
