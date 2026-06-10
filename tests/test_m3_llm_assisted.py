from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from mosaic.cli import app
from mosaic.llm_gateway import LLMGateway, LLMProviderError, canonical_input_hash, render_prompt
from mosaic.m3_models import (
    FusionLLMDecision,
    LLMCallResult,
    LLMModelConfig,
    M3ExperimentConfig,
    SchemaLLMDecision,
    load_m3_experiment_config,
)
from mosaic.m3_pipeline import (
    LLMBudgetTracker,
    _apply_fusion_decision,
    _finish_assisted_result,
    _quality_cost_table,
    run_assisted_pipeline,
)
from pydantic import BaseModel
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_prompt_rendering_hashing_and_fake_provider_are_deterministic() -> None:
    config = LLMModelConfig(provider="fake", execution_mode="fake")
    payload_a = {"b": 2, "a": {"z": 1}}
    payload_b = {"a": {"z": 1}, "b": 2}

    assert render_prompt("payload={{payload_json}}", {"payload_json": payload_a}).startswith(
        "payload={"
    )
    assert (
        canonical_input_hash(
            stage="schema",
            prompt_version="prompts/schema/v20260610_m3_assisted",
            model_config=config,
            payload=payload_a,
        )
        == canonical_input_hash(
            stage="schema",
            prompt_version="prompts/schema/v20260610_m3_assisted",
            model_config=config,
            payload=payload_b,
        )
    )

    gateway = LLMGateway(config, REPO_ROOT, "run_test_m3")
    result = gateway.call_structured(
        stage="schema",
        prompt_version="prompts/schema/v20260610_m3_assisted",
        template_path=REPO_ROOT / "prompts/schema/v20260610_m3_assisted/template.md",
        payload={
            "attribute_name": "maker",
            "deterministic_candidates": [
                {"target_attribute_name": "brand", "score_total": 0.82}
            ],
        },
        output_model=SchemaLLMDecision,
        schema_name="mosaic_schema_decision",
    )

    assert result.validation_status == "valid"
    assert result.parsed_response is not None
    assert result.parsed_response["target_attribute"] == "brand"


def test_gateway_records_invalid_json_as_validation_failure(tmp_path: Path) -> None:
    class TinyOutput(BaseModel):
        value: str

    cache_path = tmp_path / "cache/schema/bad.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("not-json", encoding="utf-8")
    config = LLMModelConfig(
        provider="fake",
        execution_mode="fake",
        cache_mode="read",
        cache_root=str(tmp_path / "cache"),
        call_log_root=str(tmp_path / "calls"),
    )
    gateway = LLMGateway(config, REPO_ROOT, "run_invalid_json")
    payload = {"case": "bad"}
    input_hash = canonical_input_hash(
        stage="schema",
        prompt_version="p",
        model_config=config,
        payload=payload,
    )
    expected_path = tmp_path / "cache/schema" / f"{input_hash}.json"
    expected_path.write_text("not-json", encoding="utf-8")

    result = gateway.call_structured(
        stage="schema",
        prompt_version="p",
        template_path=REPO_ROOT / "prompts/schema/v20260610_m3_assisted/template.md",
        payload=payload,
        output_model=TinyOutput,
        schema_name="tiny",
    )

    assert result.validation_status == "invalid"
    assert result.failure_type == "invalid_json"
    assert result.cache_status == "hit"


def test_gateway_records_provider_errors_and_retry_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TinyOutput(BaseModel):
        value: str

    config = LLMModelConfig(
        provider="openai",
        execution_mode="live",
        model="test-model",
        cache_mode="off",
        call_log_root=str(tmp_path / "calls"),
    )
    gateway = LLMGateway(config, REPO_ROOT, "run_timeout")

    def fail_provider(**_: object) -> object:
        raise LLMProviderError(
            failure_type="timeout",
            validation_status="timeout",
            retry_count=2,
            message="timed out",
        )

    monkeypatch.setattr(gateway, "_invoke_provider", fail_provider)
    result = gateway.call_structured(
        stage="schema",
        prompt_version="p",
        template_path=REPO_ROOT / "prompts/schema/v20260610_m3_assisted/template.md",
        payload={"case": "timeout"},
        output_model=TinyOutput,
        schema_name="tiny",
    )

    assert result.validation_status == "timeout"
    assert result.failure_type == "timeout"
    assert result.retry_count == 2
    assert (tmp_path / "calls/run_timeout/schema_calls.jsonl").exists()


