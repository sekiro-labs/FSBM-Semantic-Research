"""Offline Batch 3 selection and scraper compatibility checks."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


batch3 = load_module("fsbm_batch3", ROOT / "src/scraping/validate_batch3.py")
scraper = load_module("fsbm_scraper_batch3", ROOT / "src/scraping/scraper.py")


class FakeScholar:
    def search_author_id(self, scholar_id):
        return {"scholar_id": scholar_id}

    def fill(self, item, sections=None):
        if sections:
            return {"name": "New Person", "affiliation": "FSBM", "interests": [],
                    "publications": []}
        return item


class Batch3Test(unittest.TestCase):
    def test_actual_batch3_asmaa_id_and_typo_diagnostic(self):
        selection = ROOT / "data/input/new_researchers_batch3.json"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline, first, second, output = [root / name for name in
                ("baseline.json", "first.json", "second.json", "third.json")]
            baseline.write_text("[]", encoding="utf-8")
            first.write_text('{"profiles": []}', encoding="utf-8")
            second.write_text('{"profiles": []}', encoding="utf-8")
            with patch.object(scraper, "BASELINE", baseline), patch.object(scraper, "OUTPUT", first), \
                 patch.object(scraper, "BATCH2_OUTPUT", second), patch.object(scraper, "pause"):
                error = io.StringIO()
                with redirect_stderr(error), self.assertRaises(SystemExit):
                    scraper.main(["--selection", str(selection), "--output", str(output),
                                  "--scholar-id", "fIzgYIoAAAAJ"], FakeScholar())
                self.assertIn("did you mean tIzgYIoAAAAJ?", error.getvalue())
                self.assertFalse(output.exists())
                scraper.main(["--selection", str(selection), "--output", str(output),
                              "--scholar-id", "tIzgYIoAAAAJ", "--max-publications", "15",
                              "--delay", "8", "--retries", "1"], FakeScholar())
            profile = json.loads(output.read_text(encoding="utf-8"))["profiles"][0]
            self.assertEqual(profile["scholar_id"], "tIzgYIoAAAAJ")

    def test_deduplicates_id_and_normalized_name(self):
        rows = [
            {"chercheur_id": "AAAAAAAAAAAA", "nom_complet": "Émile Dupont"},
            {"chercheur_id": "AAAAAAAAAAAA", "nom_complet": "Emile Dupont"},
            {"chercheur_id": "BBBBBBBBBBBB", "nom_complet": "Emile  Dupont"},
            {"chercheur_id": "CCCCCCCCCCCC", "nom_complet": "Existing Person"},
            {"chercheur_id": "short", "nom_complet": "Malformed"},
        ]
        selected, excluded, suspicious = batch3.make_batch(
            rows, [("DDDDDDDDDDDD", "Existing Person")], [])
        self.assertEqual(len(selected), 1)
        self.assertEqual([item["reason"] for item in excluded],
                         ["duplicate_input_id", "duplicate_input_name", "already_represented_name"])
        self.assertEqual(len(suspicious), 1)
        self.assertFalse(selected[0]["manual_verification"])
        self.assertEqual(selected[0]["selection_source"], "original_faculty_input")

    def test_batch3_can_use_separate_checkpoint_without_manual_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selection, baseline, first, second, output = [root / name for name in
                ("selection.json", "baseline.json", "first.json", "second.json", "third.json")]
            selection.write_text(json.dumps([{"chercheur_id": "AAAAAAAAAAAA", "nom_complet": "New Person",
                                              "manual_verification": False,
                                              "selection_source": "original_faculty_input"}]), encoding="utf-8")
            baseline.write_text("[]", encoding="utf-8")
            first.write_text('{"profiles": []}', encoding="utf-8")
            second.write_text('{"profiles": []}', encoding="utf-8")
            with patch.object(scraper, "SELECTION", first), patch.object(scraper, "BASELINE", baseline), \
                 patch.object(scraper, "OUTPUT", first), patch.object(scraper, "BATCH2_OUTPUT", second), \
                 patch.object(scraper, "pause"):
                scraper.main(["--selection", str(selection), "--output", str(output),
                              "--scholar-id", "AAAAAAAAAAAA", "--max-publications", "15",
                              "--delay", "8", "--retries", "1"], FakeScholar())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["profiles"][0]["scholar_id"],
                             "AAAAAAAAAAAA")


if __name__ == "__main__":
    unittest.main()
