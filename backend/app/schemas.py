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
    pass



# Pydantic models for Portfolio
class PortfolioBase(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="The name of the portfolio")
    
class PortfolioCreate(PortfolioBase):
    pass

class PortfolioResponse(PortfolioBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    date_created: str