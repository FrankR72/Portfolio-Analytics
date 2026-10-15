"""Tests for ai/prompts.py (the messages sent to the LLM).

Pure functions: snapshots are built with build_snapshot from plain
HoldingBase objects, and the real files in prompt_templates/ are read. No
database, no network, no LLM call. These tests check that the prompt is
assembled correctly, not how good the model's answer is (that's the evals'
job).
"""

import json

import pytest

from ai.prompts import (
    DEFAULT_PROMPT_VERSION,
    TEMPLATES_DIR,
    build_prompt,
    load_system_prompt,
    render_user_prompt,
)
from ai.snapshot import build_snapshot
from db.schemas import HoldingBase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def holding(symbol, shares, cost, value=None):
    """Open position; value=None means the price lookup failed."""
    fields = dict(
        symbol=symbol, number_current_shares=shares,
        avg_cost_per_share=cost / shares, cost_bases=cost,
    )
    if value is not None:
        gain = value - cost
        fields.update(
            current_price_per_share=value / shares, current_value=value,
            unrealized_gain_loss=gain, return_percentage=gain / cost * 100,
        )
    return HoldingBase(**fields)


def unwrap(user_prompt):
    """The JSON between the <portfolio_data> tags, parsed."""
    start, end = "<portfolio_data>\n", "\n</portfolio_data>"
    assert user_prompt.startswith(start) and user_prompt.endswith(end)
    return json.loads(user_prompt[len(start):-len(end)])


# ---------------------------------------------------------------------------
# load_system_prompt
# ---------------------------------------------------------------------------

def test_default_version_file_exists_and_is_loaded():
    # The default version must always have its file.
    assert (TEMPLATES_DIR / f"{DEFAULT_PROMPT_VERSION}.txt").is_file()
    assert load_system_prompt().startswith("Eres un asistente")


def test_system_prompt_mentions_the_data_tags():
    # The instructions and render_user_prompt must use the same tags, or the
    # model is told to look for data that isn't marked that way.
    system = load_system_prompt()
    assert "<portfolio_data>" in system and "</portfolio_data>" in system


def test_unknown_version_raises_and_lists_available():
    # A typo in the version name fails clearly instead of sending no prompt.
    with pytest.raises(ValueError, match="summary_v1"):
        load_system_prompt("summary_v999")


# ---------------------------------------------------------------------------
# render_user_prompt
# ---------------------------------------------------------------------------

def test_user_prompt_is_the_snapshot_between_tags():
    # AAPL: cost 1000, value 1500 -> gain +500.00, 100.0% of the portfolio.
    snapshot = build_snapshot([holding("AAPL", 10, 1000, 1500)], [])

    data = unwrap(render_user_prompt(snapshot))

    assert data["positions"][0]["symbol"] == "AAPL"
    assert data["positions"][0]["unrealized_gain"] == "+500.00"
    assert data["total_value"] == "1,500.00"


def test_user_prompt_leaves_out_none_fields():
    # TSLA has no price, so its value/allocation/gain are None and left out;
    # price_available=False stays. No sales -> no total_realized_gain.
    snapshot = build_snapshot([holding("TSLA", 2, 400)], [])

    data = unwrap(render_user_prompt(snapshot))

    assert data["positions"][0] == {
        "symbol": "TSLA", "shares": 2, "cost_basis": "400.00", "price_available": False,
    }
    assert "total_realized_gain" not in data
    assert "performance" not in data


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

def test_build_prompt_combines_both_messages_and_records_version():
    # system = the instructions file; user = the wrapped snapshot.
    snapshot = build_snapshot([holding("AAPL", 10, 1000, 1500)], [])

    prompt = build_prompt(snapshot)

    assert prompt.version == DEFAULT_PROMPT_VERSION
    assert prompt.system == load_system_prompt(DEFAULT_PROMPT_VERSION)
    assert prompt.user == render_user_prompt(snapshot)
