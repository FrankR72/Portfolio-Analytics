"""Convert the downloaded SEC filings to Markdown with sec2md.

Finds every HTML filing under backend/data/edgar/ (saved by ingest_data.py)
and writes a .md file with the same name next to it. Files that already
have a .md are skipped. This is an experiment to judge sec2md's parsing
quality; section extraction comes later. Run as a module from backend/app/:

    uv run python -m ai.rag.parse_document
"""
### Parsing SEC 10k documents

# 5 step strategy

# 1. download primary html done in ingest_data.py
# 2. divide into html <body><body> sections, treat each one as one block
# 3. detect items, not from the table of contents, but from the actual text, and label each block with the item number
# 4. detect css formats to dientify subsections
# 5. nest paragraphs and tables under the nearest header

# Do some testing to see how well sec2md works.

from pathlib import Path

import sec2md

# backend/data/edgar/.
EDGAR_DIR = Path(__file__).resolve().parents[3] / "data" / "edgar"


def extract_html_filing_paths(edgar_dir: Path) -> list[Path]:
    """Find every downloaded HTML filing under the EDGAR folder.

    Only works while ingest_data.py saves just the primary document of
    each filing; if exhibits are downloaded too, read primary_document
    from each metadata.json instead.

    Args:
        edgar_dir (Path): The folder with the filings ({cik}/{accession}/).

    Returns:
        list[Path]: Paths to the .htm and .html files, sorted.
    """
    return sorted(
        path for path in edgar_dir.rglob("*") if path.suffix in {".htm", ".html"}
    )


def convert_to_md(html_path: Path) -> Path:
    """Convert an HTML filing to Markdown and save it next to the HTML.

    A filing that already has a .md file is not converted again.

    Args:
        html_path (Path): Path to the HTML filing.

    Returns:
        Path: Path to the Markdown file.
    """
    md_path = html_path.with_suffix(".md")
    
    if md_path.exists():
        return md_path
    
    # sec2md takes the HTML itself (or a URL), not a file path: a path
    # given as a string would be parsed as if it were the HTML.
    filing_md = sec2md.convert_to_markdown(html_path.read_bytes())
    md_path.write_text(filing_md, encoding="utf-8")
    return md_path


def main():
    """Convert every downloaded filing to Markdown."""
    for html_path in extract_html_filing_paths(EDGAR_DIR):
        md_path = convert_to_md(html_path)
        print(f"{md_path} ({len(md_path.read_text(encoding='utf-8')):,} chars)")



if __name__ == "__main__":
    main()