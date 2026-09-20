"""Offline PDF enrichment checks. Every external response is mocked."""

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

from src.enrichment import pdf_enrichment as pdf


def publication(article_id="scholar:one", *, url="https://publisher.example/article/10.1234/example"):
    return {"article_id": article_id, "title": "A Study of Renewable Materials", "authors": ["A. Author"],
            "publication_year": 2024, "publication_url": url, "pdf_url": None,
            "abstract": "Original abstract remains intact.", "references": ["Source reference"]}


def oa_work(pdf_url="https://hal.science/example/document.pdf"):
    return {"doi": "https://doi.org/10.1234/example", "title": "A Study of Renewable Materials",
            "publication_year": 2024, "open_access": {"is_oa": True},
            "best_oa_location": {"is_oa": True, "pdf_url": pdf_url}}


class FakeClient:
    email = None

    def __init__(self, result=None, pdf_bytes=None, content_type="application/pdf", allowed=True):
        self.result = result if result is not None else oa_work()
        self.pdf_bytes = pdf_bytes or (b"%PDF-1.7\n" + b"x" * 1100)
        self.content_type = content_type
        self.allowed = allowed
        self.json_calls = []
        self.pdf_calls = []
        self.robots_calls = []

    def get_json(self, url):
        self.json_calls.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def robots_allows(self, url):
        self.robots_calls.append(url)
        return self.allowed

    def get_pdf(self, url):
        self.pdf_calls.append(url)
        return self.pdf_bytes, self.content_type


