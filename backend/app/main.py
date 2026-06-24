from fastapi import FastAPI

from routers import UserRoutes, PortfolioRoutes

app = FastAPI()


@app.get("/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}

app.include_router(router=UserRoutes, prefix="api/users", tags=["users"])
app.include_router(router=PortfolioRoutes, prefix="api/portfolios", tags=["portfolios"])