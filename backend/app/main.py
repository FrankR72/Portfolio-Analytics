from fastapi import FastAPI

from app.routers import UserRoutes, PortfolioRoutes

# Async-related imports
from contextlib import asynccontextmanager


from app.database import Base, engine

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

app.include_router(UserRoutes.router, prefix="/api/users", tags=["users"])
app.include_router(PortfolioRoutes.router, prefix="/api/portfolios", tags=["portfolios"])