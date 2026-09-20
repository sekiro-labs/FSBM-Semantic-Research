"""Fast API checks that never load the zembed-1 model."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import main


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_health_and_stats_do_not_load_search(self):
        with patch.object(main, "get_search_service", side_effect=AssertionError("loaded")):
            self.assertEqual(self.client.get("/health").json()["status"], "ok")
            self.assertEqual(self.client.get("/docs").status_code, 200)
            self.assertEqual(self.client.get("/stats").json(), {
                "researchers": 77, "raw_publications": 1044, "unique_publications": 959,
                "embedding_eligible": 895, "excluded_publications": 64,
                "indexed_publications": 895,
            })

    def test_researchers_and_publications(self):
        researchers = self.client.get("/researchers?page=2&page_size=3")
        self.assertEqual(researchers.status_code, 200)
        self.assertEqual((researchers.json()["total"], len(researchers.json()["items"])), (77, 3))
        researcher_id = researchers.json()["items"][0]["scholar_id"]
        detail = self.client.get(f"/researchers/{researcher_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["scholar_id"], researcher_id)
        self.assertIn("publications", detail.json())

        publication = main.publications()[0]
        article_id = publication["article_id"]
        response = self.client.get(f"/publications/{article_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["article_id"], article_id)
        filtered = self.client.get("/publications", params={"researcher_id": publication["researcher_id"]})
        self.assertEqual(filtered.status_code, 200)
        self.assertGreater(filtered.json()["total"], 0)
        if publication["publication_year"]:
            by_year = self.client.get("/publications", params={"year": publication["publication_year"]})
            self.assertTrue(all(p["publication_year"] == publication["publication_year"]
                                for p in by_year.json()["items"]))

    def test_not_found_and_validation(self):
        self.assertEqual(self.client.get("/researchers/missing").status_code, 404)
        self.assertEqual(self.client.get("/publications/missing").status_code, 404)
        self.assertEqual(self.client.get("/researchers?page=0").status_code, 422)
        self.assertEqual(self.client.get("/publications?page_size=0").status_code, 422)
        self.assertEqual(self.client.get("/search?q=%20%20").status_code, 422)
        self.assertEqual(self.client.get("/search?q=test&top_k=21").status_code, 422)
        self.assertEqual(self.client.get("/search?q=test&top_k=0").status_code, 422)

    def test_search_uses_mocked_service_and_enriches_result(self):
        publication = main.publications()[0]
        class FakeSearch:
            def search(self, query, top_k):
                self_call.append((query, top_k))
                return [{"article_id": publication["article_id"], "title": publication["title"],
                         "similarity_score": 0.75}]

        self_call = []
        with patch.object(main, "get_search_service", return_value=FakeSearch()):
            response = self.client.get("/search", params={"q": "  machine learning  ", "top_k": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self_call, [("machine learning", 1)])
        result = response.json()["results"][0]
        self.assertEqual(result["publication_id"], publication["article_id"])
        self.assertEqual(result["abstract"], publication["abstract"])
        self.assertEqual(result["similarity_score"], 0.75)

    def test_relative_final_manifest_resolves_without_loading_model(self):
        from src.search import semantic_search as search_module

        observed = {}

        class Collection:
            def count(self):
                return 895

        class Client:
            def __init__(self, path):
                observed["path"] = path

            def get_collection(self, name):
                observed["collection"] = name
                return Collection()

        import sys
        from types import SimpleNamespace
        with patch.dict(sys.modules, {"chromadb": SimpleNamespace(PersistentClient=Client)}), \
                patch.object(search_module, "load_model", return_value=object()):
            service = search_module.SemanticSearcher()
        self.assertEqual(observed["path"], str(main.FINAL_INDEX.resolve()))
        self.assertEqual(observed["collection"], service.manifest["collection"])


if __name__ == "__main__":
    unittest.main()
