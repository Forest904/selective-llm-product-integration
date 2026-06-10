from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from mosaic.cli import app
from mosaic.m2_models import MappingCandidate, load_baseline_pipeline_config
from mosaic.m2_pipeline import (
    _clusters_compatible,
    _exact_name_mapping_score,
    normalize_measurement,
    normalize_model_number,
    normalize_price,
    normalize_specification_key,
    run_baseline_pipeline,
)
from mosaic.schema_validation import validate_mediated_schema
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_monitor_schema_extends_core_mediated_attributes() -> None:
    schema = validate_mediated_schema(
        REPO_ROOT / "configs" / "schemas" / "monitor_mediated_schema.json"
    )
    names = {attribute.name for attribute in schema.attributes}

    assert {
        "title",
        "brand",
        "model_number",
        "category",
        "description",
        "price",
        "currency",
        "specifications",
    } <= names
    assert {"screen_size_diagonal", "supported_resolution", "has_hdmi_port"} <= names
    assert len(schema.attributes) >= 90


def test_m2_normalizers_preserve_canonical_identity() -> None:
    assert normalize_model_number("EOS-4000D") == "EOS4000D"
    assert normalize_model_number("EOS 4000D") == "EOS4000D"
    assert normalize_price("$310") == {"amount": "310.00", "currency": "USD"}
    assert normalize_measurement('24.3 MP', "sensor resolution") == {
        "value": "24.3",
        "unit": "MP",
        "method": "measurement_parse",
    }
    assert normalize_specification_key("Body Colour") == "body_colour"


def test_exact_detailed_schema_label_score_wins() -> None:
    row = {"attribute_name": "response time"}

    score = _exact_name_mapping_score(row, "response_time")

    assert score["target_attribute_name"] == "response_time"
    assert score["score_total"] == 1.0


def test_cluster_constraints_reject_unsafe_merges() -> None:
    config = load_baseline_pipeline_config(REPO_ROOT / "configs" / "pipelines" / "fixture_m2.json")
    records = {
        "a": {
            "source_id": "source_a",
            "brand": "Canon",
            "model_number": "EOS4000D",
            "screen_size_diagonal": "15",
        },
        "b": {
            "source_id": "source_a",
            "brand": "Canon",
            "model_number": "EOS4000D",
            "screen_size_diagonal": "15",
        },
        "c": {
            "source_id": "source_b",
            "brand": "Sony",
            "model_number": "A6000",
            "screen_size_diagonal": "15",
        },
        "d": {
            "source_id": "source_b",
            "brand": "Canon",
            "model_number": "EOS4000D",
            "screen_size_diagonal": "24",
        },
    }

    assert _clusters_compatible({"a"}, {"b"}, records, config) == (
        False,
        "same_source_duplicate",
    )
    assert _clusters_compatible({"a"}, {"c"}, records, config) == (False, "brand_conflict")
    assert _clusters_compatible({"a"}, {"d"}, records, config) == (
        False,
        "screen_size_conflict",
    )


def test_artifact_model_validation_rejects_bad_mapping_candidate() -> None:
    with pytest.raises(ValueError):
        MappingCandidate.model_validate({"source_attribute_id": "s//field"})


def test_fixture_baseline_pipeline_writes_required_artifacts() -> None:
    config = load_baseline_pipeline_config(REPO_ROOT / "configs" / "pipelines" / "fixture_m2.json")

    result = run_baseline_pipeline(config, REPO_ROOT)

    expected_artifacts = {
        "mapping_candidates",
        "accepted_schema_mappings",
        "normalized_records",
        "normalized_values",
        "candidate_pairs",
        "pair_features",
        "pair_predictions",
        "clusters",
        "cluster_memberships",
        "attribute_claims",
        "fused_values",
        "integrated_entities",
        "integrated_entities_jsonl",
        "baseline_error_candidates",
        "cluster_evidence_summary",
        "cluster_largest_clusters",
        "cluster_overmerge_errors",
        "cluster_undermerge_errors",
        "cluster_weak_bridge_merges",
        "fusion_curated_errors",
        "fusion_high_conflict_attributes",
        "fusion_unsupported_values",
        "m2_baseline_summary",
        "run_manifest",
        "schema_ambiguous_candidates",
        "schema_false_negatives",
        "schema_false_positives",
        "schema_unmapped_gold",
    }
    assert expected_artifacts <= set(result.artifacts)
    assert all(Path(path).exists() for path in result.artifacts.values())

    candidate_pairs = pl.read_parquet(result.artifacts["candidate_pairs"])
    assert candidate_pairs.height > 0
    assert (
        candidate_pairs.filter(pl.col("left_record_uid") == pl.col("right_record_uid")).height
        == 0
    )

    memberships = pl.read_parquet(result.artifacts["cluster_memberships"])
    active = memberships.filter(pl.col("cluster_method") == "constraint_agglomerative")
    assert active.select("record_uid").n_unique() == active.height

    claims = pl.read_parquet(result.artifacts["attribute_claims"])
    claim_record_uids = set(claims["record_uid"].to_list())
    membership_record_uids = set(active["record_uid"].to_list())
    assert claim_record_uids <= membership_record_uids

    fused = pl.read_parquet(result.artifacts["fused_values"])
    assert fused.height > 0
    assert all(json.loads(value) for value in fused["supporting_claim_ids"].to_list())

    schema_metrics = json.loads(Path(result.metrics["schema_metrics"]).read_text(encoding="utf-8"))
    assert "core_schema_metrics" in schema_metrics
    assert "monitor_detail_schema_metrics" in schema_metrics

    fusion_metrics = json.loads(Path(result.metrics["fusion_metrics"]).read_text(encoding="utf-8"))
    assert "bootstrap_fusion_metrics" in fusion_metrics
    assert "curated_fusion_metrics" in fusion_metrics


def test_m2_cli_stage_commands_run_on_fixture_config() -> None:
    result = runner.invoke(
        app,
        ["schema", "propose", "--config", "configs/pipelines/fixture_m2.json"],
    )

    assert result.exit_code == 0
    assert "wrote schema mapping artifacts" in result.output

    result = runner.invoke(
        app,
        ["pipeline", "run", "--config", "configs/pipelines/fixture_m2.json"],
    )

    assert result.exit_code == 0
    assert "baseline pipeline completed" in result.output
