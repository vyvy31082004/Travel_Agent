import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.common import load_jsonl
from memory_eval.retrieval_schema import SCENARIO_TYPES, validate_dataset


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "long_term_memory_eval"


def test_retrieval_fixture_validates():
    rows = load_jsonl(FIXTURES / "retrieval_cases.jsonl")
    assert validate_dataset(rows) == []

    scenario_types = {row["scenario_type"] for row in rows}
    assert scenario_types == set(SCENARIO_TYPES)
