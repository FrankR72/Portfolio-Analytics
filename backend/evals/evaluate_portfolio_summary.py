"""Compare models and prompt versions on a fixed set of portfolios.

Each case in portfolio_cases.json is run through the real pipeline
(build_snapshot -> build_prompt -> generate_text), every answer is scored
with checks.py, and the run is saved to results/ with its settings, so two
runs can be compared later. This calls real models and uses quota: it is
never run by pytest or CI.

Run from Portfolio-Analytics/ (uses the LLM settings in backend/app/.env):

    uv run python backend/evals/evaluate_portfolio_summary.py --dry-run
    uv run python backend/evals/evaluate_portfolio_summary.py
    uv run python backend/evals/evaluate_portfolio_summary.py \\
        --models nvidia/nemotron-3-super-120b-a12b:free google/gemma-4-31b-it:free \\
        --cases gains_and_losses missing_price --show
    uv run python backend/evals/evaluate_portfolio_summary.py \
        --rescore backend/evals/results/<file>.json --show

Free models allow few requests per minute and per day: --delay spaces the
calls out, and --cases runs a subset. --rescore scores the answers of a
saved run again with the current checks.py, without calling any model.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
# Same imports as the app (rooted at backend/app/), plus `evals.` from backend/.
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND)]

from ai.client import LLMUnavailableError, generate_text
from ai.prompts import DEFAULT_PROMPT_VERSION, build_prompt
from ai.snapshot import PortfolioSnapshot, build_snapshot
from core.config import settings
from db.schemas import ClosedTransaction, HoldingBase
from evals.checks import run_checks, score


CASES_FILE = Path(__file__).parent / "portfolio_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# Cases -> snapshots
# ---------------------------------------------------------------------------

def load_cases(ids: list[str] | None = None) -> list[dict]:
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    if ids:
        unknown = set(ids) - {c["id"] for c in cases}
        if unknown:
            raise SystemExit(f"Unknown case ids: {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in ids]
    return cases


def case_snapshot(case: dict) -> PortfolioSnapshot:
    """Build the snapshot with the app's own build_snapshot, from the case's raw numbers."""
    holdings = []
    for h in case["holdings"]:
        fields = dict(
            symbol=h["symbol"], number_current_shares=h["shares"],
            avg_cost_per_share=h["cost"] / h["shares"], cost_bases=h["cost"],
        )
        if h["value"] is not None:
            gain = h["value"] - h["cost"]
            fields.update(
                current_price_per_share=h["value"] / h["shares"], current_value=h["value"],
                unrealized_gain_loss=gain, return_percentage=gain / h["cost"] * 100,
            )
        holdings.append(HoldingBase(**fields))

    closed = []
    for s in case["sales"]:
        gain = s["proceeds"] - s["cost"]
        closed.append(ClosedTransaction(
            transaction_date=datetime(2026, 1, 1), symbol=s["symbol"],
            number_shares_sold=s["shares"], avg_cost_per_share=s["cost"] / s["shares"],
            sold_price_per_share=s["proceeds"] / s["shares"],
            total_cost_of_shares_sold=s["cost"], total_sold_price=s["proceeds"],
            realized_gain_loss=gain, return_percentage=gain / s["cost"] * 100,
        ))

    performance = None
    if case["performance"]:
        p = case["performance"]
        performance = {
            "start_date": p["start_date"], "end_date": p["end_date"],
            "history_limited": p["history_limited"],
            "points": [{"return_percentage": p["return_percentage"]}],
        }
    return build_snapshot(holdings, closed, performance)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

async def run_one(model: str, case: dict, prompt_version: str) -> dict:
    """One model on one case: the answer, its checks and the call's numbers."""
    snapshot = case_snapshot(case)
    prompt = build_prompt(snapshot, prompt_version)
    # generate_text reads the model from settings; the script owns this
    # process, so switching it per run is safe here.
    settings.llm_model = model
    row = {"model": model, "case": case["id"]}
    start = time.perf_counter()
    try:
        result = await generate_text(prompt.system, prompt.user)
    except LLMUnavailableError as error:
        return row | {"ok": False, "error": str(error)[:300], "latency_seconds": round(time.perf_counter() - start, 2)}

    checks = run_checks(result.text, snapshot)
    return row | {
        "ok": True,
        "latency_seconds": round(result.latency_seconds, 2),
        "output_tokens": result.output_tokens,
        "score": round(score(checks), 3),
        "checks": checks,
        "answer": result.text,
    }


