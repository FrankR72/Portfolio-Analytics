# RAG over SEC filings — plan and decision log

Ask questions about the companies in your holdings, answered from their SEC filings, with citations. It lives on the **Stock Analysis** page.

**Status (2026-10-29):** architecture agreed, no code yet. Next: Phase 0.

---

## 1. Decisions

| Topic | Decision |
|---|---|
| Language | English: questions, answers, page text, error messages. |
| Companies | Only the ones in your holdings. |
| Documents | SEC filings from EDGAR: 10-K and 10-Q, later 8-K Exhibit 99.1 (earnings releases). No earnings-call transcripts (no free legal source). |
| Portfolio data | **Not ingested.** It's read live from the existing services when a question is asked (see [5](#5-what-is-and-isnt-ingested)). |
| Vector storage | Postgres + pgvector, in tables we own (Alembic). No separate vector database. |
| Embeddings | A hosted API. The provider is chosen in Phase 0 by measuring. |
| Generation | The existing `ai/client.generate_text` (free models on OpenRouter). |
| LangChain | Only for splitting text into chunks (see [3](#3-where-langchain-is-used)). |
| Numbers | Never from vector search or the LLM. Exact figures come from data and code (XBRL in Phase 4). |
| Not planned | Agents, LangGraph, knowledge graphs, an LLM fact-checker, automatic learning from feedback. |

---

## 2. How it works

Two separate parts that share only the database:

```
INGESTION (offline batch job, never inside a user request)

  EDGAR ──▶ download ──▶ save raw HTML ──▶ split into Items ──▶ chunk ──▶ embed ──▶ Postgres
           (by accession   (backend/data/    (1, 1A, 7, 7A)                        (documents,
            number)         edgar/, gitignored)                                     chunks)


QUESTION (POST /api/research/ask)

  question ──▶ preprocess ──▶ ticker in your ──▶ embed ──▶ vector search ──▶ 0 chunks? ──▶ fixed answer
               (validate,     holdings?          question   (Postgres)           │          (no LLM call)
                normalize)    (404 if not)                                       ▼
                                                                    build context ──▶ LLM ──▶ check citations
                                                                    (numbered sources)          │
                                                                                                ▼
                                                                                  {answer, citations}
```

### Code layout

```
backend/app/
  rag/                 reusable core: knows nothing about stocks or SEC
    types.py           Chunk, RetrievedChunk, Citation, RetrievalTrace
    interfaces.py      DocumentSource, Parser, Chunker, Embedder, ChunkRepository
    preprocessing.py   validate + normalize the question
    chunking.py        the only file that imports LangChain
    embeddings.py      Embedder on the openai SDK
    repository.py      store and search chunks (SQLAlchemy + pgvector)
    ingestion.py       source → parse → chunk → embed → store
    retrieval.py       embed the question → search → trace
    context.py         numbered sources within a token budget
    citations.py       read [n] in the answer, drop invalid ones
    metrics.py         recall@k, MRR, citation validity (for evals)
  research/            the stock-specific part
    edgar.py           EDGAR client
    filings.py         10-K / 10-Q → Item sections
    research_service.py  ResearchService.ask(user_id, question, ticker)
  routers/research.py  POST /api/research/ask
backend/scripts/ingest_filings.py   the ingestion command
```

**Rule:** `rag/` never imports from `research/`, `services/` or `ai/`. That's what keeps it reusable for other document projects (contracts, papers…): another project would only write its own source, parser, prompt and eval set.

---

## 3. Where LangChain is used

| Part | LangChain? | Why |
|---|---|---|
| Splitting text into chunks | **Yes** (`langchain-text-splitters`) | Small, does exactly this. Imported only in `rag/chunking.py`, version pinned, and a test catches upgrades that change the splits. |
| Loading documents | No | EDGAR needs its own handling: required `User-Agent`, rate limit, finding the main document, splitting by Item. Generic loaders don't do this. |
| Embeddings | No | A thin wrapper on the `openai` SDK we already use (if the provider is OpenAI-compatible). |
| Vector store | No | `langchain-postgres` creates its own tables outside Alembic, with untyped metadata and its own connections. |
| Retrieval | No | It's one SQL query, and its scores and ranks must be visible for debugging and evals. |

The LangChain article we read (Yasaswinitatikonda, Dec 2025) reached "use it for the boring parts, write the important parts yourself". Its own worst problems were in loading, vector-store filters and retrieval, which is why those stay ours. Its code examples use an old LangChain API, so take its lessons, not its code.

---

## 4. Ingestion strategy

- **Each filing is ingested once,** identified by its accession number. Filings never change after they're filed (a correction is a new filing, `10-K/A`), so ingesting again only means **checking for new filings**.
- **It's a batch job, never part of a user's request:**
  - Phases 1–2: you run the command by hand;
  - later: a daily scheduled run (new filings arrive a few times a year, so daily is plenty).
- **Which companies:** every ticker held by any user. Documents are public, so each company is stored once and shared by all users.
- **A new position doesn't trigger ingestion.** Ingesting takes tens of seconds and could fail, which would break adding a transaction. The next sync picks the ticker up. Until then the page says "Documents for X aren't indexed yet".
- **The raw HTML is kept on disk** (`backend/data/edgar/{cik}/{accession}/`, gitignored, with a `metadata.json`). Changing the parser, the chunk size or the embedding model then reprocesses those files (`--rebuild`) without downloading again.
- **What's kept:**
  - Phase 1: the latest 10-K of one company;
  - Phase 2: the latest 10-K plus the last ~4 10-Qs per company;
  - old filings stay;
  - amendments are ignored at first.

### EDGAR basics

1. Ticker → CIK (the SEC's company id): `https://www.sec.gov/files/company_tickers.json`.
2. A company's filings: `https://data.sec.gov/submissions/CIK##########.json` (CIK padded to 10 digits). Under `filings.recent` there are parallel lists: `form`, `accessionNumber`, `filingDate`, `reportDate`, `primaryDocument`.
3. A document: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession without dashes}/{primaryDocument}`.
4. Every request needs `User-Agent: "Your Name your@email"`, and at most 10 requests per second.

---

## 5. What is and isn't ingested

| | SEC filings | Portfolio data |
|---|---|---|
| Kind | Long text, searched by meaning | Numbers you look up exactly |
| Changes | Never | Every few minutes (prices) and with every transaction |
| Who sees it | Public, shared | Private to each user |
| How it reaches the answer | **Ingested**: vector search | **Not ingested**: read live by `ResearchService` through the existing services, added to the prompt as a `<portfolio_data>` block (reusing the summary's snapshot) |

Embedding portfolio data would mean:
- stale copies after every change;
- one user's positions retrievable by another unless every search filters by user;
- paying for embeddings of data Postgres already has exactly.

Phase 1 doesn't need portfolio data at all: a question about a 10-K only needs the 10-K.

---

## 6. Database

One Alembic migration:

| Table | Holds |
|---|---|
| (extension) | `CREATE EXTENSION vector` |
| `documents` | One row per document: source, external id (unique), title, URL, published date, content hash, extra metadata (JSON). |
| `chunks` | One row per chunk: document, section, start/end position in the text, text, token count, `embedding vector(N)`, `embedding_model`. |
| `sec_filings` | One row per filing, linked 1–1 to `documents`: ticker, CIK, form, accession, fiscal year and period, filing date. Typed columns so filters are plain SQL. |

- No vector index at first. With a few thousand chunks an exact search takes milliseconds, and exact results keep the evals reproducible. Add an HNSW index above ~100k chunks.
- The Postgres container moves to the `pgvector/pgvector:pg18` image, keeping the same volume.
- Embedding settings (`embedding_base_url`, `embedding_model`, `embedding_api_key`, `embedding_dimensions`) are optional, like the LLM ones. Without them the endpoint answers 503.

---

## 7. Answering a question

### Query preprocessing (first step, no I/O)

`preprocess_query(raw) → PreprocessedQuery`, or it raises `QueryRejectedError(code)`:

1. Unicode normalization (NFKC).
2. Remove control and invisible characters (zero-width spaces, BOM).
3. Collapse whitespace and strip the ends.
4. Validate the cleaned text:

| Code | When |
|---|---|
| `empty` | Nothing left |
| `no_content` | No letter or digit (`"???"`) |
| `too_short` | Under 3 characters |
| `too_long` | Over 500 characters: **rejected, never cut** |

- The API returns **422** with `{code, message}`.
- The request schema also has a 2000-character hard cap, against huge request bodies.
- **Not done here:** LLM rewriting, security classifiers, SQL-injection regexes. Parameterized queries already cover SQL.

### Safeguards

| Safeguard | What it prevents |
|---|---|
| Question model must match the indexed model, else 503 | Silently empty results (the article's worst bug) |
| 0 chunks found → fixed "I couldn't find this in the documents", no LLM call | Answers invented without sources |
| Prompt: only from the sources, cite `[n]`, no calculations, say when the sources don't answer | Hallucination, made-up numbers |
| No financial advice (prompt rule + the summary's `no_advice` check) | "You should buy / sell / rebalance" |
| Invalid `[n]` citations are dropped and counted | Links to sources that don't exist |
| A timeout for each stage; the frontend waits longer than the backend's worst case | Hanging requests, a timeout instead of a clear 503 |

### Trace (observability)

One JSON line per question in `backend/logs/research_traces.jsonl` (gitignored). It's used by the evals and for debugging, and isn't sent to the browser. It records:
- the **outcome**: `answered | refused | no_sources | rejected | error`;
- question length and what preprocessing changed;
- the chunks found, with their distance and rank;
- context tokens;
- valid and invalid citations;
- the time per stage.

---

## 8. Evals

- **Written before building:** 25–30 questions about one 10-K, each with the **quoted** evidence that answers it, plus 3–5 questions the filing can't answer.
- **Evidence is quoted text, not chunk ids,** so the eval set still works after changing the chunk size.
- **Metrics:**
  - retrieval: recall@5 (was the evidence in the top 5?) and MRR (how high was it ranked?);
  - answers: citation validity, refusal on unanswerable questions, no advice.
- **The runner** is `backend/evals/evaluate_research.py`, the same style as the summary evals (results saved as JSON, with an option to re-score saved answers).
- **A feature that's meant to improve quality** (hybrid search, reranking, query rewriting) **stays only if the evals show a gain.** Each one adds a row to the results table below.

---

## 9. Phases

| Phase | Scope | Done when |
|---|---|---|
| **0. Spike** (notebook, no app code) | Download MSFT's latest 10-K; compare plain HTML parsing vs `edgartools` for finding Items 1, 1A, 7, 7A; pick 2–3 embedding providers; write the eval set. | Parser and providers chosen and recorded here. |
| **1. MVP** | One company, one 10-K, vector search only, end to end: migration, ingestion command, `rag/` core, `ResearchService`, endpoint, prompt, Stock Analysis page, eval runner. | Baseline eval recorded; tests pass; one full question works in the browser. |
| **2. Corpus** | All holdings; 10-K + 10-Q (+ 8-K Ex 99.1); filters by ticker, form and fiscal period ("latest" from the data, since fiscal years differ: MSFT's ends in June); foreign filers (NBIS may file 20-F/6-K). | Multi-company and period questions in the evals. |
| **3. Retrieval quality** | Hybrid search (Postgres full-text + vectors, merged by rank fusion); a reranker; LLM query rewriting only if the evals show it helps; follow-up questions (they need rewriting into a standalone question). | Each addition is a row in the results table. |
| **4. Structured numbers** | XBRL `companyfacts` → a `financial_facts` table; numeric questions answered by code; routing numeric vs text questions. | Numbers in answers match the facts. |
| **5. Wrap-up** | Feedback buttons, a per-user rate limit on questions, final results table, CLAUDE.md. | — |

### Phase 1 tests

- **Unit tests, no database:** preprocessing (table of inputs → output or code); chunking (with a fixed-boundaries test); citations; context budget; metrics; the 10-K parser on a saved HTML file.
- **Database tests** (new `db_tests/` folder, against Postgres + pgvector, skipped when no test database is set): storing twice adds nothing; search order; filters. CI gets a Postgres service container.
- **Service tests with fakes:** model mismatch → 503; 0 chunks → fixed answer with no LLM call; a rejected question never reaches the embedder or the LLM; the `outcome` value of each path.
- **API tests:** 200, 401, 404 (ticker not in your holdings), 422 with a `code`, 503. The new route goes into `ROUTES` in `test_api_security.py`.
- **Never call the outside world:** EDGAR and embedding calls are blocked in tests, like `block_llm`.

---

## 10. Risks

1. **Parsing 10-Ks is the hardest part:**
   - the table of contents repeats the Item headings;
   - inline-XBRL markup;
   - page headers and footers;
   - tables of numbers.
2. **Changing the embedding model means re-embedding everything.** The vector size is part of the table, which is why the provider is chosen by measuring first.
3. **Tests can't use SQLite for vector search.** Hence the new `db_tests/` folder (it also starts the "Run the tests against Postgres" TODO).
4. **Free LLM rate limits** slow down eval runs: keep runs small and re-score saved answers.
5. **News, if added later,** usually can't be stored and quoted for free: check licensing first.

---

## 11. Open questions

- The contact for the EDGAR `User-Agent` (name and email).
- Which 2–3 embedding providers to compare.
- May the local trace log store the question text? It's useful for building the eval set; the summary's log never stores content.

---

## 12. Results

Filled in from Phase 1 onwards: one row per eval run (setup, recall@5, MRR, citation validity, refusal rate, latency).
