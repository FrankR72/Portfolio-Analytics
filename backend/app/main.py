from fastapi import FastAPI

from contextlib import asynccontextmanager

from db.database import engine

from routers import user, auth, portfolio, transaction, holding

from db.redis_client import redis_client


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Shutdown code
    await engine.dispose() 
    if redis_client is not None:
        redis_client.close()
    

app = FastAPI(lifespan=lifespan)

@app.get("/", include_in_schema=False)
def root():
    return {"message": "¡Stock Platform!"}

# Routers
app.include_router(user.router, prefix="/api/users", tags=["Users"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(portfolio.router, prefix="/api/portfolios", tags=["Portfolios"])
app.include_router(transaction.router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(holding.router, prefix="/api/holdings", tags=["holdings"])
