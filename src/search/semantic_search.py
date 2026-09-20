"""Cosine semantic search over the zembed-1 FSBM publication index."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.embeddings.generate_vectors_and_index import (
    COLLECTION_NAME, MANIFEST, MODEL_NAME, VECTOR_DB, load_model, validated_vectors,
)
from src.embeddings import incremental


def validate_query(query, top_k):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Query must be nonempty text")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    return query.strip()


def format_results(response, preview_chars=220):
    ids = response.get("ids", [[]])[0]
    metadata = response.get("metadatas", [[]])[0]
    documents = response.get("documents", [[]])[0]
    distances = response.get("distances", [[]])[0]
    if not (len(ids) == len(metadata) == len(documents) == len(distances)):
        raise ValueError("Chroma returned inconsistent result lengths")
    results = []
    for article_id, meta, document, distance in zip(ids, metadata, documents, distances):
        if distance is None:
            raise ValueError("Chroma did not return cosine distances")
        results.append({
            "rank": 0,
            "title": meta.get("title"),
            "researcher_name": meta.get("researcher_name"),
            "publication_year": meta.get("publication_year"),
            "journal": meta.get("journal"),
            "citations": meta.get("citations"),
            "article_id": article_id,
            "similarity_score": round(1.0 - float(distance), 6),
            "abstract_preview": (document or "")[:preview_chars].rstrip(),
        })
    results.sort(key=lambda item: item["similarity_score"], reverse=True)
    for rank, item in enumerate(results, 1):
        item["rank"] = rank
    return results


class SemanticSearcher:
    def __init__(self):
        import chromadb

        manifest_path = incremental.FINAL_MANIFEST if incremental.FINAL_MANIFEST.exists() else MANIFEST
        if not manifest_path.exists():
            raise FileNotFoundError(f"Index manifest missing: {manifest_path}. Run the embedding/index script first")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("model_name") != MODEL_NAME or self.manifest.get("similarity") != "cosine":
            raise ValueError("Index was not built with the required zembed-1 cosine configuration")
        if manifest_path == incremental.FINAL_MANIFEST:
            if self.manifest.get("document_format") != incremental.DOCUMENT_FORMAT:
                raise ValueError("Final index document format does not match the current encoder")
            index_path = (incremental.ROOT / self.manifest["index"]).resolve()
            if not (index_path / "chroma.sqlite3").is_file():
                raise FileNotFoundError(f"Final Chroma index missing: {index_path}")
            collection_name = self.manifest["collection"]
        else:
            index_path = VECTOR_DB
            collection_name = COLLECTION_NAME
        client = chromadb.PersistentClient(path=str(index_path))
        self.collection = client.get_collection(name=collection_name)
        if self.collection.count() != self.manifest["publication_count"]:
            raise ValueError("Index count differs from manifest; rebuild the index")
        self.model = load_model()

    def search(self, query, top_k=5):
        query = validate_query(query, top_k)
        vector = validated_vectors(self.model.encode_query(query), 1, self.manifest["embedding_dimension"])
        response = self.collection.query(
            query_embeddings=vector.tolist(),
            n_results=min(top_k, self.collection.count()),
            include=["metadatas", "documents", "distances"],
        )
        return format_results(response)


def semantic_search(query: str, top_k: int = 5):
    """Return the most similar indexed publications using the exact zembed-1 model."""
    validate_query(query, top_k)
    return SemanticSearcher().search(query, top_k)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Search text")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    try:
        results = semantic_search(args.query, args.top_k)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
    for item in results:
        print(f"{item['rank']}. {item['similarity_score']:.4f}  {item['title']}")
        print(f"   {item['researcher_name']} | {item['publication_year']} | {item['journal']} | citations: {item['citations']}")
        print(f"   ID: {item['article_id']}")
        print(f"   {item['abstract_preview']}")
