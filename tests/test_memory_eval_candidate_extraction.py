import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory
from memory_eval.candidate_extraction import (
    CandidateExtractionCase,
    CandidateExtractionEvaluator,
    CandidateExtractionReport,
    GoldMemory,
    load_candidate_extraction_cases,
)
from memory_eval.semantic_match import (
    CallableSemanticJudge,
    maximum_bipartite_matching,
    texts_exactly_equivalent,
)


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "long_term_memory_eval"
    / "extraction_cases.jsonl"
)


def _mem(text: str, *, category="hotel_preference", domain="hotel", evidence=None):
    return TravelMemory(
        user_id="eval-user",
        memory_text=text,
        category=MemoryCategory(category),
        domain=MemoryDomain(domain),
        evidence_text=evidence or text,
        source_thread_id="t",
    )


def _gold(text: str, *, category="hotel_preference", domain="hotel", family="travel_preferences"):
    return GoldMemory(
        memory_text=text,
        category=category,
        domain=domain,
        family=family,
    )


def _case(
    case_id: str,
    *,
    messages,
    gold_memories=(),
    expected_store=True,
    unsafe=False,
):
    return CandidateExtractionCase(
        case_id=case_id,
        messages=tuple(messages),
        gold_memories=tuple(gold_memories),
        expected_store=expected_store,
        unsafe=unsafe,
        requirement_id="REQ-TEST",
        risk="test",
        split="development",
        code_path=("test",),
        metric=("semantic_extraction_precision",),
        rationale="unit test",
    )


class _FixedExtractor:
    def __init__(self, by_case: dict[str, list[TravelMemory]]):
        self.by_case = by_case

    async def extract(self, messages, *, user_id, thread_id, existing_active=(), limit=5):
        case_id = thread_id.split(":")[-1]
        return list(self.by_case.get(case_id, []))


def test_gold_fixture_has_traceability_and_expected_splits():
    cases = load_candidate_extraction_cases(FIXTURE)
    assert len(cases) == 150
    assert sum(1 for case in cases if case.split == "development") == 65
    assert sum(1 for case in cases if case.split == "test") == 85
    assert {case.split for case in cases} == {"development", "test"}
    development = [case for case in cases if case.split == "development"]
    test_cases = [case for case in cases if case.split == "test"]
    assert sum(1 for case in development if case.requirement_id == "REQ-EXTRACT-VALID") == 18
    assert sum(1 for case in test_cases if case.requirement_id == "REQ-EXTRACT-VALID") == 20
    assert all(case.requirement_id for case in cases)
    assert all(case.rationale for case in cases)
    assert all(case.code_path for case in cases)
    assert all(case.metric for case in cases)
    assert all(hasattr(case, "expected_store") for case in cases)
    assert any(not case.expected_store for case in cases)
    assert any(case.expected_store for case in cases)


def test_candidate_extraction_report_has_all_requested_metrics():
    cases = load_candidate_extraction_cases(FIXTURE)
    report = asyncio.run(CandidateExtractionEvaluator().evaluate(cases))
    metrics = report.metrics()
    assert "semantic_extraction_precision" in metrics
    assert "semantic_extraction_recall" in metrics
    assert "semantic_extraction_f1" in metrics
    assert "evidence_faithfulness_rate" in metrics
    assert "domain_accuracy" in metrics
    assert "family_accuracy" in metrics
    assert "no_store_rejection_rate" in metrics
    assert "unsafe_rejection_rate" in metrics
    assert report.total_cases == len(cases)
    assert report.total_gold_memories > 0
    assert report.unsafe_gold_cases > 0
    assert report.no_store_cases > 0
    assert all(
        0 <= metric.value <= 1
        for metric in metrics.values()
        if metric.value is not None
    )


def test_unsafe_rejection_metric_is_measured_without_hard_coding_target():
    cases = load_candidate_extraction_cases(FIXTURE)
    report = asyncio.run(CandidateExtractionEvaluator().evaluate(cases))
    metric = report.unsafe_rejection_rate
    assert metric.value is not None
    assert metric.denominator == sum(case.unsafe for case in cases)
    assert metric.numerator == sum(
        case.correctly_rejected_unsafe is True for case in report.cases
    )
    assert 0 <= metric.value <= 1


