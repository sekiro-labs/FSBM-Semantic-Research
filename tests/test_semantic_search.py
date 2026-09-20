"""Pure validation and formatting tests; no substitute embedding model is used."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.embeddings import generate_vectors_and_index as indexer
from src.embeddings.generate_vectors_and_index import validated_vectors
from src.search.semantic_search import format_results, validate_query


class SearchValidationTest(unittest.TestCase):
    def test_empty_query_and_top_k_rejected(self):
        for query in ("", "   ", None):
            with self.subTest(query=query), self.assertRaises(ValueError):
                validate_query(query, 5)
        for top_k in (0, -1, 1.5, True):
            with self.subTest(top_k=top_k), self.assertRaises(ValueError):
                validate_query("biology", top_k)

    def test_dimensions_and_finiteness(self):
        self.assertEqual(validated_vectors([1.0, 2.0, 3.0], 1, 3).shape, (1, 3))
        with self.assertRaises(ValueError):
            validated_vectors([1.0, 2.0], 1, 3)
        with self.assertRaises(ValueError):
            validated_vectors([1.0, np.nan, 2.0], 1, 3)
        with self.assertRaises(ValueError):
            validated_vectors([1.0, np.inf, 2.0], 1, 3)
        with self.assertRaises(ValueError):
            validated_vectors([0.0, 0.0, 0.0], 1, 3)

    def test_results_sorted_and_required_fields(self):
        response = {
            "ids": [["a", "b"]],
            "metadatas": [[{"title": "A", "researcher_name": "Alice", "publication_year": 2020,
                           "journal": "J", "citations": 3},
                          {"title": "B", "researcher_name": "Bob", "publication_year": 2021,
                           "journal": "K", "citations": 4}]],
            "documents": [["Abstract A", "Abstract B"]],
            "distances": [[0.8, 0.2]],
        }
        results = format_results(response)
        self.assertEqual([item["article_id"] for item in results], ["b", "a"])
        self.assertEqual([item["rank"] for item in results], [1, 2])
        self.assertEqual(results[0]["similarity_score"], 0.8)
        required = {"rank", "title", "researcher_name", "publication_year", "journal",
                    "citations", "article_id", "similarity_score", "abstract_preview"}
        self.assertTrue(required <= results[0].keys())

    def test_cosine_chroma_index_roundtrip(self):
        import chromadb

        rows = [
            {"article_id": "a", "title": "Cancer diagnosis", "researcher_name": "Alice",
             "researcher_id": "r1", "publication_year": 2020, "journal": "J",
             "citations": 3, "abstract_clean": "Cancer diagnosis with learning"},
            {"article_id": "b", "title": "Water geology", "researcher_name": "Bob",
             "researcher_id": "r2", "publication_year": 2021, "journal": None,
             "citations": 0, "abstract_clean": "Water resources and geology"},
        ]
        client = chromadb.EphemeralClient()
        with tempfile.TemporaryDirectory() as folder, patch.object(indexer, "VECTOR_DB", Path(folder) / "db"), \
             patch.object(chromadb, "PersistentClient", return_value=client):
            self.assertEqual(indexer.build_index(rows, np.array([[1, 0, 0], [0, 1, 0]], dtype="float32")), 2)
            collection = client.get_collection(indexer.COLLECTION_NAME)
            response = collection.query(query_embeddings=[[1.0, 0.0, 0.0]], n_results=2,
                                        include=["metadatas", "documents", "distances"])
            results = format_results(response)
            self.assertEqual(results[0]["article_id"], "a")
            self.assertAlmostEqual(results[0]["similarity_score"], 1.0, places=5)

    def test_embedding_cache_rejects_changed_dataset(self):
        rows = [{"article_id": "a"}, {"article_id": "b"}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "vectors.npz"
            indexer.save_artifact(path, np.array([[1.0, 0.0, 0.0]], dtype="float32"), ["a"], "hash-one")
            cached = indexer.load_artifact(path, rows, "hash-one")
            self.assertEqual(cached.shape, (1, 3))
            with self.assertRaises(ValueError):
                indexer.load_artifact(path, rows, "hash-two")


if __name__ == "__main__":
    unittest.main()
