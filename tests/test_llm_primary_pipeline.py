from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from mosaic.m3_models import load_m3_experiment_config
from mosaic.m3_pipeline import (
    _apply_primary_fusion_decision,
    _apply_primary_linkage_decision,
    _apply_primary_schema_decision,
    batch_decisions_by_case,
    run_assisted_pipeline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_batch_decision_validation_rejects_duplicate_case_ids() -> None:
    with pytest.raises(ValueError, match="duplicate case_id"):
        batch_decisions_by_case(
            {"decisions": [{"case_id": "a"}, {"case_id": "a"}]},
            ["a"],
        )


def test_batch_decision_validation_rejects_unknown_case_ids() -> None:
    with pytest.raises(ValueError, match="unknown case_id"):
        batch_decisions_by_case(
            {"decisions": [{"case_id": "b"}]},
            ["a"],
        )


def test_batch_decision_validation_rejects_missing_case_ids() -> None:
    with pytest.raises(ValueError, match="missing case_id"):
        batch_decisions_by_case(
            {"decisions": [{"case_id": "a"}]},
            ["a", "b"],
        )


def test_primary_schema_failure_defaults_to_unmapped() -> None:
    output, reason = _apply_primary_schema_decision(
        {
            "source_attribute_id": "source//brandish",
            "source_id": "source",
            "attribute_name": "brandish",
            "target_attribute_name": "brand",
            "decision": "accepted",
            "score_total": 0.9,
            "score_margin": 0.4,
            "method": "deterministic",
        },
        {
            "case_id": "source//brandish",
            "target_attribute": "brand",
            "confidence": 0.1,
            "abstain": False,
        },
        {"brand"},
        0.7,
    )

    assert reason == "low_confidence"
    assert output["target_attribute_name"] == "UNMAPPED"
    assert output["decision"] == "unmapped"
    assert output["method"].startswith("llm_primary_default_schema_v1")


def test_primary_linkage_failure_defaults_to_non_match() -> None:
    output, reason = _apply_primary_linkage_decision(
        {
            "candidate_pair_id": "p1",
            "left_record_uid": "a",
            "right_record_uid": "b",
            "split": "test",
            "ground_truth_label": 1,
            "match_probability": 0.95,
            "match_prediction": 1,
            "threshold": 0.5,
            "rule_score": 1.0,
            "rule_prediction": 1,
            "model_status": "deterministic",
        },
        {"case_id": "p1", "decision": "match", "confidence": 0.1, "abstain": False},
        0.72,
    )

    assert reason == "low_confidence"
    assert output["match_prediction"] == 0
    assert output["model_status"].startswith("llm_primary_default_non_match_v1")


def test_primary_fusion_unsupported_value_defaults_to_abstained_missing() -> None:
    output, reason = _apply_primary_fusion_decision(
        {
            "fused_value_id": "f1",
            "entity_id": "e1",
            "mediated_attribute_name": "brand",
            "selected_value": "Acer",
            "selected_unit": None,
            "fusion_method": "deterministic",
            "confidence": 1.0,
            "supporting_claim_ids": "[\"c1\"]",
            "contradicting_claim_ids": "[]",
            "alternative_values": "[]",
            "llm_used": False,
            "abstained": False,
        },
        {
            "case_id": "e1|brand",
            "selected_value": "invented",
            "supporting_claim_ids": ["c1"],
            "contradicting_claim_ids": [],
            "confidence": 0.9,
            "abstain": False,
        },
        ["Acer", "ABSTAIN"],
        [{"claim_id": "c1", "normalized_value": "Acer", "unit": None}],
        0.7,
    )

    assert reason == "unsupported_value"
    assert output["selected_value"] == ""
    assert output["abstained"] is True
    assert output["fusion_method"].startswith("llm_primary_default_abstain_v1")


def test_fixture_primary_pipeline_writes_artifacts_and_counts_primary_defaults() -> None:
    config = load_m3_experiment_config(
        REPO_ROOT / "configs/experiments/m4_c_llm_primary_fixture.json"
    )

    result = run_assisted_pipeline(config, REPO_ROOT)

    manifest = json.loads(Path(result.artifacts["run_manifest"]).read_text(encoding="utf-8"))
    assert manifest["decision_mode"] == "primary"
    assert manifest["primary_defaults"]["linkage"] == "non_match"

    predictions = pl.read_parquet(result.artifacts["assisted_pair_predictions"])
    assert predictions.height > 0
    assert predictions["model_status"].str.contains("llm_primary").any()

    linkage_quality = json.loads(
        Path(result.artifacts["linkage_quality_cost"]).read_text(encoding="utf-8")
    )
    assert linkage_quality["eligible_count"] >= linkage_quality["selected_count"]
    assert "defaulted_count" in linkage_quality
    assert "unselected_default_count" in linkage_quality

    call_logs = list((REPO_ROOT / "artifacts/llm_calls" / result.run_id).glob("*_calls.jsonl"))
    assert call_logs
    for log_path in call_logs:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)["request_payload"]
            assert "ground_truth_label" not in json.dumps(payload)
