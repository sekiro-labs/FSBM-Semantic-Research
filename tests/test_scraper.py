"""Offline checkpoint and resume test for the collection boundary."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "src/scraping/scraper.py"
spec = importlib.util.spec_from_file_location("fsbm_scraper", SCRIPT)
scraper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scraper)


class FakeScholar:
    def __init__(self):
        self.lookups = 0

    def search_author_id(self, scholar_id):
        self.lookups += 1
        return {"scholar_id": scholar_id}

    def fill(self, item, sections=None):
        if sections:
            return {"name": "Test Researcher", "affiliation": "FSBM", "interests": ["physics"],
                    "citedby": 12, "hindex": 2, "i10index": 1,
                    "publications": [{"author_pub_id": "abc", "bib": {"title": "Test paper"}}]}
        return {**item, "num_citations": 3,
                "bib": {"title": "Test paper", "author": "A and B", "abstract": "A public abstract"}}


class CheckpointTest(unittest.TestCase):
    def test_one_researcher_then_resume_skips_completed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selection = root / "selection.json"
            baseline = root / "baseline.json"
            output = root / "new.json"
            selection.write_text(json.dumps([{"chercheur_id": "NEW_ID", "nom_complet": "Test Researcher"}]))
            baseline.write_text(json.dumps([{"chercheur_id": "OLD_ID"}]))
            client = FakeScholar()
            with patch.object(scraper, "SELECTION", selection), patch.object(scraper, "BASELINE", baseline), \
                 patch.object(scraper, "OUTPUT", output), patch.object(scraper, "pause"):
                scraper.main(["--max-researchers", "1", "--delay", "0"], client)
                first = json.loads(output.read_text())
                self.assertEqual(first["profiles"][0]["status"], "complete")
                self.assertEqual(first["profiles"][0]["publications"][0]["abstract"], "A public abstract")
                scraper.main(["--max-researchers", "1", "--delay", "0"], client)
                self.assertEqual(client.lookups, 1)
                self.assertEqual(json.loads(output.read_text()), first)


if __name__ == "__main__":
    unittest.main()
