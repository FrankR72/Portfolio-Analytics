from fastapi import FastAPI

from routers import UserRoutes, PortfolioRoutes

# Async-related imports
from contextlib import asynccontextmanager
from fastapi.exception_handlers import http_exception_handler, websocket_request_validation_exception_handler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


from database import Base, engine, get_db

# Create tables in a lifespan function
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await engine.dispose()
    




app = FastAPI(lifespan=lifespan)


@app.get("/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}

app.include_router(router=UserRoutes, prefix="api/users", tags=["users"])
app.include_router(router=PortfolioRoutes, prefix="api/portfolios", tags=["portfolios"])