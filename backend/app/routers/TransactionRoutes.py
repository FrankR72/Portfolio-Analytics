from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from app.database import get_session
from app.models import Transaction, Portfolio
from app.schemas import TransactionCreate, TransactionResponse


router = APIRouter()