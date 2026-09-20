"""Build and audit Batch 3 from the original faculty input, without network access."""

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/input/input_faculty_list.json"
BATCH1 = ROOT / "data/input/new_researchers.json"
BATCH2 = ROOT / "data/input/new_researchers_batch2.json"
BATCH3 = ROOT / "data/input/new_researchers_batch3.json"
BASELINE = ROOT / "data/raw/raw_scholar_data.json"
NEW1 = ROOT / "data/raw/new_scholar_data.json"
NEW2 = ROOT / "data/raw/new_scholar_data_batch2.json"
SCHOLAR_ID = re.compile(r"[A-Za-z0-9_-]{12}\Z")


def read(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def normalize_name(name):
    plain = unicodedata.normalize("NFKD", name.casefold())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def make_batch(input_rows, represented_rows, first_selection):
    represented_ids = {row[0] for row in represented_rows}
    represented_names = {normalize_name(row[1]) for row in represented_rows if row[1]}
    first_by_id = {row["chercheur_id"]: row for row in first_selection}
    seen_ids, seen_names, selected, excluded, suspicious = set(), set(), [], [], []
    for index, row in enumerate(input_rows):
        scholar_id, name = row.get("chercheur_id"), row.get("nom_complet")
        if not isinstance(scholar_id, str) or not SCHOLAR_ID.fullmatch(scholar_id) or not isinstance(name, str) or not normalize_name(name):
            suspicious.append({"row": index + 1, "record": row, "reason": "missing_or_malformed_id_or_name"})
            continue
        normalized = normalize_name(name)
        if scholar_id in represented_ids:
            excluded.append({"row": index + 1, "scholar_id": scholar_id, "reason": "already_represented_id"})
            continue
        if normalized in represented_names:
            excluded.append({"row": index + 1, "scholar_id": scholar_id, "reason": "already_represented_name"})
            continue
        if scholar_id in seen_ids:
            excluded.append({"row": index + 1, "scholar_id": scholar_id, "reason": "duplicate_input_id"})
            continue
        if normalized in seen_names:
            excluded.append({"row": index + 1, "scholar_id": scholar_id, "reason": "duplicate_input_name"})
            continue
        seen_ids.add(scholar_id)
        seen_names.add(normalized)
        entry = dict(row)
        entry.update(scholar_id=scholar_id, name=name,
                     selection_source="original_faculty_input", manual_verification=False)
        earlier = first_by_id.get(scholar_id, {})
        for key in ("selection_area", "evidence_url"):
            if earlier.get(key):
                entry[key] = earlier[key]
        selected.append(entry)
    return selected, excluded, suspicious


def audit():
    input_rows, first, second = read(INPUT), read(BATCH1), read(BATCH2)
    baseline, new1, new2 = read(BASELINE), read(NEW1), read(NEW2)
    represented = [(row["chercheur_id"], row.get("nom_complet", "")) for row in baseline]
    represented += [(row["scholar_id"], row.get("full_name", "")) for data in (new1, new2) for row in data["profiles"]]
    selected, excluded, suspicious = make_batch(input_rows, represented, first)
    existing = read(BATCH3)
    if existing != selected:
        raise ValueError("Batch 3 differs from the deterministic selection built from the current inputs")
    counts = Counter(item["reason"] for item in excluded)
    input_id_counts = Counter(row.get("chercheur_id") for row in input_rows)
    input_name_counts = Counter(normalize_name(row["nom_complet"]) for row in input_rows
                                if isinstance(row.get("nom_complet"), str))
    report = {
        "original_input_rows": len(input_rows),
        "original_input_distinct_scholar_ids": len({row.get("chercheur_id") for row in input_rows}),
        "duplicate_ids_in_original_input": sorted(key for key, count in input_id_counts.items() if key and count > 1),
        "duplicate_normalized_names_in_original_input": sorted(key for key, count in input_name_counts.items() if key and count > 1),
        "already_represented_distinct_scholar_ids": len({row[0] for row in represented}),
        "batch3_candidates": len(selected),
        "excluded_by_reason": dict(sorted(counts.items())),
        "excluded_total": len(excluded),
        "suspicious_rows": suspicious,
        "unverified_candidates": sum(not row["manual_verification"] for row in selected),
        "batch2_selection_count": len(second),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(audit(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
