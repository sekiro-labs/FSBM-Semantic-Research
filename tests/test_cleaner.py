"""Behavioral tests for meaning-preserving cleaning and explicit exclusions."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "src/preprocessing/cleaner.py"
spec = importlib.util.spec_from_file_location("fsbm_cleaner", SCRIPT)
cleaner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleaner)


def profile(articles):
    return {"chercheur_id": "A", "nom_complet": "Émilie", "affiliation": "FSBM",
            "metriques": {"citations_totales": 3, "h_index": 1, "i10_index": 0}, "articles": articles}


def article(article_id, title, abstract, year="2021", authors=None):
    return {"article_id": article_id, "titre": title, "abstract": abstract,
            "date_publication": year, "auteurs": authors or ["Émilie Dupont"],
            "journal": "Journal A", "citations": 0}


class CleanerTest(unittest.TestCase):
    def test_unicode_html_whitespace_and_original_preservation(self):
        original = " <p>Écologie&nbsp; et <b>réseaux</b>\n  français — données.</p> "
        rows, clean, excluded = cleaner.clean_profiles([profile([article("a", "  Étude — modèle  ", original)])])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(clean), 1)
        self.assertFalse(excluded)
        self.assertEqual(clean[0]["abstract"], original)
        self.assertEqual(clean[0]["abstract_clean"], "écologie et réseaux français — données.")
        self.assertEqual(clean[0]["title"], "  Étude — modèle  ")
        self.assertEqual(clean[0]["title_normalized"], "étude modèle")

    def test_duplicates_require_exact_title_year_and_support(self):
        abstract = "A meaningful abstract about a publication."
        items = [article("a", "Machine Learning: An Overview", abstract),
                 article("b", "Machine learning — an overview", abstract),
                 article("c", "Machine Learning: An Overview", abstract, year="2022"),
                 article("d", "Machine Learning: A Different Overview", abstract)]
        rows, clean, excluded = cleaner.clean_profiles([profile(items)])
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(clean), 3)
        self.assertEqual([item["exclusion_reason"] for item in excluded], ["duplicate_publication"])

    def test_missing_short_abstract_and_missing_title(self):
        items = [article("a", "No abstract", ""), article("b", "Too short", "Résumé"),
                 article("c", "", "A complete abstract with enough content.")]
        _, clean, excluded = cleaner.clean_profiles([profile(items)])
        self.assertFalse(clean)
        self.assertEqual({item["exclusion_reason"] for item in excluded},
                         {"missing_abstract", "abstract_too_short", "missing_title"})

    def test_json_parquet_and_report_generation(self):
        import pandas as pd

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / "raw.json"
            raw.write_text(json.dumps([profile([article("a", "Titre français", "Résumé détaillé d'une étude scientifique en français.")])], ensure_ascii=False), encoding="utf-8")
            report = cleaner.run_cleaning(raw, root / "out")
            exported = json.loads((root / "out/publications.json").read_text(encoding="utf-8"))
            parquet = pd.read_parquet(root / "out/publications.parquet")
            self.assertEqual(report["clean_publication_count"], 1)
            self.assertEqual(len(exported), len(parquet))
            self.assertEqual(exported[0]["abstract"], parquet.iloc[0]["abstract"])
            self.assertEqual(json.loads((root / "out/publications_excluded.json").read_text()), [])
            self.assertTrue((root / "out/data_quality_report.md").exists())


if __name__ == "__main__":
    unittest.main()
