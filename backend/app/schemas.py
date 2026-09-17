from pydantic import BaseModel, Field, ConfigDict, EmailStr
from datetime import datetime
from models import TransactionType


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
class PortfolioBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    
class PortfolioCreate(PortfolioBase):
    pass

class PortfolioPrivate(PortfolioBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int

class PortfolioUpdate(PortfolioBase):
    name: str | None = Field(min_length=1, max_length=100)
    user_id: int | None = None


# Transaction schema
class TransactionBase(BaseModel):
    symbol: str = Field(min_length=1)
    transaction_type: TransactionType
    quantity_actions: int = Field(gt=0)
    price: float = Field(gt=0)


class TransactionCreate(TransactionBase):
    portfolio_id: int


class TransactionPrivate(TransactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_date: datetime
    portfolio_id: int


class TransactionUpdate(BaseModel):
    symbol: str | None = Field(default=None, min_length=1)
    transaction_type: TransactionType | None = None
    quantity_actions: int | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, gt=0)
