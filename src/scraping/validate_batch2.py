"""Audit Batch 2 against both raw collections and the original input list."""

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def normalized_name(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(character for character in value if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def audit(baseline, new_data, batch, input_list):
    existing = {}
    for record in baseline:
        existing[record["chercheur_id"]] = record.get("nom_complet", "")
    for record in new_data["profiles"]:
        existing[record["scholar_id"]] = record.get("full_name", "")
    ids = [record["chercheur_id"] for record in batch]
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    represented = [{"scholar_id": item, "name": existing[item]} for item in sorted(set(ids) & existing.keys())]
    input_ids = {item["chercheur_id"] for item in input_list}
    near_names = []
    comparison = [(item["chercheur_id"], item["nom_complet"], "batch") for item in batch]
    comparison += [(item, name, "represented") for item, name in existing.items()]
    for index, (left_id, left_name, left_group) in enumerate(comparison):
        if left_group != "batch":
            break
        for right_id, right_name, right_group in comparison[index + 1:]:
            if left_id == right_id:
                continue
            score = SequenceMatcher(None, normalized_name(left_name), normalized_name(right_name)).ratio()
            if score >= 0.88:
                near_names.append({"candidate": left_name, "candidate_id": left_id,
                                   "match": right_name, "match_id": right_id,
                                   "match_group": right_group, "similarity": round(score, 3)})
    return {
        "baseline_researchers": len(baseline),
        "already_newly_collected_researchers": len(new_data["profiles"]),
        "represented_unique_scholar_ids": len(existing),
        "batch2_candidate_count": len(batch),
        "duplicate_scholar_ids_in_batch": duplicate_ids,
        "candidates_rejected_already_represented": represented,
        "duplicate_or_near_duplicate_names": near_names,
        "ids_missing_from_original_input": sorted(set(ids) - input_ids),
        "missing_affiliation_evidence": [item["chercheur_id"] for item in batch if not item.get("evidence_url")],
        "scholar_profiles_pending_direct_verification": [item["chercheur_id"] for item in batch if not item.get("scholar_profile_verified")],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, default=ROOT / "data/input/new_researchers_batch2.json")
    args = parser.parse_args(argv)
    report = audit(
        read_json(ROOT / "data/raw/raw_scholar_data.json"),
        read_json(ROOT / "data/raw/new_scholar_data.json"),
        read_json(args.batch),
        read_json(ROOT / "data/input/input_faculty_list.json"),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    main()
