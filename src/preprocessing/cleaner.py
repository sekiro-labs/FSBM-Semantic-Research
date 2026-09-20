"""Build an embedding-ready, flat publication dataset from preserved Scholar raw data."""

import argparse
import html
import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_RAW_FILE = PROJECT_ROOT / "data/raw/raw_scholar_data.json"
OUTPUT_DIR = PROJECT_ROOT / "data/clean"
MIN_ABSTRACT_CHARS = 20
LOG = logging.getLogger("fsbm.cleaner")
YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
TAG_PATTERN = re.compile(r"<[^>]+>")

FIELDS = [
    "researcher_id", "researcher_name", "affiliation", "citations_total", "h_index",
    "i10_index", "research_interests", "researcher_ids", "article_id", "article_ids", "title", "title_normalized", "authors",
    "publication_date", "publication_year", "journal", "volume", "pages",
    "publisher", "citations", "publication_url", "scholar_url", "pdf_url", "abstract",
    "abstract_clean", "references", "metadata_source", "abstract_source",
    "references_source", "raw_source", "raw_sources", "profile_status", "embedding_eligible", "also_researcher_ids",
]


def missing(value):
    return value is None or isinstance(value, str) and value.strip().lower() in ("", "unknown", "n/a", "null", "none")


def nullable(value):
    return None if missing(value) else value


def normalize_text(value):
    """Conservative Unicode normalization for meaning-preserving embedding text."""
    if missing(value):
        return ""
    value = html.unescape(str(value))
    value = TAG_PATTERN.sub(" ", value)
    value = unicodedata.normalize("NFKC", value)
    value = "".join(" " if unicodedata.category(char) in ("Cc", "Cf", "Cs") or char == "\ufffd" else char for char in value)
    return re.sub(r"\s+", " ", value).strip().lower()


def normalize_title(value):
    text = normalize_text(value).casefold()
    return re.sub(r"[\W_]+", " ", text, flags=re.UNICODE).strip()


def year_from(value):
    if missing(value):
        return None
    match = YEAR_PATTERN.search(str(value))
    return int(match.group()) if match else None


def author_list(value):
    if missing(value) or value == []:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if not missing(item)]
    return [part.strip() for part in str(value).split(" and ") if part.strip()]


def reference_list(value):
    if missing(value) or value == []:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def publication_row(profile, article):
    metrics = profile.get("metriques") or {}
    title = article.get("title", article.get("titre"))
    raw_abstract = article.get("abstract")
    date = nullable(article.get("publication_date", article.get("date_publication")))
    researcher_id = nullable(profile.get("scholar_id", profile.get("chercheur_id")))
    return {
        "researcher_id": researcher_id,
        "researcher_name": nullable(profile.get("full_name", profile.get("nom_complet"))),
        "affiliation": nullable(profile.get("affiliation")),
        "citations_total": nullable(profile.get("total_citations", metrics.get("citations_totales"))),
        "h_index": nullable(profile.get("h_index", metrics.get("h_index"))),
        "i10_index": nullable(profile.get("i10_index", metrics.get("i10_index"))),
        "research_interests": profile.get("research_interests") or None,
        "researcher_ids": [researcher_id] if researcher_id else [],
        "article_id": nullable(article.get("article_id")),
        "article_ids": [article["article_id"]] if article.get("article_id") else [],
        "title": title,  # Preserve the original string, including whitespace and punctuation.
        "title_normalized": normalize_title(title),
        "authors": author_list(article.get("authors", article.get("auteurs"))),
        "publication_date": str(date) if date is not None else None,
        "publication_year": year_from(article.get("publication_year")) or year_from(date),
        "journal": nullable(article.get("journal_conference", article.get("journal"))),
        "volume": nullable(article.get("volume")),
        "pages": nullable(article.get("pages")),
        "publisher": nullable(article.get("publisher")),
        "citations": nullable(article.get("citation_count", article.get("citations"))),
        "publication_url": nullable(article.get("publication_url")),
        "scholar_url": nullable(article.get("scholar_url")),
        "pdf_url": nullable(article.get("pdf_url")),
        "abstract": raw_abstract,  # Keep exactly what was collected, including an empty string.
        "abstract_clean": normalize_text(raw_abstract),
        "references": reference_list(article.get("references")),
        "metadata_source": nullable(article.get("metadata_source")),
        "abstract_source": nullable(article.get("abstract_source")),
        "references_source": nullable(article.get("references_source")),
        "raw_source": article.get("raw_source") or profile.get("raw_source"),
        "raw_sources": [article.get("raw_source") or profile.get("raw_source")] if article.get("raw_source") or profile.get("raw_source") else [],
        "profile_status": article.get("profile_status") or profile.get("status"),
        "embedding_eligible": None,
        "also_researcher_ids": [],
    }


