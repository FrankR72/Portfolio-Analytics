"""
Very rough draft demo of what chunking and storage could look like
"""

from pathlib import Path

import sec2md

from openai import AsyncOpenAI, APIError

import asyncio

from core.config import settings

import chromadb

from datetime import datetime


# backend/data/edgar/.
EDGAR_DIR = Path(__file__).resolve().parents[4] / "data" / "edgar"
CHROMADB_DIR = Path(__file__).resolve().parents[4] / "data" / "chromadb"

MODEL = "liquid/lfm-2.5-embedding-350m:free"



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
    "create chunks with sec2md, no additional parsing | see how it works without it"
    pages = sec2md.parse_filing(filing_html)
    sections = sec2md.extract_sections(pages, filing_type='10-K')
    chunks = sec2md.chunk_pages(pages, chunk_size=350, max_table_tokens=350)
    
    
    texts = [chunk.content for chunk in chunks]
    
    
    return texts


async def embed_chunks(chunks, embedding_model: str):
    "embed chunks using a generic model with the openai async lient"
    try:
        async with AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
        ) as client:
            response = await client.embeddings.create(
                model=embedding_model,
                input=chunks
            )
            response_dict = response.model_dump()
                
        return response_dict
    except APIError as error:
        raise


def generate_embedding_id(embeddings):
    "generate a unique id for each embedding"
    return [f"10k{i}_AAPL" for i in range(len(embeddings['data']))]

def create_chromadb_collection(store_path:str):
    
    # initiate chroma db client (in memory for now)
    chromadb_client = chromadb.PersistentClient(store_path)
    
    collection = chromadb_client.get_or_create_collection(
        name="10k_AAPL_v1",
        embedding_function=None,
        metadata={
            "description": "chromadb collection for testing full RAG mvp pipeline with AAPL 10k",
            "created": str(datetime.now())
        }
    )
    return collection
    

def _add_embedding_to_vectordb(chromadb_collection, id, embeddings, store_path:str):
    
    chromadb_client = chromadb.PersistentClient(store_path)
    
    collection = chromadb_client.get_or_create_collection(str(chromadb_collection))
    
    collection.add(
        ids=id,
        embeddings=[data['embedding'] for data in embeddings['data']],
    )
    return


def main():
    chunks = []
    for hmtl_path in extract_html_filing_paths(EDGAR_DIR):
        chunks.extend(chunk_filings(hmtl_path.read_text(encoding="utf-8")))
    chunks = chunks[:10]
    embeddings = asyncio.run(embed_chunks(chunks, MODEL))
    ids = generate_embedding_id(embeddings)
    collection = create_chromadb_collection(store_path=str(CHROMADB_DIR))
    _add_embedding_to_vectordb(collection.name, ids, embeddings, store_path=str(CHROMADB_DIR))
    
    print(f"Number of chunks {len(chunks)}")
    print(f"Embeddings length {len(embeddings['data'])} with a shape of {len(embeddings['data'][0]['embedding'])}")
    print(f"Embedding model: {embeddings['model']}")
    print(f"Total tokens: {embeddings['usage']['total_tokens']}")
    print(f"Embedding cost: ${embeddings['usage']['cost']}")

    print(f"Chromadb collection created at {CHROMADB_DIR} with name {collection.name} and metadata {collection.metadata}")
    print(collection.get(ids=["10k0_AAPL"], include=["embeddings"]))



     
if __name__ == "__main__":
    main()