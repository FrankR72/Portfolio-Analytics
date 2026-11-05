from pathlib import Path

import sec2md

from openai import AsyncOpenAI, APIError

import asyncio

from core.config import settings

import chromadb



# backend/data/edgar/.
EDGAR_DIR = Path(__file__).resolve().parents[3] / "data" / "edgar"


MODEL = "liquid/lfm-2.5-embedding-350m:free"
BASE_URL=settings.llm_base_url
API_KEY=settings.api_key


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



def chunk_filings(filing_html):
    
    pages = sec2md.parse_filing(filing_html)
    sections = sec2md.extract_sections(pages, filing_type='10-k')
    chunks = sec2md.chunk_pages(pages, chunk_size=350, max_table_tokens=350)
    
    
    texts = [chunk.content for chunk in chunks]
    
    return texts

async def embed_chunks(chunks, embedding_model: str):
    
    try:
        async with AsyncOpenAI(
            base_url=BASE_URL,
            api_key=API_KEY,
        ) as client:
            response = await client.embeddings.create(
                model=embedding_model,
                input=chunks
            )
            response_dict = response.model_dump()
                
        return response_dict
    except APIError as error:
        raise


def store_embeddings(embeddings, output_file: Path):
    
    # initiate chroma db client (in memory for now)
    chromadb_client = chromadb.PersistentClient()
    
    collection = chromadb_client.create_collection(name="")
    
    
    # initialize 
    
    
    






def main():
    chunks = []
    for hmtl_path in extract_html_filing_paths(EDGAR_DIR):
        chunks.extend(chunk_filings(hmtl_path.read_text(encoding="utf-8")))
    embeddings = asyncio.run(embed_chunks(chunks[:10], MODEL))
    print(f"Embeddings length {len(embeddings['data'])} with a shape of {len(embeddings['data'][0]['embedding'])}")
        
    
        
        
if __name__ == "__main__":
    main()