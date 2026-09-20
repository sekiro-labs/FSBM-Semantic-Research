"""Resumable collection of new Scholar profiles. Never writes the baseline sample."""

import argparse
import difflib
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parents[2]
SELECTION = ROOT / "data/input/new_researchers.json"
BASELINE = ROOT / "data/raw/raw_scholar_data.json"
OUTPUT = ROOT / "data/raw/new_scholar_data.json"
BATCH2_OUTPUT = ROOT / "data/raw/new_scholar_data_batch2.json"
PAPERS = ROOT / "data/papers"
USER_AGENT = "FSBM-Academic-Research/1.0 (respectful open-access retrieval)"
LOG = logging.getLogger("fsbm.scraper")


class ScholarBlocked(RuntimeError):
    """Scholar requires a login, CAPTCHA, or has rate-limited access."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_checkpoint(path, payload):
    """Atomic replacement keeps the previous checkpoint if interrupted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def is_blocked(exc):
    message = str(exc).lower()
    return any(term in message for term in (
        "captcha", "blocked", "robot", "too many requests", "429",
        "403 forbidden", "403 client error", "maxtriedexception",
        "'nonetype' object has no attribute 'get'",
    )) or isinstance(exc, HTTPError) and exc.code in (403, 429)


def retry(call, label, attempts, delay):
    for number in range(1, attempts + 1):
        try:
            return call()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            if is_blocked(exc):
                raise ScholarBlocked(f"{label}: Scholar/access block: {exc}") from exc
            if number == attempts:
                raise
            wait = delay * (2 ** (number - 1)) + random.uniform(0, min(delay, 1))
            LOG.warning("%s failed (%s/%s): %s; retry in %.1fs", label, number, attempts, exc, wait)
            time.sleep(wait)


def pause(seconds):
    if seconds:
        time.sleep(seconds + random.uniform(0, min(1, seconds * 0.2)))


