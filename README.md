# Cartographie Sémantique et Analyse des Publications de la FSBM par NLP & Web Scraping

Academic project exploring a representative, **partial** sample of researchers from the Faculté des Sciences Ben M'Sick (FSBM), Université Hassan II de Casablanca. The project collects Google Scholar profiles and publications, consolidates and cleans their metadata, embeds available abstracts with zembed-1, and provides cosine semantic search through a CLI, FastAPI, and a Jupyter notebook.

## Results

| Measure | Final corpus |
| --- | ---: |
| Unique researchers | 77 |
| Raw publication records | 1,044 |
| Unique cleaned publications | 959 |
| Eligible for embeddings | 895 |
| Ineligible for embeddings | 64 |
| Final embedding vectors | 895 × 2,560 |
| Legacy vectors reused / newly generated | 380 / 515 |
| Final ChromaDB records | 895 |

Counts come from `data/clean/data_quality_report.json` and `data/embeddings/final_manifest.json`. The sample is not a census of FSBM research.

## Pipeline

```text
Google Scholar → conservative scraping → preserved raw JSON
→ Unicode normalization and careful deduplication → clean JSON / Parquet
→ zeroentropy/zembed-1-embedding → 2,560-dimensional vectors
→ ChromaDB HNSW index (cosine) → CLI / FastAPI semantic search
```

## Repository structure

```text
data/
  input/             Researcher selections and coverage audit
  raw/               Preserved source profiles from the original and later collection runs
  clean/             Consolidated researcher and publication data; quality report
  embeddings/        Small manifests; large NPZ vectors distributed separately
  vector_db_final/   Local final ChromaDB index; distributed separately
  vector_db/         Local legacy index
  papers/            Optional openly accessible PDFs
src/
  scraping/          Resumable Scholar collection and selection validation
  preprocessing/     Normalization, deduplication, final consolidation
  embeddings/        Pinned zembed-1 encoding and incremental checkpointing
  search/            Cosine semantic search and evaluation
  api/               FastAPI demonstration service
notebooks/           Academic demonstration notebook
tests/               Offline tests and mocked API/search checks
```

The input selections and four raw JSON sources are retained as provenance for **one consolidated dataset**. They are not separate final corpora.

## Installation

Use Python 3.13 from the project root (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The requirements keep `bibtexparser<2` for compatibility with `scholarly`; they do not select a machine-specific CUDA build. No environment variable or credential is required for local data exploration. The pinned zembed-1 revision is `cf13c81f3274394053d166740294f7eea4586f7a`. Loading it for live search requires its model weights to be available; the model cache is **not** part of this repository.

### Generated search artifacts

Raw and clean datasets are small enough to version directly. The final NPZ (`data/embeddings/final_publication_embeddings.npz`) and complete ChromaDB directory (`data/vector_db_final/`) are intentionally excluded from ordinary Git commits. To run search from a fresh clone, obtain the matching validated artifacts from the project's release/submission package and place them at those exact paths. The committed `final_manifest.json` uses paths relative to the project root. Both artifacts must match its model, collection, corpus hash, dimension, and record count. Do not substitute another model or rebuild the index merely to open the notebook.

The notebook's normal exploration cells work with the committed clean data and report; its vector/index validation cells require the distributed artifacts. Live search is optional and loads the large model only on request.

## Collection and cleaning

`src/scraping/scraper.py` supports delays, retries with backoff, logging, per-researcher error handling, checkpoints, and resume. It records available Scholar profile metrics and publication metadata while retaining source/provenance fields. Google Scholar may return HTTP 429 or CAPTCHA; the scraper does not bypass rate limits, CAPTCHA, authentication, robots rules, or paywalls. PDF retrieval is limited to openly accessible files.

`src/preprocessing/merge_raw_data.py` combines the preserved raw sources. Cleaning keeps original titles and abstracts, creates Unicode-aware normalized fields, and merges duplicates using DOI or exact title/year with supporting author evidence. Publications without adequate abstract text remain in the clean dataset and are recorded in `data/clean/publications_excluded.json`. The 64 ineligible final publications lack usable abstracts.

To reproduce the clean dataset **only when intentionally regenerating it**:

```powershell
python src/preprocessing/merge_raw_data.py
```

## Embeddings and semantic search

The **only** embedding model is `zeroentropy/zembed-1-embedding` at revision `cf13c81f3274394053d166740294f7eea4586f7a`; there is no fallback model. Document text is `abstract_clean` (`abstract_clean/v1`), encoded with `encode_document`. Queries use `encode_query`. The final vectors have dimension 2,560 and are indexed in ChromaDB with HNSW cosine distance. Each vector is linked to a publication ID and a content hash.

Once the matching final artifacts and model cache are present:

```powershell
python src/search/semantic_search.py "machine learning for medical diagnosis" --top-k 5
```

The following is an **expensive recovery/reproduction command**, not required to read or demonstrate the final dataset. It may load/download the roughly 4B-parameter model and writes vector/index artifacts:

```powershell
python src/embeddings/generate_vectors_and_index.py --incremental-final --batch-size 4 --torch-threads 8
```

## FastAPI demonstration

Start the local API from the project root:

```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Swagger documentation: <http://127.0.0.1:8000/docs>.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | API and project status |
| `GET /stats` | Corpus and index counts from artifacts |
| `GET /researchers`, `GET /researchers/{researcher_id}` | Researcher browsing and associated publications |
| `GET /publications`, `GET /publications/{publication_id}` | Cleaned publication browsing |
| `GET /search?q=...&top_k=5` | Cosine semantic search |

List endpoints support `page` and `page_size`; publications can be filtered by `year` and `researcher_id`. Example: <http://127.0.0.1:8000/search?q=machine%20learning%20medical%20diagnosis&top_k=5>. The first search request can be slow because zembed-1 loads lazily; later requests reuse the same service. Other API endpoints do not load the model.

## Notebook and tests

Open `notebooks/fsbm_semantic_research_demo.ipynb` in a Jupyter-compatible editor. It explains the pipeline, explores the final data, and validates stored embeddings and index metadata without regenerating them. Its live-search cell is disabled by default and explicitly marked expensive.

Run safe automated tests without loading the 4B model:

```powershell
python -m unittest discover -s tests -q
```

## Limitations and responsible use

- Google Scholar blocking, CAPTCHA, and HTTP 429 limit coverage. The sample is representative/partial, not guaranteed exhaustive.
- PDF URLs and references were not systematically available; source abstracts and provenance are retained where available.
- Sixty-four unique publications lack sufficient abstract text for embeddings.
- Retrieval quality varies by query and corpus coverage. In validation, `cancer prediction using machine learning` retrieved mostly general machine-learning papers rather than cancer-specific studies; this does not establish a model defect.
- Researcher affiliation evidence and Scholar records should be checked against current institutional sources before drawing institutional conclusions.
- Respect publisher access controls and Google Scholar restrictions. No proxy rotation, CAPTCHA bypass, or paywall circumvention is used.
