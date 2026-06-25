from fastapi import FastAPI

from routers import UserRoutes, PortfolioRoutes

# Async-related imports
from contextlib import asynccontextmanager
from fastapi.exception_handlers import http_exception_handler, websocket_request_validation_exception_handler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


# Create tables in a lifespan function


app = FastAPI()


@app.get("/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}

app.include_router(router=UserRoutes, prefix="api/users", tags=["users"])
app.include_router(router=PortfolioRoutes, prefix="api/portfolios", tags=["portfolios"])