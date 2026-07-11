"""
Define models for Database using SQLAlchemy for the FastAPI application.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from datetime import datetime

from app.database import Base


class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    
    portfolios: Mapped[list[Portfolio]] = relationship(
        back_populates="author",
        cascade="all, delete-orphan"
    ) 
    


class Portfolio(Base):
    __tablename__ = "portfolios"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    date_created: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )
    author: Mapped[User] = relationship(back_populates="portfolios")
    
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan"
    )
    
    
class Transaction(Base):
    
    __tablename__ = "transactions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    transaction_type: Mapped[bool] = mapped_column(Boolean, nullable=False)
    quntity_actions: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    transaction_date: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id"),
        nullable=False,
        index=True
    )
    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")