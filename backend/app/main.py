from fastapi import FastAPI

from contextlib import asynccontextmanager

from database import Base, engine

from routers import user, auth



@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup code
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # Create tables if they don't exist
    yield
    # Shutdown code
    await engine.dispose()  # Dispose of the engine when the app shuts down
    

app = FastAPI(lifespan=lifespan)

@app.get("/", include_in_schema=False)
def root():
    return {"message": "¡Plataforma para Cuantifiación de Huella de Carbono!"}

# Routers
app.include_router(user.router, prefix="/api/users", tags=["Users"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])