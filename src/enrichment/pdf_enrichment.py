"""Discover public PDF locations without changing the cleaned corpus or search index.

Discovery is the default. Supplying --download explicitly enables PDF transfers.
No network request occurs when this module is imported.
"""

import argparse
import hashlib
import ipaddress
import json
import logging
import os
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/clean/publications.json"
OUTPUT = ROOT / "data/enriched/publications_with_pdf.json"
REPORT = ROOT / "data/enriched/pdf_enrichment_report.json"
PAPERS = ROOT / "data/papers"
OPENALEX = "https://api.openalex.org"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s?#]+", re.IGNORECASE)
MAX_PDF_BYTES = 30_000_000
MIN_PDF_BYTES = 1_024
LOG = logging.getLogger("fsbm.pdf_enrichment")

# Only explicit PDF links on these open repositories/publishers are accepted
# without OpenAlex OA evidence. A generic publisher or ResearchGate URL is not.
PUBLIC_PDF_HOSTS = (
    "arxiv.org", "hal.science", "zenodo.org", "pmc.ncbi.nlm.nih.gov",
    "biorxiv.org", "medrxiv.org", "frontiersin.org", "mdpi.com",
)
DONE_STATUSES = {"discovered", "not_found", "downloaded", "existing_pdf"}


class RateLimited(RuntimeError):
    """A public metadata source has asked the client to slow down or stop."""


class AccessRestricted(RuntimeError):
    """The requested resource requires access that this stage will not bypass."""


