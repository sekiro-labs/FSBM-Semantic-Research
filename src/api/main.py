"""FastAPI facade over the final cleaned data and existing semantic search."""

import json
import logging
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
CLEAN = ROOT / "data" / "clean"
FINAL_MANIFEST = ROOT / "data" / "embeddings" / "final_manifest.json"
FINAL_INDEX = ROOT / "data" / "vector_db_final"
MODEL = "zeroentropy/zembed-1-embedding"
REVISION = "cf13c81f3274394053d166740294f7eea4586f7a"
logger = logging.getLogger(__name__)

app = FastAPI(title="FSBM Semantic Research API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000",
                   "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


class Health(BaseModel):
    status: str
    project: str
    model: str
    documentation: str


class Stats(BaseModel):
    researchers: int
    raw_publications: int
    unique_publications: int
    embedding_eligible: int
    excluded_publications: int
    indexed_publications: int


class Page(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[dict[str, Any]]


class SearchResult(BaseModel):
    publication_id: str
    title: str | None = None
    authors: Any = None
    publication_year: int | None = None
    publication_date: str | None = None
    abstract: str | None = None
    researcher_id: str | None = None
    researcher_name: str | None = None
    researcher_ids: list[str] = Field(default_factory=list)
    similarity_score: float


class SearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[SearchResult]


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.exception("Cannot read project artifact %s", path)
        raise HTTPException(status_code=503, detail=f"Project artifact unavailable: {path.name}") from exc


@lru_cache(maxsize=1)
def researchers():
    return read_json(CLEAN / "researchers.json")


@lru_cache(maxsize=1)
def publications():
    return read_json(CLEAN / "publications.json")


def paginate(items: list[dict[str, Any]], page: int, page_size: int) -> Page:
    start = (page - 1) * page_size
    return Page(page=page, page_size=page_size, total=len(items), items=items[start:start + page_size])


_search_service = None
_search_lock = Lock()


def get_search_service():
    """Load the existing pinned model once, only for the first search request."""
    global _search_service
    if _search_service is None:
        with _search_lock:
            if _search_service is None:
                manifest = read_json(FINAL_MANIFEST)
                if (manifest.get("model_name") != MODEL or
                        manifest.get("model_revision") != REVISION or
                        manifest.get("document_format") != "abstract_clean/v1" or
                        manifest.get("similarity") != "cosine" or
                        (ROOT / manifest.get("index", "")).resolve() != FINAL_INDEX.resolve()):
                    raise HTTPException(status_code=503, detail="Final search manifest is incompatible")
                from src.search.semantic_search import SemanticSearcher
                _search_service = SemanticSearcher()
    return _search_service


@app.get("/health", response_model=Health)
def health():
    return Health(status="ok", project="FSBM Semantic Research", model=MODEL, documentation="/docs")


@app.get("/stats", response_model=Stats)
def stats():
    report = read_json(CLEAN / "data_quality_report.json")
    manifest = read_json(FINAL_MANIFEST)
    return Stats(
        researchers=report["total_unique_researchers"],
        raw_publications=report["raw_publication_records"],
        unique_publications=report["unique_publications"],
        embedding_eligible=report["embedding_eligible"],
        excluded_publications=report["embedding_ineligible"],
        indexed_publications=manifest["publication_count"],
    )


@app.get("/researchers", response_model=Page)
def list_researchers(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return paginate(researchers(), page, page_size)


@app.get("/researchers/{researcher_id}")
def get_researcher(researcher_id: str):
    researcher = next((r for r in researchers() if r.get("scholar_id") == researcher_id), None)
    if researcher is None:
        raise HTTPException(status_code=404, detail="Researcher not found")
    associated = [p for p in publications() if researcher_id in
                  set((p.get("researcher_ids") or []) + (p.get("also_researcher_ids") or []) +
                      ([p["researcher_id"]] if p.get("researcher_id") else []))]
    return {**researcher, "publications": associated}


@app.get("/publications", response_model=Page)
def list_publications(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      year: int | None = None, researcher_id: str | None = None):
    items = publications()
    if year is not None:
        items = [p for p in items if p.get("publication_year") == year]
    if researcher_id:
        items = [p for p in items if researcher_id in
                 set((p.get("researcher_ids") or []) + (p.get("also_researcher_ids") or []) +
                     ([p["researcher_id"]] if p.get("researcher_id") else []))]
    return paginate(items, page, page_size)


@app.get("/publications/{publication_id}")
def get_publication(publication_id: str):
    publication = next((p for p in publications() if p.get("article_id") == publication_id), None)
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    return publication


@app.get("/search", response_model=SearchResponse)
def search(q: str = Query(...), top_k: int = Query(5, ge=1, le=20)):
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q must contain non-whitespace text")
    try:
        matches = get_search_service().search(query, top_k=top_k)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Semantic search failed")
        raise HTTPException(status_code=503, detail="Semantic search unavailable") from exc
    by_id = {p["article_id"]: p for p in publications()}
    results = []
    for match in matches:
        publication_id = match["article_id"]
        publication = by_id.get(publication_id, {})
        results.append(SearchResult(
            publication_id=publication_id,
            title=publication.get("title") or match.get("title"),
            authors=publication.get("authors"),
            publication_year=publication.get("publication_year"),
            publication_date=publication.get("publication_date"),
            abstract=publication.get("abstract"),
            researcher_id=publication.get("researcher_id"),
            researcher_name=publication.get("researcher_name") or match.get("researcher_name"),
            researcher_ids=publication.get("researcher_ids") or [],
            similarity_score=match["similarity_score"],
        ))
    return SearchResponse(query=query, top_k=top_k, results=results)
