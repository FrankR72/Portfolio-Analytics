"""Split the downloaded 10-K filings into chunks that follow their structure.

Each filing is parsed with sec2md into pages and Item sections. Inside an
Item, chunks follow the filing's own headings (subsection, sub-subsection,
risk factor), so a chunk is a heading with its paragraphs and whole tables
and its length varies. A token limit is only a fallback: a unit over
MAX_TOKENS is split into parts of about TARGET_TOKENS.

sec2md doesn't detect headings in these filings (it only marks <h1>-<h6>
tags, which they don't use), so they're found from the styling that
survives in the element text: ALL-CAPS lines, whole-line bold/italic, and
a bold lead-in sentence (how Item 1A titles each risk factor). The rules
were tuned on MSFT's 10-K; a section without any detected heading becomes
one unit and is split by the fallback.

Each chunk keeps its content, its embedding text (header + content) and
its metadata apart, and the chunks of each filing are written to
chunks_preview.jsonl next to its HTML to inspect them. This is an
experiment to compare chunking strategies; no embeddings yet. Run as a
module from backend/app/:

    uv run python -m ai.rag.chunking
"""
import json
import re
import statistics
from pathlib import Path

import sec2md
from sec2md.chunker.chunker import Chunker
from sec2md.utils import count_tokens

from ai.rag.parse_document import EDGAR_DIR, extract_html_filing_paths

PREVIEW_FILE = "chunks_preview.jsonl"

# A unit over MAX_TOKENS is split into parts of about TARGET_TOKENS.
TARGET_TOKENS = 512
MAX_TOKENS = 800

# The titles sec2md reads from the filing can have broken letter spacing
# ("RIS K FACTORS"), so the header uses the official Form 10-K titles.
ITEM_10K_TITLES = {
    "ITEM 1": "Business",
    "ITEM 1A": "Risk Factors",
    "ITEM 1B": "Unresolved Staff Comments",
    "ITEM 1C": "Cybersecurity",
    "ITEM 2": "Properties",
    "ITEM 3": "Legal Proceedings",
    "ITEM 4": "Mine Safety Disclosures",
    "ITEM 5": "Market for Registrant's Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities",
    "ITEM 6": "[Reserved]",
    "ITEM 7": "Management's Discussion and Analysis of Financial Condition and Results of Operations",
    "ITEM 7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "ITEM 8": "Financial Statements and Supplementary Data",
    "ITEM 9": "Changes in and Disagreements with Accountants on Accounting and Financial Disclosure",
    "ITEM 9A": "Controls and Procedures",
    "ITEM 9B": "Other Information",
    "ITEM 9C": "Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",
    "ITEM 10": "Directors, Executive Officers and Corporate Governance",
    "ITEM 11": "Executive Compensation",
    "ITEM 12": "Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters",
    "ITEM 13": "Certain Relationships and Related Transactions, and Director Independence",
    "ITEM 14": "Principal Accountant Fees and Services",
    "ITEM 15": "Exhibits and Financial Statement Schedules",
    "ITEM 16": "Form 10-K Summary",
}

# Page furniture: running "PART I" headers and bare page numbers.
FURNITURE_RE = re.compile(r"^(PART\s+[IV]+|\d{1,3}|Table of Contents)$", re.IGNORECASE)
# The Item's own heading; the header already says which Item it is.
ITEM_HEADING_RE = re.compile(r"^\**\s*ITEM\s+\d+[A-C]?\b")
# A whole line in *italic*, **bold** or ***bold italic***.
EMPHASIS_RE = re.compile(r"^(\*{1,3})([^*].*?)\*{1,3}$")
# "**Bold lead-in sentence.** Body..." (a risk factor's title).
LEAD_IN_RE = re.compile(r"^\*\*([^*]{20,}?)\*\*\s+\S")


def heading_of(line: str) -> tuple[int, str] | None:
    """Tell whether a line is a heading, and at which level.

    Levels: 2 ALL-CAPS line, 3 ***bold italic***, 4 **bold** or *italic*,
    5 bold lead-in sentence. A lower number is a higher level.

    Args:
        line (str): A stripped line of element text.

    Returns:
        tuple[int, str] | None: The level and the title without markup, or
            None if the line isn't a heading.
    """
    if match := EMPHASIS_RE.match(line):
        if len(line) < 300:
            return (3 if len(match.group(1)) == 3 else 4), match.group(2).strip()
        return None
    if match := LEAD_IN_RE.match(line):
        return 5, match.group(1).strip()
    letters = re.sub(r"[^A-Za-z]", "", line)
    if len(letters) > 3 and line.upper() == line and len(line) < 100:
        return 2, line
    return None


