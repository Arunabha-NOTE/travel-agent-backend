"""Inspect the pgvector knowledge base and print all unique chunks."""

import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")


def main() -> None:
    from app.agents.rag.vector_store import get_vector_store

    store = get_vector_store()

    queries = [
        "travel tips destinations culture",
        "visa requirements passport customs",
        "airport transit immigration layover",
        "hotel booking accommodation stay",
        "transportation taxi bus train",
        "food restaurants dining tipping etiquette",
        "safety travel insurance health",
        "museum attraction sightseeing free",
        "pet animals cabin flight airline",
        "night bus late transport 2am",
    ]

    seen = {}
    for q in queries:
        docs = store.similarity_search(q, k=8)
        for d in docs:
            key = d.page_content[:100]
            if key not in seen:
                seen[key] = d.page_content

    print(f"Total unique chunks found: {len(seen)}\n")
    print("=" * 60)
    for i, (key, content) in enumerate(seen.items(), 1):
        print(f"\n[CHUNK {i}]")
        print(content[:600])
        print("-" * 40)


if __name__ == "__main__":
    main()
