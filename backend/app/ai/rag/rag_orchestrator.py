"""Run the RAG ingestion for every ticker traded on the platform.

Reads the tickers from Postgres, so the container must be running, and
downloads the latest 10-K of each one. Run as a module from backend/app/:

    uv run python -m ai.rag.rag_orchestrator
"""
import asyncio

from ai.rag.ingestion.loader import download_filings
from db.database import AsyncSessionLocal, engine
from services.holding_service import HoldingService


async def get_tickers() -> list[str]:
    """Return every ticker traded by any user.

    A script has no FastAPI request, so it opens its own session.

    Returns:
        list[str]: The ticker symbols.
    """
    async with AsyncSessionLocal() as session:
        tickers = await HoldingService(session).get_all_traded_symbols()
    await engine.dispose()
    return tickers


def main():
    """Get the tickers and download their filings."""
    tickers = asyncio.run(get_tickers())
    download_filings(tickers)
    


if __name__ == "__main__":
    main()
