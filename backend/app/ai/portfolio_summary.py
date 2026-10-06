"""Plain-language summary of a portfolio, written by an LLM.

The coordinator of the ai/ package. It gets the numbers from the existing
services, packs them with build_snapshot, builds the prompt, calls the
model and logs the call. Every calculation happens in the services and in
snapshot.py; the model only puts the numbers into words.

Only three services are used (holdings, closed transactions, performance).
The distribution endpoints would fetch every price again and turn a failed
lookup into a 500, while summarize_holdings already has value and gain per
position and survives a failed lookup.

No ownership check here: the services already do it, so a portfolio that
isn't the user's raises their 404 before anything is sent to the model.
"""

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ai.client import LLMUnavailableError, generate_text
from ai.prompts import DEFAULT_PROMPT_VERSION, build_prompt
from ai.request_log import log_llm_call
from ai.snapshot import build_snapshot
from core.config import settings
from services.analytic_service import AnalyticService
from services.holding_service import HoldingService
from services.transaction_service import TransactionService


# Period of the return shown in the summary.
PERFORMANCE_DAYS = 365

# Answer for a portfolio with no positions and no sales. Fixed text instead
# of an LLM call: there is nothing to explain, so don't spend quota or time.
EMPTY_PORTFOLIO_SUMMARY = (
    "Este portafolio todavía no tiene transacciones para analizar. "
    "Agrega una compra para ver aquí un resumen."
)


class PortfolioSummaryService:
    def __init__(self, session: AsyncSession):
        self.holding_service = HoldingService(session)
        self.transaction_service = TransactionService(session)
        self.analytic_service = AnalyticService(session)

    async def summarize(
        self,
        user_id: int,
        portfolio_id: int,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
    ) -> str:
        """Return a plain-language summary of the portfolio, in Spanish.

        Raises:
            HTTPException: 404 if the portfolio isn't the user's, 400 if its
                transaction history is invalid (from the services).
            LLMUnavailableError: If the LLM isn't configured or the call
                fails.
        """
        # Check first, so an unconfigured app doesn't fetch prices for
        # nothing.
        if not settings.llm_configured:
            raise LLMUnavailableError("LLM is not configured (LLM_BASE_URL / LLM_MODEL missing)")

        holdings = await self.holding_service.summarize_holdings(portfolio_id, user_id)
        closed = await self.transaction_service.get_closed_transactions(portfolio_id, user_id)
        if not holdings and not closed:
            return EMPTY_PORTFOLIO_SUMMARY

        performance = await self._performance_or_none(user_id, portfolio_id)

        prompt = build_prompt(build_snapshot(holdings, closed, performance), prompt_version)
        try:
            result = await generate_text(prompt.system, prompt.user)
        except LLMUnavailableError as error:
            log_llm_call(
                model=settings.llm_model, prompt_version=prompt.version,
                success=False, error=str(error),
            )
            raise

        log_llm_call(
            model=result.model, prompt_version=prompt.version, success=True,
            latency_seconds=result.latency_seconds,
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        )
        return result.text

    async def _performance_or_none(self, user_id: int, portfolio_id: int) -> dict | None:
        """Return over the last PERFORMANCE_DAYS, or None if it can't be calculated.

        get_portfolio_performance raises ValueError on purpose in several
        cases (a stock split in the period, a missing price, ...). The
        return is one part of the summary, so the summary goes ahead
        without it instead of failing.
        """
        end = date.today()
        try:
            return await self.analytic_service.get_portfolio_performance(
                user_id, portfolio_id, start_date=end - timedelta(days=PERFORMANCE_DAYS), end_date=end,
            )
        except ValueError:
            return None