class NoRedirect(HTTPRedirectHandler):
    """Reject redirects so a PDF target is never fetched before robots checking."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_public_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return address.is_global


def normalized_title(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"\w+", text, flags=re.UNICODE))


def extract_doi(publication):
    for key in ("doi", "publication_url", "article_id", "scholar_url"):
        text = unquote(str(publication.get(key) or ""))
        match = DOI_PATTERN.search(text)
        if match:
            return match.group().rstrip(".,);]}").lower()
    return None


def safe_pdf_filename(article_id):
    if not isinstance(article_id, str) or not article_id.strip():
        raise ValueError("A nonempty publication ID is required for a PDF filename")
    return f"paper_{hashlib.sha256(article_id.encode('utf-8')).hexdigest()[:24]}.pdf"


def valid_existing_pdf(path, min_bytes=MIN_PDF_BYTES, max_bytes=MAX_PDF_BYTES):
    try:
        if not path.is_file() or not min_bytes <= path.stat().st_size <= max_bytes:
            return False
        with path.open("rb") as stream:
            return stream.read(5) == b"%PDF-"
    except OSError:
        return False


def valid_pdf_response(content, content_type, min_bytes=MIN_PDF_BYTES, max_bytes=MAX_PDF_BYTES):
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    if kind in ("text/html", "application/xhtml+xml", "text/plain"):
        return False
    return min_bytes <= len(content) <= max_bytes and content.startswith(b"%PDF-")


def display_path(path):
    resolved = Path(path).resolve()
    return resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else str(resolved)


class PublicClient:
    """Bounded public HTTP client; deliberately does not follow redirects."""

    def __init__(self, *, email=None, delay=1.5, retries=1, timeout=20, opener=None, sleep=time.sleep):
        if delay < 0 or retries < 0 or timeout <= 0:
            raise ValueError("delay and retries must be nonnegative; timeout must be positive")
        self.email = email
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.opener = opener or build_opener(NoRedirect())
        self.sleep = sleep
        self.last_request = None
        self.robots_cache = {}
        self.last_pdf_response = None
        self.user_agent = f"FSBM-Semantic-Research/1.0 (academic OA metadata; contact: {email})" if email else "FSBM-Semantic-Research/1.0 (academic OA metadata)"

    def _open(self, url, max_bytes):
        if not safe_public_url(url):
            raise AccessRestricted("Non-public or unsupported URL")
        if self.last_request is not None:
            self.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json, application/pdf;q=0.8"})
        for attempt in range(self.retries + 1):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    final_url = response.geturl()
                    if final_url != url:  # Defensive: custom openers might follow redirects.
                        raise AccessRestricted("Redirected response was not pre-approved")
                    if getattr(response, "status", 200) != 200:
                        raise AccessRestricted("Non-200 response")
                    if max_bytes == MAX_PDF_BYTES:
                        self.last_pdf_response = {"http_status": getattr(response, "status", 200),
                                                  "content_type": response.headers.get("Content-Type", ""),
                                                  "redirected": False}
                    return response.read(max_bytes + 1), response.headers.get("Content-Type", "")
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise AccessRestricted(f"HTTP {exc.code}: access restricted") from exc
                if exc.code == 429:
                    raise RateLimited("HTTP 429: public source rate limit") from exc
                if exc.code not in (500, 502, 503, 504) or attempt == self.retries:
                    raise
            except (URLError, TimeoutError, OSError):
                if attempt == self.retries:
                    raise
            wait = min(2 ** attempt * max(self.delay, 1), 30)
            LOG.warning("Transient request failure; retrying %s after %.1fs", urlsplit(url).netloc, wait)
            self.sleep(wait)
            self.last_request = time.monotonic()
        raise AssertionError("unreachable")

    def get_json(self, url):
        content, _ = self._open(url, 2_000_000)
        if len(content) > 2_000_000:
            raise ValueError("Metadata response exceeds 2 MB")
        return json.loads(content)

    def get_pdf(self, url):
        return self._open(url, MAX_PDF_BYTES)

    def robots_allows(self, url):
        if not safe_public_url(url):
            return False
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.robots_cache:
            robots_url = f"{origin}/robots.txt"
            try:
                content, _ = self._open(robots_url, 250_000)
                if len(content) > 250_000:
                    allowed = False
                else:
                    parser = RobotFileParser()
                    parser.parse(content.decode("utf-8", errors="replace").splitlines())
                    self.robots_cache[origin] = parser
                    allowed = parser.can_fetch(self.user_agent, url)
            except HTTPError as exc:
                allowed = exc.code == 404  # No robots rules published.
            except RateLimited:
                raise
            except (URLError, TimeoutError, OSError, AccessRestricted):
                allowed = False
            if origin not in self.robots_cache:
                self.robots_cache[origin] = allowed
            return allowed
        cached = self.robots_cache[origin]
        return cached.can_fetch(self.user_agent, url) if isinstance(cached, RobotFileParser) else cached


def is_explicit_public_pdf(url):
    if not safe_public_url(url) or not urlsplit(url).path.lower().endswith(".pdf"):
        return False
    host = urlsplit(url).hostname.lower()
    return any(host == domain or host.endswith("." + domain) for domain in PUBLIC_PDF_HOSTS)


def matching_work(work, publication, doi=None):
    if not isinstance(work, dict):
        return False
    if doi:
        work_doi = extract_doi({"doi": work.get("doi")})
        return work_doi == doi
    title = normalized_title(publication.get("title"))
    if not title or normalized_title(work.get("title") or work.get("display_name")) != title:
        return False
    year = publication.get("publication_year")
    if year and work.get("publication_year") and int(year) != int(work["publication_year"]):
        return False
    known_authors = {normalized_title(name) for name in publication.get("authors") or []}
    oa_authors = {normalized_title(a.get("author", {}).get("display_name")) for a in work.get("authorships") or []}
    return not known_authors or not oa_authors or bool(known_authors & oa_authors)


def oa_pdf_from_work(work):
    if not isinstance(work, dict) or not (work.get("open_access") or {}).get("is_oa"):
        return None, None
    locations = [("best_oa_location", work.get("best_oa_location"))]
    locations.extend(("locations", item) for item in work.get("locations") or [])
    candidates = []
    for name, location in locations:
        if not isinstance(location, dict) or location.get("is_oa") is not True:
            continue
        url = location.get("pdf_url")
        if safe_public_url(url):
            source = location.get("source") or {}
            repository = isinstance(source, dict) and source.get("type") == "repository"
            candidates.append((not repository, name != "best_oa_location", url, name))
    if candidates:
        _, _, url, name = min(candidates)
        return url, f"openalex:{name}"
    return None, None


def discover_pdf(publication, client):
    """Return a public candidate URL and provenance, or no candidate."""
    for field in ("pdf_url", "publication_url"):
        url = publication.get(field)
        if is_explicit_public_pdf(url):
            return url, f"existing:{field}", extract_doi(publication)

    doi = extract_doi(publication)
    work = None
    if doi:
        url = f"{OPENALEX}/works/{quote('https://doi.org/' + doi, safe=':/')}"
        try:
            candidate = client.get_json(url)
            if matching_work(candidate, publication, doi):
                work = candidate
        except HTTPError as exc:
            if exc.code != 404:
                raise
    if work is None and publication.get("title"):
        params = {"search": publication["title"], "per-page": 5}
        if getattr(client, "email", None):
            params["mailto"] = client.email
        response = client.get_json(f"{OPENALEX}/works?{urlencode(params)}")
        if not isinstance(response, dict):
            raise ValueError("Malformed OpenAlex search response")
        work = next((item for item in (response.get("results") or []) if matching_work(item, publication)), None)
    pdf_url, source = oa_pdf_from_work(work)
    return pdf_url, source, doi


def download_pdf(publication_id, url, client, papers_dir=PAPERS, force=False):
    """Write a validated PDF atomically; never replace a valid file by default."""
    path = Path(papers_dir) / safe_pdf_filename(publication_id)
    if valid_existing_pdf(path) and not force:
        return display_path(path), "existing_pdf", {}
    if not client.robots_allows(url):
        return None, "robots_disallowed", {"pdf_error": "robots.txt disallows the candidate URL"}
    content, content_type = client.get_pdf(url)
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    response_type = "pdf_signature" if content.startswith(b"%PDF-") else (
        "html" if content.lstrip()[:20].lower().startswith((b"<!doctype html", b"<html")) or kind in
        ("text/html", "application/xhtml+xml") else "other_non_pdf")
    details = {"pdf_http_status": (getattr(client, "last_pdf_response", None) or {}).get("http_status", 200),
               "pdf_content_type": content_type, "pdf_redirected": False,
               "pdf_response_type": response_type, "pdf_response_bytes": len(content)}
    if not valid_pdf_response(content, content_type):
        if kind in ("text/html", "application/xhtml+xml", "text/plain"):
            reason = f"rejected Content-Type: {kind}"
        elif not content.startswith(b"%PDF-"):
            reason = "missing %PDF- signature"
        elif not MIN_PDF_BYTES <= len(content) <= MAX_PDF_BYTES:
            reason = f"PDF size outside {MIN_PDF_BYTES}-{MAX_PDF_BYTES} bytes"
        else:
            reason = "invalid PDF response"
        return None, "invalid_pdf", {**details, "pdf_error": reason}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pdf.tmp")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return display_path(path), "downloaded", details


def enrich_publication(publication, client, *, download=False, papers_dir=PAPERS, force=False, known_candidate=None):
    result = {**publication, "pdf_available": False, "pdf_url": None, "pdf_local_path": None,
              "pdf_source": None, "pdf_status": "not_found", "pdf_checked_at": utc_now(), "pdf_error": None,
              "doi": extract_doi(publication), "original_pdf_url": publication.get("pdf_url")}
    try:
        url, source, doi = known_candidate or discover_pdf(publication, client)
        result["doi"] = doi
        if not url:
            return result
        result.update(pdf_available=True, pdf_url=url, pdf_source=source, pdf_status="discovered")
        if download:
            local_path, status, details = download_pdf(publication["article_id"], url, client, papers_dir, force)
            result.update(pdf_local_path=local_path, pdf_status=status, **details)
            if status in ("robots_disallowed", "invalid_pdf"):
                result["pdf_available"] = False
        return result
    except RateLimited as exc:
        result.update(pdf_status="rate_limited", pdf_error=str(exc))
        return result
    except AccessRestricted as exc:
        result.update(pdf_status="restricted", pdf_error=str(exc))
        return result
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
        result.update(pdf_status="error", pdf_error=f"{type(exc).__name__}: {exc}")
        return result


def ranked_publications(rows):
    """Stable order favors existing public URLs, then DOI and source metadata."""
    unique = {}
    for row in rows:
        article_id = row.get("article_id")
        if article_id and article_id not in unique:
            unique[article_id] = row
    return sorted(unique.values(), key=lambda row: (
        -int(any(is_explicit_public_pdf(row.get(key)) for key in ("pdf_url", "publication_url"))),
        -int(bool(extract_doi(row))), -int(bool(row.get("publication_url"))),
        row["article_id"],
    ))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def build_report(source_count, records, selected_count):
    statuses = Counter(item["pdf_status"] for item in records)
    return {"source_publications": source_count, "selected_publications": selected_count,
            "checked_publications": len(records), "pdf_candidates": sum(bool(item.get("pdf_url")) for item in records),
            "downloaded_pdfs": sum(item.get("pdf_status") in ("downloaded", "existing_pdf") for item in records),
            "statuses": dict(sorted(statuses.items())), "updated_at": utc_now()}


def run(*, source=SOURCE, output=OUTPUT, report_path=REPORT, papers_dir=PAPERS,
        limit=None, download=False, force=False, client=None, article_ids=None):
    """Process a bounded selection and resume by article ID and source hash."""
    if limit is not None and limit < 1:
        raise ValueError("--limit must be a positive integer")
    source = Path(source)
    raw_bytes = source.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    publications = json.loads(raw_bytes)
    if not isinstance(publications, list):
        raise ValueError("Final cleaned publication input must be a JSON list")
    selected = ranked_publications(publications)
    if article_ids:
        requested = set(article_ids)
        selected = [row for row in selected if row["article_id"] in requested]
        missing = requested - {row["article_id"] for row in selected}
        if missing:
            raise ValueError(f"Unknown publication IDs: {', '.join(sorted(missing))}")
    if limit is not None:
        selected = selected[:limit]
    output = Path(output)
    existing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
    if existing and existing.get("source_sha256") != source_hash:
        raise ValueError("Existing enrichment is for a different cleaned dataset; use a separate output path")
    records = {row["article_id"]: row for row in (existing or {}).get("records", [])}
    client = client or PublicClient()
    for publication in selected:
        article_id = publication["article_id"]
        previous = records.get(article_id)
        if previous and not force and previous.get("pdf_status") in DONE_STATUSES:
            complete_download = previous["pdf_status"] in ("downloaded", "existing_pdf") and bool(previous.get("pdf_local_path")) and valid_existing_pdf(ROOT / previous["pdf_local_path"])
            if not download or previous["pdf_status"] == "not_found" or complete_download:
                LOG.info("Skipping completed publication %s", article_id)
                continue
        known_candidate = None
        if previous and download and previous.get("pdf_url") and previous.get("pdf_source") and not force:
            # A previous discovery-only run can be downloaded without another API lookup.
            known_candidate = (previous["pdf_url"], previous["pdf_source"], previous.get("doi"))
        item = enrich_publication(publication, client, download=download, papers_dir=papers_dir,
                                  force=force, known_candidate=known_candidate)
        records[article_id] = item
        source_label = display_path(source)
        payload = {"schema_version": 1, "source_file": source_label, "source_sha256": source_hash,
                   "records": [records[key] for key in sorted(records)]}
        atomic_json(output, payload)
        atomic_json(report_path, build_report(len(publications), payload["records"], len(selected)))
        LOG.info("%s: %s", article_id, item["pdf_status"])
        if item["pdf_status"] == "rate_limited":
            LOG.warning("Stopping after public-source rate limit; checkpoint is safe to resume later")
            break
    final_report = build_report(len(publications), list(records.values()), len(selected))
    if records:
        atomic_json(report_path, final_report)
    return final_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--limit", type=int, help="Process only the most promising N publications")
    scope.add_argument("--all", action="store_true", help="Explicitly check the full cleaned corpus")
    parser.add_argument("--article-id", action="append", help="Restrict to this publication ID; repeat for multiple IDs")
    parser.add_argument("--download", action="store_true", help="Explicitly download discovered public PDFs")
    parser.add_argument("--force", action="store_true", help="Recheck selected publications and redownload valid PDFs")
    parser.add_argument("--email", help="Optional contact email for the OpenAlex polite pool")
    parser.add_argument("--delay", type=float, default=1.5, help="Minimum seconds between requests (default: 1.5)")
    parser.add_argument("--retries", type=int, default=1, help="Retries for transient HTTP errors (default: 1)")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP timeout in seconds (default: 20)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.email and ("@" not in args.email or " " in args.email):
        parser.error("--email must be a valid contact email")
    try:
        report = run(limit=args.limit, download=args.download, force=args.force, article_ids=args.article_id,
                     client=PublicClient(email=args.email, delay=args.delay, retries=args.retries, timeout=args.timeout))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
