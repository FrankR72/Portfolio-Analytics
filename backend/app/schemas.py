from pydantic import BaseModel, Field, ConfigDict, EmailStr

from sqlalchemy import String


# User schema
class UserBase(BaseModel):
    username: str = Field(String, min_length=1, max_length=100)
    email: EmailStr = Field(String, max_length=120)
    
class UserCreate(UserBase):
    password: str = Field(String, min_length=8)
    
class UserPublic(UserBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    username: str
    
class UserPrivate(UserPublic):
    email: EmailStr
    
class UserUpdate(UserBase):
    username: str | None = Field(String, min_length=1, max_length=100)
    email: EmailStr | None = Field(String, max_length=120)
    
    
# JWT token schema
class Token(BaseModel):
    access_token: str
    token_type: str