def test_no_store_rejection_metric_uses_expected_store():
    cases = load_candidate_extraction_cases(FIXTURE)
    report = asyncio.run(CandidateExtractionEvaluator().evaluate(cases))
    metric = report.no_store_rejection_rate
    assert metric.denominator == sum(not case.expected_store for case in cases)
    assert metric.numerator == sum(
        case.correctly_rejected_no_store is True for case in report.cases
    )


def test_atomic_gold_cases_are_reported_as_recall_failures_when_baseline_merges_facts():
    cases = load_candidate_extraction_cases(FIXTURE)
    report = asyncio.run(CandidateExtractionEvaluator().evaluate(cases))
    atomic = next(case for case in report.cases if case.case_id == "atomic_001")
    assert len(atomic.matched_gold_indices) < 3
    assert report.extraction_recall.value is not None


def test_zero_denominator_is_undefined_not_zero():
    report = CandidateExtractionReport(
        total_cases=0,
        total_extracted_memories=0,
        true_positives=0,
        false_positives=0,
        false_negatives=0,
        valid_extracted_memories=0,
        correctly_extracted_gold_memories=0,
        total_gold_memories=0,
        memories_supported_by_user_evidence=0,
        approved_memories=0,
        category_correct=0,
        category_labeled_cases=0,
        domain_correct=0,
        domain_labeled_cases=0,
        family_correct=0,
        family_labeled_cases=0,
        correctly_rejected_no_store_cases=0,
        no_store_cases=0,
        correctly_rejected_unsafe_cases=0,
        unsafe_gold_cases=0,
    )
    assert report.semantic_extraction_precision.value is None
    assert report.semantic_extraction_recall.value is None
    assert report.unsafe_rejection_rate.value is None
    assert report.no_store_rejection_rate.value is None


def test_maximum_matching_is_stable_under_tie_break():
    # Two maximum matchings of size 2; deterministic tie-break prefers
    # matching extracted 0 -> gold 0, extracted 1 -> gold 1.
    matrix = [
        [True, True, False],
        [True, True, False],
        [False, False, False],
    ]
    first = maximum_bipartite_matching(matrix)
    second = maximum_bipartite_matching(matrix)
    assert first == second == [(0, 0), (1, 1)]

    # Prefer larger matching: only max-size assignment is (0,1)+(1,0).
    matrix2 = [
        [True, True],
        [True, False],
    ]
    assert maximum_bipartite_matching(matrix2) == [(0, 1), (1, 0)]


def test_paraphrase_counts_as_true_positive_with_semantic_judge():
    def equivalent(a, b):
        # Treat thích / thường chọn as equivalent when the rest matches.
        def strip(v: str) -> str:
            v = v.casefold()
            for token in ("thích ", "thường chọn ", "ưu tiên ", "muốn "):
                v = v.replace(token, "")
            return " ".join(v.split())

        return strip(a) == strip(b)

    judge = CallableSemanticJudge(
        equivalent_fn=equivalent,
        supports_fn=lambda evidence, memory: True,
    )
    case = _case(
        "para",
        messages=[{"type": "human", "content": "Tôi thường chọn resort yên tĩnh"}],
        gold_memories=[_gold("thường chọn resort yên tĩnh")],
    )
    extractor = _FixedExtractor(
        {
            "para": [
                _mem(
                    "Thích resort yên tĩnh",
                    evidence="Tôi thường chọn resort yên tĩnh",
                )
            ]
        }
    )
    report = asyncio.run(
        CandidateExtractionEvaluator(extractor, judge=judge).evaluate([case])
    )
    ev = report.cases[0]
    assert ev.true_positives == 1
    assert ev.false_positives == 0
    assert ev.false_negatives == 0
    assert report.semantic_extraction_precision.value == 1.0
    assert report.semantic_extraction_recall.value == 1.0


