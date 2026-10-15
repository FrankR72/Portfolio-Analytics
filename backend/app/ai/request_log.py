"""One log line per LLM call, to track latency, usage and failures over time.

Each call appends a JSON object on its own line ("JSON Lines") to
backend/logs/llm_requests.jsonl (gitignored). One object per line is easy
to append to and easy to load later (for example with pandas.read_json(...,
lines=True)) to see average latency, error rate or tokens per model.

What is logged: time, model, prompt version, latency, tokens, success and
the error message. What is not: the portfolio data, the prompt or the
answer, and no user or portfolio ids, so the log holds nothing personal.

Logging must never break a summary: if the file can't be written, the
error is ignored.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


# backend/logs/, next to app/. A module-level constant so tests can point
# it at a temporary file.
LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "llm_requests.jsonl"


def log_llm_call(
    *,
    model: str | None,
    prompt_version: str,
    success: bool,
    latency_seconds: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error: str | None = None,
) -> None:
    """Append one JSON line describing an LLM call."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "prompt_version": prompt_version,
        "success": success,
        "latency_seconds": round(latency_seconds, 2) if latency_seconds is not None else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        # Provider errors can be long; the start says what happened.
        "error": error[:300] if error else None,
    }
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