class PdfEnrichmentTests(unittest.TestCase):
    def test_open_access_location_and_provenance(self):
        row = publication()
        result = pdf.enrich_publication(row, FakeClient())
        self.assertTrue(result["pdf_available"])
        self.assertEqual(result["pdf_status"], "discovered")
        self.assertEqual(result["pdf_url"], "https://hal.science/example/document.pdf")
        self.assertEqual(result["pdf_source"], "openalex:best_oa_location")
        self.assertEqual(result["doi"], "10.1234/example")
        self.assertEqual(result["abstract"], row["abstract"])
        self.assertEqual(result["references"], row["references"])
        self.assertIsNone(result["pdf_local_path"])

    def test_no_pdf_and_malformed_metadata(self):
        closed = oa_work()
        closed["open_access"] = {"is_oa": False}
        self.assertEqual(pdf.enrich_publication(publication(), FakeClient(closed))["pdf_status"], "not_found")
        self.assertEqual(pdf.enrich_publication(publication(), FakeClient([]))["pdf_status"], "error")

    def test_html_response_is_never_saved_as_pdf(self):
        direct = publication(url="https://hal.science/example/document.pdf")
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient(pdf_bytes=b"<html>Login required</html>", content_type="text/html")
            result = pdf.enrich_publication(direct, client, download=True, papers_dir=folder)
            self.assertEqual(result["pdf_status"], "invalid_pdf")
            self.assertFalse(result["pdf_available"])
            self.assertEqual(result["pdf_content_type"], "text/html")
            self.assertEqual(result["pdf_response_type"], "html")
            self.assertEqual(result["pdf_error"], "rejected Content-Type: text/html")
            self.assertFalse(result["pdf_redirected"])
            self.assertEqual(pdf.build_report(1, [result], 1)["pdf_candidates"], 1)
            self.assertEqual(list(Path(folder).glob("*.pdf")), [])

    def test_robots_denial_and_timeout_preserve_record(self):
        direct = publication(url="https://hal.science/example/document.pdf")
        denied = pdf.enrich_publication(direct, FakeClient(allowed=False), download=True)
        self.assertEqual(denied["pdf_status"], "robots_disallowed")
        self.assertIsNone(denied["pdf_local_path"])
        timeout = pdf.enrich_publication(publication(), FakeClient(TimeoutError("timed out")))
        self.assertEqual(timeout["pdf_status"], "error")
        self.assertEqual(timeout["abstract"], publication()["abstract"])

    def test_publication_matching_rejects_wrong_title_or_doi(self):
        row = publication()
        self.assertFalse(pdf.matching_work({**oa_work(), "doi": "https://doi.org/10.1234/other"}, row, "10.1234/example"))
        self.assertFalse(pdf.matching_work({**oa_work(), "title": "Unrelated research"}, row))
        self.assertFalse(pdf.oa_pdf_from_work({"open_access": {"is_oa": False},
            "best_oa_location": {"pdf_url": "https://example.org/paper.pdf"}})[0])

    def test_open_repository_location_precedes_publisher_best_location(self):
        work = oa_work("https://link.springer.com/content/pdf/paper.pdf")
        work["best_oa_location"]["source"] = {"type": "journal"}
        work["locations"] = [{"is_oa": True, "pdf_url": "https://hal.science/paper.pdf",
                              "source": {"type": "repository"}}]
        self.assertEqual(pdf.oa_pdf_from_work(work), ("https://hal.science/paper.pdf", "openalex:locations"))
        work["locations"][0]["is_oa"] = False
        self.assertEqual(pdf.oa_pdf_from_work(work)[0], "https://link.springer.com/content/pdf/paper.pdf")

    def test_safe_filename_existing_pdf_and_download(self):
        name = pdf.safe_pdf_filename("../scholar:one/../../private")
        self.assertTrue(name.startswith("paper_"))
        self.assertEqual(len(name), len("paper_") + 24 + len(".pdf"))
        self.assertNotIn("/", name)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / pdf.safe_pdf_filename("scholar:one")
            target.write_bytes(b"%PDF-1.7\n" + b"a" * 1100)
            client = FakeClient()
            location, status, _ = pdf.download_pdf("scholar:one", "https://hal.science/a.pdf", client, folder)
            self.assertEqual(status, "existing_pdf")
            self.assertEqual(location, str(target))
            self.assertEqual(client.pdf_calls, [])
            target.write_bytes(b"<html>not a PDF</html>")
            self.assertFalse(pdf.valid_existing_pdf(target))
            _, status, _ = pdf.download_pdf("scholar:one", "https://hal.science/a.pdf", client, folder)
            self.assertEqual(status, "downloaded")
            self.assertTrue(pdf.valid_existing_pdf(target))

    def test_resume_duplicate_prevention_and_force(self):
        rows = [publication(), publication(), publication("scholar:two", url=None)]
        client = FakeClient()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "publications.json"
            output = root / "enriched.json"
            report = root / "report.json"
            source.write_text(json.dumps(rows), encoding="utf-8")
            first = pdf.run(source=source, output=output, report_path=report, limit=1, client=client)
            self.assertEqual(first["checked_publications"], 1)
            self.assertEqual(len(client.json_calls), 1)
            second = pdf.run(source=source, output=output, report_path=report, limit=1, client=client)
            self.assertEqual(second["checked_publications"], 1)
            self.assertEqual(len(client.json_calls), 1)
            pdf.run(source=source, output=output, report_path=report, limit=1, force=True, client=client)
            self.assertEqual(len(client.json_calls), 2)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["records"]), 1)
            self.assertEqual(payload["records"][0]["article_id"], "scholar:one")

    def test_force_retry_is_limited_to_selected_ids(self):
        rows = [publication("scholar:one"), publication("scholar:two")]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, output, report = [root / name for name in ("source.json", "output.json", "report.json")]
            source.write_text(json.dumps(rows), encoding="utf-8")
            client = FakeClient()
            pdf.run(source=source, output=output, report_path=report, limit=2, client=client)
            self.assertEqual(len(client.json_calls), 2)
            pdf.run(source=source, output=output, report_path=report, limit=2,
                    article_ids=["scholar:two"], force=True, client=client)
            self.assertEqual(len(client.json_calls), 3)
            self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))["records"]), 2)

    def test_download_after_discovery_reuses_candidate_without_api_call(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, output, report = [root / name for name in ("source.json", "output.json", "report.json")]
            source.write_text(json.dumps([publication()]), encoding="utf-8")
            client = FakeClient()
            pdf.run(source=source, output=output, report_path=report, client=client)
            self.assertEqual(len(client.json_calls), 1)
            pdf.run(source=source, output=output, report_path=report, papers_dir=root,
                    download=True, client=client)
            self.assertEqual(len(client.json_calls), 1)
            self.assertEqual(len(client.pdf_calls), 1)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["records"][0]["pdf_status"], "downloaded")

    def test_bounded_retry_and_rate_limit_are_offline(self):
        class Response:
            headers = {"Content-Type": "application/json"}
            def __init__(self, url): self.url = url
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def geturl(self): return self.url
            def read(self, _): return b'{"results": []}'

        class Opener:
            def __init__(self): self.calls = 0
            def open(self, request, timeout):
                self.calls += 1
                if self.calls == 1: raise URLError("temporary")
                return Response(request.full_url)

        opener = Opener()
        client = pdf.PublicClient(delay=0, retries=1, opener=opener, sleep=lambda _: None)
        self.assertEqual(client.get_json("https://api.openalex.org/works?search=test"), {"results": []})
        self.assertEqual(opener.calls, 2)
        class Limited:
            def open(self, request, timeout):
                raise HTTPError(request.full_url, 429, "rate limited", {}, None)
        with self.assertRaises(pdf.RateLimited):
            pdf.PublicClient(delay=0, retries=3, opener=Limited(), sleep=lambda _: None).get_json(
                "https://api.openalex.org/works?search=test")


if __name__ == "__main__":
    unittest.main()
