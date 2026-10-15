"""
Eval Grader type 1: code-based
 
Automatic checks for one summary, given the snapshot the model received.

Each check returns True (passed), False (failed) or None (doesn't apply to
this case), plus a short detail for the report. They are deliberately
simple text checks: cheap, repeatable, and good at catching the mistakes
that matter most here (invented or reformatted numbers, missing key
figures, advice, wrong language). Tone and clarity still need a human
read of the answers saved in results/.

Known limit of exact_numbers: it proves every number comes from the data
and is written as given, not that it is attached to the right concept (a
real "+500.00" called "the total" passes). Read the answers too.
"""

import re

from ai.snapshot import PortfolioSnapshot


# The prompt asks for 120-200 words.
MIN_WORDS, MAX_WORDS = 100, 200

# With more symbols than this, the prompt asks to highlight the ones that
# matter most, so naming every symbol isn't required.
MAX_SYMBOLS_TO_NAME = 5

# Plain integers up to this are allowed anywhere ("dos posiciones", "3
# acciones", "4 activos"): counting things isn't inventing a figure.
SMALL_INT_LIMIT = 20

ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# A number as the snapshot writes it: optional sign, thousands commas,
# decimals, optional "%".
NUMBER = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?%?")

ADVICE = re.compile(
    r"te recomiendo|recomendamos|recomendaría|recomendable|deberías|debería considerar|"
    r"te sugiero|sugerimos|conviene|aconsej|considera (vender|comprar|diversificar)",
    re.IGNORECASE,
)
CURRENCY = re.compile(r"\$|\bUSD\b|dólar|dolar|\beuros?\b|€", re.IGNORECASE)
# Talking about the data itself instead of the portfolio: field names, or
# saying that something is missing (the prompt says not to mention it).
META_TALK = re.compile(
    r"\b(performance|positions_without_price|start_date|end_date|history_limited|null|"
    r"campos?|JSON)\b|no se (proporciona|dispone|especifica)|no hay (información|datos)",
    re.IGNORECASE,
)
SPANISH_WORDS = {"el", "la", "los", "las", "de", "del", "que", "con", "por", "una", "su", "es", "en", "y"}
ENGLISH_WORDS = {"the", "and", "of", "with", "your", "is", "in", "portfolio", "gain", "loss"}


def _variants(value: str) -> set[str]:
    """A formatted value with and without its sign and "%" ("+12.5%" -> 4 forms).

    Dropping the sign is fine ("una pérdida de 500.00"); writing the
    opposite sign is not, and is not in the set.
    """
    unsigned = value.lstrip("+-")
    return {value, value.rstrip("%"), unsigned, unsigned.rstrip("%")}


def allowed_numbers(snapshot: PortfolioSnapshot) -> set[str]:
    """Every number the model may write, as text."""
    allowed = set()
    strings = [
        snapshot.total_value,
        snapshot.total_cost,
        snapshot.total_unrealized_gain, 
        snapshot.total_unrealized_return,
        snapshot.total_realized_gain,
    ]
    for p in snapshot.positions:
        strings += [p.cost_basis, p.current_value, p.allocation, p.unrealized_gain, p.unrealized_return]
        allowed.add(str(p.shares))
    for r in snapshot.realized:
        strings += [r.realized_gain, r.realized_return]
        allowed.add(str(r.shares_sold))
    if snapshot.performance:
        strings.append(snapshot.performance.return_percentage)
        for day in (snapshot.performance.start_date, snapshot.performance.end_date):
            allowed |= {day, day[:4]}  # the full date, or just its year
    for s in strings:
        if s is not None:
            allowed |= _variants(s)
    return allowed


def numbers_in(answer: str) -> list[str]:
    """The numbers written in an answer, as text (ISO dates kept whole)."""
    dates = ISO_DATE.findall(answer)
    rest = ISO_DATE.sub(" ", answer)
    # A comma or period right after a number is punctuation, not a decimal.
    return dates + [n.rstrip(",.") for n in NUMBER.findall(rest)]


def quotes(answer: str, value: str) -> bool:
    """True if the answer writes this value in one of its allowed forms.

    Not inside a bigger number: "60.0%" must not match "160.00".
    """
    return any(
        re.search(rf"(?<![\d.,]){re.escape(form)}(?![\d])", answer)
        for form in _variants(value)
    )


def key_figures(snapshot: PortfolioSnapshot) -> list[str]:
    """The figures a good summary must quote, one per topic the prompt asks for."""
    figures = []
    if snapshot.positions and snapshot.positions[0].allocation:
        figures.append(snapshot.positions[0].allocation)  # weight of the largest position, assumes positions are ordered
    figures += [snapshot.total_unrealized_gain, snapshot.total_realized_gain]
    if snapshot.performance:
        figures.append(snapshot.performance.return_percentage)
    return [f for f in figures if f is not None]


def run_checks(answer: str, snapshot: PortfolioSnapshot) -> dict[str, dict]:
    """All checks for one answer: {name: {"passed": bool | None, "detail": str}}."""
    results = {}

    def record(name, passed, detail=""):
        results[name] = {"passed": passed, "detail": detail}

    words = len(answer.split())
    record("length", MIN_WORDS <= words <= MAX_WORDS, f"{words} words")

    tokens = re.findall(r"[a-záéíóúñ]+", answer.lower())
    spanish = sum(t in SPANISH_WORDS for t in tokens)
    english = sum(t in ENGLISH_WORDS for t in tokens)
    record("spanish", spanish > 3 * max(english, 1), f"{spanish} es / {english} en markers")

    # No number the snapshot doesn't contain, written exactly as given.
    allowed = allowed_numbers(snapshot)
    invented = [
        n for n in numbers_in(answer)
        if n not in allowed and not (n.isdigit() and int(n) <= SMALL_INT_LIMIT)
    ]
    record("exact_numbers", not invented, ", ".join(invented))

    missing = [f for f in key_figures(snapshot) if not quotes(answer, f)]
    record("key_figures", not missing, "missing " + ", ".join(missing) if missing else "")

    symbols = list(dict.fromkeys([p.symbol for p in snapshot.positions] + [r.symbol for r in snapshot.realized]))
    if len(symbols) <= MAX_SYMBOLS_TO_NAME:
        absent = [s for s in symbols if not re.search(rf"\b{re.escape(s)}\b", answer)]
        record("mentions_symbols", not absent, "missing " + ", ".join(absent) if absent else "")
    else:
        record("mentions_symbols", None)

    if snapshot.positions_without_price:
        ok = "precio" in answer.lower() and all(s in answer for s in snapshot.positions_without_price)
        record("explains_missing_price", ok)
    else:
        record("explains_missing_price", None)

    advice = [m.group(0) for m in ADVICE.finditer(answer)]
    record("no_advice", not advice, ", ".join(advice))
    currency = [m.group(0) for m in CURRENCY.finditer(answer)]
    record("no_currency", not currency, ", ".join(currency))
    meta = [m.group(0) for m in META_TALK.finditer(answer)]
    record("no_meta_talk", not meta, ", ".join(meta))

    return results


def score(results: dict[str, dict]) -> float:
    """Share of the applicable checks that passed (0.0 to 1.0)."""
    applicable = [r["passed"] for r in results.values() if r["passed"] is not None]
    return sum(applicable) / len(applicable) if applicable else 0.0
