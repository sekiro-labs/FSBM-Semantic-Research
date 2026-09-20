"""Offline coverage of mixed raw schemas, relationships, and final exports."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/preprocessing"))
spec = importlib.util.spec_from_file_location("fsbm_merge", ROOT / "src/preprocessing/merge_raw_data.py")
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)
from cleaner import clean_profiles  # noqa: E402


class MergeTest(unittest.TestCase):
    def fixtures(self, root):
        abstract = "Étude détaillée de réseaux et données en français."
        legacy = [
            {"chercheur_id": "A", "nom_complet": "Émilie Dupont", "affiliation": "FSBM",
             "metriques": {"citations_totales": 5},
             "articles": [{"article_id": "A:one", "titre": "Étude des réseaux", "auteurs": ["Émilie Dupont"],
                           "date_publication": "2022", "journal": "Revue", "citations": 2,
                           "abstract": abstract}]},
        ]
        first = {"profiles": [
            {"scholar_id": "B", "full_name": "Other Researcher", "status": "partial_limited",
             "publications": [{"article_id": "B:other", "title": "Étude des réseaux",
                               "authors": ["Émilie Dupont", "Other Researcher"],
                               "publication_date": 2022, "citation_count": 3,
                               "abstract": abstract, "publication_url": "https://example.org/paper"}]},
            {"scholar_id": "A", "full_name": "Émilie Dupont", "status": "complete",
             "publications": [{"article_id": "A:second", "title": "A second study",
                               "authors": [], "abstract": None, "citation_count": None}]},
        ], "failures": {}}
        batch2 = {"profiles": [], "failures": {}}
        batch3 = {"profiles": [{"scholar_id": "C", "full_name": "No publications yet",
                                "status": "in_progress", "publications": []}], "failures": {}}
        sources = []
        for name, value in (("legacy.json", legacy), ("first.json", first),
                            ("batch2.json", batch2), ("batch3.json", batch3)):
            path = root / name
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            sources.append(path)
        return sources

    def test_mixed_schemas_dedup_unicode_and_partial_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            profiles, sources, statuses, issues = merge.load_sources(self.fixtures(Path(folder)))
            self.assertEqual(len(profiles), 3)
            self.assertEqual(sources["legacy.json"]["publications"], 1)
            self.assertEqual(sources["first.json"]["publications"], 2)
            self.assertEqual(statuses["in_progress"], 1)
            self.assertFalse(issues)
            a = next(profile for profile in profiles if profile["scholar_id"] == "A")
            self.assertEqual(len(a["publications"]), 2)
            self.assertEqual(set(a["raw_sources"]), {"legacy.json", "first.json"})
            raw, eligible, excluded = clean_profiles(profiles)
            self.assertEqual(len(raw), 3)
            self.assertEqual(len(eligible), 1)
            self.assertEqual({row["exclusion_reason"] for row in excluded},
                             {"duplicate_publication", "missing_abstract"})
            self.assertEqual(set(eligible[0]["researcher_ids"]), {"A", "B"})
            self.assertEqual(eligible[0]["abstract"], "Étude détaillée de réseaux et données en français.")
            self.assertIn("étude", eligible[0]["abstract_clean"])
            self.assertIsNone(eligible[0]["pdf_url"])

    def test_json_parquet_round_trip(self):
        import pandas as pd

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = merge.run(root / "out", self.fixtures(root))
            self.assertEqual(report["total_unique_researchers"], 3)
            self.assertEqual(report["researchers_represented_in_publications"], 2)
            self.assertEqual(report["raw_publication_records"], 3)
            self.assertEqual(report["unique_publications"], 2)
            self.assertEqual(report["duplicate_publications_merged"], 1)
            self.assertEqual(report["embedding_eligible"], 1)
            records = json.loads((root / "out/publications.json").read_text(encoding="utf-8"))
            parquet = pd.read_parquet(root / "out/publications.parquet")
            self.assertEqual(len(records), len(parquet))
            linked = next(row for row in records if row["embedding_eligible"])
            self.assertEqual(set(linked["researcher_ids"]), {"A", "B"})
            self.assertEqual([row["abstract"] or "" for row in records], parquet["abstract"].fillna("").tolist())
            self.assertIsNone(next(row for row in records if not row["embedding_eligible"])["abstract"])
            self.assertNotIn("__index_level_0__", parquet.columns)

    def test_actual_partial_batch3_is_not_treated_as_full_selection(self):
        profiles, sources, _, _ = merge.load_sources()
        self.assertEqual(sources["new_scholar_data_batch3.json"]["researchers"], 21)
        self.assertEqual(sources["new_scholar_data_batch3.json"]["publications"], 307)
        self.assertEqual(len(profiles), 77)


if __name__ == "__main__":
    unittest.main()