def section_blocks(section) -> list[dict]:
    """Turn a section's elements into blocks of text lines and whole tables.

    Every non-empty line of an element is a block, except that a run of
    "|" lines is one table block. Page furniture and the Item heading are
    dropped. A page sec2md left without elements (it happens in tiny
    sections like "Not applicable.") falls back to the page's text, like
    sec2md's own chunker does; its blocks have no element_id.

    Args:
        section (sec2md.Section): A section from sec2md.extract_sections.

    Returns:
        list[dict]: Blocks in reading order, each with kind ("text" or
            "table"), text, page, page_end, element_id and tags.
    """
    blocks = []
    for page in section.pages:
        elements = list(enumerate(page.elements or []))
        # Same order sec2md's own chunker uses: by offset when known.
        elements.sort(key=lambda pair: (
            pair[1].content_start_offset if pair[1].content_start_offset is not None else float("inf"),
            pair[0],
        ))
        sources = [
            (element.content, {
                "page": element.page_start,
                "page_end": element.page_end,
                "element_id": element.id,
                "tags": element.tags or [],
            })
            for _, element in elements
        ] or [(page.content, {"page": page.number, "page_end": page.number, "element_id": None, "tags": []})]

        for text, source in sources:
            table_lines = []
            for line in text.split("\n") + [""]:
                line = line.strip()
                if line.startswith("|"):
                    table_lines.append(line)
                    continue
                if table_lines:
                    blocks.append({"kind": "table", "text": "\n".join(table_lines), **source})
                    table_lines = []
                if not line or FURNITURE_RE.match(line):
                    continue
                plain = line.strip("*").strip()
                if ITEM_HEADING_RE.match(line) and plain.upper() == plain:
                    continue
                blocks.append({"kind": "text", "text": line, **source})
    return blocks


def group_units(blocks: list[dict]) -> list[dict]:
    """Group blocks under the heading they belong to.

    A heading opens a new unit and replaces the headings at its level and
    below in the current path. Levels 2-4 headings go only into the path;
    a bold lead-in stays in the text too, since it's the first sentence of
    its paragraph. A heading followed directly by another one leaves no
    unit of its own, but its title stays in the next unit's path.

    Args:
        blocks (list[dict]): Blocks from section_blocks.

    Returns:
        list[dict]: Units, each with path (heading titles, top first) and
            blocks.
    """
    units = []
    path: dict[int, str] = {}
    current = None
    for block in blocks:
        heading = heading_of(block["text"]) if block["kind"] == "text" else None
        if heading:
            level, title = heading
            path = {lvl: t for lvl, t in path.items() if lvl < level}
            path[level] = title
            current = {"path": [path[lvl] for lvl in sorted(path)], "blocks": []}
            units.append(current)
            if level == 5:
                current["blocks"].append(block)
            continue
        if current is None:
            current = {"path": [], "blocks": []}
            units.append(current)
        current["blocks"].append(block)
    return [unit for unit in units if unit["blocks"]]


def block_text(blocks: list[dict]) -> str:
    """Join blocks into chunk content, one paragraph or table per block."""
    return "\n\n".join(block["text"] for block in blocks)


def split_unit(unit: dict) -> list[list[dict]]:
    """Split a unit over MAX_TOKENS into parts; smaller units stay whole.

    Whole blocks are packed into parts of about TARGET_TOKENS. Tables are
    never split. A single paragraph over MAX_TOKENS is split by sentences
    with sec2md's chunker.

    Args:
        unit (dict): A unit from group_units.

    Returns:
        list[list[dict]]: The blocks of each part.
    """
    if count_tokens(block_text(unit["blocks"])) <= MAX_TOKENS:
        return [unit["blocks"]]

    parts = []
    current: list[dict] = []
    current_tokens = 0
    for block in unit["blocks"]:
        tokens = count_tokens(block["text"])
        if block["kind"] == "text" and tokens > MAX_TOKENS:
            if current:
                parts.append(current)
                current, current_tokens = [], 0
            sentences = Chunker(chunk_size=TARGET_TOKENS, chunk_overlap=0).chunk_text(block["text"])
            parts.extend([{**block, "text": text}] for text in sentences)
            continue
        if current and current_tokens + tokens > TARGET_TOKENS:
            parts.append(current)
            current, current_tokens = [], 0
        current.append(block)
        current_tokens += tokens
    if current:
        parts.append(current)
    return parts


