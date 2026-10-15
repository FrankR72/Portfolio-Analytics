"""Tests for ai/client.py (the only code that talks to the LLM provider).

No network: AsyncOpenAI is patched in ai.client with a fake whose
chat.completions.create returns responses built with `response()`, shaped
like the openai package's (choices, finish_reason, usage). The LLM
settings are set per test with monkeypatch, because CI has no .env.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import APIConnectionError

from ai.client import LLMUnavailableError, generate_text
from core.config import settings


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def response(content="Resumen.", finish_reason="stop", choices=True):
    """A chat completion like the provider returns."""
    return SimpleNamespace(
        model="fake-model",
        choices=[SimpleNamespace(
            finish_reason=finish_reason, message=SimpleNamespace(content=content),
        )] if choices else [],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


@pytest.fixture(autouse=True)
def llm_configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "http://fake-llm/v1")
    monkeypatch.setattr(settings, "llm_model", "fake-model")
    monkeypatch.setattr(settings, "llm_disable_reasoning", True)


@pytest.fixture
def create(mocker):
    """The fake chat.completions.create; set return_value or side_effect."""
    create = AsyncMock(return_value=response())
    client = MagicMock()
    client.chat.completions.create = create
    # `async with AsyncOpenAI(...) as client` gives back this fake client.
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    mocker.patch("ai.client.AsyncOpenAI", return_value=client)
    return create


# ---------------------------------------------------------------------------
# generate_text
# ---------------------------------------------------------------------------

async def test_returns_text_and_usage(create):
    # Text stripped, model and tokens from the response.
    create.return_value = response(content="  Resumen.\n")

    result = await generate_text("system", "user")

    assert (result.text, result.model) == ("Resumen.", "fake-model")
    assert (result.input_tokens, result.output_tokens) == (100, 50)


async def test_sends_system_and_user_messages(create):
    # Instructions as "system", data as "user", in that order.
    await generate_text("las reglas", "los datos")

    assert create.call_args.kwargs["messages"] == [
        {"role": "system", "content": "las reglas"},
        {"role": "user", "content": "los datos"},
    ]


async def test_reasoning_disabled_by_default(create):
    # Otherwise reasoning models spend max_tokens thinking and return no text.
    await generate_text("system", "user")

    assert create.call_args.kwargs["extra_body"] == {"reasoning": {"enabled": False}}


async def test_reasoning_option_not_sent_when_turned_off(create, monkeypatch):
    # For providers that reject options outside the OpenAI standard.
    monkeypatch.setattr(settings, "llm_disable_reasoning", False)

    await generate_text("system", "user")

    assert create.call_args.kwargs["extra_body"] is None


async def test_not_configured_raises_without_calling(create, monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", None)

    with pytest.raises(LLMUnavailableError, match="not configured"):
        await generate_text("system", "user")

    create.assert_not_called()


async def test_cut_off_answer_raises_even_when_empty(create):
    # finish_reason "length" with empty text is what a reasoning model gives
    # when it thinks through the whole budget: report "cut off", not "empty".
    create.return_value = response(content="", finish_reason="length")

    with pytest.raises(LLMUnavailableError, match="cut off"):
        await generate_text("system", "user")


async def test_cut_off_answer_with_text_raises(create):
    # Half a summary is worse than none.
    create.return_value = response(content="El portafolio contiene", finish_reason="length")

    with pytest.raises(LLMUnavailableError, match="cut off"):
        await generate_text("system", "user")


@pytest.mark.parametrize("content", ["", "   ", None])
async def test_empty_answer_raises(create, content):
    create.return_value = response(content=content)

    with pytest.raises(LLMUnavailableError, match="empty"):
        await generate_text("system", "user")


async def test_no_choices_raises(create):
    create.return_value = response(choices=False)

    with pytest.raises(LLMUnavailableError, match="no answer"):
        await generate_text("system", "user")


async def test_provider_error_becomes_llm_unavailable(create):
    # Network errors, timeouts and 4xx/5xx all derive from openai.APIError.
    create.side_effect = APIConnectionError(request=httpx.Request("POST", "http://fake-llm/v1"))

    with pytest.raises(LLMUnavailableError, match="request failed"):
        await generate_text("system", "user")
