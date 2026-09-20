"""Offline checks for Batch 2 identity and overlap reporting."""

import importlib.util
import unittest
from pathlib import Path

script = Path(__file__).resolve().parents[1] / "src/scraping/validate_batch2.py"
spec = importlib.util.spec_from_file_location("batch2_validation", script)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


class Batch2ValidationTest(unittest.TestCase):
    def test_id_overlap_and_name_similarity(self):
        baseline = [{"chercheur_id": "OLD", "nom_complet": "Émile Dupont"}]
        new = {"profiles": [{"scholar_id": "NEW", "full_name": "New Person"}]}
        batch = [
            {"chercheur_id": "OLD", "nom_complet": "Emile Dupont", "evidence_url": "https://example.org"},
            {"chercheur_id": "X", "nom_complet": "Another Person", "evidence_url": "https://example.org"},
            {"chercheur_id": "X", "nom_complet": "Another Person", "evidence_url": "https://example.org"},
            {"chercheur_id": "Y", "nom_complet": "Another Person", "evidence_url": "https://example.org"},
        ]
        report = validation.audit(baseline, new, batch, batch)
        self.assertEqual(report["represented_unique_scholar_ids"], 2)
        self.assertEqual(report["duplicate_scholar_ids_in_batch"], ["X"])
        self.assertEqual(report["candidates_rejected_already_represented"][0]["scholar_id"], "OLD")
        self.assertTrue(report["duplicate_or_near_duplicate_names"])


if __name__ == "__main__":
    unittest.main()
