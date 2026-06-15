from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mosaic.cli import app
from mosaic.m4_release import (
    _export_error_cases,
    _load_root_env,
    _resume_id_for_configuration,
    _summarize_run,
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


def test_explicit_resume_run_id_only_applies_to_current_configuration() -> None:
    checkpoint = {"current_configuration": "C-LLM"}
    run_ids_by_config = {"A0": "run_a0"}

    assert (
        _resume_id_for_configuration(
            "C-LLM",
            explicit_resume_run_id="run_partial",
            run_ids_by_config=run_ids_by_config,
            checkpoint=checkpoint,
        )
        == "run_partial"
    )
    assert (
        _resume_id_for_configuration(
            "B-All",
            explicit_resume_run_id="run_partial",
            run_ids_by_config=run_ids_by_config,
            checkpoint=checkpoint,
        )
        is None
    )
    assert (
        _resume_id_for_configuration(
            "A0",
            explicit_resume_run_id="run_partial",
            run_ids_by_config=run_ids_by_config,
            checkpoint=checkpoint,
        )
        == "run_a0"
    )


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

    figure_names = [
        "component_quality",
        "configuration_quality_heatmap",
        "linkage_performance",
        "operational_dashboard",
        "routing_budget_frontier",
    ]
    for figure_name in figure_names:
        for suffix in (".png", ".pdf"):
            figure_path = REPO_ROOT / "reports/release/figures" / f"{figure_name}{suffix}"
            assert figure_path.exists()
            assert figure_path.stat().st_size > 0

    report_tex = (REPO_ROOT / "reports/report.tex").read_text(encoding="utf-8")
    report_md = (REPO_ROOT / "reports/report.md").read_text(encoding="utf-8")
    assert "Luca Foresti" in report_tex
    assert "Submission-ready benchmark report" not in report_tex
    assert "Mosaic Research Release" not in report_tex
    assert "Full subset-live metric matrix" not in report_tex
    assert "Linkage confusion matrix on the test split" not in report_tex
    assert "Operational decision counts and estimated live-model cost" not in report_tex
    assert "Routing-budget variants for the hybrid release" not in report_tex
    for figure_name in figure_names:
        assert f"figures/{figure_name}.pdf" in report_tex
        assert f"figures/{figure_name}.png" in report_md

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


def test_zero_denominator_fusion_accuracy_is_unavailable(tmp_path: Path) -> None:
    metrics_path = tmp_path / "fusion_metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "curated_fusion_metrics": {
                    "accuracy": None,
                    "evaluated_value_count": 0,
                    "correct_value_count": 0,
                    "gold_available": False,
                },
                "bootstrap_fusion_metrics": {
                    "accuracy": 1.0,
                    "evaluated_value_count": 1,
                    "correct_value_count": 1,
                    "gold_available": True,
                },
            }
        ),
        encoding="utf-8",
    )

    summary = _summarize_run(
        {
            "configuration_id": "A0",
            "run_id": "run_zero_fusion_denominator",
            "metrics": {"fusion_metrics": metrics_path.relative_to(tmp_path).as_posix()},
        },
        tmp_path,
    )

    assert summary["fusion_accuracy"] == ""
    assert summary["fusion_evaluated_values"] == 0
    assert summary["end_to_end_quality"] == 0.0


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


def test_submission_report_rejects_zero_evaluated_fusion_values(tmp_path: Path) -> None:
    metrics_path = tmp_path / "fusion_metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "curated_fusion_metrics": {
                    "accuracy": None,
                    "evaluated_value_count": 0,
                    "correct_value_count": 0,
                    "gold_available": False,
                }
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "subset_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "mode": "subset_live",
                "reported_live_assisted": True,
                "subset": {"subset_id": "alaska_monitor_live_subset_60"},
                "runs": [
                    {
                        "configuration_id": config,
                        "run_id": f"run_{config.lower().replace('-', '_')}",
                        "metrics": {
                            "fusion_metrics": metrics_path.relative_to(tmp_path).as_posix()
                        },
                    }
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
        ),
        encoding="utf-8",
    )
    scale_manifest_path = tmp_path / "scale_manifest.json"
    scale_manifest_path.write_text(
        json.dumps(
            {
                "mode": "deterministic_scale",
                "runs": [
                    {"configuration_id": "A0-camera"},
                    {"configuration_id": "A0-monitor"},
                    {"configuration_id": "A0-notebook"},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="no evaluated curated fusion values"):
        build_m4_report(
            tmp_path,
            manifest_path=manifest_path,
            scale_manifest_path=scale_manifest_path,
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