def test_gateway_missing_api_key_is_logged_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TinyOutput(BaseModel):
        value: str

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = LLMModelConfig(
        provider="openai",
        execution_mode="live",
        model="test-model",
        cache_mode="off",
        call_log_root=str(tmp_path / "calls"),
    )

    result = LLMGateway(config, REPO_ROOT, "run_missing_key").call_structured(
        stage="schema",
        prompt_version="p",
        template_path=REPO_ROOT / "prompts/schema/v20260610_m3_assisted/template.md",
        payload={"case": "missing_key"},
        output_model=TinyOutput,
        schema_name="tiny",
    )

    assert result.validation_status == "error"
    assert result.failure_type == "missing_api_key"


def test_budget_tracker_enforces_call_cost_and_daily_budgets(tmp_path: Path) -> None:
    model = LLMModelConfig(
        provider="fake",
        execution_mode="fake",
        call_log_root="calls",
        pricing={"input_usd_per_1m_tokens": 1000, "output_usd_per_1m_tokens": 1000},
    )
    gateway = LLMGateway(model, tmp_path, "run_budget")
    config = M3ExperimentConfig.model_validate(
        {
            "experiment_id": "budget",
            "routing": {
                "per_run_call_budget": 1,
                "per_run_cost_budget_usd": 0.01,
                "daily_call_budget": None,
                "daily_cost_budget_usd": None,
                "max_cases_per_stage": 2,
            },
        }
    )
    tracker = LLMBudgetTracker(config, gateway, tmp_path)

    assert tracker.skip_reason("schema", 0.001) is None
    tracker.record(
        "schema",
        LLMCallResult(
            request_id="r",
            stage="schema",
            prompt_version="p",
            input_hash="h",
            raw_response="{}",
            parsed_response={},
            validation_status="valid",
            estimated_cost_usd=0.001,
        ),
    )
    assert tracker.skip_reason("schema", 0.001) == "per_run_call_budget"

    cost_limited = M3ExperimentConfig.model_validate(
        {"experiment_id": "budget", "routing": {"per_run_cost_budget_usd": 0.001}}
    )
    assert LLMBudgetTracker(cost_limited, gateway, tmp_path).skip_reason(
        "schema", 0.002
    ) == "per_run_cost_budget"

    log_dir = tmp_path / "calls/run_prior"
    log_dir.mkdir(parents=True)
    log_dir.joinpath("schema_calls.jsonl").write_text(
        json.dumps(
            {
                "created_at": datetime.now(UTC).isoformat(),
                "estimated_cost_usd": 0.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    daily_limited = M3ExperimentConfig.model_validate(
        {"experiment_id": "budget", "routing": {"daily_call_budget": 1}}
    )
    assert LLMBudgetTracker(daily_limited, gateway, tmp_path).skip_reason(
        "schema", 0.0
    ) == "daily_call_budget"


def test_fusion_validation_rejects_unsupported_values_unknown_claims_and_units() -> None:
    deterministic = {
        "selected_value": "24",
        "selected_unit": "inch",
        "supporting_claim_ids": json.dumps(["c1"]),
        "contradicting_claim_ids": json.dumps(["c2"]),
        "llm_used": False,
        "abstained": False,
    }
    unsupported = FusionLLMDecision(
        selected_value="27",
        confidence=0.9,
        supporting_claim_ids=["c1"],
        contradicting_claim_ids=[],
        reason="unsupported",
        abstain=False,
    )
    unknown_id = FusionLLMDecision(
        selected_value="24",
        confidence=0.9,
        supporting_claim_ids=["missing"],
        contradicting_claim_ids=[],
        reason="unknown",
        abstain=False,
    )
    result_base = {
        "request_id": "r",
        "stage": "fusion",
        "prompt_version": "p",
        "input_hash": "h",
        "raw_response": "{}",
        "validation_status": "valid",
    }

    _, reason = _apply_fusion_decision(
        deterministic,
        LLMCallResult(**result_base, parsed_response=unsupported.model_dump()),
        ["24", "ABSTAIN"],
        [
            {"claim_id": "c1", "normalized_value": "24", "unit": "inch"},
            {"claim_id": "c2", "normalized_value": "25", "unit": "inch"},
        ],
        0.7,
    )
    assert reason == "unsupported_value"

    _, reason = _apply_fusion_decision(
        deterministic,
        LLMCallResult(**result_base, parsed_response=unknown_id.model_dump()),
        ["24", "ABSTAIN"],
        [
            {"claim_id": "c1", "normalized_value": "24", "unit": "inch"},
            {"claim_id": "c2", "normalized_value": "25", "unit": "inch"},
        ],
        0.7,
    )
    assert reason == "unknown_claim_id"

    incompatible_unit = FusionLLMDecision(
        selected_value="24",
        confidence=0.9,
        supporting_claim_ids=["c1"],
        contradicting_claim_ids=[],
        reason="wrong unit",
        abstain=False,
    )
    _, reason = _apply_fusion_decision(
        deterministic,
        LLMCallResult(**result_base, parsed_response=incompatible_unit.model_dump()),
        ["24", "ABSTAIN"],
        [{"claim_id": "c1", "normalized_value": "24", "unit": "cm"}],
        0.7,
    )
    assert reason == "incompatible_unit"


def test_quality_cost_output_contains_frontier_points() -> None:
    payload = _quality_cost_table(
        [
            {
                "selected": True,
                "cache_status": "miss",
                "validation_status": "valid",
                "fallback_applied": False,
                "accepted": True,
                "input_tokens": 10,
                "output_tokens": 5,
                "estimated_cost_usd": 0.01,
                "assisted_correct": 1,
            },
            {
                "selected": True,
                "cache_status": "hit",
                "validation_status": "invalid",
                "fallback_applied": True,
                "fallback_reason": "invalid_json",
                "accepted": False,
                "input_tokens": 3,
                "output_tokens": 1,
                "estimated_cost_usd": 0.0,
            },
        ],
        M3ExperimentConfig(),
    )

    assert payload["frontier"][0]["call_budget"] == 0
    assert payload["frontier"][-1]["selected_count"] == 2
    assert payload["frontier"][-1]["fallback_count"] == 1


def test_fixture_assisted_pipeline_writes_m3_artifacts_and_omits_prompt_truth() -> None:
    config = load_m3_experiment_config(
        REPO_ROOT / "configs/experiments/m3_llm_assisted_example.json"
    )

    result = run_assisted_pipeline(config, REPO_ROOT)

    expected_artifacts = {
        "assisted_schema_mappings",
        "schema_routing_manifest",
        "schema_quality_cost",
        "assisted_pair_predictions",
        "assisted_pair_decisions",
        "linkage_routing_manifest",
        "linkage_quality_cost",
        "assisted_fused_values",
        "assisted_integrated_entities",
        "assisted_integrated_entities_jsonl",
        "fusion_routing_manifest",
        "fusion_quality_cost",
        "run_manifest",
    }
    assert expected_artifacts <= set(result.artifacts)
    assert all(Path(path).exists() for path in result.artifacts.values())

    manifest = json.loads(Path(result.artifacts["run_manifest"]).read_text(encoding="utf-8"))
    assert manifest["llm_decisions"] is True
    assert manifest["prompt_versions"]["schema"] == "prompts/schema/v20260610_m3_assisted"
    assert manifest["model_config"]["execution_mode"] == "fake"
    assert manifest["llm_call_logs"] == f"artifacts/llm_calls/{result.run_id}"

    predictions = pl.read_parquet(result.artifacts["assisted_pair_predictions"])
    assert predictions.height > 0

    call_logs = list((REPO_ROOT / "artifacts/llm_calls" / result.run_id).glob("*_calls.jsonl"))
    assert call_logs
    for log_path in call_logs:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)["request_payload"]
            assert "ground_truth_label" not in json.dumps(payload)


def test_manifest_respects_custom_call_log_root(tmp_path: Path) -> None:
    result = _finish_assisted_result(
        config=M3ExperimentConfig(),
        model_config={"call_log_root": "custom/calls"},
        run_id="run_custom",
        run_dir=tmp_path / "artifacts/runs/run_custom",
        completed_stage="export",
        artifacts={},
        metrics={},
        repo_root=tmp_path,
    )

    manifest = json.loads(Path(result.artifacts["run_manifest"]).read_text(encoding="utf-8"))
    assert manifest["llm_call_logs"] == "custom/calls/run_custom"


def test_live_smoke_skips_without_live_configuration() -> None:
    result = runner.invoke(
        app,
        ["experiment", "live-smoke", "configs/experiments/m3_llm_assisted_example.json"],
    )

    assert result.exit_code == 0
    assert "live smoke skipped" in result.output
