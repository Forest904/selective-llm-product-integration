from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mosaic.cli import app
from mosaic.m4_release import (
    _export_error_cases,
    _load_root_env,
    _validate_report_manifest,
    aggregate_operational_metrics,
    build_m4_report,
    confusion_matrix,
)
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_confusion_matrix_extracts_test_split_counts() -> None:
    metrics = {
        "metrics_by_split": {
            "test": {
                "true_positive": 5,
                "false_positive": 2,
                "true_negative": 7,
                "false_negative": 1,
            }
        }
    }

    assert confusion_matrix(metrics) == {
        "true_positive": 5,
        "false_positive": 2,
        "true_negative": 7,
        "false_negative": 1,
    }


def test_operational_metrics_sum_counts_cost_and_weighted_latency() -> None:
    payload = aggregate_operational_metrics(
        [
            {
                "eligible_count": 10,
                "selected_count": 2,
                "llm_call_count": 2,
                "cache_hit_count": 1,
                "invalid_output_count": 1,
                "abstention_count": 0,
                "fallback_count": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "estimated_cost_usd": 0.02,
                "average_latency_ms": 100,
            },
            {
                "eligible_count": 5,
                "selected_count": 1,
                "llm_call_count": 1,
                "cache_hit_count": 0,
                "invalid_output_count": 0,
                "abstention_count": 1,
                "fallback_count": 1,
                "input_tokens": 40,
                "output_tokens": 8,
                "estimated_cost_usd": 0.01,
                "average_latency_ms": 400,
            },
        ]
    )

    assert payload["eligible_count"] == 15
    assert payload["llm_call_count"] == 3
    assert payload["estimated_cost_usd"] == 0.03
    assert payload["average_latency_ms"] == 200


def test_fixture_report_builder_writes_release_bundle(tmp_path: Path) -> None:
    manifest_path = tmp_path / "fixture_release_manifest.json"

    outputs = build_m4_report(
        REPO_ROOT,
        manifest_path=manifest_path,
        fixture=True,
        build_pdf=False,
    )

    assert outputs["manifest"] == manifest_path
    assert outputs["report_md"] is not None and outputs["report_md"].exists()
    assert outputs["release_manifest"] is not None and outputs["release_manifest"].exists()
    assert outputs["final_dataset"] is not None and outputs["final_dataset"].exists()

    error_cases = json.loads((REPO_ROOT / "reports/appendix/m4_error_cases.json").read_text())
    assert len(error_cases) >= 3
    assert "fusion" in {case["stage"] for case in error_cases}
    assert all(case["case_id"] for case in error_cases)


def test_root_env_loader_sets_missing_values_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.joinpath(".env").write_text(
        "OPENAI_API_KEY=from-file\nEXISTING=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING", "from-shell")

    loaded = _load_root_env(tmp_path)

    assert loaded == {"OPENAI_API_KEY"}
    assert os.environ["OPENAI_API_KEY"] == "from-file"
    assert os.environ["EXISTING"] == "from-shell"


def test_submission_report_refuses_fixture_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "fixture_release_manifest.json"
    build_m4_report(REPO_ROOT, manifest_path=manifest_path, fixture=True, build_pdf=False)

    with pytest.raises(RuntimeError, match="requires a subset live M4 manifest"):
        build_m4_report(REPO_ROOT, manifest_path=manifest_path, build_pdf=False)


def test_subset_live_manifest_shape_is_accepted() -> None:
    manifest = {
        "mode": "subset_live",
        "reported_live_assisted": True,
        "subset": {"subset_id": "alaska_monitor_live_subset_60"},
        "runs": [
            {"configuration_id": config}
            for config in [
                "A0",
                "C-LLM",
                "B-All",
                "B-S",
                "B-L",
                "B-F",
                "B-SL",
                "B-LF",
                "Budget-0",
                "Budget-5",
                "Budget-10",
                "Budget-25",
            ]
        ],
    }

    _validate_report_manifest(manifest, fixture=False)


def test_default_report_requires_deterministic_scale_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "subset_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "mode": "subset_live",
                "reported_live_assisted": True,
                "subset": {"subset_id": "alaska_monitor_live_subset_60"},
                "runs": [{"configuration_id": config} for config in [
                    "A0",
                    "C-LLM",
                    "B-All",
                    "B-S",
                    "B-L",
                    "B-F",
                    "B-SL",
                    "B-LF",
                    "Budget-0",
                    "Budget-5",
                    "Budget-10",
                    "Budget-25",
                ]],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="deterministic scale manifest not found"):
        build_m4_report(
            REPO_ROOT,
            manifest_path=manifest_path,
            scale_manifest_path=tmp_path / "missing_scale.json",
            build_pdf=False,
        )


def test_submission_error_export_rejects_placeholder_shortfall(tmp_path: Path) -> None:
    manifest = {
        "runs": [
            {
                "configuration_id": "B-All",
                "run_id": "run_empty_full_live",
                "artifacts": {},
                "metrics": {},
            }
        ]
    }

    with pytest.raises(RuntimeError, match="at least three real source-level error cases"):
        _export_error_cases(REPO_ROOT, manifest, tmp_path / "appendix", fixture=False)


def test_full_release_requires_live_flag_or_fixture_mode() -> None:
    result = runner.invoke(app, ["experiment", "release"])

    assert result.exit_code == 1
    assert "requires --live" in result.output
