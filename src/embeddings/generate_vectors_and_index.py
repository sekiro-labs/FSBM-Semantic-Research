"""Embed cleaned FSBM abstracts with zembed-1 and build a cosine Chroma index."""

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HOME", str(ROOT / ".hf_cache"))

import numpy as np
from src.embeddings import incremental

MODEL_NAME = "zeroentropy/zembed-1-embedding"
MODEL_DTYPE = "float32"
SOURCE = ROOT / "data/clean/publications.json"
EMBEDDINGS_DIR = ROOT / "data/embeddings"
ARTIFACT = EMBEDDINGS_DIR / "publication_embeddings.npz"
MANIFEST = EMBEDDINGS_DIR / "manifest.json"
VECTOR_DB = ROOT / "data/vector_db"
COLLECTION_NAME = "fsbm_zembed1_publications"
LOG = logging.getLogger("fsbm.embeddings")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_publications(path=SOURCE):
    raw = Path(path).read_bytes()
    rows = json.loads(raw.decode("utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Clean publication JSON must contain a nonempty list")
    ids = [row.get("article_id") for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Clean publications must have distinct nonempty article IDs")
    if any(not isinstance(row.get("abstract_clean"), str) or not row["abstract_clean"].strip() for row in rows):
        raise ValueError("Every publication must have a usable abstract_clean")
    return rows, hashlib.sha256(raw).hexdigest()


def load_model(device="cpu"):
    from sentence_transformers import SentenceTransformer
    import torch

    if device != "cpu":
        raise ValueError("GPU loading requires a separately validated compatibility path")
    LOG.info("Loading required model %s with %s CPU weights", MODEL_NAME, MODEL_DTYPE)
    try:
        return SentenceTransformer(MODEL_NAME, revision=incremental.MODEL_REVISION, device="cpu", trust_remote_code=True,
                                   model_kwargs={"torch_dtype": torch.float32})
    except Exception as exc:
        raise RuntimeError(f"Required embedding model {MODEL_NAME} could not load: {exc}") from exc


def validated_vectors(values, expected_count, expected_dim=None):
    array = np.asarray(values)
    if array.ndim == 1 and expected_count == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2 or array.shape[0] != expected_count or array.shape[1] == 0:
        raise ValueError(f"Invalid embedding shape {array.shape}; expected {expected_count} vectors")
    if expected_dim is not None and array.shape[1] != expected_dim:
        raise ValueError(f"Embedding dimension changed: {array.shape[1]} != {expected_dim}")
    if not np.issubdtype(array.dtype, np.number) or not np.isfinite(array).all():
        raise ValueError("Embedding contains NaN, Infinity, or nonnumeric values")
    norms = np.linalg.norm(array.astype(np.float32), axis=1)
    if np.any(norms == 0) or not np.isfinite(norms).all():
        raise ValueError("Embedding contains a zero or invalid vector")
    return array.astype(np.float32)


def smoke_test(model, abstract, query="deep learning for medical diagnosis"):
    doc = validated_vectors(model.encode_document(abstract), 1)
    query_vector = validated_vectors(model.encode_query(query), 1, doc.shape[1])
    LOG.info("Smoke test: document=%s, query=%s, finite=yes, first values=%s",
             doc.shape, query_vector.shape, doc[0, :5].tolist())
    return doc.shape[1]


def save_artifact(path, vectors, ids, dataset_sha256):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".npz.tmp")
    with temp.open("wb") as handle:
        np.savez_compressed(handle, vectors=vectors, ids=np.asarray(ids),
                            model_name=np.asarray(MODEL_NAME), model_dtype=np.asarray(MODEL_DTYPE),
                            dataset_sha256=np.asarray(dataset_sha256))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def load_artifact(path, rows, dataset_sha256):
    if not path.exists():
        return np.empty((0, 0), dtype=np.float32)
    with np.load(path, allow_pickle=False) as stored:
        if "model_dtype" not in stored:
            raise ValueError("Embedding cache has no recorded precision; move the old artifact before rebuilding")
        if (str(stored["model_name"]) != MODEL_NAME or
                str(stored["model_dtype"]) != MODEL_DTYPE or
                str(stored["dataset_sha256"]) != dataset_sha256):
            raise ValueError("Embedding cache model, precision, or clean-dataset hash differs; move the old artifact before rebuilding")
        ids = stored["ids"].tolist()
        vectors = stored["vectors"]
    if ids != [row["article_id"] for row in rows[:len(ids)]]:
        raise ValueError("Embedding cache IDs do not match the ordered clean dataset")
    if len(ids) > len(rows):
        raise ValueError("Embedding cache has more records than the clean dataset")
    if not len(ids):
        return np.empty((0, 0), dtype=np.float32)
    return validated_vectors(vectors, len(ids))


def publication_metadata(row):
    values = {
        "article_id": row.get("article_id"),
        "title": row.get("title"),
        "researcher_name": row.get("researcher_name"),
        "researcher_id": row.get("researcher_id"),
        "publication_year": row.get("publication_year"),
        "journal": row.get("journal"),
        "citations": row.get("citations"),
        "content_sha256": row.get("content_sha256"),
    }
    metadata = {}
    for key, value in values.items():
        if isinstance(value, np.generic):
            value = value.item()
        if value is None or value == "" or isinstance(value, float) and not np.isfinite(value):
            continue
        if key in ("publication_year", "citations") and isinstance(value, float) and value.is_integer():
            value = int(value)
        metadata[key] = value
    for key in ("researcher_ids", "raw_sources"):
        value = row.get(key)
        if isinstance(value, np.ndarray):
            value = value.tolist()
        if value:
            metadata[key] = json.dumps(value, ensure_ascii=False)
    return metadata


def build_index(rows, vectors, batch_size=32, vector_db=None, collection_name=None, document_format=None):
    import chromadb

    vector_db = Path(vector_db) if vector_db is not None else VECTOR_DB
    collection_name = collection_name or COLLECTION_NAME
    vector_db.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(vector_db))
    metadata = {"hnsw:space": "cosine", "model": MODEL_NAME}
    if document_format:
        metadata["document_format"] = document_format
    collection = client.get_or_create_collection(name=collection_name, metadata=metadata)
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        collection.upsert(
            ids=[row["article_id"] for row in chunk],
            embeddings=vectors[start:start + len(chunk)].tolist(),
            documents=[row["abstract_clean"] for row in chunk],
            metadatas=[publication_metadata(row) for row in chunk],
        )
        LOG.info("Indexed %d/%d publications", min(start + batch_size, len(rows)), len(rows))
    if collection.count() != len(rows):
        raise RuntimeError(f"Index has {collection.count()} records; expected {len(rows)}")
    return collection.count()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def save_incremental(path, records):
    """Atomically checkpoint final vectors with per-document content hashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = list(records)
    vectors = validated_vectors([records[key]["vector"] for key in ids], len(ids), incremental.EXPECTED_DIMENSION) if ids else np.empty((0, incremental.EXPECTED_DIMENSION), dtype=np.float32)
    temporary = path.with_suffix(".npz.tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, ids=np.asarray(ids), vectors=vectors,
                            content_sha256=np.asarray([records[key]["content_sha256"] for key in ids]),
                            provenance=np.asarray([records[key]["provenance"] for key in ids]),
                            model_name=np.asarray(MODEL_NAME), model_dtype=np.asarray(MODEL_DTYPE),
                            model_revision=np.asarray(incremental.MODEL_REVISION),
                            dimension=np.asarray(incremental.EXPECTED_DIMENSION),
                            document_format=np.asarray(incremental.DOCUMENT_FORMAT))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_incremental(path, rows):
    if not Path(path).exists():
        return {}
    with np.load(path, allow_pickle=False) as stored:
        if (str(stored["model_name"]) != MODEL_NAME or str(stored["model_dtype"]) != MODEL_DTYPE or
                str(stored["model_revision"]) != incremental.MODEL_REVISION or
                int(stored["dimension"]) != incremental.EXPECTED_DIMENSION or
                str(stored["document_format"]) != incremental.DOCUMENT_FORMAT):
            raise ValueError("Final embedding checkpoint model, precision, dimension, or document format differs")
        ids = stored["ids"].tolist()
        hashes = stored["content_sha256"].tolist()
        provenance = stored["provenance"].tolist()
        vectors = stored["vectors"]
        if vectors.dtype != np.float32:
            raise ValueError("Final embedding checkpoint vector precision is not float32")
    if len(ids) != len(set(ids)) or not (len(ids) == len(hashes) == len(provenance)):
        raise ValueError("Final embedding checkpoint has duplicate IDs or inconsistent metadata")
    validated = validated_vectors(vectors, len(ids), incremental.EXPECTED_DIMENSION) if ids else np.empty((0, incremental.EXPECTED_DIMENSION), dtype=np.float32)
    expected = {row["article_id"]: row["content_sha256"] for row in rows}
    return {key: {"vector": vector, "content_sha256": digest, "provenance": source}
            for key, digest, source, vector in zip(ids, hashes, provenance, validated)
            if expected.get(key) == digest}


def incremental_plan(rows, old_vectors, old_documents, checkpoint=None):
    base = incremental.plan(rows, old_vectors, old_documents)
    records = {row["article_id"]: {"vector": base["reusable"][row["article_id"]],
                                  "content_sha256": row["content_sha256"], "provenance": "legacy_reused"}
               for row in rows if row["article_id"] in base["reusable"]}
    records.update(checkpoint or {})
    pending = [row for row in rows if row["article_id"] not in records]
    return records, pending, base


def run_incremental(batch_size=4, torch_threads=24, artifact=None, manifest_path=None,
                    vector_db=None, model_loader=load_model):
    if batch_size < 1 or torch_threads < 1:
        raise ValueError("batch_size and torch_threads must be positive")
    artifact = Path(artifact) if artifact is not None else incremental.FINAL_ARTIFACT
    manifest_path = Path(manifest_path) if manifest_path is not None else incremental.FINAL_MANIFEST
    vector_db = Path(vector_db) if vector_db is not None else incremental.FINAL_VECTOR_DB
    if artifact.resolve() == ARTIFACT.resolve() or manifest_path.resolve() == MANIFEST.resolve() or vector_db.resolve() == VECTOR_DB.resolve():
        raise ValueError("Incremental outputs must not overwrite legacy embeddings or index")
    rows = incremental.load_final_rows()
    old_vectors, old_documents, old_manifest = incremental.read_old_vectors()
    checkpoint = load_incremental(artifact, rows)
    records, pending, base = incremental_plan(rows, old_vectors, old_documents, checkpoint)
    LOG.info("Final corpus: %d eligible; %d reusable old; %d checkpointed; %d to encode",
             len(rows), len(base["reusable"]), len(checkpoint), len(pending))
    # Establish a content-validated final checkpoint before any expensive model work.
    save_incremental(artifact, records)
    if pending:
        import torch
        torch.set_num_threads(torch_threads)
        model = model_loader()
        if not callable(getattr(model, "encode_document", None)) or not callable(getattr(model, "encode_query", None)):
            raise RuntimeError("Required zembed-1 model lacks document or query encoding path")
        query_probe = validated_vectors(model.encode_query("FSBM research"), 1, incremental.EXPECTED_DIMENSION)
        del query_probe
        for start in range(0, len(pending), batch_size):
            chunk = pending[start:start + batch_size]
            encoded = model.encode_document([incremental.document_text(row) for row in chunk],
                                            batch_size=batch_size, show_progress_bar=False)
            vectors = validated_vectors(encoded, len(chunk), incremental.EXPECTED_DIMENSION)
            for row, vector in zip(chunk, vectors):
                records[row["article_id"]] = {"vector": vector,
                                               "content_sha256": row["content_sha256"],
                                               "provenance": "generated"}
            save_incremental(artifact, records)
            LOG.info("Checkpointed %d/%d new vectors", min(start + batch_size, len(pending)), len(pending))
    if len(records) != len(rows):
        raise AssertionError("Not all eligible publications have vectors")
    ordered = validated_vectors([records[row["article_id"]]["vector"] for row in rows], len(rows), incremental.EXPECTED_DIMENSION)
    corpus_hash = hashlib.sha256("\n".join(row["article_id"] + ":" + row["content_sha256"] for row in rows).encode("utf-8")).hexdigest()
    collection_name = "fsbm_final_" + corpus_hash[:12]
    count = build_index(rows, ordered, vector_db=vector_db, collection_name=collection_name,
                        document_format=incremental.DOCUMENT_FORMAT)
    manifest = {"model_name": MODEL_NAME, "model_revision": incremental.MODEL_REVISION,
                "model_revision_evidence": "single local Hugging Face cache snapshot; legacy manifest did not record revision",
                "model_dtype": MODEL_DTYPE,
                "embedding_dimension": incremental.EXPECTED_DIMENSION,
                "publication_count": count, "document_format": incremental.DOCUMENT_FORMAT,
                "corpus_sha256": corpus_hash, "legacy_dataset_sha256": old_manifest["dataset_sha256"],
                "legacy_reused": len(base["reusable"]), "created_at_utc": utc_now(),
                "artifact": str(artifact.resolve().relative_to(ROOT)) if artifact.resolve().is_relative_to(ROOT) else str(artifact),
                "index": str(vector_db.resolve().relative_to(ROOT)) if vector_db.resolve().is_relative_to(ROOT) else str(vector_db),
                "collection": collection_name, "similarity": "cosine"}
    atomic_json(manifest_path, manifest)
    return manifest


def run(batch_size=4, torch_threads=24):
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if torch_threads < 1:
        raise ValueError("torch_threads must be positive")
    import torch
    torch.set_num_threads(torch_threads)
    rows, dataset_sha256 = load_publications()
    cached = load_artifact(ARTIFACT, rows, dataset_sha256)
    model = load_model()  # The exact model is always required, including for resumed runs.
    dimension = smoke_test(model, rows[0]["abstract_clean"])
    if len(cached) and cached.shape[1] != dimension:
        raise ValueError("Cached vectors have a different dimension from the required model")
    parts = [cached] if len(cached) else []
    completed = len(cached)
    LOG.info("Resume point: %d/%d publications", completed, len(rows))
    for start in range(completed, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        encoded = model.encode_document([row["abstract_clean"] for row in chunk], batch_size=batch_size,
                                        show_progress_bar=False)
        vectors = validated_vectors(encoded, len(chunk), dimension)
        parts.append(vectors)
        completed += len(chunk)
        combined = np.concatenate(parts, axis=0)
        save_artifact(ARTIFACT, combined, [row["article_id"] for row in rows[:completed]], dataset_sha256)
        LOG.info("Embedded and checkpointed %d/%d publications", completed, len(rows))
    combined = np.concatenate(parts, axis=0)
    count = build_index(rows, combined)
    import sentence_transformers
    import torch

    manifest = {
        "model_name": MODEL_NAME,
        "model_dtype": MODEL_DTYPE,
        "embedding_dimension": dimension,
        "publication_count": count,
        "dataset_sha256": dataset_sha256,
        "created_at_utc": utc_now(),
        "sentence_transformers_version": sentence_transformers.__version__,
        "torch_version": torch.__version__,
        "artifact": str(ARTIFACT.relative_to(ROOT)),
        "index": str(VECTOR_DB.relative_to(ROOT)),
        "collection": COLLECTION_NAME,
        "similarity": "cosine",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    LOG.info("Complete: %d publications, dimension %d", count, dimension)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit-final", action="store_true", help="Offline audit; never loads the model or writes vectors")
    mode.add_argument("--incremental-final", action="store_true", help="Resume final corpus migration in separate artifacts")
    mode.add_argument("--legacy", action="store_true", help="Run the original baseline-only pipeline explicitly")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--torch-threads", type=int, default=24)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.audit_final:
        final_rows = incremental.load_final_rows()
        legacy_vectors, legacy_documents, _ = incremental.read_old_vectors()
        report = incremental.audit(final_rows, legacy_vectors, legacy_documents)
        checkpoint = load_incremental(incremental.FINAL_ARTIFACT, final_rows)
        report["valid_final_checkpoint_vectors"] = len(checkpoint)
        report["remaining_after_checkpoint"] = len(incremental_plan(final_rows, legacy_vectors, legacy_documents, checkpoint)[1])
        print(json.dumps(report, indent=2))
    elif args.incremental_final:
        run_incremental(args.batch_size, args.torch_threads)
    else:
        run(args.batch_size, args.torch_threads)
