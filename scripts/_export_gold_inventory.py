import json
from collections import Counter
from pathlib import Path

rows = [
    json.loads(line)
    for line in Path("tests/fixtures/long_term_memory_eval/extraction_cases.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
for split in ("development", "test"):
    print(f"=== {split}")
    for row in rows:
        if row["split"] != split:
            continue
        golds = row.get("gold_memories") or []
        if not golds:
            continue
        cats = Counter(g["category"] for g in golds)
        print(f"{row['case_id']:25} n={len(golds)} {dict(cats)}")