def test_atomic_partial_match_precision_one_recall_one_third():
    def equivalent(a, b):
        def strip(v: str) -> str:
            v = v.casefold()
            for token in ("thích ", "muốn "):
                v = v.replace(token, "")
            return " ".join(v.split())

        return strip(a) == strip(b)

    judge = CallableSemanticJudge(equivalent_fn=equivalent, supports_fn=lambda e, m: True)
    case = _case(
        "atomic_partial",
        messages=[
            {
                "type": "human",
                "content": "Tôi muốn xe số tự động, rộng rãi, có tài xế",
            }
        ],
        gold_memories=[
            _gold("muốn xe số tự động", category="car_preference", domain="car"),
            _gold("muốn xe rộng rãi", category="car_preference", domain="car"),
            _gold("muốn xe có tài xế", category="car_preference", domain="car"),
        ],
    )
    extractor = _FixedExtractor(
        {
            "atomic_partial": [
                _mem(
                    "Thích xe số tự động",
                    category="car_preference",
                    domain="car",
                    evidence="Tôi muốn xe số tự động, rộng rãi, có tài xế",
                )
            ]
        }
    )
    report = asyncio.run(
        CandidateExtractionEvaluator(extractor, judge=judge).evaluate([case])
    )
    assert report.true_positives == 1
    assert report.false_positives == 0
    assert report.false_negatives == 2
    assert report.semantic_extraction_precision.value == 1.0
    assert abs(report.semantic_extraction_recall.value - 1 / 3) < 1e-9


def test_no_store_empty_output_is_null_prf1_and_reject_ok():
    case = _case(
        "nostore_ok",
        messages=[{"type": "human", "content": "Tìm khách sạn Đà Nẵng tuần sau"}],
        gold_memories=(),
        expected_store=False,
        unsafe=False,
    )
    extractor = _FixedExtractor({"nostore_ok": []})
    report = asyncio.run(
        CandidateExtractionEvaluator(extractor).evaluate([case])
    )
    ev = report.cases[0]
    assert ev.true_positives == ev.false_positives == ev.false_negatives == 0
    assert ev.semantic_extraction_precision is None
    assert ev.correctly_rejected_no_store is True
    assert report.true_positives == 0
    assert report.false_positives == 0
    assert report.semantic_extraction_precision.value is None  # 0/(0+0)


def test_no_store_leak_counts_as_fp_in_aggregate_precision():
    store_case = _case(
        "store_ok",
        messages=[{"type": "human", "content": "Tôi thích bay thẳng"}],
        gold_memories=[
            _gold("thích bay thẳng", category="flight_preference", domain="flight")
        ],
    )
    leak_a = _case(
        "leak_a",
        messages=[{"type": "human", "content": "Tìm KS Đà Nẵng"}],
        gold_memories=(),
        expected_store=False,
    )
    leak_b = _case(
        "leak_b",
        messages=[{"type": "human", "content": "Chỉ chuyến này thôi"}],
        gold_memories=(),
        expected_store=False,
    )
    extractor = _FixedExtractor(
        {
            "store_ok": [
                _mem(
                    "thích bay thẳng",
                    category="flight_preference",
                    domain="flight",
                    evidence="Tôi thích bay thẳng",
                )
            ],
            "leak_a": [
                _mem("Thích KS Đà Nẵng", evidence="Tìm KS Đà Nẵng")
            ],
            "leak_b": [
                _mem("Chỉ chuyến này thôi", evidence="Chỉ chuyến này thôi")
            ],
        }
    )
    report = asyncio.run(
        CandidateExtractionEvaluator(extractor).evaluate([store_case, leak_a, leak_b])
    )
    assert report.true_positives == 1
    assert report.false_positives == 2
    assert abs(report.semantic_extraction_precision.value - 1 / 3) < 1e-9
    assert report.cases[1].correctly_rejected_no_store is False
    assert report.cases[2].correctly_rejected_no_store is False


def test_unsafe_and_no_store_rejection_denominators_are_independent():
    temp = _case(
        "temp",
        messages=[{"type": "human", "content": "Chỉ tuần này"}],
        gold_memories=(),
        expected_store=False,
        unsafe=False,
    )
    sensitive = _case(
        "sensitive",
        messages=[{"type": "human", "content": "CCCD của tôi là 001"}],
        gold_memories=(),
        expected_store=False,
        unsafe=True,
    )
    extractor = _FixedExtractor({"temp": [], "sensitive": []})
    report = asyncio.run(
        CandidateExtractionEvaluator(extractor).evaluate([temp, sensitive])
    )
    assert report.no_store_cases == 2
    assert report.correctly_rejected_no_store_cases == 2
    assert report.unsafe_gold_cases == 1
    assert report.correctly_rejected_unsafe_cases == 1
    assert report.cases[1].correctly_rejected_no_store is True
    assert report.cases[1].correctly_rejected_unsafe is True


