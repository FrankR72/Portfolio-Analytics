"""
Define models for Database using SQLAlchemy for the FastAPI application.
"""

from unittest.mock import Base

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[int] = mapped_column(String, unique=True, index=True)



class Portfolio(Base):
    __tablename__ = "portfolio"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    date_created: Mapped[datetime] = mapped_column(default=datetime.utcnow)