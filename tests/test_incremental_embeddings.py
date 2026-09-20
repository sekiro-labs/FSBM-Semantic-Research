"""Offline migration tests; no model or live vector index is loaded."""

import tempfile
import unittest
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.embeddings import incremental
from src.embeddings import generate_vectors_and_index as indexer


def row(article_id, text, aliases=None):
    return {"article_id": article_id, "article_ids": aliases or [article_id],
            "abstract_clean": text, "content_sha256": incremental.content_hash(text)}


def vector(value=1):
    return np.full(incremental.EXPECTED_DIMENSION, value, dtype=np.float32)


class IncrementalTest(unittest.TestCase):
    def test_default_model_loader_explicitly_stays_on_cpu(self):
        observed = {}

        def fake_transformer(name, **kwargs):
            observed.update(name=name, **kwargs)
            return object()

        with patch.dict(sys.modules, {
                "sentence_transformers": SimpleNamespace(SentenceTransformer=fake_transformer),
                "torch": SimpleNamespace(float32="float32")}):
            indexer.load_model()
            self.assertEqual(observed["name"], incremental.MODEL_NAME)
            self.assertEqual(observed["revision"], incremental.MODEL_REVISION)
            self.assertEqual(observed["device"], "cpu")
            self.assertEqual(observed["model_kwargs"]["torch_dtype"], "float32")
            with self.assertRaisesRegex(ValueError, "GPU"):
                indexer.load_model("cuda")

    def test_offline_run_uses_document_and_query_paths_then_resumes(self):
        rows = [row("a", "legacy abstract"), row("b", "new abstract")]
        calls = []

        class FakeModel:
            def encode_query(self, text):
                calls.append(("query", text))
                return vector()

            def encode_document(self, texts, **kwargs):
                calls.append(("document", list(texts)))
                return np.stack([vector(2) for _ in texts])

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact, manifest, index = root / "final.npz", root / "final.json", root / "index"
            with patch.object(incremental, "load_final_rows", return_value=rows), \
                 patch.object(incremental, "read_old_vectors", return_value=(
                     {"a": vector()}, {"a": "legacy abstract"}, {"dataset_sha256": "old"})), \
                 patch.object(indexer, "build_index", return_value=2) as build, \
                 patch.dict(sys.modules, {"torch": SimpleNamespace(set_num_threads=lambda _: None)}):
                result = indexer.run_incremental(artifact=artifact, manifest_path=manifest,
                                                 vector_db=index, model_loader=FakeModel)
                self.assertEqual(result["publication_count"], 2)
                self.assertEqual(result["legacy_reused"], 1)
                self.assertEqual(calls, [("query", "FSBM research"),
                                         ("document", ["new abstract"])])
                self.assertEqual(build.call_count, 1)
                saved = indexer.load_incremental(artifact, rows)
                self.assertEqual(set(saved), {"a", "b"})
                self.assertEqual(saved["a"]["provenance"], "legacy_reused")
                self.assertEqual(saved["b"]["provenance"], "generated")
                indexer.run_incremental(artifact=artifact, manifest_path=manifest,
                                        vector_db=index,
                                        model_loader=lambda: self.fail("Model loaded on resume"))
                self.assertEqual(calls, [("query", "FSBM research"),
                                         ("document", ["new abstract"])])

    def test_final_index_upserts_ids_without_duplicates(self):
        class Collection:
            def __init__(self):
                self.records = {}

            def upsert(self, ids, embeddings, documents, metadatas):
                for key, vector_value, document, metadata in zip(ids, embeddings, documents, metadatas):
                    self.records[key] = (vector_value, document, metadata)

            def count(self):
                return len(self.records)

        collection = Collection()
        observed = {}

        class Client:
            def __init__(self, path):
                observed["path"] = path

            def get_or_create_collection(self, name, metadata):
                observed["name"] = name
                observed["metadata"] = metadata
                return collection

        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {
                "chromadb": SimpleNamespace(PersistentClient=Client)}):
            entries = [{"article_id": "a", "abstract_clean": "An abstract", "title": "A",
                        "content_sha256": "digest", "researcher_ids": ["r1"]}]
            values = np.stack([vector()])
            self.assertEqual(indexer.build_index(entries, values, vector_db=Path(folder) / "db",
                                                  collection_name="final_test",
                                                  document_format=incremental.DOCUMENT_FORMAT), 1)
            self.assertEqual(indexer.build_index(entries, values, vector_db=Path(folder) / "db",
                                                  collection_name="final_test",
                                                  document_format=incremental.DOCUMENT_FORMAT), 1)
            self.assertEqual(set(collection.records), {"a"})
            self.assertEqual(collection.records["a"][2]["content_sha256"], "digest")
            self.assertEqual(observed["metadata"]["hnsw:space"], "cosine")

    def test_reuse_changed_content_stale_ids_and_linkage(self):
        rows = [row("final-a", "French ecology abstract", ["old-a"]),
                row("final-b", "New abstract", ["old-b"]),
                row("final-c", "Brand new publication")]
        old = {"old-a": vector(1), "old-b": vector(2), "old-stale": vector(3)}
        documents = {"old-a": "French ecology abstract", "old-b": "Earlier abstract",
                     "old-stale": "Unrelated abstract"}
        result = incremental.plan(rows, old, documents)
        self.assertEqual(set(result["reusable"]), {"final-a"})
        self.assertEqual(result["changed_old_ids"], {"old-b"})
        self.assertEqual(result["stale_old_ids"], {"old-stale"})
        self.assertEqual(result["present_old_ids"], {"old-a", "old-b"})
        self.assertEqual(result["missing_ids"], ["final-b", "final-c"])

    def test_checkpoint_resume_content_change_and_metadata(self):
        rows = [row("a", "unchanged"), row("b", "new text")]
        records = {"a": {"vector": vector(), "content_sha256": rows[0]["content_sha256"],
                         "provenance": "legacy_reused"}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "final.npz"
            indexer.save_incremental(path, records)
            loaded = indexer.load_incremental(path, rows)
            self.assertEqual(list(loaded), ["a"])
            self.assertEqual(loaded["a"]["provenance"], "legacy_reused")
            cache, pending, _ = indexer.incremental_plan(rows, {}, {}, loaded)
            self.assertEqual(list(cache), ["a"])
            self.assertEqual([item["article_id"] for item in pending], ["b"])
            changed = [row("a", "changed"), rows[1]]
            self.assertEqual(indexer.load_incremental(path, changed), {})
            with np.load(path, allow_pickle=False) as stored:
                self.assertEqual(str(stored["model_name"]), incremental.MODEL_NAME)
                self.assertEqual(str(stored["model_revision"]), incremental.MODEL_REVISION)
                self.assertEqual(int(stored["dimension"]), incremental.EXPECTED_DIMENSION)
                self.assertEqual(str(stored["document_format"]), incremental.DOCUMENT_FORMAT)

    def test_invalid_dimension_duplicate_id_and_ambiguous_alias_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                indexer.save_incremental(Path(folder) / "bad.npz", {
                    "a": {"vector": np.ones(3), "content_sha256": "hash", "provenance": "generated"}})
        with self.assertRaises(ValueError):
            incremental.plan([row("a", "a", ["shared"]), row("b", "b", ["shared"])], {}, {})
        with self.assertRaises(ValueError):
            incremental.plan([row("a", "a")], {"x": vector()}, {})

    def test_checkpoint_rejects_wrong_model_or_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wrong.npz"
            np.savez_compressed(path, ids=np.asarray(["a"]), vectors=np.stack([vector()]),
                                content_sha256=np.asarray([incremental.content_hash("text")]),
                                provenance=np.asarray(["generated"]), model_name=np.asarray("another/model"),
                                model_dtype=np.asarray("float32"), dimension=np.asarray(2560),
                                model_revision=np.asarray(incremental.MODEL_REVISION),
                                document_format=np.asarray(incremental.DOCUMENT_FORMAT))
            with self.assertRaisesRegex(ValueError, "model"):
                indexer.load_incremental(path, [row("a", "text")])
            np.savez_compressed(path, ids=np.asarray(["a", "a"]), vectors=np.stack([vector(), vector()]),
                                content_sha256=np.asarray([incremental.content_hash("text")] * 2),
                                provenance=np.asarray(["generated", "generated"]),
                                model_name=np.asarray(incremental.MODEL_NAME), model_dtype=np.asarray("float32"),
                                model_revision=np.asarray(incremental.MODEL_REVISION),
                                dimension=np.asarray(2560), document_format=np.asarray(incremental.DOCUMENT_FORMAT))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                indexer.load_incremental(path, [row("a", "text")])

    def test_actual_legacy_artifacts_are_read_only_and_reusable(self):
        required = [incremental.OLD_ARTIFACT, incremental.OLD_MANIFEST,
                    incremental.OLD_SQLITE,
                    incremental.MODEL_CACHE / "snapshots" / incremental.MODEL_REVISION]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            self.skipTest("Optional legacy migration artifacts/cache absent: " + ", ".join(missing))
        rows = incremental.load_final_rows()
        vectors, documents, manifest = incremental.read_old_vectors()
        report = incremental.audit(rows, vectors, documents)
        self.assertEqual(report["existing_valid_embeddings"], 380)
        self.assertEqual(report["dimension"], 2560)
        self.assertEqual(report["model_name"], "zeroentropy/zembed-1-embedding")
        self.assertEqual(report["safely_reusable_final_publications"], 380)
        self.assertEqual(report["stale_old_embeddings"], 0)
        self.assertEqual(report["embeddings_to_generate"], 515)
        self.assertEqual(manifest["publication_count"], 380)


if __name__ == "__main__":
    unittest.main()