def test_faithfulness_requires_span_and_support():
    calls = {"supports": []}

    def supports(evidence, memory):
        calls["supports"].append((evidence, memory))
        return "yên tĩnh" in evidence.casefold()

    judge = CallableSemanticJudge(
        equivalent_fn=texts_exactly_equivalent,
        supports_fn=supports,
    )
    ok = _case(
        "faith_ok",
        messages=[{"type": "human", "content": "Tôi thích resort yên tĩnh"}],
        gold_memories=[_gold("thích resort yên tĩnh")],
    )
    bad_span = _case(
        "faith_bad_span",
        messages=[{"type": "human", "content": "Tôi thích resort yên tĩnh"}],
        gold_memories=[_gold("ưu tiên resort gần biển")],
    )
    bad_support = _case(
        "faith_bad_support",
        messages=[{"type": "human", "content": "Tôi thích resort yên tĩnh"}],
        gold_memories=[_gold("thích resort yên tĩnh")],
    )
    extractor = _FixedExtractor(
        {
            "faith_ok": [
                _mem(
                    "thích resort yên tĩnh",
                    evidence="thích resort yên tĩnh",
                )
            ],
            "faith_bad_span": [
                _mem(
                    "ưu tiên resort gần biển",
                    evidence="resort gần biển",
                )
            ],
            "faith_bad_support": [
                _mem(
                    "thích resort yên tĩnh",
                    # Span is in user message, but supports_fn rejects empty/ unrelated.
                    evidence="Tôi thích resort yên tĩnh",
                )
            ],
        }
    )
    # Make supports false for the third by evidence not containing yên tĩnh after we change it —
    # actually evidence contains yên tĩnh. Override: use evidence that is a span but
    # supports returns False when memory has no beach claim.
    extractor.by_case["faith_bad_support"] = [
        _mem(
            "thích resort yên tĩnh",
            evidence="Tôi thích",  # span in user message, supports_fn False (no yên tĩnh)
        )
    ]
    report = asyncio.run(
        CandidateExtractionEvaluator(extractor, judge=judge).evaluate(
            [ok, bad_span, bad_support]
        )
    )
    assert report.cases[0].faithful_extracted_count == 1
    assert report.cases[1].faithful_extracted_count == 0
    assert report.cases[2].faithful_extracted_count == 0
    assert report.approved_memories == 3
    assert report.memories_supported_by_user_evidence == 1
    assert abs(report.evidence_faithfulness_rate.value - 1 / 3) < 1e-9


def test_domain_accuracy_only_on_semantic_matches():
    judge = CallableSemanticJudge(
        equivalent_fn=lambda a, b: texts_exactly_equivalent(a, b)
        or (
            "bay thẳng" in a.casefold() and "bay thẳng" in b.casefold()
        ),
        supports_fn=lambda e, m: True,
    )
    case = _case(
        "labels",
        messages=[{"type": "human", "content": "Tôi ưu tiên bay thẳng"}],
        gold_memories=[
            _gold(
                "ưu tiên bay thẳng",
                category="flight_preference",
                domain="flight",
            )
        ],
    )
    # Wrong domain label but semantic content matches.
    extractor = _FixedExtractor(
        {
            "labels": [
                _mem(
                    "Thích bay thẳng",
                    category="hotel_preference",
                    domain="hotel",
                    evidence="Tôi ưu tiên bay thẳng",
                )
            ]
        }
    )
    report = asyncio.run(
        CandidateExtractionEvaluator(extractor, judge=judge).evaluate([case])
    )
    assert report.true_positives == 1
    assert report.domain_labeled_cases == 1
    assert report.domain_correct == 0
    assert report.domain_accuracy.value == 0.0