def summarize_rows(rows: list[dict]) -> dict[str, dict]:
    """Per-model totals: answered calls, average score, median latency and
    how many answers passed each check. Saved in the results file and
    printed by print_report, so both always show the same numbers."""
    summary = {}
    for model in dict.fromkeys(r["model"] for r in rows):
        mine = [r for r in rows if r["model"] == model]
        ok = [r for r in mine if r["ok"]]
        entry = {"answered": f"{len(ok)}/{len(mine)}"}
        if not ok:
            entry["first_error"] = mine[0].get("error")
        else:
            entry["avg_score"] = round(statistics.mean(r["score"] for r in ok), 3)
            entry["median_latency_seconds"] = round(statistics.median(r["latency_seconds"] for r in ok), 2)
            entry["checks"] = {}
            for name in ok[0]["checks"]:
                # Only the answers where the check applies (None = not applicable).
                passed = [r["checks"][name]["passed"] for r in ok if r["checks"][name]["passed"] is not None]
                if passed:
                    entry["checks"][name] = f"{sum(passed)}/{len(passed)}"
        summary[model] = entry
    return summary


def print_report(rows: list[dict], show: bool) -> None:
    """Per-model table, then (with --show) every answer and its failed checks."""
    for model, entry in summarize_rows(rows).items():
        print(f"\n=== {model}")
        if "first_error" in entry:
            print(f"  answered: {entry['answered']}  (first error: {entry['first_error']})")
            continue
        print(f"  answered: {entry['answered']}   avg score: {entry['avg_score']:.0%}"
              f"   median latency: {entry['median_latency_seconds']:.1f}s")
        for name, passed in entry["checks"].items():
            print(f"    {name:<24} {passed}")

    if show:
        for r in rows:
            print(f"\n--- {r['model']} | {r['case']} | " + (f"score {r['score']:.0%}" if r["ok"] else f"ERROR {r['error']}"))
            if r["ok"]:
                print(r["answer"])
                for name, c in r["checks"].items():
                    if c["passed"] is False:
                        print(f"  ✗ {name}: {c['detail']}")


def rescore(path: Path, show: bool) -> None:
    """Run the current checks on the answers saved in a results file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in load_cases()}
    for row in data["rows"]:
        if row["ok"]:
            row["checks"] = run_checks(row["answer"], case_snapshot(cases[row["case"]]))
            row["score"] = round(score(row["checks"]), 3)
    print(f"Rescored {path.name} (prompt {data['prompt_version']}) with the current checks:")
    print_report(data["rows"], show)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--models", nargs="+", help="OpenRouter model ids (default: LLM_MODEL from .env)")
    parser.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION)
    parser.add_argument("--cases", nargs="+", help="Case ids to run (default: all)")
    parser.add_argument("--delay", type=float, default=4.0, help="Seconds between calls (rate limits)")
    parser.add_argument("--show", action="store_true", help="Print every answer and its failed checks")
    parser.add_argument("--dry-run", action="store_true", help="Print the first prompt and the plan; no calls")
    parser.add_argument("--rescore", type=Path, help="Score a saved results file again; no calls")
    args = parser.parse_args()

    if args.rescore:
        rescore(args.rescore, args.show)
        return

    models = args.models or [settings.llm_model]
    cases = load_cases(args.cases)
    if not settings.llm_configured and not args.dry_run:
        raise SystemExit("LLM_BASE_URL / LLM_MODEL are not set in backend/app/.env")

    if args.dry_run:
        prompt = build_prompt(case_snapshot(cases[0]), args.prompt_version)
        print(f"--- system ({args.prompt_version})\n{prompt.system}\n\n--- user ({cases[0]['id']})\n{prompt.user}\n")
        print(f"Would make {len(models) * len(cases)} calls: {len(models)} model(s) x {len(cases)} case(s).")
        return

    rows = []
    total = len(models) * len(cases)
    for model in models:
        for case in cases:
            if rows:
                await asyncio.sleep(args.delay)
            row = await run_one(model, case, args.prompt_version)
            rows.append(row)
            status = f"score {row['score']:.0%}" if row["ok"] else "ERROR"
            print(f"[{len(rows)}/{total}] {model} | {case['id']}: {status}", flush=True)

    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{args.prompt_version}.json"
    path.write_text(json.dumps({
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_version": args.prompt_version,
        "settings": {
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "disable_reasoning": settings.llm_disable_reasoning,
        },
        "models": models,
        "cases": [c["id"] for c in cases],
        "summary": summarize_rows(rows),
        "rows": rows,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print_report(rows, args.show)
    print(f"\nSaved to {path.relative_to(BACKEND.parent)}")


if __name__ == "__main__":
    asyncio.run(main())
