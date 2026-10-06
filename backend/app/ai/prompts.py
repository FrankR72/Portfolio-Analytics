"""Builds the two messages sent to the LLM from a portfolio snapshot.

The instructions live in versioned text files in prompt_templates/
(summary_v1.txt, summary_v2.txt, ...), not in code, so the wording can
change without touching logic and each version stays comparable in the
evals. A new wording is a new file; an existing version is never edited
once its results are recorded.

The two messages:
- system: the instructions file, unchanged.
- user: the snapshot as JSON between <portfolio_data> tags. The tags mark
  it as data, so the model doesn't follow anything written inside it.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from ai.snapshot import PortfolioSnapshot


TEMPLATES_DIR = Path(__file__).parent / "prompt_templates"
DEFAULT_PROMPT_VERSION = "summary_v1"


@dataclass
class Prompt:
    """The messages for one call, plus the version used (for logs and evals)."""

    version: str
    system: str
    user: str


@cache
def load_system_prompt(version: str = DEFAULT_PROMPT_VERSION) -> str:
    """Read the instructions file for a prompt version (cached after the first read).

    Raises:
        ValueError: If there is no file for that version.
    """
    path = TEMPLATES_DIR / f"{version}.txt"
    if not path.is_file():
        available = sorted(p.stem for p in TEMPLATES_DIR.glob("*.txt"))
        raise ValueError(f"Unknown prompt version {version!r}. Available: {available}")
    return path.read_text(encoding="utf-8").strip()


def render_user_prompt(snapshot: PortfolioSnapshot) -> str:
    """Wrap the snapshot as JSON between <portfolio_data> tags.

    None fields are left out: they mean "no data", and leaving them out
    keeps the prompt shorter and gives the model nothing to misread.
    """
    data = snapshot.model_dump_json(indent=2, exclude_none=True)
    return f"<portfolio_data>\n{data}\n</portfolio_data>"


def build_prompt(snapshot: PortfolioSnapshot, version: str = DEFAULT_PROMPT_VERSION) -> Prompt:
    """Both messages for one summary request."""
    return Prompt(
        version=version,
        system=load_system_prompt(version),
        user=render_user_prompt(snapshot),
    )
