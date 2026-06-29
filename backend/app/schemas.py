"""
Define Pydantic models for request and response validation in the FastAPI application.
"""
from pydantic import BaseModel, Field, ConfigDict, EmailStr



# Pydantic models for User
class UserBase(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=120)
    
class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int

class UserUpdate(UserBase):
    username: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=120)



# Pydantic models for Portfolio
class PortfolioBase(BaseModel):
    title: str = Field(max_length=100, description="The name of the portfolio")
    
class PortfolioCreate(PortfolioBase):
    user_id: int #TEMPORARY

class PortfolioResponse(PortfolioBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    date_created: str
    author: UserResponse
    
class PortfolioUpdate(PortfolioBase):
    title: str | None = Field(default=None, max_length=100)
    