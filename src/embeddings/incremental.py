"""Read-only legacy audit and content-aware planning for the final publication corpus."""

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

MODEL_NAME = "zeroentropy/zembed-1-embedding"
MODEL_DTYPE = "float32"
MODEL_REVISION = "cf13c81f3274394053d166740294f7eea4586f7a"
DOCUMENT_FORMAT = "abstract_clean/v1"
EXPECTED_DIMENSION = 2560
ROOT = Path(__file__).resolve().parents[2]
FINAL_PARQUET = ROOT / "data/clean/publications.parquet"
OLD_ARTIFACT = ROOT / "data/embeddings/publication_embeddings.npz"
OLD_MANIFEST = ROOT / "data/embeddings/manifest.json"
OLD_SQLITE = ROOT / "data/vector_db/chroma.sqlite3"
FINAL_ARTIFACT = ROOT / "data/embeddings/final_publication_embeddings.npz"
FINAL_MANIFEST = ROOT / "data/embeddings/final_manifest.json"
FINAL_VECTOR_DB = ROOT / "data/vector_db_final"
MODEL_CACHE = ROOT / ".hf_cache/hub/models--zeroentropy--zembed-1-embedding"


def verify_cached_revision():
    snapshots = MODEL_CACHE / "snapshots"
    available = [path.name for path in snapshots.iterdir() if path.is_dir()] if snapshots.exists() else []
    ref = MODEL_CACHE / "refs/main"
    current = ref.read_text(encoding="utf-8").strip() if ref.exists() else None
    if available != [MODEL_REVISION] or current != MODEL_REVISION:
        raise ValueError("Legacy model revision cannot be inferred from a single matching local snapshot")
    return MODEL_REVISION


def document_text(row):
    """Legacy-compatible document encoding input; title remains searchable metadata."""
    return row["abstract_clean"]


def content_hash(text):
    return hashlib.sha256((DOCUMENT_FORMAT + "\n" + text).encode("utf-8")).hexdigest()


def load_final_rows(path=FINAL_PARQUET):
    import pandas as pd

    frame = pd.read_parquet(path)
    required = {"article_id", "article_ids", "title", "abstract_clean", "embedding_eligible"}
    if not required <= set(frame.columns):
        raise ValueError(f"Final Parquet is missing columns: {sorted(required - set(frame.columns))}")
    rows = []
    for row in frame.to_dict("records"):
        if not row["embedding_eligible"]:
            continue
        if not isinstance(row["article_id"], str) or not row["article_id"]:
            raise ValueError("Eligible publication has no article ID")
        text = document_text(row)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Eligible publication {row['article_id']} has no usable document text")
        aliases = row["article_ids"]
        if isinstance(aliases, np.ndarray):
            aliases = aliases.tolist()
        row["article_ids"] = list(dict.fromkeys([row["article_id"], *(aliases or [])]))
        row["content_sha256"] = content_hash(text)
        rows.append(row)
    ids = [row["article_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Final eligible publication IDs are not unique")
    return rows


def read_old_documents(path=OLD_SQLITE):
    uri = Path(path).resolve().as_uri().replace("file:///", "file:/") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        collection = connection.execute("select name,dimension from collections").fetchall()
        if collection != [("fsbm_zembed1_publications", EXPECTED_DIMENSION)]:
            raise ValueError(f"Unexpected legacy Chroma collection: {collection}")
        metadata = dict(connection.execute(
            "select key,str_value from collection_metadata where key in ('model','hnsw:space')").fetchall())
        if metadata != {"model": MODEL_NAME, "hnsw:space": "cosine"}:
            raise ValueError(f"Unexpected legacy index metadata: {metadata}")
        records = connection.execute(
            "select e.embedding_id,m.string_value from embeddings e "
            "join embedding_metadata m on m.id=e.id where m.key='chroma:document'").fetchall()
        if len(records) != connection.execute("select count(*) from embeddings").fetchone()[0]:
            raise ValueError("Legacy Chroma has missing stored documents")
        return dict(records)
    finally:
        connection.close()


def read_old_vectors(path=OLD_ARTIFACT, manifest_path=OLD_MANIFEST, sqlite_path=OLD_SQLITE):
    verify_cached_revision()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    with np.load(path, allow_pickle=False) as stored:
        ids = stored["ids"].tolist()
        if stored["vectors"].dtype != np.float32:
            raise ValueError("Legacy NPZ vector precision does not match recorded float32")
        vectors = stored["vectors"]
        fields = {key: str(stored[key]) for key in ("model_name", "model_dtype", "dataset_sha256")}
    if fields != {"model_name": MODEL_NAME, "model_dtype": MODEL_DTYPE,
                  "dataset_sha256": manifest.get("dataset_sha256")}:
        raise ValueError("Legacy NPZ model, precision, or dataset hash disagrees with manifest")
    if (manifest.get("model_name") != MODEL_NAME or manifest.get("model_dtype") != MODEL_DTYPE or
            manifest.get("embedding_dimension") != EXPECTED_DIMENSION or
            manifest.get("publication_count") != len(ids)):
        raise ValueError("Legacy manifest count, model, or dimension mismatch")
    if (vectors.shape != (len(ids), EXPECTED_DIMENSION) or len(ids) != len(set(ids)) or
            not np.isfinite(vectors).all() or np.any(np.linalg.norm(vectors, axis=1) == 0)):
        raise ValueError("Legacy vectors have invalid dimension, duplicate IDs, or invalid values")
    documents = read_old_documents(sqlite_path)
    if set(documents) != set(ids) or len(documents) != len(ids):
        raise ValueError("Legacy NPZ IDs and Chroma document IDs disagree")
    return dict(zip(ids, vectors)), documents, manifest


def plan(rows, old_vectors, old_documents):
    """Match by article ID/alias and exact encoded text; never match on title alone."""
    aliases = {}
    for row in rows:
        for article_id in row["article_ids"]:
            if article_id in aliases and aliases[article_id] != row["article_id"]:
                raise ValueError(f"Ambiguous article ID across final publications: {article_id}")
            aliases[article_id] = row["article_id"]
    if set(old_vectors) != set(old_documents):
        raise ValueError("Legacy vector and document IDs disagree")
    reusable = {}
    changed = set()
    stale = set()
    present = set()
    for old_id, vector in old_vectors.items():
        final_id = aliases.get(old_id)
        if final_id is None:
            stale.add(old_id)
            continue
        present.add(old_id)
        row = next(item for item in rows if item["article_id"] == final_id)
        if old_documents[old_id] != document_text(row):
            changed.add(old_id)
            continue
        reusable.setdefault(final_id, vector)
    missing = [row["article_id"] for row in rows if row["article_id"] not in reusable]
    return {"reusable": reusable, "present_old_ids": present, "stale_old_ids": stale,
            "changed_old_ids": changed, "missing_ids": missing}


def audit(rows, old_vectors, old_documents):
    result = plan(rows, old_vectors, old_documents)
    return {
        "model_name": MODEL_NAME,
        "model_revision_inferred_from_cache": MODEL_REVISION,
        "dimension": EXPECTED_DIMENSION,
        "document_format": DOCUMENT_FORMAT,
        "existing_valid_embeddings": len(old_vectors),
        "existing_ids_present_in_final": len(result["present_old_ids"]),
        "stale_old_embeddings": len(result["stale_old_ids"]),
        "changed_content_old_embeddings": len(result["changed_old_ids"]),
        "safely_reusable_final_publications": len(result["reusable"]),
        "final_eligible_publications": len(rows),
        "embeddings_to_generate": len(result["missing_ids"]),
    }