def doi_from(row):
    for value in (row.get("publication_url"), row.get("article_id")):
        if not value:
            continue
        match = re.search(r"10\.\d{4,9}/[^\s?#]+", str(value), flags=re.I)
        if match:
            return match.group().rstrip(".,)").lower()
    return None


def authors_overlap(left, right):
    a = {normalize_title(name) for name in left.get("authors") or []}
    b = {normalize_title(name) for name in right.get("authors") or []}
    return bool(a & b)


def duplicate_of(row, kept):
    """Prefer DOI, then exact normalized title/year with author or venue evidence."""
    doi = doi_from(row)
    if doi and doi == doi_from(kept):
        return True
    if (row.get("article_id") and row["article_id"] == kept.get("article_id") and
            row.get("researcher_id") == kept.get("researcher_id")):
        return True
    if doi and doi_from(kept) and doi != doi_from(kept):
        return False
    title = row["title_normalized"]
    if not title or len(title) < 12 or len(title.split()) < 3:
        return False
    if title != kept["title_normalized"] or not row["publication_year"] or row["publication_year"] != kept["publication_year"]:
        return False
    if authors_overlap(row, kept):
        return True
    return False


def merge_duplicate(kept, other):
    """Keep the strongest row while retaining links and missing source metadata."""
    for key in ("researcher_ids", "article_ids", "raw_sources"):
        kept[key] = list(dict.fromkeys((kept.get(key) or []) + (other.get(key) or [])))
    kept["also_researcher_ids"] = [item for item in kept["researcher_ids"] if item != kept["researcher_id"]]
    for key in ("title", "title_normalized", "authors", "publication_date", "publication_year", "journal", "volume", "pages", "publisher",
                "publication_url", "scholar_url", "pdf_url", "abstract", "abstract_clean",
                "references", "metadata_source", "abstract_source", "references_source"):
        if missing(kept.get(key)) and not missing(other.get(key)):
            kept[key] = other[key]
    if kept.get("citations") is None and other.get("citations") is not None:
        kept["citations"] = other["citations"]


def quality_score(row):
    return (
        bool(row["abstract_clean"]),
        len(row["abstract_clean"]),
        sum(not missing(row.get(key)) for key in ("journal", "publication_url", "pdf_url", "volume", "pages", "publisher")),
    )


def deduplicate(rows):
    """Return retained records and explicit duplicate exclusions."""
    ordered = sorted(enumerate(rows), key=lambda pair: quality_score(pair[1]), reverse=True)
    retained = {}
    duplicates = []
    by_doi = defaultdict(list)
    by_title_year = defaultdict(list)
    by_article = defaultdict(list)
    for index, row in ordered:
        doi = doi_from(row)
        candidates = []
        if doi:
            candidates.extend(by_doi[doi])
        if row.get("article_id"):
            candidates.extend(by_article[(row["researcher_id"], row["article_id"])])
        if row["title_normalized"] and row["publication_year"]:
            candidates.extend(by_title_year[(row["title_normalized"], row["publication_year"])])
        prior = next((item for item in candidates if duplicate_of(row, item)), None)
        if prior:
            duplicates.append({**row, "exclusion_reason": "duplicate_publication", "duplicate_of": prior["article_id"]})
            merge_duplicate(prior, row)
            updated_doi = doi_from(prior)
            if updated_doi and prior not in by_doi[updated_doi]:
                by_doi[updated_doi].append(prior)
            if row.get("article_id") and prior not in by_article[(row["researcher_id"], row["article_id"])]:
                by_article[(row["researcher_id"], row["article_id"])].append(prior)
        else:
            retained[index] = row
            if doi:
                by_doi[doi].append(row)
            if row.get("article_id"):
                by_article[(row["researcher_id"], row["article_id"])].append(row)
            if row["title_normalized"] and row["publication_year"]:
                by_title_year[(row["title_normalized"], row["publication_year"])].append(row)
    return [retained[index] for index in sorted(retained)], duplicates