def authors(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    return [part.strip() for part in str(value).split(" and ") if part.strip()]


def publication_record(pub, scholar_id):
    bib = pub.get("bib") or {}
    pub_id = pub.get("author_pub_id")
    scholar_url = (
        f"https://scholar.google.com/citations?view_op=view_citation&user={scholar_id}&citation_for_view={pub_id}"
        if pub_id else None
    )
    abstract = bib.get("abstract") or bib.get("description") or None
    references = bib.get("references") or None
    return {
        "article_id": f"{scholar_id}:{pub_id}" if pub_id else None,
        "title": bib.get("title") or None,
        "authors": authors(bib.get("author")),
        "publication_date": bib.get("pub_date") or bib.get("pub_year") or None,
        "journal_conference": bib.get("journal") or bib.get("conference") or None,
        "volume": bib.get("volume") or None,
        "pages": bib.get("pages") or None,
        "publisher": bib.get("publisher") or None,
        "citation_count": pub.get("num_citations"),
        "scholar_url": scholar_url,
        "publication_url": pub.get("pub_url") or pub.get("url_scholarbib") or None,
        "pdf_url": pub.get("eprint_url") or None,
        "pdf_path": None,
        "abstract": abstract,
        "references": references,
        "metadata_source": scholar_url or "Google Scholar profile",
        "abstract_source": scholar_url if abstract else None,
        "references_source": scholar_url if references else None,
        "status": "complete",
        "error": None,
    }


def robots_allows(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
        return parser.can_fetch(USER_AGENT, url)
    except Exception as exc:
        LOG.warning("Cannot verify robots rules for %s: %s", url, exc)
        return False


def download_pdf(url, article_id, timeout=20, max_bytes=30_000_000):
    """Fetch only a public PDF allowed by robots; failures leave metadata intact."""
    if not url or not robots_allows(url):
        return None, "PDF URL absent or disallowed by robots.txt"
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            if not robots_allows(final_url):
                return None, "Redirect target disallowed by robots.txt"
            content_type = response.headers.get("Content-Type", "").lower()
            if "pdf" not in content_type and not final_url.lower().split("?")[0].endswith(".pdf"):
                return None, f"Not a PDF (Content-Type: {content_type})"
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes or not content.startswith(b"%PDF-"):
                return None, "PDF too large or invalid"
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in article_id)
        PAPERS.mkdir(parents=True, exist_ok=True)
        destination = PAPERS / f"{safe_id}.pdf"
        if not destination.exists():
            temp = destination.with_suffix(".pdf.tmp")
            temp.write_bytes(content)
            os.replace(temp, destination)
        return str(destination.relative_to(ROOT)), None
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return None, f"PDF unavailable: {exc}"


def scrape_researcher(target, scholarly, args, on_progress=None):
    scholar_id = target["chercheur_id"]
    profile_url = f"https://scholar.google.com/citations?user={scholar_id}"
    author = retry(lambda: scholarly.search_author_id(scholar_id), f"profile {scholar_id}", args.retries, args.delay)
    if author is None:
        raise ScholarBlocked(f"Profile {scholar_id} unavailable (Scholar returned no profile; possible login/block)")
    pause(args.delay)
    author = retry(
        lambda: scholarly.fill(author, sections=["basics", "indices", "publications"]),
        f"profile details {scholar_id}", args.retries, args.delay,
    )
    profile = {
        "scholar_id": scholar_id,
        "full_name": author.get("name") or target.get("nom_complet"),
        "affiliation": author.get("affiliation") or None,
        "research_interests": author.get("interests") or [],
        "total_citations": author.get("citedby"),
        "h_index": author.get("hindex"),
        "i10_index": author.get("i10index"),
        "scholar_url": profile_url,
        "profile_source": profile_url,
        "selection_evidence_url": target.get("evidence_url"),
        "selected_area": target.get("selection_area"),
        "publications": [],
        "status": "complete",
        "errors": [],
        "collected_at": utc_now(),
    }
    publications = author.get("publications") or []
    for index, pub in enumerate(publications, 1):
        if args.max_publications is not None and index > args.max_publications:
            profile["status"] = "partial_limited"
            break
        pause(args.delay)
        try:
            filled = retry(lambda: scholarly.fill(pub), f"publication {index} for {scholar_id}", args.retries, args.delay)
            record = publication_record(filled, scholar_id)
        except ScholarBlocked:
            record = publication_record(pub, scholar_id)
            record["status"] = "partial_blocked"
            record["error"] = "Scholar blocked publication detail retrieval"
            profile["publications"].append(record)
            profile["status"] = "partial_blocked"
            profile["errors"].append(f"Publication {index}: Scholar blocked access; remaining publication stubs retained")
            for remaining in publications[index:]:
                stub = publication_record(remaining, scholar_id)
                stub["status"] = "not_filled_blocked"
                profile["publications"].append(stub)
            if on_progress:
                on_progress(profile)
            break
        except Exception as exc:
            record = publication_record(pub, scholar_id)
            record["status"] = "partial_error"
            record["error"] = str(exc)
            profile["errors"].append(f"Publication {index}: {exc}")
        if args.download_pdfs and record["pdf_url"]:
            record["pdf_path"], pdf_error = download_pdf(record["pdf_url"], record["article_id"] or f"{scholar_id}_{index}")
            if pdf_error:
                record["pdf_error"] = pdf_error
        profile["publications"].append(record)
        if on_progress:
            on_progress(profile)
    return profile


def main(argv=None, scholarly_client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-researchers", type=int, default=None, help="Process at most this many pending IDs")
    parser.add_argument("--selection", type=Path, default=SELECTION, help="Researcher selection JSON")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="Separate checkpoint/output JSON")
    parser.add_argument("--scholar-id", help="Process only this selected Scholar ID")
    parser.add_argument("--max-publications", type=int, default=None, help="Limit publication details for a trial; profile remains partial")
    parser.add_argument("--delay", type=float, default=5.0, help="Minimum seconds between Scholar requests")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--download-pdfs", action="store_true", help="Download public, robots-allowed PDFs")
    parser.add_argument("--skip-blocked", action="store_true", help="Skip IDs recorded as blocked in this checkpoint")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    if args.delay < 0 or args.retries < 1 or args.max_researchers is not None and args.max_researchers < 1 or args.max_publications is not None and args.max_publications < 1:
        parser.error("delay must be nonnegative; retries and max-researchers must be positive")
    if args.output.resolve() == BASELINE.resolve():
        parser.error("output must not overwrite the baseline raw dataset")
    if args.selection.resolve() != SELECTION.resolve() and args.output.resolve() == OUTPUT.resolve():
        parser.error("alternate selections require a separate output checkpoint")
    selected = load_json(args.selection)
    baseline = load_json(BASELINE)
    if not isinstance(selected, list) or not isinstance(baseline, list):
        raise ValueError("Selection or baseline JSON must contain a list")
    normalized_selection = []
    for person in selected:
        if not isinstance(person, dict):
            raise ValueError("Each selected researcher must be an object")
        scholar_id = person.get("scholar_id") or person.get("chercheur_id")
        if not scholar_id or (person.get("scholar_id") and person.get("chercheur_id") and
                              person["scholar_id"] != person["chercheur_id"]):
            raise ValueError("Selection has a missing or conflicting Scholar ID")
        name = person.get("nom_complet") or person.get("name")
        if not name:
            raise ValueError(f"Selection has no name for Scholar ID {scholar_id}")
        normalized_selection.append({**person, "chercheur_id": scholar_id, "nom_complet": name})
    selected = normalized_selection
    existing_ids = {p["chercheur_id"] for p in baseline}
    if args.output.resolve() != OUTPUT.resolve():
        prior_new = load_json(OUTPUT, {"profiles": []})
        existing_ids.update(p["scholar_id"] for p in prior_new.get("profiles", []) if p.get("scholar_id"))
    if args.output.resolve() != BATCH2_OUTPUT.resolve():
        prior_batch2 = load_json(BATCH2_OUTPUT, {"profiles": []})
        existing_ids.update(p["scholar_id"] for p in prior_batch2.get("profiles", []) if p.get("scholar_id"))
    selected_ids = [p["chercheur_id"] for p in selected]
    if len(selected_ids) != len(set(selected_ids)) or set(selected_ids) & existing_ids:
        raise ValueError("Selection has duplicate or baseline Scholar IDs")
    if args.selection.resolve() != SELECTION.resolve():
        targets = [p for p in selected if not args.scholar_id or p["chercheur_id"] == args.scholar_id]
        if any(p.get("scholar_profile_verified") is False for p in targets):
            parser.error("selected Scholar profile ID requires direct verification before scraping")
    checkpoint = load_json(args.output, {"schema_version": 1, "profiles": [], "failures": {}})
    if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get("profiles"), list):
        raise ValueError("Invalid checkpoint format; refusing to overwrite it")
    completed = {p["scholar_id"] for p in checkpoint["profiles"] if p.get("status") == "complete"}
    pending = [p for p in selected if p["chercheur_id"] not in completed]
    if args.skip_blocked:
        pending = [p for p in pending if checkpoint.get("failures", {}).get(p["chercheur_id"], {}).get("status") != "blocked"]
    if args.scholar_id:
        if args.scholar_id not in selected_ids:
            close = difflib.get_close_matches(args.scholar_id, selected_ids, n=1, cutoff=0.8)
            suggestion = f"; did you mean {close[0]}?" if close else ""
            parser.error(f"Scholar ID {args.scholar_id} is not in the selection{suggestion}")
        pending = [p for p in pending if p["chercheur_id"] == args.scholar_id]
    if args.max_researchers is not None:
        pending = pending[:args.max_researchers]
    if not pending:
        LOG.info("No pending researchers; checkpoint unchanged")
        return checkpoint
    if scholarly_client is None:
        from scholarly import scholarly as scholarly_client
    for target in pending:
        scholar_id = target["chercheur_id"]
        LOG.info("Processing %s (%s)", target["nom_complet"], scholar_id)
        try:
            def checkpoint_progress(profile):
                staged = dict(profile)
                staged["status"] = "in_progress" if profile["status"] == "complete" else profile["status"]
                checkpoint["profiles"] = [p for p in checkpoint["profiles"] if p.get("scholar_id") != scholar_id]
                checkpoint["profiles"].append(staged)
                save_checkpoint(args.output, checkpoint)

            profile = scrape_researcher(target, scholarly_client, args, checkpoint_progress)
            checkpoint["profiles"] = [p for p in checkpoint["profiles"] if p.get("scholar_id") != scholar_id]
            checkpoint["profiles"].append(profile)
            checkpoint["failures"].pop(scholar_id, None)
            save_checkpoint(args.output, checkpoint)
            LOG.info("Checkpoint saved: %s, %s publications, status=%s", scholar_id, len(profile["publications"]), profile["status"])
            if profile["status"] == "partial_blocked":
                LOG.error("Scholar blocking detected; stopping this run")
                break
        except KeyboardInterrupt:
            LOG.warning("Interrupted; previous checkpoint remains available")
            raise
        except ScholarBlocked as exc:
            checkpoint["failures"][scholar_id] = {"status": "blocked", "error": str(exc), "at": utc_now()}
            save_checkpoint(args.output, checkpoint)
            LOG.error("Scholar blocking detected; stopping this run: %s", exc)
            break
        except Exception as exc:
            checkpoint["failures"][scholar_id] = {"status": "error", "error": str(exc), "at": utc_now()}
            save_checkpoint(args.output, checkpoint)
            LOG.exception("Researcher failed; checkpoint saved and continuing")
        pause(args.delay)
    return checkpoint


if __name__ == "__main__":
    main()
