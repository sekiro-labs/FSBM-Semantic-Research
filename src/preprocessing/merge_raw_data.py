"""Consolidate collected legacy and checkpoint data without changing raw sources."""

import argparse
import json
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

from cleaner import FIELDS, clean_profiles, missing, nullable

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    ROOT / "data/raw/raw_scholar_data.json",
    ROOT / "data/raw/new_scholar_data.json",
    ROOT / "data/raw/new_scholar_data_batch2.json",
    ROOT / "data/raw/new_scholar_data_batch3.json",
)
OUTPUT = ROOT / "data/clean"


def load_sources(paths=SOURCES):
    """Return standardized researcher profiles, audit counts, and issues."""
    profiles_by_id = {}
    source_counts = {}
    status_counts = Counter()
    issues = []
    for path in paths:
        path = Path(path)
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            raw_profiles, schema = data, "legacy"
        elif isinstance(data, dict) and isinstance(data.get("profiles"), list):
            raw_profiles, schema = data["profiles"], "checkpoint"
            for scholar_id, failure in (data.get("failures") or {}).items():
                issues.append({"source": path.name, "scholar_id": scholar_id,
                               "issue": "checkpoint_failure", "status": failure.get("status")})
        else:
            raise ValueError(f"Unrecognized raw schema: {path}")
        publication_count = 0
        for index, raw in enumerate(raw_profiles):
            if not isinstance(raw, dict):
                issues.append({"source": path.name, "profile_index": index, "issue": "profile_not_object"})
                continue
            scholar_id = raw.get("scholar_id") or raw.get("chercheur_id")
            if not scholar_id:
                issues.append({"source": path.name, "profile_index": index, "issue": "missing_scholar_id"})
                continue
            articles = raw.get("articles") if schema == "legacy" else raw.get("publications")
            if not isinstance(articles, list):
                issues.append({"source": path.name, "scholar_id": scholar_id, "issue": "publications_not_list"})
                articles = []
            status = raw.get("status") or ("legacy" if schema == "legacy" else "unknown")
            status_counts[status] += 1
            metrics = raw.get("metriques") or {}
            incoming = {
                "scholar_id": scholar_id,
                "full_name": raw.get("full_name") or raw.get("nom_complet"),
                "affiliation": nullable(raw.get("affiliation")),
                "research_interests": raw.get("research_interests") or None,
                "total_citations": raw.get("total_citations", metrics.get("citations_totales")),
                "h_index": raw.get("h_index", metrics.get("h_index")),
                "i10_index": raw.get("i10_index", metrics.get("i10_index")),
                "raw_sources": [path.name],
                "source_statuses": {path.name: status},
                "publications": [],
            }
            if scholar_id not in profiles_by_id:
                profiles_by_id[scholar_id] = incoming
            target = profiles_by_id[scholar_id]
            if path.name not in target["raw_sources"]:
                target["raw_sources"].append(path.name)
            target["source_statuses"][path.name] = status
            for field in ("full_name", "affiliation", "research_interests", "total_citations", "h_index", "i10_index"):
                if missing(target.get(field)) and not missing(incoming.get(field)):
                    target[field] = incoming[field]
            for pub_index, article in enumerate(articles):
                if not isinstance(article, dict):
                    issues.append({"source": path.name, "scholar_id": scholar_id,
                                   "publication_index": pub_index, "issue": "publication_not_object"})
                    continue
                target["publications"].append({**article, "raw_source": path.name,
                                               "_profile_status": status})
                publication_count += 1
        source_counts[path.name] = {"schema": schema, "researchers": len(raw_profiles),
                                    "publications": publication_count}
    profiles = list(profiles_by_id.values())
    # Preserve status at the publication boundary even if one researcher appears in several sources.
    for profile in profiles:
        for article in profile["publications"]:
            article["profile_status"] = article.pop("_profile_status")
    return profiles, source_counts, dict(status_counts), issues