def clean_profiles(profiles, min_abstract_chars=MIN_ABSTRACT_CHARS):
    rows = [publication_row(profile, article) for profile in profiles for article in (profile.get("articles") or profile.get("publications") or [])]
    retained, duplicates = deduplicate(rows)
    clean = []
    excluded = list(duplicates)
    for row in retained:
        if missing(row["title"]):
            reason = "missing_title"
        elif not row["abstract_clean"]:
            reason = "missing_abstract"
        elif len(row["abstract_clean"]) < min_abstract_chars:
            reason = "abstract_too_short"
        else:
            row["embedding_eligible"] = True
            clean.append(row)
            continue
        row["embedding_eligible"] = False
        excluded.append({**row, "exclusion_reason": reason})
    return rows, clean, excluded


def length_stats(values):
    if not values:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    values = sorted(values)
    count = len(values)
    middle = (values[(count - 1) // 2] + values[count // 2]) / 2
    return {"count": count, "min": values[0], "median": middle, "mean": round(sum(values) / count, 2), "max": values[-1]}


def quality_report(profiles, rows, clean, excluded):
    reasons = Counter(item["exclusion_reason"] for item in excluded)
    missing_fields = {
        field: sum(missing(row.get(field)) or row.get(field) == [] for row in rows)
        for field in FIELDS if field != "also_researcher_ids"
    }
    by_researcher = Counter(row["researcher_id"] or "unknown" for row in rows)
    by_year = Counter(str(row["publication_year"]) for row in rows if row["publication_year"])
    clean_by_researcher = Counter(row["researcher_id"] or "unknown" for row in clean)
    clean_by_year = Counter(str(row["publication_year"]) for row in clean if row["publication_year"])
    return {
        "raw_researcher_count": len(profiles),
        "raw_publication_count": len(rows),
        "clean_publication_count": len(clean),
        "excluded_publication_count": len(excluded),
        "duplicate_count": reasons.get("duplicate_publication", 0),
        "exclusion_reasons": dict(sorted(reasons.items())),
        "missing_values_raw": missing_fields,
        "researcher_affiliation": {
            "present": sum(not missing(p.get("affiliation")) for p in profiles),
            "missing": sum(missing(p.get("affiliation")) for p in profiles),
            "explicit_fsbm_or_ben_msick": sum(bool(re.search(r"fsbm|ben\s*m", str(p.get("affiliation") or ""), re.I)) for p in profiles),
        },
        "abstract_length_raw_nonempty": length_stats([len(row["abstract"].strip()) for row in rows if isinstance(row["abstract"], str) and row["abstract"].strip()]),
        "abstract_length_clean_included": length_stats([len(row["abstract_clean"]) for row in clean]),
        "publications_by_researcher_raw": dict(sorted(by_researcher.items())),
        "publications_by_researcher_clean": dict(sorted(clean_by_researcher.items())),
        "publications_by_year_raw": dict(sorted(by_year.items())),
        "publications_by_year_clean": dict(sorted(clean_by_year.items())),
        "suspicious_record_counts": {
            "replacement_character_in_abstract": sum("\ufffd" in str(row.get("abstract") or "") for row in rows),
            "truncated_abstract_ellipsis": sum(str(row.get("abstract") or "").rstrip().endswith(("…", "...")) for row in rows),
            "missing_researcher_id": missing_fields["researcher_id"],
            "missing_article_id": missing_fields["article_id"],
            "profiles_without_publications": sum(not (p.get("articles") or p.get("publications")) for p in profiles),
            "noninteger_citation_counts": sum(row["citations"] is not None and (not isinstance(row["citations"], int) or isinstance(row["citations"], bool)) for row in rows),
            "negative_citation_counts": sum(isinstance(row["citations"], (int, float)) and row["citations"] < 0 for row in rows),
            "implausible_publication_year": sum(row["publication_year"] is not None and not 1900 <= row["publication_year"] <= datetime.now(timezone.utc).year + 1 for row in rows),
        },
        "limitations": [
            "Legacy raw records do not contain publication/PDF URLs, references, or source provenance; those columns remain null.",
            "Affiliation strings are self-reported Scholar data and do not independently verify current FSBM membership.",
            "Many abstracts may be truncated or contain Unicode replacement characters already present in the source; original text is preserved.",
            "Deduplication uses DOI where available, otherwise exact normalized title and year plus author overlap or matching venue; uncertain matches remain separate.",
            "Only records with a title and at least 20 cleaned abstract characters enter the embedding-ready output.",
        ],
    }


def markdown_report(report):
    lines = ["# Data quality report", "", "| Measure | Count |", "|---|---:|"]
    for key in ("raw_researcher_count", "raw_publication_count", "clean_publication_count", "excluded_publication_count", "duplicate_count"):
        lines.append(f"| {key} | {report[key]} |")
    lines += ["", "## Exclusion reasons", ""]
    lines += [f"- {key}: {value}" for key, value in report["exclusion_reasons"].items()]
    lines += ["", "## Missing fields in raw publications", "", "| Field | Missing |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in report["missing_values_raw"].items()]
    lines += ["", "## Suspicious records", "", "| Finding | Count |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in report["suspicious_record_counts"].items()]
    lines += ["", "## Abstract lengths", "", "```json", json.dumps({"raw_nonempty": report["abstract_length_raw_nonempty"], "clean_included": report["abstract_length_clean_included"]}, indent=2), "```", "", "## Publications by researcher (raw)", "", "| Scholar ID | Publications |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in report["publications_by_researcher_raw"].items()]
    lines += ["", "## Publications by year (raw)", "", "| Year | Publications |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in report["publications_by_year_raw"].items()]
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in report["limitations"]]
    return "\n".join(lines) + "\n"


def run_cleaning(input_path=INPUT_RAW_FILE, output_dir=OUTPUT_DIR, min_abstract_chars=MIN_ABSTRACT_CHARS):
    import pandas as pd

    input_path = Path(input_path)
    output_dir = Path(output_dir)
    with input_path.open(encoding="utf-8") as handle:
        profiles = json.load(handle)
    if not isinstance(profiles, list):
        raise ValueError("Raw input must be a list of researcher profiles")
    rows, clean, excluded = clean_profiles(profiles, min_abstract_chars)
    report = quality_report(profiles, rows, clean, excluded)
    if len(clean) + len(excluded) != len(rows):
        raise AssertionError("Every raw publication must be included or explicitly excluded")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "publications.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "publications_excluded.json").write_text(json.dumps(excluded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    frame = pd.DataFrame(clean, columns=FIELDS)
    frame.to_parquet(output_dir / "publications.parquet", index=False)
    (output_dir / "data_quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "data_quality_report.md").write_text(markdown_report(report), encoding="utf-8")
    LOG.info("Cleaned %d of %d publications; %d excluded (%d duplicates)", len(clean), len(rows), len(excluded), report["duplicate_count"])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_RAW_FILE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-abstract-chars", type=int, default=MIN_ABSTRACT_CHARS)
    args = parser.parse_args()
    if args.min_abstract_chars < 1:
        parser.error("--min-abstract-chars must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_cleaning(args.input, args.output_dir, args.min_abstract_chars)
