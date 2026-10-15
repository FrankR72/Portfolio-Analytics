"""Tests for backend/evals/checks.py (how eval answers are scored).

The checks decide which model and prompt win, so they are tested like any
other logic: pure functions, fixed answers written by hand, no LLM. The
snapshot comes from the gains_and_losses eval case through the script's
case_snapshot (the app's real build_snapshot):

    AAPL  allocation 60.0%  unrealized +500.00 (+50.0%)
    MSFT  allocation 40.0%  unrealized -1,000.00 (-50.0%)
    total unrealized -500.00 (-16.7%), total value 2,500.00
    NVDA  sold 3 shares, realized +150.00 (+50.0%)
    return +8.2% from 2025-10-14 to 2026-10-14
"""

import pytest

from evals.checks import key_figures, numbers_in, quotes, run_checks, score
from evals.evaluate_portfolio_summary import case_snapshot, load_cases


GOOD = (
    "El portafolio tiene dos posiciones: AAPL pesa el 60.0% del valor total y MSFT el 40.0%, "
    "así que AAPL es la posición con más peso. El valor total de las posiciones es 2,500.00. "
    "La pérdida no realizada total es de -500.00, un -16.7%: AAPL gana +500.00, mientras que "
    "MSFT pierde -1,000.00, que es lo que más pesa en el resultado. "
    "Por las ventas ya hechas, la venta de 3 acciones de NVDA dejó una ganancia realizada de "
    "+150.00, un +50.0% sobre lo que costaron. "
    "Entre el 2025-10-14 y el 2026-10-14 la rentabilidad del portafolio fue de +8.2%, "
    "lo que muestra que en el año completo el conjunto avanzó a pesar de la pérdida de MSFT. "
    "En resumen, es un portafolio pequeño y concentrado en dos empresas de tecnología, "
    "con una posición ganadora y otra perdedora que hoy se compensan en parte, y con "
    "ganancias ya aseguradas por la venta de NVDA durante el período analizado."
)


@pytest.fixture(scope="module")
def snapshot():
    [case] = load_cases(["gains_and_losses"])
    return case_snapshot(case)


def failed(answer, snapshot):
    """Names of the checks that failed."""
    return {name for name, r in run_checks(answer, snapshot).items() if r["passed"] is False}


# ---------------------------------------------------------------------------
# numbers_in / quotes
# ---------------------------------------------------------------------------

def test_numbers_in_keeps_dates_whole_and_drops_punctuation():
    # "2025-10-14" is one token, not "2025", "-10", "-14"; the trailing
    # comma/period after a number is punctuation.
    assert numbers_in("Desde el 2025-10-14, subió +8.2%, y vale 1,500.00.") == [
        "2025-10-14", "+8.2%", "1,500.00",
    ]


def test_quotes_accepts_dropped_sign_but_not_a_bigger_number():
    # "-500.00" may be written "500.00"; "60.0%" must not match inside "160.00".
    assert quotes("una pérdida de 500.00", "-500.00")
    assert not quotes("vale 160.00 en total", "60.0%")


# ---------------------------------------------------------------------------
# run_checks
# ---------------------------------------------------------------------------

def test_good_answer_passes_everything(snapshot):
    # A hand-written answer that follows every rule: 100%.
    results = run_checks(GOOD, snapshot)

    assert failed(GOOD, snapshot) == set()
    assert results["explains_missing_price"]["passed"] is None  # no missing prices here
    assert score(results) == 1.0


@pytest.mark.parametrize("wrong, right", [
    ("-16.7%", "-16.67%"),  # more decimals than given
    ("+8.2%", "8%"),        # rounded
    ("-16.7%", "+16.7%"),  # opposite sign of the total loss
    ("2,500.00", "2.500,00"),  # reformatted (Spanish separators)
])
def test_changed_number_fails_exact_numbers(snapshot, wrong, right):
    # The model must copy numbers exactly as given.
    answer = GOOD.replace(wrong, right, 1)

    assert "exact_numbers" in failed(answer, snapshot)


def test_real_number_on_the_wrong_concept_is_not_caught(snapshot):
    # Known limit: "+500.00" exists (AAPL's gain), so calling it the total
    # passes. The check proves numbers come from the data, not that each is
    # attached to the right concept; that needs a human read.
    answer = GOOD.replace("La pérdida no realizada total es de -500.00", "La ganancia no realizada total es de +500.00")

    assert "exact_numbers" not in failed(answer, snapshot)


def test_invented_number_fails(snapshot):
    # A figure that isn't in the data at all.
    answer = GOOD + " La comisión fue de 12.50."

    assert "exact_numbers" in failed(answer, snapshot)


def test_small_counts_are_allowed(snapshot):
    # "3 acciones", "2 posiciones": counting isn't inventing a figure.
    assert "exact_numbers" not in failed(GOOD.replace("dos posiciones", "2 posiciones"), snapshot)


def test_missing_key_figure_fails(snapshot):
    # Without the period's return, one of the four topics is missing.
    answer = GOOD.replace("fue de +8.2%", "fue positiva")

    assert failed(answer, snapshot) >= {"key_figures"}
    assert key_figures(snapshot) == ["60.0%", "-500.00", "+150.00", "+8.2%"]


def test_missing_symbol_fails(snapshot):
    answer = GOOD.replace("NVDA", "una acción")

    assert "mentions_symbols" in failed(answer, snapshot)


@pytest.mark.parametrize("extra, check", [
    (" Te recomiendo vender MSFT.", "no_advice"),
    (" Deberías diversificar más.", "no_advice"),
    (" El valor total es de $2,500.00.", "no_currency"),
    (" No se proporciona información sobre dividendos.", "no_meta_talk"),
    (" El campo history_limited es false.", "no_meta_talk"),
])
def test_forbidden_content_fails(snapshot, extra, check):
    assert check in failed(GOOD + extra, snapshot)


def test_english_answer_fails(snapshot):
    answer = (
        "The portfolio has two positions and the gain of the portfolio is in line with "
        "the market, with AAPL and MSFT and the loss of the portfolio in MSFT."
    )

    assert "spanish" in failed(answer, snapshot)


def test_short_answer_fails_length(snapshot):
    assert "length" in failed("El portafolio sube +8.2%.", snapshot)


def test_many_symbols_need_not_all_be_named():
    # many_positions has 9 symbols: the prompt asks to highlight the main
    # ones, so mentions_symbols doesn't apply.
    [case] = load_cases(["many_positions"])

    assert run_checks("AAPL y MSFT son las mayores.", case_snapshot(case))[
        "mentions_symbols"]["passed"] is None


def test_saying_not_in_totals_is_not_meta_talk():
    # The prompt asks for it: "XYZ no se incluye en los totales".
    [case] = load_cases(["missing_price"])

    assert run_checks("XYZ no tiene precio y no se incluye en los totales.", case_snapshot(case))[
        "no_meta_talk"]["passed"] is True


def test_missing_price_must_be_explained():
    # missing_price case: XYZ has no price, so the answer must say so.
    [case] = load_cases(["missing_price"])
    snapshot = case_snapshot(case)

    assert run_checks("AAPL vale 1,450.00 y XYZ no tiene precio actual.", snapshot)[
        "explains_missing_price"]["passed"] is True
    assert run_checks("AAPL vale 1,450.00 y también hay XYZ.", snapshot)[
        "explains_missing_price"]["passed"] is False


# ---------------------------------------------------------------------------
# Cases file
# ---------------------------------------------------------------------------

def test_every_case_builds_a_snapshot():
    # A typo in portfolio_cases.json fails here, not halfway through a paid run.
    cases = load_cases()

    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        case_snapshot(case)