def quality_report(profiles, source_counts, statuses, issues, raw_rows, unique_rows, excluded):
    reasons = Counter(row["exclusion_reason"] for row in excluded)
    raw_sources = Counter(source for row in unique_rows for source in row.get("raw_sources") or [])
    total = len(raw_rows)
    missing_count = lambda key: sum(missing(row.get(key)) or row.get(key) == [] for row in unique_rows)
    eligible = sum(bool(row["embedding_eligible"]) for row in unique_rows)
    represented = {item for row in unique_rows for item in row.get("researcher_ids") or []}
    return {
        "total_unique_researchers": len(profiles),
        "researchers_represented_in_publications": len(represented),
        "researchers_by_raw_source": {name: item["researchers"] for name, item in source_counts.items()},
        "source_counts": source_counts,
        "researcher_status_distribution": statuses,
        "raw_publication_records": total,
        "unique_publications": len(unique_rows),
        "duplicate_publications_merged": reasons["duplicate_publication"],
        "publications_with_abstracts": total - sum(missing(row.get("abstract")) for row in raw_rows),
        "publications_without_abstracts": sum(missing(row.get("abstract")) for row in raw_rows),
        "unique_publications_with_abstracts": len(unique_rows) - missing_count("abstract"),
        "unique_publications_without_abstracts": missing_count("abstract"),
        "embedding_eligible": eligible,
        "embedding_ineligible": len(unique_rows) - eligible,
        "exclusion_reasons": dict(sorted(reasons.items())),
        "missing_year_or_date": sum(row.get("publication_year") is None and missing(row.get("publication_date")) for row in unique_rows),
        "missing_publication_year": sum(row.get("publication_year") is None for row in unique_rows),
        "missing_publication_date": missing_count("publication_date"),
        "missing_journal_or_conference": missing_count("journal"),
        "missing_authors": missing_count("authors"),
        "missing_citation_count": missing_count("citations"),
        "publication_urls_available": len(unique_rows) - missing_count("publication_url"),
        "pdf_urls_available": len(unique_rows) - missing_count("pdf_url"),
        "references_available": len(unique_rows) - missing_count("references"),
        "publication_raw_source_memberships": dict(sorted(raw_sources.items())),
        "suspicious_or_malformed_records": issues,
        "suspicious_record_counts": {
            "profiles_without_publications": sum(not profile["publications"] for profile in profiles),
            "raw_publications_without_title": sum(missing(row.get("title")) for row in raw_rows),
            "replacement_character_in_abstract": sum("\ufffd" in str(row.get("abstract") or "") for row in raw_rows),
            "implausible_publication_year": sum(row.get("publication_year") is not None and
                not 1900 <= row["publication_year"] <= datetime.now(timezone.utc).year + 1 for row in raw_rows),
        },
        "limitations": [
            "The legacy source does not supply publication URLs, PDF URLs, references, or provenance for individual fields.",
            "A source affiliation string does not independently establish current FSBM membership.",
            "Partial checkpoints contain only the publication records saved at collection time.",
            "Scholar publication IDs are scoped to a researcher; cross-researcher matching requires DOI or exact title, year, and author overlap.",
            "Original abstracts may already be truncated or contain replacement characters; they are preserved.",
        ],
    }


def markdown_report(report):
    lines = ["# Consolidated data quality report", "", "| Measure | Count |", "|---|---:|"]
    for key in ("total_unique_researchers", "researchers_represented_in_publications",
                "raw_publication_records", "unique_publications", "duplicate_publications_merged",
                "publications_with_abstracts", "publications_without_abstracts",
                "embedding_eligible", "embedding_ineligible", "missing_publication_year",
                "missing_publication_date", "missing_journal_or_conference", "missing_authors",
                "missing_citation_count", "publication_urls_available", "pdf_urls_available",
                "references_available"):
        lines.append(f"| {key} | {report[key]} |")
    lines += ["", "## Raw sources", "", "| Source | Schema | Researchers | Publications |", "|---|---|---:|---:|"]
    for name, value in report["source_counts"].items():
        lines.append(f"| {name} | {value['schema']} | {value['researchers']} | {value['publications']} |")
    lines += ["", "## Checkpoint statuses", ""]
    lines += [f"- {key}: {value}" for key, value in report["researcher_status_distribution"].items()]
    lines += ["", "## Exclusion reasons", ""]
    lines += [f"- {key}: {value}" for key, value in report["exclusion_reasons"].items()]
    lines += ["", "## Publication source memberships", ""]
    lines += [f"- {key}: {value}" for key, value in report["publication_raw_source_memberships"].items()]
    lines += ["", "## Suspicious records", ""]
    lines += [f"- {key}: {value}" for key, value in report["suspicious_record_counts"].items()]
    lines += [f"- {item}" for item in report["suspicious_or_malformed_records"]]
    lines += ["", "## Limitations", ""]
    lines += [f"- {value}" for value in report["limitations"]]
    return "\n".join(lines) + "\n"


def run(output_dir=OUTPUT, paths=SOURCES):
    import pandas as pd

    profiles, source_counts, statuses, issues = load_sources(paths)
    raw_rows, eligible_rows, excluded = clean_profiles(profiles)
    unique_rows = eligible_rows + [row for row in excluded if row["exclusion_reason"] != "duplicate_publication"]
    unique_rows.sort(key=lambda row: (row.get("researcher_id") or "", row.get("title") or ""))
    if len(raw_rows) != len(unique_rows) + sum(row["exclusion_reason"] == "duplicate_publication" for row in excluded):
        raise AssertionError("Raw publication accounting mismatch")
    report = quality_report(profiles, source_counts, statuses, issues, raw_rows, unique_rows, excluded)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    researchers = [{key: value for key, value in profile.items() if key != "publications"} for profile in profiles]
    for name, value in (("researchers.json", researchers), ("publications.json", unique_rows),
                        ("publications_excluded.json", excluded), ("data_quality_report.json", report)):
        (output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    frame = pd.DataFrame(unique_rows, columns=FIELDS)
    frame.to_parquet(output_dir / "publications.parquet", index=False)
    check = pd.read_parquet(output_dir / "publications.parquet")
    if len(check) != len(unique_rows) or any(field not in check for field in FIELDS) or "__index_level_0__" in check:
        raise AssertionError("Parquet row count, columns, or index validation failed")
    for column in ("title", "abstract"):
        if check[column].fillna("").tolist() != frame[column].fillna("").tolist():
            raise AssertionError(f"Parquet Unicode round-trip failed for {column}")
    (output_dir / "data_quality_report.md").write_text(markdown_report(report), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), ensure_ascii=False, indent=2))
