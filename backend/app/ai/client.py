"""The only code that talks to the LLM provider.

Any OpenAI-compatible API works (OpenRouter today); the address, model and
key come from the llm_* settings in core/config.py, so switching provider
or model is a change to app/.env, not to code.

Every failure (not configured, network error, timeout, rate limit, bad key,
empty answer) is raised as LLMUnavailableError, so callers handle one error
type and the API can turn it into a single 503.
"""

import time
from dataclasses import dataclass

from openai import APIError, AsyncOpenAI

from core.config import settings


class LLMUnavailableError(Exception):
    """The model could not produce an answer. The message says why."""


@dataclass
class LLMResult:
    """The model's answer plus the data needed to log and compare calls."""

    text: str
    model: str
    latency_seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None


async def generate_text(system_prompt: str, user_prompt: str) -> LLMResult:
    """Send one prompt to the configured model and return its answer.

    Args:
        system_prompt: Instructions: role, rules, language, length.
        user_prompt: The content to work on (the portfolio data).

    Raises:
        LLMUnavailableError: If the LLM isn't configured, the request fails
            or times out, or the answer comes back empty.
    """
    if not settings.llm_configured:
        raise LLMUnavailableError("LLM is not configured (LLM_BASE_URL / LLM_MODEL missing)")

    # The client requires some key; providers that need none (e.g. Ollama)
    # ignore it.
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else "not-needed"

    start = time.perf_counter()
    try:
        # max_retries=1: one retry covers a brief hiccup without making the
        # user wait through several timeouts.
        async with AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
        ) as client:
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
            )
    except APIError as error:
        # Base class of connection errors, timeouts and every non-2xx status
        # (401 bad key, 402 no credits, 429 rate limit, 5xx provider down).
        raise LLMUnavailableError(f"LLM request failed: {error}") from error
    latency = time.perf_counter() - start

    # Some providers answer 200 with no choices or empty content when the
    # model fails, so check instead of trusting the status code.
    text = response.choices[0].message.content if response.choices else None
    if not text or not text.strip():
        raise LLMUnavailableError("LLM returned an empty answer")
    # "length" means the answer hit llm_max_tokens and was cut off mid-text
    # (reasoning models can spend the whole budget "thinking"). A half
    # summary is worse than none.
    if response.choices[0].finish_reason == "length":
        raise LLMUnavailableError("LLM answer was cut off (raise LLM_MAX_TOKENS or use a non-reasoning model)")

    usage = response.usage
    return LLMResult(
        text=text.strip(),
        model=response.model or settings.llm_model,
        latency_seconds=latency,
        input_tokens=usage.prompt_tokens if usage else None,
        output_tokens=usage.completion_tokens if usage else None,
    )