def build_header(metadata: dict, section, path: list[str]) -> str:
    """Build the header that goes in front of a chunk's embedding text.

    Example: "MSFT | Form 10-K | Fiscal year ended 2026-06-30 | Item 1A:
    Risk Factors > STRATEGIC AND COMPETITIVE RISKS > Business model
    competition".

    Args:
        metadata (dict): The filing's metadata.json.
        section (sec2md.Section): The chunk's section.
        path (list[str]): The chunk's heading titles, top first.

    Returns:
        str: The header.
    """
    titles = ITEM_10K_TITLES if metadata["form"] == "10-K" else {}
    if section.item:
        location = f"{section.item.title()}: {titles.get(section.item, section.item_title)}"
    else:
        location = section.item_title or "Unknown section"
    location = " > ".join([location, *path])
    return (
        f"{metadata['ticker']} | Form {metadata['form']} | "
        f"Fiscal year ended {metadata['report_date']} | {location}"
    )


def chunk_filing(html_path: Path) -> list[dict]:
    """Split one downloaded filing into structure-aware chunks.

    Args:
        html_path (Path): Path to the filing's HTML; its metadata.json must
            be in the same folder.

    Returns:
        list[dict]: One record per chunk, with chunk_id, content,
            embedding_text and metadata kept apart.
    """
    metadata = json.loads((html_path.parent / "metadata.json").read_text(encoding="utf-8"))
    pages = sec2md.convert_to_markdown(html_path.read_bytes(), return_pages=True)
    sections = sec2md.extract_sections(pages, filing_type=metadata["form"])
    titles = ITEM_10K_TITLES if metadata["form"] == "10-K" else {}

    records = []
    for section in sections:
        display_pages = {page.number: page.display_page for page in section.pages}
        for unit in group_units(section_blocks(section)):
            parts = split_unit(unit)
            for part_index, blocks in enumerate(parts):
                header = build_header(metadata, section, unit["path"])
                content = block_text(blocks)
                embedding_text = f"{header}\n\n{content}"
                start_page = min(block["page"] for block in blocks)
                end_page = max(block["page_end"] for block in blocks)
                records.append({
                    "chunk_id": f"{metadata['accession_number']}-{len(records):04d}",
                    "content": content,
                    "embedding_text": embedding_text,
                    "metadata": {
                        "ticker": metadata["ticker"],
                        "cik": metadata["cik"],
                        "form": metadata["form"],
                        "accession_number": metadata["accession_number"],
                        "filing_date": metadata["filing_date"],
                        "report_date": metadata["report_date"],
                        "part": section.part,
                        "item": section.item,
                        "item_title": titles.get(section.item, section.item_title),
                        "heading_path": unit["path"],
                        "part_index": part_index,
                        "parts": len(parts),
                        "start_page": start_page,
                        "end_page": end_page,
                        "start_display_page": display_pages.get(start_page),
                        "end_display_page": display_pages.get(end_page),
                        "num_tokens": count_tokens(content),
                        "embedding_tokens": count_tokens(embedding_text),
                        "has_table": any(block["kind"] == "table" for block in blocks),
                        "element_ids": list(dict.fromkeys(
                            block["element_id"] for block in blocks if block["element_id"]
                        )),
                        # Sorted so the file is the same on every run.
                        "xbrl_tags": sorted({tag for block in blocks for tag in block["tags"]}),
                    },
                })
    return records


def write_preview(records: list[dict], path: Path) -> None:
    """Write the chunks as JSON Lines, one chunk per line, to inspect them.

    Args:
        records (list[dict]): Records from chunk_filing.
        path (Path): Where to write the file; it's overwritten.
    """
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    """Chunk every downloaded filing and write its chunks_preview.jsonl."""
    for html_path in extract_html_filing_paths(EDGAR_DIR):
        records = chunk_filing(html_path)
        preview_path = html_path.parent / PREVIEW_FILE
        write_preview(records, preview_path)

        tokens = sorted(record["metadata"]["num_tokens"] for record in records)
        print(
            f"{preview_path}: {len(records)} chunks, tokens median {statistics.median(tokens):.0f}, "
            f"p90 {tokens[int(0.9 * len(tokens))]}, max {tokens[-1]}"
        )


if __name__ == "__main__":
    main()
