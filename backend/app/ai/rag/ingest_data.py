"""Download SEC filings from EDGAR and store them for the RAG pipeline.

Calls the EDGAR API to find a company's filings, downloads the filing
documents (HTML) and saves them in backend/data/edgar/{cik}/{accession}/,
next to a metadata.json with the filing's details. The next steps
(parsing, chunking, embedding) read from that local copy, so a filing
is only downloaded once: if its document is already on disk it's skipped.

The SEC requires every request to carry a User-Agent with a name and an
email, and allows at most 10 requests per second. The User-Agent comes
from SEC_USER_AGENT in app/.env. Run as a module from backend/app/:

    uv run python -m ai.rag.ingest_data

Note: for now this only works with one document, Microsoft's (MSFT)
latest 10-K. It doesn't go through the users' holdings yet; that comes
once the pipeline works for this single filing.
"""
import json
import os
import time
from pathlib import Path

from core.config import settings

import httpx

# backend/data/edgar/.
SAVE_DIR = Path(__file__).resolve().parents[3] / "data" / "edgar"

SEC_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_USER_AGENT = settings.sec_user_agent

REQUEST_TIMEOUT_SECONDS = 15
# The SEC allows at most 10 requests per second.
REQUEST_DELAY_SECONDS = 0.1


def sec_get(url: str) -> httpx.Response:
    """GET a SEC URL with the required User-Agent, respecting the rate limit.

    Args:
        url (str): The SEC URL to request.

    Returns:
        httpx.Response: The successful response.

    Raises:
        RuntimeError: If SEC_USER_AGENT is not set.
        httpx.HTTPStatusError: If the SEC answers with an error status.
    """
    user_agent = SEC_USER_AGENT
    if not user_agent:
        raise RuntimeError(
            'Set SEC_USER_AGENT to "Your Name your@email"; the SEC rejects requests without it.'
        )

    time.sleep(REQUEST_DELAY_SECONDS)
    response = httpx.get(
        url, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response


def get_company_cik(tickers: list[str]) -> dict[str, str]:
    """Get the CIK for each company ticker.

    Tickers the SEC doesn't know are left out of the result, with a warning.

    Args:
        tickers (list[str]): A list of company stock ticker symbols.

    Returns:
        dict[str, str]: A dictionary mapping ticker symbols (uppercase) to
            their CIKs, zero-padded to 10 digits.
    """
    wanted = {ticker.upper() for ticker in tickers}

    # JSON dictionary of every company, with its ticker and CIK.
    companies = sec_get(SEC_TICKER_CIK_URL).json()
    cik_dict = {}
    for company in companies.values():
        symbol = company["ticker"].upper()
        if symbol in wanted:
            cik_dict[symbol] = str(company["cik_str"]).zfill(10)  # CIK is zero-padded to 10 digits

    missing = wanted - cik_dict.keys()
    if missing:
        print(f"Warning: no CIK found for {', '.join(sorted(missing))}")
    return cik_dict


def get_latest_10k_filing(ticker: str, cik: str) -> dict:
    """Get the latest 10-K filing for a given company CIK.

    Amendments (10-K/A) are skipped: only an exact "10-K" matches.

    Args:
        ticker (str): The company's stock ticker symbol.
        cik (str): The company's CIK (Central Index Key).

    Returns:
        dict: A dictionary containing the filing information, including
              the filing URL and other metadata.
        dict format:
        {
            "ticker": str,                  # Company's stock ticker symbol.
            "cik": str,                     # Company's CIK, zero-padded to 10 digits.
            "form": str,                    # Filing type, e.g. "10-K".
            "accession_number": str,        # Unique filing identifier.
            "filing_date": str,             # Date submitted to the SEC (YYYY-MM-DD).
            "report_date": str,             # Fiscal year-end covered by the filing.
            "primary_document": str,        # Main HTML document filename.
            "url": str                      # Direct URL to the filing's HTML document.
        }

    Raises:
        ValueError: If the company has no 10-K among its recent filings
            (for example a foreign company, which files 20-F instead).
    """
    cik = cik.zfill(10)
    response = sec_get(SEC_SUBMISSIONS_URL.format(cik=cik))

    filings_data = response.json()  # for now only 10-K
    # Parallel lists, newest filing first, so the first 10-K is the latest.
    recent = filings_data["filings"]["recent"]

    try:
        index = recent["form"].index("10-K")
    except ValueError:
        raise ValueError(f"{ticker}: no 10-K found in recent filings") from None

    accession = recent["accessionNumber"][index]
    primary_document = recent["primaryDocument"][index]

    document_url = (
        f"{SEC_ARCHIVES_URL}/"
        f"{int(cik)}/{accession.replace('-', '')}/{primary_document}"
    )
    return {
        "ticker": ticker,
        "cik": cik,
        "form": recent["form"][index],
        "accession_number": accession,
        "filing_date": recent["filingDate"][index],
        "report_date": recent["reportDate"][index],
        "primary_document": primary_document,
        "url": document_url,
    }


def download_filing_document(filing_info: dict, save_dir: Path) -> Path:
    """Download the filing document (HTML) and save it with its metadata.

    Filings never change once filed, so a document already on disk is not
    downloaded again.

    Args:
        filing_info (dict): The filing information from get_latest_10k_filing.
        save_dir (Path): The directory where filings are saved.

    Returns:
        Path: The local file path of the filing document.
    """
    folder_path = save_dir / filing_info["cik"] / filing_info["accession_number"]
    file_path = folder_path / filing_info["primary_document"]
    if file_path.exists():
        return file_path

    response = sec_get(filing_info["url"])

    folder_path.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(response.content)
    # Lets later steps (and a --rebuild) know what the file is without calling EDGAR again.
    (folder_path / "metadata.json").write_text(json.dumps(filing_info, indent=2))
    return file_path


def main():
    """Orchestrate ingestion function"""
    tickers = ["MSFT"]
    ciks = get_company_cik(tickers)

    for ticker, cik in ciks.items():
        try:
            filing = get_latest_10k_filing(ticker, cik)
        except ValueError as error:
            print(f"Skipped: {error}")
            continue
        file_path = download_filing_document(filing, SAVE_DIR)
        print(f"{ticker}: {file_path}")


if __name__ == "__main__":
    main()
