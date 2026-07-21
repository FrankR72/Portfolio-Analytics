"""
Define Pydantic models for request and response validation in the FastAPI application.
"""
from pydantic import BaseModel, Field, ConfigDict, EmailStr

from datetime import datetime


# Pydantic models for User
class UserBase(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=120)
    
class UserCreate(UserBase):
    password: str = Field(min_length=8)

class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    username: str
    
class UserPrivate(UserPublic):
    email: EmailStr


class UserUpdate(UserBase):
    username: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=120)



# Pydantic models for Portfolio
class PortfolioBase(BaseModel):
    title: str = Field(max_length=100, description="The title of the portfolio")
    
class PortfolioCreate(PortfolioBase):
    user_id: int #TEMPORARY

class PortfolioResponse(PortfolioBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    date_created: str
    author: UserPublic
    
class PortfolioUpdate(PortfolioBase):
    title: str | None = Field(default=None, max_length=100)
    


# Pydantic models for Transactions
class TransactionBase(BaseModel):
    symbol: str = Field(min_length=1, max_length=6, description="The symbol of the stock.")
    transaction_type: bool
    quantity_actions: int = Field(gt=0)
    price: float = Field(gt=0)
    
class TransactionCreate(TransactionBase):
    portfolio_id : int #TEMPORARY

class TransactionResponse(TransactionBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    portfolio_id: int
    transaction_date: datetime
    portfolio: PortfolioResponse

class TransactionUpdate(TransactionBase):
    symbol: str | None = Field(default=None, min_length=1, max_length=6)
    transaction_type: bool | None = Field(default=None)
    quantity_actions: int | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, gt=0)
    

# Pydantic models for Auth
class LoginRequest(BaseModel):
    email: EmailStr
    

class Token(BaseModel):
    access_token: str
    token_type: str