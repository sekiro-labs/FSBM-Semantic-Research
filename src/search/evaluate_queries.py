"""Run the five required academic evaluation queries with the indexed zembed-1 model."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.search.semantic_search import SemanticSearcher

QUERIES = [
    "deep learning for medical diagnosis",
    "natural language processing",
    "renewable energy and smart materials",
    "water resources and environmental geology",
    "cancer prediction using machine learning",
]
OUTPUT = ROOT / "data/embeddings/query_evaluation.json"


def main():
    searcher = SemanticSearcher()
    evaluation = {query: searcher.search(query, 5) for query in QUERIES}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for query, results in evaluation.items():
        print(f"\n{query}")
        for item in results:
            print(f"  {item['rank']}. {item['similarity_score']:.4f} {item['title']}")


if __name__ == "__main__":
    main()
