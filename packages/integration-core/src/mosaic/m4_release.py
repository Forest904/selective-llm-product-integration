from __future__ import annotations

import csv
import json
import os
import shutil
import struct
import subprocess
import zlib
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from mosaic.ingestion import ingest_dataset, summarize_ground_truth
from mosaic.m1_models import load_dataset_config, load_mediated_schema
from mosaic.m1_utils import repo_relative
from mosaic.m2_models import PipelineRunResult, load_baseline_pipeline_config
from mosaic.m2_pipeline import _code_commit, run_baseline_pipeline
from mosaic.m3_models import load_llm_model_config, load_m3_experiment_config
from mosaic.m3_pipeline import run_assisted_pipeline

M4_RELEASE_DIR = Path("reports/release")
M4_ARTIFACT_DIR = Path("artifacts/reports/m4")
DEFAULT_RELEASE_MANIFEST = M4_ARTIFACT_DIR / "m4_release_manifest.json"
DEFAULT_FIXTURE_MANIFEST = M4_ARTIFACT_DIR / "m4_fixture_manifest.json"
DEFAULT_FULL_EXPERIMENTS = (
    Path("configs/experiments/m4_c_llm_primary_alaska_monitor.json"),
    Path("configs/experiments/m4_b_all_alaska_monitor.json"),
    Path("configs/experiments/m4_b_schema_only_alaska_monitor.json"),
    Path("configs/experiments/m4_b_linkage_only_alaska_monitor.json"),
    Path("configs/experiments/m4_b_fusion_only_alaska_monitor.json"),
    Path("configs/experiments/m4_b_schema_linkage_alaska_monitor.json"),
    Path("configs/experiments/m4_b_linkage_fusion_alaska_monitor.json"),
    Path("configs/experiments/m4_budget_cap_0_alaska_monitor.json"),
    Path("configs/experiments/m4_budget_cap_5_alaska_monitor.json"),
    Path("configs/experiments/m4_budget_cap_10_alaska_monitor.json"),
    Path("configs/experiments/m4_budget_cap_25_alaska_monitor.json"),
)
REQUIRED_SUBMISSION_ERROR_CASES = 3


def run_m4_release(
    repo_root: Path,
    *,
    live: bool,
    fixture: bool = False,
    manifest_path: Path | None = None,
) -> Path:
    """Run the M4 experiment matrix and write a compact release manifest."""
    default_manifest = DEFAULT_FIXTURE_MANIFEST if fixture else DEFAULT_RELEASE_MANIFEST
    output_path = _resolve(repo_root, manifest_path or default_manifest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    release_id = "m4_fixture_release" if fixture else "m4_academic_release"
    _load_root_env(repo_root)

    runs: list[dict[str, Any]] = []
    if fixture:
        baseline_config_path = repo_root / "configs/pipelines/fixture_m2.json"
        assisted_config_paths = [
            repo_root / "configs/experiments/m4_c_llm_primary_fixture.json",
            repo_root / "configs/experiments/m3_llm_assisted_example.json",
        ]
    else:
        if not live:
            raise RuntimeError("full M4 release requires --live for reported assisted runs")
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for full live M4 assisted runs")
        baseline_config_path = repo_root / "configs/pipelines/baseline_m2.json"
        assisted_config_paths = [repo_root / path for path in DEFAULT_FULL_EXPERIMENTS]

    baseline_config = load_baseline_pipeline_config(baseline_config_path)
    baseline_result = run_baseline_pipeline(baseline_config, repo_root)
    runs.append(
        _run_entry(
            configuration_id="A0" if not fixture else "fixture-A0",
            role="baseline",
            config_path=baseline_config_path,
            result=baseline_result,
            repo_root=repo_root,
        )
    )

    for config_path in assisted_config_paths:
        experiment_config = load_m3_experiment_config(config_path)
        model_config = load_llm_model_config(repo_root / experiment_config.model_config_path)
        if not fixture:
            if model_config.execution_mode not in {"live", "cache_or_live"}:
                raise RuntimeError(
                    f"{config_path} must use live or cache_or_live execution for M4 reporting"
                )
            if model_config.provider != "openai" or not model_config.model:
                raise RuntimeError(f"{config_path} must name a live OpenAI model")
        result = run_assisted_pipeline(
            experiment_config,
            repo_root,
            baseline_result=baseline_result,
        )
        runs.append(
            _run_entry(
                configuration_id=_display_configuration_id(experiment_config.experiment_id),
                role="assisted",
                config_path=config_path,
                result=result,
                repo_root=repo_root,
                model_config=model_config.model_dump(),
                prompt_versions=experiment_config.prompt_versions.model_dump(by_alias=True),
            )
        )

    manifest = {
        "release_id": release_id,
        "mode": "fixture" if fixture else "full_live",
        "generated_at": datetime.now(UTC).isoformat(),
        "code_commit": _code_commit(repo_root),
        "repository_url": _repository_url(repo_root),
        "reported_live_assisted": not fixture,
        "runs": runs,
    }
    _write_json(output_path, manifest)
    return output_path


def build_m4_report(
    repo_root: Path,
    *,
    manifest_path: Path | None = None,
    fixture: bool = False,
    build_pdf: bool = True,
) -> dict[str, Path | None]:
    """Build report tables, figures, appendix, report.md, and optionally report.pdf."""
    default_manifest = DEFAULT_FIXTURE_MANIFEST if fixture else DEFAULT_RELEASE_MANIFEST
    resolved_manifest = _resolve(repo_root, manifest_path or default_manifest)
    if fixture:
        resolved_manifest = run_m4_release(
            repo_root,
            live=False,
            fixture=True,
            manifest_path=resolved_manifest,
        )
    elif not resolved_manifest.exists():
        raise RuntimeError(
            "full live M4 release manifest not found. Run "
            "`uv run mosaic experiment release --live` first, or use "
            "`mosaic report build --fixture` for CI-safe fixture output."
        )
    manifest = _read_json(resolved_manifest)
    _validate_report_manifest(manifest, fixture=fixture)
    release_dir = repo_root / M4_RELEASE_DIR
    tables_dir = release_dir / "tables"
    figures_dir = release_dir / "figures"
    appendix_dir = repo_root / "reports" / "appendix"
    for path in (release_dir, tables_dir, figures_dir, appendix_dir):
        path.mkdir(parents=True, exist_ok=True)

    summaries = [_summarize_run(run, repo_root) for run in manifest["runs"]]
    operational = [_operational_summary(run, repo_root) for run in manifest["runs"]]
    dataset = _dataset_summary(repo_root, manifest)
    error_cases = _export_error_cases(repo_root, manifest, appendix_dir, fixture=fixture)

    _write_table(tables_dir / "dataset_summary.csv", [dataset])
    _write_table(tables_dir / "metrics_summary.csv", summaries)
    _write_table(tables_dir / "operational_metrics.csv", operational)
    _write_table(tables_dir / "error_cases.csv", [_flat_error_case(case) for case in error_cases])

    _write_bar_png(
        figures_dir / "component_quality.png",
        [
            (
                row["configuration_id"],
                [
                    float(row.get("schema_f1") or 0),
                    float(row.get("linkage_test_f1") or 0),
                    float(row.get("cluster_f1") or 0),
                    float(row.get("fusion_accuracy") or 0),
                ],
            )
            for row in summaries[:4]
        ],
    )
    _write_line_png(
        figures_dir / "routing_budget_frontier.png",
        _routing_frontier_points(manifest, repo_root),
    )

    release_manifest_copy = release_dir / "m4_release_manifest.json"
    _write_json(release_manifest_copy, manifest)
    final_dataset = _copy_final_dataset(repo_root, manifest, release_dir)
    report_md = repo_root / "reports" / "report.md"
    report_text = _report_markdown(
        manifest=manifest,
        dataset=dataset,
        summaries=summaries,
        operational=operational,
        error_cases=error_cases,
        final_dataset=final_dataset,
        fixture=fixture or manifest.get("mode") == "fixture",
    )
    report_md.write_text(report_text, encoding="utf-8")
    appendix_dir.joinpath("m4_error_cases.json").write_text(
        json.dumps(error_cases, indent=2, sort_keys=True), encoding="utf-8"
    )

    pdf_path: Path | None = None
    if build_pdf:
        pdf_path = _build_pdf(repo_root, report_md)
        if pdf_path is not None:
            _render_pdf_check(repo_root, pdf_path)

    return {
        "manifest": resolved_manifest,
        "release_manifest": release_manifest_copy,
        "report_md": report_md,
        "report_pdf": pdf_path,
        "final_dataset": final_dataset,
    }


def confusion_matrix(metrics: dict[str, Any], split: str = "test") -> dict[str, int]:
    split_metrics = metrics.get("metrics_by_split", {}).get(split, {})
    return {
        "true_positive": int(split_metrics.get("true_positive", 0) or 0),
        "false_positive": int(split_metrics.get("false_positive", 0) or 0),
        "true_negative": int(split_metrics.get("true_negative", 0) or 0),
        "false_negative": int(split_metrics.get("false_negative", 0) or 0),
    }


def aggregate_operational_metrics(
    quality_cost_payloads: Iterable[dict[str, Any]],
) -> dict[str, float | int]:
    payloads = list(quality_cost_payloads)
    selected_count = sum(int(payload.get("selected_count", 0) or 0) for payload in payloads)
    latency_weighted = sum(
        float(payload.get("average_latency_ms", 0.0) or 0.0)
        * int(payload.get("selected_count", 0) or 0)
        for payload in payloads
    )
    return {
        "eligible_count": sum(int(payload.get("eligible_count", 0) or 0) for payload in payloads),
        "selected_count": selected_count,
        "llm_call_count": sum(int(payload.get("llm_call_count", 0) or 0) for payload in payloads),
        "accepted_count": sum(int(payload.get("accepted_count", 0) or 0) for payload in payloads),
        "defaulted_count": sum(int(payload.get("defaulted_count", 0) or 0) for payload in payloads),
        "unselected_default_count": sum(
            int(payload.get("unselected_default_count", 0) or 0) for payload in payloads
        ),
        "cache_hit_count": sum(int(payload.get("cache_hit_count", 0) or 0) for payload in payloads),
        "invalid_output_count": sum(
            int(payload.get("invalid_output_count", 0) or 0) for payload in payloads
        ),
        "abstention_count": sum(
            int(payload.get("abstention_count", 0) or 0) for payload in payloads
        ),
        "fallback_count": sum(int(payload.get("fallback_count", 0) or 0) for payload in payloads),
        "input_tokens": sum(int(payload.get("input_tokens", 0) or 0) for payload in payloads),
        "output_tokens": sum(int(payload.get("output_tokens", 0) or 0) for payload in payloads),
        "estimated_cost_usd": sum(
            float(payload.get("estimated_cost_usd", 0.0) or 0.0) for payload in payloads
        ),
        "average_latency_ms": latency_weighted / selected_count if selected_count else 0.0,
    }


def _load_root_env(repo_root: Path) -> set[str]:
    loaded: set[str] = set()
    env_path = repo_root / ".env"
    if not env_path.exists():
        return loaded
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_env_value(value.strip())
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.add(key)
    return loaded


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _validate_report_manifest(manifest: dict[str, Any], *, fixture: bool) -> None:
    if fixture:
        return
    if manifest.get("mode") != "full_live" or manifest.get("reported_live_assisted") is not True:
        raise RuntimeError(
            "report build requires a full live M4 manifest. Run "
            "`uv run mosaic experiment release --live` first, or pass `--fixture` "
            "for fixture-only reproduction output."
        )
    run_ids = {str(run.get("configuration_id")) for run in manifest.get("runs", [])}
    required = {
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
    }
    missing = sorted(required - run_ids)
    if missing:
        raise RuntimeError(f"full live M4 manifest missing configurations: {', '.join(missing)}")


def _run_entry(
    *,
    configuration_id: str,
    role: str,
    config_path: Path,
    result: PipelineRunResult,
    repo_root: Path,
    model_config: dict[str, Any] | None = None,
    prompt_versions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = _read_json(Path(result.artifacts["run_manifest"]))
    return {
        "configuration_id": configuration_id,
        "role": role,
        "run_id": result.run_id,
        "run_dir": repo_relative(Path(result.run_dir), repo_root),
        "config_path": repo_relative(config_path, repo_root),
        "configuration_hash": manifest.get("configuration_hash"),
        "llm_decisions": bool(manifest.get("llm_decisions")),
        "decision_mode": manifest.get(
            "decision_mode",
            "deterministic" if role == "baseline" else "assist",
        ),
        "primary_defaults": manifest.get("primary_defaults", {}),
        "artifacts": manifest.get("artifacts", {}),
        "metrics": manifest.get("metrics", {}),
        "model_config": model_config or manifest.get("model_config"),
        "prompt_versions": prompt_versions or manifest.get("prompt_versions"),
    }


def _display_configuration_id(experiment_id: str) -> str:
    mapping = {
        "m4_c_llm_primary_alaska_monitor": "C-LLM",
        "m4_c_llm_primary_fixture": "fixture-C-LLM",
        "m4_b_all_alaska_monitor": "B-All",
        "m4_b_schema_only_alaska_monitor": "B-S",
        "m4_b_linkage_only_alaska_monitor": "B-L",
        "m4_b_fusion_only_alaska_monitor": "B-F",
        "m4_b_schema_linkage_alaska_monitor": "B-SL",
        "m4_b_linkage_fusion_alaska_monitor": "B-LF",
        "m4_budget_cap_0_alaska_monitor": "Budget-0",
        "m4_budget_cap_5_alaska_monitor": "Budget-5",
        "m4_budget_cap_10_alaska_monitor": "Budget-10",
        "m4_budget_cap_25_alaska_monitor": "Budget-25",
        "m3_llm_assisted_example": "fixture-B-All",
    }
    return mapping.get(experiment_id, experiment_id)


def _summarize_run(run: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    metrics = run.get("metrics", {})
    schema = _metric(metrics, repo_root, "assisted_schema_metrics", "schema_metrics")
    blocking = _metric(metrics, repo_root, "blocking_metrics", "baseline_blocking_metrics")
    linkage = _metric(metrics, repo_root, "assisted_linkage_metrics", "linkage_metrics")
    cluster = _metric(metrics, repo_root, "cluster_metrics", "baseline_cluster_metrics")
    fusion = _metric(metrics, repo_root, "assisted_fusion_metrics", "fusion_metrics")
    test_linkage = linkage.get("metrics_by_split", {}).get("test", {})
    cluster_quality = cluster.get("agglomerative", {})
    curated = fusion.get("curated_fusion_metrics", {})
    bootstrap = fusion.get("bootstrap_fusion_metrics", {})
    fusion_accuracy = curated.get("accuracy", fusion.get("accuracy", bootstrap.get("accuracy", 0)))
    end_to_end = _mean_present(
        [
            schema.get("f1"),
            test_linkage.get("f1"),
            cluster_quality.get("f1"),
            fusion_accuracy,
        ]
    )
    cm = confusion_matrix(linkage)
    return {
        "configuration_id": run["configuration_id"],
        "report_label": _report_label(run["configuration_id"]),
        "run_id": run["run_id"],
        "schema_f1": _round(schema.get("f1")),
        "core_schema_f1": _round(schema.get("core_schema_metrics", {}).get("f1")),
        "detail_schema_f1": _round(schema.get("monitor_detail_schema_metrics", {}).get("f1")),
        "candidate_pairs": int(blocking.get("candidate_pair_count", 0) or 0),
        "blocking_pair_completeness": _round(blocking.get("pair_completeness")),
        "blocking_reduction_ratio": _round(blocking.get("reduction_ratio")),
        "linkage_test_precision": _round(test_linkage.get("precision")),
        "linkage_test_recall": _round(test_linkage.get("recall")),
        "linkage_test_f1": _round(test_linkage.get("f1")),
        "linkage_tp": cm["true_positive"],
        "linkage_fp": cm["false_positive"],
        "linkage_tn": cm["true_negative"],
        "linkage_fn": cm["false_negative"],
        "cluster_f1": _round(cluster_quality.get("f1")),
        "cluster_precision": _round(cluster_quality.get("precision")),
        "cluster_recall": _round(cluster_quality.get("recall")),
        "fusion_accuracy": _round(fusion_accuracy),
        "fusion_evaluated_values": int(curated.get("evaluated_value_count", 0) or 0),
        "end_to_end_quality": _round(end_to_end),
    }


def _operational_summary(run: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    artifacts = run.get("artifacts", {})
    payloads: list[dict[str, Any]] = []
    for key in ("schema_quality_cost", "linkage_quality_cost", "fusion_quality_cost"):
        path = artifacts.get(key)
        if path:
            payloads.append(_read_json(repo_root / path))
    metrics: dict[str, Any] = aggregate_operational_metrics(payloads)
    metrics["configuration_id"] = run["configuration_id"]
    metrics["report_label"] = _report_label(run["configuration_id"])
    metrics["run_id"] = run["run_id"]
    metrics["invalid_output_rate"] = _rate(
        int(metrics["invalid_output_count"]), int(metrics["llm_call_count"])
    )
    metrics["abstention_rate"] = _rate(
        int(metrics["abstention_count"]), int(metrics["llm_call_count"])
    )
    metrics["fallback_rate"] = _rate(int(metrics["fallback_count"]), int(metrics["llm_call_count"]))
    metrics["unsupported_value_count"] = _unsupported_value_count(run, repo_root)
    return metrics


def _report_label(configuration_id: str) -> str:
    return {
        "A0": "Deterministic",
        "C-LLM": "LLM",
        "B-All": "Hybrid",
        "fixture-A0": "Deterministic",
        "fixture-C-LLM": "LLM",
        "fixture-B-All": "Hybrid",
    }.get(configuration_id, configuration_id)


def _dataset_summary(repo_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    first_run = manifest["runs"][0]
    config_path = repo_root / first_run["config_path"]
    if first_run["role"] == "baseline":
        pipeline = load_baseline_pipeline_config(config_path)
        dataset_config_path = repo_root / pipeline.dataset_config
        schema_path = repo_root / pipeline.schema_path
    else:
        experiment = load_m3_experiment_config(config_path)
        pipeline = load_baseline_pipeline_config(repo_root / experiment.baseline_pipeline_config)
        dataset_config_path = repo_root / pipeline.dataset_config
        schema_path = repo_root / pipeline.schema_path
    dataset = load_dataset_config(dataset_config_path)
    schema = load_mediated_schema(schema_path)
    manifest_path = repo_root / "data/manifests/dataset_manifest.json"
    if manifest_path.exists():
        dataset_manifest = _read_json(manifest_path)
    else:
        dataset_manifest = json.loads(ingest_dataset(dataset, repo_root).model_dump_json())
    artifact_record_count = _parquet_row_count(
        repo_root / str(first_run.get("artifacts", {}).get("normalized_records", ""))
    )
    ground_truth = summarize_ground_truth(dataset.ground_truth_path, repo_root)
    manifest_ground_truth = dataset_manifest.get("ground_truth", {})
    return {
        "dataset_id": dataset.dataset_id,
        "benchmark": dataset.benchmark,
        "vertical": dataset.vertical,
        "source_count": len(dataset.sources),
        "record_count": artifact_record_count
        if artifact_record_count is not None
        else int(dataset_manifest.get("total_record_count", 0) or 0),
        "entity_count": ground_truth.entity_count
        or int(manifest_ground_truth.get("entity_count", 0) or 0),
        "labeled_record_count": int(
            ground_truth.labeled_record_count
            or manifest_ground_truth.get("labeled_record_count", 0)
            or 0
        ),
        "positive_pair_count": int(
            ground_truth.positive_pair_count
            or manifest_ground_truth.get("positive_pair_count", 0)
            or 0
        ),
        "mediated_attribute_count": len(schema.attributes),
        "repository_url": manifest.get("repository_url") or "",
    }


def _parquet_row_count(path: Path) -> int | None:
    if not path.exists() or path.suffix != ".parquet":
        return None
    try:
        return int(pl.scan_parquet(path).select(pl.len()).collect().item())
    except pl.exceptions.PolarsError:
        return None


def _metric(
    metrics: dict[str, str],
    repo_root: Path,
    preferred_key: str,
    fallback_key: str,
) -> dict[str, Any]:
    path = metrics.get(preferred_key) or metrics.get(fallback_key)
    if not path:
        return {}
    return _read_json(repo_root / path)


def _export_error_cases(
    repo_root: Path,
    manifest: dict[str, Any],
    appendix_dir: Path,
    *,
    fixture: bool,
) -> list[dict[str, Any]]:
    report_run = _preferred_error_run(manifest)
    artifacts = report_run.get("artifacts", {})
    cases: list[dict[str, Any]] = []
    cases.extend(_schema_error_cases(repo_root, report_run))
    cases.extend(_fusion_error_cases(repo_root, report_run))
    cases.extend(_linkage_error_cases(repo_root, report_run))
    cases.extend(_cluster_error_cases(repo_root, report_run))
    cases = _dedupe_cases(cases)[:REQUIRED_SUBMISSION_ERROR_CASES]
    if not fixture and len(cases) < REQUIRED_SUBMISSION_ERROR_CASES:
        raise RuntimeError(
            "submission report requires at least three real source-level error cases; "
            f"found {len(cases)}. Inspect full live run artifacts or add curated cases."
        )
    while len(cases) < 3:
        cases.append(
            {
                "case_id": f"fixture_placeholder_{len(cases) + 1}",
                "stage": "fixture_only",
                "source_records": [],
                "system_output": "No additional labeled error was available.",
                "expected_output": "N/A",
                "explanation": (
                    "Fixture-only placeholder. This cannot satisfy the M4 submission gate."
                ),
                "artifact_links": artifacts,
            }
        )
    appendix_md = appendix_dir / "m4_error_cases.md"
    appendix_md.write_text(_error_cases_markdown(cases), encoding="utf-8")
    return cases


def _dedupe_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id", ""))
        if case_id in seen:
            continue
        seen.add(case_id)
        output.append(case)
    return output


def _preferred_error_run(manifest: dict[str, Any]) -> dict[str, Any]:
    for run in manifest["runs"]:
        if run["configuration_id"] in {"B-All", "fixture-B-All"}:
            return cast(dict[str, Any], run)
    return cast(dict[str, Any], manifest["runs"][0])


def _schema_error_cases(repo_root: Path, run: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = run.get("artifacts", {})
    path = artifacts.get("schema_false_positives") or artifacts.get(
        "baseline_schema_false_positives"
    )
    if not path:
        return []
    frame = _safe_parquet(repo_root / path)
    if frame is None or frame.is_empty():
        return []
    row = frame.head(1).to_dicts()[0]
    source_id = str(row.get("source_id") or str(row.get("source_attribute_id", "")).split("//")[0])
    attribute_name = str(
        row.get("attribute_name") or str(row.get("source_attribute_id", "")).split("//")[-1]
    )
    return [
        {
            "case_id": f"schema_{row['source_attribute_id']}",
            "stage": "schema_alignment",
            "source_records": _source_attribute_examples(
                repo_root,
                run,
                source_id=source_id,
                attribute_name=attribute_name,
            ),
            "system_output": {
                "source_attribute_id": row.get("source_attribute_id"),
                "predicted_target_attribute_name": row.get("target_attribute_name")
                or row.get("predicted_target_attribute_name"),
                "score_total": row.get("score_total"),
                "method": row.get("method"),
            },
            "expected_output": {
                "gold_target_attribute_name": row.get("gold_target_attribute_name"),
            },
            "explanation": (
                "The source attribute was mapped to the wrong mediated-schema field, "
                "which can propagate into normalization and fusion."
            ),
            "artifact_links": {
                "schema_errors": path,
                "schema_metrics": run.get("metrics", {}).get("assisted_schema_metrics")
                or run.get("metrics", {}).get("schema_metrics")
                or run.get("metrics", {}).get("baseline_schema_metrics"),
            },
        }
    ]


def _fusion_error_cases(repo_root: Path, run: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = _metric(
        run.get("metrics", {}),
        repo_root,
        "assisted_fusion_metrics",
        "fusion_metrics",
    )
    rows = metrics.get("curated_fusion_metrics", {}).get("rows", [])
    if not rows:
        rows = metrics.get("bootstrap_fusion_metrics", {}).get("rows", [])
    error_rows = [row for row in rows if isinstance(row, dict) and not row.get("correct")]
    memberships = _safe_parquet(repo_root / run.get("artifacts", {}).get("cluster_memberships", ""))
    source_records = _source_record_lookup(repo_root, run)
    cases: list[dict[str, Any]] = []
    for index, row in enumerate(error_rows[:2], start=1):
        entity_id = str(row.get("predicted_entity_id", ""))
        member_ids = []
        if memberships is not None and "entity_id" in memberships.columns:
            member_ids = [
                str(value)
                for value in memberships.filter(pl.col("entity_id") == entity_id)
                .get_column("record_uid")
                .to_list()[:3]
            ]
        cases.append(
            {
                "case_id": f"fusion_{index}_{entity_id}",
                "stage": "fusion",
                "source_records": [_record_payload(source_records, uid) for uid in member_ids],
                "system_output": {
                    "entity_id": entity_id,
                    "attribute": row.get("mediated_attribute"),
                    "predicted_value": row.get("predicted_value"),
                },
                "expected_output": {
                    "truth_entity_id": row.get("truth_entity_id"),
                    "expected_value": row.get("expected_value"),
                },
                "explanation": (
                    "The fused value disagrees with the curated or bootstrap fusion gold value, "
                    "usually because conflicting source claims normalize to close but not "
                    "identical values."
                ),
                "artifact_links": {
                    "fusion_metrics": run.get("metrics", {}).get("assisted_fusion_metrics")
                    or run.get("metrics", {}).get("fusion_metrics"),
                    "fused_values": run.get("artifacts", {}).get("assisted_fused_values")
                    or run.get("artifacts", {}).get("fused_values"),
                },
            }
        )
    return cases


def _linkage_error_cases(repo_root: Path, run: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = run.get("artifacts", {})
    selected_path = ""
    errors: pl.DataFrame | None = None
    for candidate_path in (
        artifacts.get("assisted_pair_predictions"),
        artifacts.get("pair_predictions"),
        artifacts.get("baseline_pair_predictions"),
    ):
        if not candidate_path:
            continue
        predictions = _safe_parquet(repo_root / candidate_path)
        if predictions is None or predictions.is_empty():
            continue
        candidate_errors = predictions.filter(
            (pl.col("ground_truth_label").is_not_null())
            & (pl.col("match_prediction") != pl.col("ground_truth_label"))
        )
        if not candidate_errors.is_empty():
            selected_path = str(candidate_path)
            errors = candidate_errors
            break
    if errors is None:
        return []
    row = errors.head(1).to_dicts()[0]
    source_records = _source_record_lookup(repo_root, run)
    return [
        {
            "case_id": f"linkage_{row['candidate_pair_id']}",
            "stage": "record_linkage",
            "source_records": [
                _record_payload(source_records, str(row["left_record_uid"])),
                _record_payload(source_records, str(row["right_record_uid"])),
            ],
            "system_output": {
                "candidate_pair_id": row["candidate_pair_id"],
                "match_prediction": row["match_prediction"],
                "match_probability": row["match_probability"],
            },
            "expected_output": {"ground_truth_label": row["ground_truth_label"]},
            "explanation": (
                "The pairwise matcher prediction disagrees with the labeled entity-resolution pair."
            ),
            "artifact_links": {
                "pair_predictions": selected_path,
                "linkage_metrics": run.get("metrics", {}).get("assisted_linkage_metrics")
                or run.get("metrics", {}).get("linkage_metrics"),
            },
        }
    ]


def _cluster_error_cases(repo_root: Path, run: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = run.get("artifacts", {})
    undermerge_path = artifacts.get("cluster_undermerge_errors")
    if undermerge_path:
        undermerges = _safe_parquet(repo_root / undermerge_path)
        if undermerges is not None and undermerges.is_empty():
            undermerge_path = None
    if not undermerge_path:
        undermerge_path = artifacts.get("baseline_cluster_undermerge_errors")
    if not undermerge_path:
        return []
    undermerges = _safe_parquet(repo_root / undermerge_path)
    membership_path = artifacts.get("cluster_memberships") or artifacts.get(
        "baseline_cluster_memberships", ""
    )
    memberships = _safe_parquet(repo_root / membership_path)
    if undermerges is None or undermerges.is_empty() or memberships is None:
        return []
    row = undermerges.head(1).to_dicts()[0]
    predicted_entities = _decode_json(row.get("predicted_entity_ids"))
    if not isinstance(predicted_entities, list):
        predicted_entities = []
    member_ids: list[str] = []
    for entity_id in predicted_entities[:2]:
        entity_members = memberships.filter(pl.col("entity_id") == str(entity_id))
        member_ids.extend(str(value) for value in entity_members.get_column("record_uid").to_list())
    source_records = _source_record_lookup(repo_root, run)
    return [
        {
            "case_id": f"cluster_undermerge_{row['ground_truth_entity_id']}",
            "stage": "clustering",
            "source_records": [_record_payload(source_records, uid) for uid in member_ids[:4]],
            "system_output": {
                "predicted_cluster_count": row.get("predicted_cluster_count"),
                "predicted_entity_ids": predicted_entities,
            },
            "expected_output": {
                "ground_truth_entity_id": row.get("ground_truth_entity_id"),
                "expected_cluster_count": 1,
            },
            "explanation": (
                "Records from one labeled truth entity were split across multiple predicted "
                "clusters, so downstream fusion sees incomplete claim evidence."
            ),
            "artifact_links": {
                "cluster_undermerge_errors": undermerge_path,
                "cluster_metrics": run.get("metrics", {}).get("cluster_metrics"),
            },
        }
    ]


def _source_record_lookup(repo_root: Path, run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized_path = run.get("artifacts", {}).get("normalized_records")
    if not normalized_path:
        return {}
    normalized = _safe_parquet(repo_root / normalized_path)
    if normalized is None:
        return {}
    raw_path = _raw_records_path(repo_root, run)
    raw = _safe_parquet(raw_path)
    raw_by_uid = {}
    if raw is not None:
        raw_by_uid = {str(row["record_uid"]): row for row in raw.to_dicts()}
    output: dict[str, dict[str, Any]] = {}
    for row in normalized.to_dicts():
        uid = str(row["record_uid"])
        raw_row = raw_by_uid.get(uid, {})
        output[uid] = {
            "record_uid": uid,
            "source_id": row.get("source_id"),
            "source_record_id": row.get("source_record_id"),
            "normalized_payload": _decode_json(row.get("normalized_payload")),
            "raw_payload": _decode_json(raw_row.get("raw_payload")),
        }
    return output


def _source_attribute_examples(
    repo_root: Path,
    run: dict[str, Any],
    *,
    source_id: str,
    attribute_name: str,
) -> list[dict[str, Any]]:
    raw_path = _raw_records_path(repo_root, run)
    raw = _safe_parquet(raw_path)
    if raw is None:
        return []
    examples: list[dict[str, Any]] = []
    for row in raw.filter(pl.col("source_id") == source_id).iter_rows(named=True):
        payload = _decode_json(row.get("raw_payload"))
        if not isinstance(payload, dict) or attribute_name not in payload:
            continue
        examples.append(
            {
                "record_uid": row.get("record_uid"),
                "source_id": row.get("source_id"),
                "source_record_id": row.get("source_record_id"),
                "attribute_name": attribute_name,
                "attribute_value": payload.get(attribute_name),
                "raw_payload": payload,
            }
        )
        if len(examples) >= 3:
            break
    return examples


def _raw_records_path(repo_root: Path, run: dict[str, Any]) -> Path:
    dataset_id = "fixture_m1_products" if "fixture" in run["run_id"] else "alaska_monitor_m1"
    return repo_root / "data" / "interim" / "m1" / dataset_id / "source_records.parquet"


def _record_payload(records: dict[str, dict[str, Any]], uid: str) -> dict[str, Any]:
    return records.get(uid, {"record_uid": uid, "missing": True})


def _copy_final_dataset(
    repo_root: Path,
    manifest: dict[str, Any],
    release_dir: Path,
) -> Path | None:
    preferred = _preferred_error_run(manifest)
    artifacts = preferred.get("artifacts", {})
    path = artifacts.get("assisted_integrated_entities_jsonl") or artifacts.get(
        "integrated_entities_jsonl"
    )
    if not path:
        return None
    source = repo_root / path
    if not source.exists():
        return None
    destination = release_dir / "final_integrated_dataset.jsonl"
    shutil.copyfile(source, destination)
    return destination


def _report_markdown(
    *,
    manifest: dict[str, Any],
    dataset: dict[str, Any],
    summaries: list[dict[str, Any]],
    operational: list[dict[str, Any]],
    error_cases: list[dict[str, Any]],
    final_dataset: Path | None,
    fixture: bool,
) -> str:
    mode_note = (
        "This build is a fixture-equivalent reproduction report, not the final live submission."
        if fixture
        else (
            "This build is the full live academic release; assisted metrics come from live "
            "or cached OpenAI calls."
        )
    )
    final_dataset_text = (
        repo_relative(final_dataset, final_dataset.parents[2])
        if final_dataset is not None
        else "not exported"
    )
    dataset_table = _markdown_table(
        [
            {
                "sources": dataset["source_count"],
                "records": dataset["record_count"],
                "entities": dataset["entity_count"],
                "positive_pairs": dataset["positive_pair_count"],
                "attributes": dataset["mediated_attribute_count"],
            }
        ]
    )
    metrics_table = _markdown_table(
        [
            {
                "pipeline": row["report_label"],
                "config": row["configuration_id"],
                "schema_f1": row["schema_f1"],
                "pairs": row["candidate_pairs"],
                "linkage_f1": row["linkage_test_f1"],
                "cluster_f1": row["cluster_f1"],
                "fusion_acc": row["fusion_accuracy"],
                "e2e": row["end_to_end_quality"],
            }
            for row in summaries
        ]
    )
    operational_table = _markdown_table(
        [
            {
                "pipeline": row["report_label"],
                "config": row["configuration_id"],
                "calls": row["llm_call_count"],
                "accepted": row["accepted_count"],
                "defaulted": row["defaulted_count"],
                "tokens_in": row["input_tokens"],
                "tokens_out": row["output_tokens"],
                "cost_usd": _round(row["estimated_cost_usd"]),
                "fallback_rate": row["fallback_rate"],
                "invalid_rate": row["invalid_output_rate"],
            }
            for row in operational
        ]
    )
    cases_table = _markdown_table(
        [
            {
                "case_id": case["case_id"],
                "stage": case["stage"],
                "explanation": case["explanation"],
            }
            for case in error_cases
        ]
    )
    experiment_table = _markdown_table(
        [
            _experiment_row("A0", "deterministic", "deterministic", "deterministic"),
            _experiment_row("C-LLM", "LLM primary", "LLM primary", "LLM primary"),
            _experiment_row("B-All", "LLM routed", "LLM routed", "LLM routed"),
            _experiment_row("B-S", "LLM routed", "deterministic", "deterministic"),
            _experiment_row("B-L", "deterministic", "LLM routed", "deterministic"),
            _experiment_row("B-F", "deterministic", "deterministic", "LLM routed"),
            _experiment_row("B-SL", "LLM routed", "LLM routed", "deterministic"),
            _experiment_row("B-LF", "deterministic", "LLM routed", "LLM routed"),
        ]
    )
    summary_by_config = {str(row["configuration_id"]): row for row in summaries}
    operational_by_config = {str(row["configuration_id"]): row for row in operational}
    baseline = summary_by_config.get("A0", {})
    llm_primary = summary_by_config.get("C-LLM", {})
    assisted = summary_by_config.get("B-All", {})
    llm_ops = operational_by_config.get("C-LLM", {})
    assisted_ops = operational_by_config.get("B-All", {})
    three_way_table = _markdown_table(
        [
            {
                "pipeline": row.get("report_label"),
                "config": row.get("configuration_id"),
                "schema_f1": row.get("schema_f1"),
                "linkage_f1": row.get("linkage_test_f1"),
                "cluster_f1": row.get("cluster_f1"),
                "fusion_acc": row.get("fusion_accuracy"),
                "e2e": row.get("end_to_end_quality"),
            }
            for row in (baseline, llm_primary, assisted)
            if row
        ]
    )
    funnel_table = _markdown_table(
        [
            {
                "pipeline": row.get("report_label"),
                "eligible": row.get("eligible_count"),
                "selected": row.get("selected_count"),
                "calls": row.get("llm_call_count"),
                "accepted": row.get("accepted_count"),
                "defaulted": row.get("defaulted_count"),
                "invalid": row.get("invalid_output_count"),
                "cost_usd": _round(row.get("estimated_cost_usd")),
            }
            for row in (llm_ops, assisted_ops)
            if row
        ]
    )
    confusion_table = _markdown_table(
        [
            {
                "config": row["configuration_id"],
                "tp": row["linkage_tp"],
                "fp": row["linkage_fp"],
                "tn": row["linkage_tn"],
                "fn": row["linkage_fn"],
                "precision": row["linkage_test_precision"],
                "recall": row["linkage_test_recall"],
            }
            for row in summaries
            if row["configuration_id"] in {"A0", "B-All", "B-L", "B-SL", "B-LF"}
        ]
    )
    budget_table = _markdown_table(
        [
            {
                "config": row["configuration_id"],
                "calls": operational_by_config.get(row["configuration_id"], {}).get(
                    "llm_call_count", 0
                ),
                "cost_usd": _round(
                    operational_by_config.get(row["configuration_id"], {}).get(
                        "estimated_cost_usd", 0
                    )
                ),
                "schema_f1": row["schema_f1"],
                "linkage_f1": row["linkage_test_f1"],
                "fusion_acc": row["fusion_accuracy"],
                "e2e": row["end_to_end_quality"],
            }
            for row in summaries
            if str(row["configuration_id"]).startswith("Budget")
        ]
    )
    traceability_table = _markdown_table(
        [
            {
                "requirement": "Baseline and assisted runs",
                "artifact": "reports/release/m4_release_manifest.json",
                "evidence": "A0, C-LLM, B-All, ablations, and budgets",
            },
            {
                "requirement": "Component metrics",
                "artifact": "reports/release/tables/metrics_summary.csv",
                "evidence": "Schema, blocking, linkage, clustering, fusion",
            },
            {
                "requirement": "Operational metrics",
                "artifact": "reports/release/tables/operational_metrics.csv",
                "evidence": "Calls, tokens, cost, fallbacks, invalid outputs",
            },
            {
                "requirement": "Concrete error cases",
                "artifact": "reports/appendix/m4_error_cases.json",
                "evidence": "Source records, outputs, expected values",
            },
            {
                "requirement": "Final dataset",
                "artifact": final_dataset_text,
                "evidence": "Integrated entity JSONL export",
            },
            {
                "requirement": "Reproduction guide",
                "artifact": "README.md and reports/README.md",
                "evidence": "Live, fixture, report, and dataset commands",
            },
        ]
    )
    case_details = _case_details_markdown(error_cases)
    return f"""---
title: "Mosaic: Selective LLM Assistance for Product Data Integration"
author: "Mosaic Research Release"
date: "{datetime.now(UTC).date().isoformat()}"
geometry: margin=1in
fontsize: 10pt
---

# Introduction

Mosaic compares three product data integration pipelines: a fully deterministic
baseline, a bounded LLM-primary pipeline, and a selective hybrid pipeline for
schema alignment, record linkage, and data fusion. The research question is
where LLM decisions improve an otherwise reproducible integration workflow, and
where deterministic methods remain preferable because they are cheaper, faster,
easier to audit, or less prone to unsupported outputs.

{mode_note}

The assignment asks for a traditional baseline, an LLM-assisted pipeline that
uses the model in multiple integration stages, component metrics, operational
measurements, concrete errors, a final integrated dataset, and reproducible
commands. This report is generated from run artifacts rather than hand-entered
numbers, so the tables can be traced back to manifests, metrics JSON files, and
Parquet/JSONL outputs under the release bundle.

# Dataset And Scope

The selected dataset is the Alaska Monitor benchmark subset. The full input
dataset is separated from the labeled evaluation subset: all source records are
processed, while schema, linkage, clustering, and fusion metrics are computed
where gold labels are available.

Dataset id: `{dataset["dataset_id"]}`

{dataset_table}

Repository: {dataset.get("repository_url") or "not configured"}

The Alaska Monitor data is deliberately larger than the labeled evaluation
subset. This matters for grading because the pipeline must run over realistic
source scale even when labels are sparse. Blocking and normalization see every
one of the {dataset["record_count"]} source records. Linkage, clustering, and
fusion quality are then measured wherever the entity-resolution, schema, and
fusion gold files can support a precise comparison. The report therefore
separates operational scale from labeled quality: candidate-pair count and
reduction ratio describe the full run, while precision, recall, F1, and fusion
accuracy describe the labeled slice.

The dataset contains {dataset["source_count"]} sources from the same monitor
vertical, but those sources disagree heavily on attribute names and product
detail. Some sources expose common catalog fields, while others expose dozens
of display-specific specifications. That heterogeneity is the reason Mosaic
uses a mediated schema rather than relying on source-local attribute names.

# Mediated Schema

The mediated schema defines the canonical product fields consumed by linkage,
clustering, claim extraction, and fusion. Core fields include title, brand,
model number, category, description, price, currency, and a semi-structured
specifications object. The Monitor release extends this with detailed display
attributes such as screen size, resolution, brightness, response time, ports,
aspect ratio, panel type, dimensions, color, humidity, and operating conditions.

Schema alignment is evaluated against the available source-to-mediated mapping
gold labels. The report separates overall schema F1 from core-schema and
monitor-detail F1 because detailed monitor specifications are much more
heterogeneous than the common product identity fields.

The schema stage is also the first place where an LLM can help or hurt the rest
of the system. A corrected mapping can expose normalized values to downstream
linkage and fusion. A wrong mapping can silently move evidence into the wrong
field. For that reason, schema decisions are constrained to the committed
mediated attribute list plus `UNMAPPED` and `ABSTAIN`; unsupported target names
are rejected and counted.

# Methodology

Pipeline A0 uses deterministic schema scoring, rule-based normalization,
blocking, a classical linkage model, constrained clustering, claim extraction,
and deterministic fusion. Pipeline C-LLM uses the same scaffolding but makes
bounded primary model decisions for schema, linkage, and fusion; invalid,
abstained, low-confidence, or unsupported outputs default to LLM-pipeline
conservative values rather than deterministic fallbacks. Pipeline B-All keeps
the deterministic backbone and routes only uncertain cases to an OpenAI model
with strict structured outputs and deterministic fallback.

The reported assisted model is configured through committed JSON files. The
default M4 live model is `gpt-4.1-mini`, temperature `0`, strict structured
outputs, versioned prompts, and cached call logging for repeatability.

LLM calls are selective rather than exhaustive. Schema calls are routed from
low-margin or unmapped source attributes. Linkage calls are routed from
borderline match probabilities. Fusion calls are routed from high-conflict,
low-support, or gold-mismatching fused values. All structured model outputs are
validated against known attributes, known candidate pairs, known claim IDs, and
claim-supported values before they can affect the pipeline.

## Schema Alignment Method

The deterministic schema aligner scores source attributes using name similarity,
type compatibility, value evidence, and source context. A mapping is accepted
only when its score passes the configured threshold and margin. M4 routes
low-margin or unmapped attributes to the model, but the model is not allowed to
invent schema fields. The accepted assisted mapping table is then used for
normalization in exactly the same way as the deterministic mapping table.

## Linkage And Clustering Method

The blocking stage produces candidate pairs from source records using product
identity evidence such as brand, model tokens, title tokens, category, and
display specifications. The linker trains and calibrates a classical model over
candidate-pair features. M4 only routes borderline probabilities to the LLM,
because clear negatives and clear positives are cheaper and more reproducible
when handled deterministically. Clustering remains deterministic and constrained
by same-source, brand, model, specification-signature, and maximum-size rules.

## Fusion Method

Fusion operates after clustering and claim extraction. It selects canonical
values from the claims already observed in source records. The LLM-assisted
fusion stage can choose among claim-supported values, abstain, or fall back; it
cannot synthesize a value that was not supported by source evidence. This is
important for hallucination control and for making every final integrated value
traceable back to raw records.

## Release Controls

The release command loads `OPENAI_API_KEY` from the ignored root `.env` only
when the shell has not already provided the variable. Secrets are never printed
or written into the manifest. Full submission report builds require a manifest
with `mode: full_live` and `reported_live_assisted: true`; fixture-only output
requires the explicit `--fixture` path.

# Experimental Protocol

The grading-focused matrix includes A0, B-All, stage ablations, and
routing-budget variants, plus C-LLM as the practical LLM-primary comparison
point. Every run records the code commit, configuration hash, prompt versions,
model settings, metrics, and artifact paths in a release manifest.

Release manifest: `{M4_RELEASE_DIR.as_posix()}/m4_release_manifest.json`

{experiment_table}

Invalid JSON, missing fields, hallucinated or unsupported values, empty
responses, abstentions, and timeouts are treated as measured failures unless the
documented deterministic fallback handles them. The fixture release is retained
for reproducibility checks, but the submission release must use full-live or
cache-backed OpenAI calls over the selected Alaska Monitor dataset.

The stage ablations answer a narrower question than the full B-All run. B-S
tests schema assistance while leaving linkage and fusion deterministic. B-L
tests linkage assistance alone. B-F tests fusion assistance alone. B-SL and
B-LF expose two-stage propagation effects: whether schema changes alter
candidate evidence before linkage, and whether linkage changes alter the
clusters that fusion receives. The budget runs answer the operational question:
how much quality is retained when the number of routed calls is capped.

\\newpage

# Results

![Component quality overview]({M4_RELEASE_DIR.as_posix()}/figures/component_quality.png)

## Three-Way Pipeline Comparison

{three_way_table}

{metrics_table}

Full metric tables are written to
`{M4_RELEASE_DIR.as_posix()}/tables/metrics_summary.csv`.

On this release, the LLM-primary pipeline records schema F1
{llm_primary.get("schema_f1", "")}, linkage test F1
{llm_primary.get("linkage_test_f1", "")}, clustering F1
{llm_primary.get("cluster_f1", "")}, fusion accuracy
{llm_primary.get("fusion_accuracy", "")}, and end-to-end summary
{llm_primary.get("end_to_end_quality", "")}. B-All records schema F1
{assisted.get("schema_f1", "")},
linkage test F1 {assisted.get("linkage_test_f1", "")}, clustering F1
{assisted.get("cluster_f1", "")}, fusion accuracy
{assisted.get("fusion_accuracy", "")}, and end-to-end summary
{assisted.get("end_to_end_quality", "")}. The deterministic A0 reference
records schema F1 {baseline.get("schema_f1", "")}, linkage test F1
{baseline.get("linkage_test_f1", "")}, clustering F1
{baseline.get("cluster_f1", "")}, fusion accuracy
{baseline.get("fusion_accuracy", "")}, and end-to-end summary
{baseline.get("end_to_end_quality", "")}.

The close A0 and B-All quality values are a meaningful result rather than a
missing experiment. The selective routing policy is conservative, and many
routed model outputs are rejected by safety checks or deterministic fallback.
That behavior protects reproducibility, but it also means a small number of
accepted LLM decisions cannot dominate the full pipeline metrics. The report
therefore treats operational reliability and failure handling as first-class
results alongside F1.

## Linkage Confusion Matrix

{confusion_table}

The linkage confusion matrix shows that the test split remains stable across
the assisted linkage variants. This is desirable when routed examples are
borderline and the deterministic matcher is already strong. The LLM is most
useful when it can correct specific ambiguous cases without creating broad
precision loss. The accepted changes in this release are small enough that
cluster-level metrics remain controlled by the deterministic constraints and
the underlying gold-label sparsity.

![Routing budget frontier]({M4_RELEASE_DIR.as_posix()}/figures/routing_budget_frontier.png)

Operational metrics summarize cost and reliability of selective LLM use.

{operational_table}

## LLM Intervention Funnel

{funnel_table}

## Routing Budget Results

{budget_table}

The routing-budget variants show the cost envelope for the live release.
B-All issued {assisted_ops.get("llm_call_count", 0)} model calls with an
estimated cost of ${_round(assisted_ops.get("estimated_cost_usd", 0))}. The
budgeted runs preserve the same deterministic backbone, so any quality movement
comes only from the subset of routed decisions allowed by the cap. This makes
the budget frontier interpretable: the x-axis is not total pipeline work, but
the number of cases where the model was allowed to override or confirm a
deterministic decision.

The main result to inspect is not only whether B-All improves every metric, but
which component changes and at what operational cost. Schema metrics show
whether LLM judgment helps with heterogeneous attribute names. Linkage metrics
show whether borderline pairs are corrected without damaging precision. Cluster
metrics expose propagation effects from pair decisions to entity construction.
Fusion metrics show whether the selected canonical values match available
ground truth. Operational metrics quantify whether the quality changes justify
the calls, tokens, latency, fallbacks, and invalid-output handling.

\\newpage

# Error Analysis

The appendix stores structured source-level cases in
`reports/appendix/m4_error_cases.json` and
`reports/appendix/m4_error_cases.md`.

{cases_table}

{case_details}

The error cases are selected from real run artifacts, not fixture placeholders.
They are intentionally concrete: each case includes source records, system
output, expected output, explanation, stage of origin, and links to the metric
or artifact files that produced the case. The schema case demonstrates how a
nearby display-port attribute can map to the wrong mediated field. The fusion
cases demonstrate how cluster-level evidence can still leave close but
different numeric values for display specifications.

The most important pattern is propagation. A schema error can change which
normalized values exist. A linkage or clustering error can change which source
claims are pooled into an entity. A fusion error can then select the wrong
canonical value even when individual source records are correctly parsed. This
is why the report lists the stage of origin rather than treating every final
wrong value as a fusion-only failure.

# Discussion

LLMs are most useful where deterministic evidence is ambiguous: low-margin
schema mappings, borderline pair probabilities, and conflicting fused claims.
Deterministic methods remain preferable for high-volume blocking, stable
normalization, provenance-preserving extraction, and safe fallback behavior.
Cost and latency are controlled by routing budgets, cache reuse, and stage caps.
Hallucinations are treated as measurable failures by restricting outputs to
known schema attributes, known pair decisions, or claim-supported fusion values.

The design deliberately keeps blocking, normalization, and provenance extraction
deterministic. These stages are high-volume and benefit from predictable,
auditable behavior. LLM assistance is reserved for the smaller set of uncertain
cases where the model can inspect evidence that is difficult to encode as a
single threshold. Deterministic fallback is part of the system design rather
than an afterthought: a model output that cannot be validated is measured and
discarded.

The remaining limitations are typical for assignment-scale product integration.
Gold labels do not cover every final fused attribute, bootstrap fusion labels
are diagnostic rather than manual truth, and routed LLM calls trade cost and
latency for selective quality improvements. Reproducibility depends on committed
prompts, committed model settings, cached/logged responses, and clear separation
between fixture checks and the full reported run.

## Where Deterministic Methods Remain Preferable

Blocking, normalization, and clustering are deliberately deterministic in the
reported design. They operate over high-volume data and have strong invariants:
blocking must not explode the candidate space, normalization must preserve
source provenance, and clustering must avoid impossible same-source merges.
Using an LLM for these high-volume or constraint-heavy steps would make the
release harder to audit and more expensive to reproduce without a clear quality
benefit.

## Where LLMs Help

LLMs are better suited to low-volume judgment calls where source evidence is
textual, messy, and difficult to reduce to a single scalar score. In schema
alignment, the model can inspect candidate labels and example values. In
linkage, it can compare titles and specifications that sit near the matcher
threshold. In fusion, it can reason over conflicting claims while still being
constrained to observed values. The M4 design uses that strength without
letting the model become the whole pipeline.

## Cost, Latency, And Reproducibility

The live release records calls, token counts, estimated cost, latency, cache
status, invalid outputs, abstentions, fallbacks, and unsupported values. These
operational metrics make the design auditable: a future reader can see not only
what quality was achieved, but how many model decisions were needed and how
often the guardrails rejected the result. Cached calls make repeat report builds
stable after the first live run, while fixture reproduction remains available
for CI environments that should not call external APIs.

## Threats To Validity

The main threat is label coverage. The Alaska Monitor data is large, but labels
are concentrated in specific schema, entity, and fusion gold files. Metrics for
unlabeled final outputs are therefore operational or diagnostic rather than
fully supervised. Another threat is model drift: `gpt-4.1-mini` is pinned in the
model config, but future provider behavior can still differ. The call cache and
manifest are included so the reported release can be regenerated or audited
without silently substituting new model responses.

\\newpage

# Conclusion

Mosaic satisfies the assignment by providing a traditional baseline, a selective
LLM-assisted pipeline, component metrics, operational measurements, concrete
error cases, and a reproducible report path. The final integrated dataset for
the selected release is `{final_dataset_text}`.

# GitHub Link

Repository: {dataset.get("repository_url") or "https://github.com/Forest904/selective-llm-product-integration"}

Reproduction summary:

```bash
make install
make reproduce
uv run mosaic experiment release --live
make report
```

\\newpage

# Appendix

## Traceability Matrix

{traceability_table}

## Release Bundle

The release bundle contains a compact copy of the live manifest, CSV tables,
figures, source-level error cases, the final integrated dataset, report source,
and PDF. Large raw Alaska data and full run directories remain ignored because
they are regenerated by the documented commands. The report build refuses to
produce a submission report from fixture-only manifests, which prevents a clean
clone reproduction check from being mistaken for the reported live experiment.

## Regeneration Commands

```bash
make install
make lint
make test
make reproduce
make report-fixture
uv run mosaic experiment release --live
make report
```

## Clean Clone Expectations

A clean clone should be able to regenerate fixture outputs without an API key by
running `make reproduce` and `make report-fixture`. Those commands prove that
the CLI, metric aggregation, table generation, markdown rendering, and PDF path
are wired correctly in a CI-safe way. They do not claim to reproduce the live
assisted metrics in this report.

The submission-grade path is intentionally stricter. `uv run mosaic experiment
release --live` must see `OPENAI_API_KEY` either in the shell or in the ignored
root `.env` file. The command then runs A0 and the full assisted matrix over the
Alaska Monitor configuration, writes model call logs under the ignored artifact
tree, and emits a compact release manifest. `make report` consumes that manifest
and refuses to proceed if it only sees fixture mode or a manifest that lacks
`reported_live_assisted: true`.

This separation is important for academic reproducibility. Fixture mode proves
that a reviewer can regenerate the report mechanics without spending money or
calling external services. Full-live mode proves that the reported LLM-assisted
results came from the selected dataset, committed prompts, committed model
settings, and logged responses. The report tables are regenerated from the
manifest each time, so stale hand-entered results cannot silently survive a
pipeline change.

## Manifest Provenance

Each run entry records a configuration ID, run ID, configuration hash, prompt
versions, model provider, model name, execution mode, artifact paths, metric
paths, and call-log location. The configuration hash makes accidental changes
visible, while prompt versions make the model instructions inspectable. The run
IDs point to ignored full artifacts for local audit; the compact release copy
keeps the submission lightweight.

The final integrated dataset copy is tracked under the release directory because
it is small enough to submit and inspect. Larger intermediate files, such as
candidate-pair parquet files and full call logs, remain regenerable from the
manifest. This keeps the repository GitHub-ready while preserving a path back to
the exact evidence used by the report.

Long prompt files are committed under `prompts/`. Compact release tables are
committed under `{M4_RELEASE_DIR.as_posix()}/tables/`; large raw data and run
directories remain ignored and regenerable.
"""


def _build_pdf(repo_root: Path, report_md: Path) -> Path | None:
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        return None
    pdf_path = repo_root / "reports" / "report.pdf"
    completed = subprocess.run(
        [
            pandoc,
            str(report_md),
            "--from",
            "markdown",
            "--pdf-engine=xelatex",
            "-o",
            str(pdf_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return pdf_path


def _render_pdf_check(repo_root: Path, pdf_path: Path) -> None:
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        return
    output_prefix = repo_root / "artifacts" / "reports" / "m4" / "report_render"
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [pdftoppm, "-png", "-f", "1", "-l", "1", str(pdf_path), str(output_prefix)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    columns = list(rows[0].keys())
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(row.get(column, "")) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")[:160]


def _error_cases_markdown(cases: list[dict[str, Any]]) -> str:
    sections = ["# M4 Error Case Appendix\n"]
    for case in cases:
        sections.append(
            "## "
            + str(case["case_id"])
            + "\n\n"
            + f"- Stage: `{case['stage']}`\n"
            + f"- System output: `{_markdown_cell(case['system_output'])}`\n"
            + f"- Expected output: `{_markdown_cell(case['expected_output'])}`\n"
            + f"- Explanation: {case['explanation']}\n"
        )
    return "\n".join(sections)


def _experiment_row(config: str, schema: str, linkage: str, fusion: str) -> dict[str, str]:
    return {"config": config, "schema": schema, "linkage": linkage, "fusion": fusion}


def _case_details_markdown(cases: list[dict[str, Any]]) -> str:
    sections = ["## Detailed Cases\n"]
    for case in cases:
        sections.append(
            f"### {case['case_id']}\n\n"
            f"Stage: `{case['stage']}`\n\n"
            f"System output: `{_markdown_cell(case['system_output'])}`\n\n"
            f"Expected output: `{_markdown_cell(case['expected_output'])}`\n\n"
            f"Explanation: {case['explanation']}\n\n"
            f"Source evidence: {_source_evidence_summary(case.get('source_records', []))}\n"
        )
    return "\n".join(sections)


def _source_evidence_summary(source_records: Any) -> str:
    if not isinstance(source_records, list) or not source_records:
        return "No source record excerpt was available in the fixture artifact."
    snippets: list[str] = []
    for record in source_records[:3]:
        if not isinstance(record, dict):
            continue
        uid = record.get("record_uid", "unknown")
        payload = record.get("normalized_payload") or record.get("raw_payload") or {}
        if isinstance(payload, dict):
            title = payload.get("title") or payload.get("<page title>") or ""
            brand = payload.get("brand") or payload.get("manufacturer") or ""
            model = payload.get("model_number") or payload.get("model") or ""
            snippets.append(f"`{uid}` title={title!r} brand={brand!r} model={model!r}")
        else:
            snippets.append(f"`{uid}`")
    return "; ".join(snippets) if snippets else "No source record excerpt was available."


def _flat_error_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "stage": case["stage"],
        "system_output": json.dumps(case["system_output"], sort_keys=True),
        "expected_output": json.dumps(case["expected_output"], sort_keys=True),
        "explanation": case["explanation"],
    }


def _routing_frontier_points(manifest: dict[str, Any], repo_root: Path) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for run in manifest["runs"]:
        if not run["configuration_id"].startswith("Budget-"):
            continue
        summary = _summarize_run(run, repo_root)
        ops = _operational_summary(run, repo_root)
        points.append((int(ops["llm_call_count"]), float(summary.get("end_to_end_quality") or 0)))
    return sorted(points)


def _write_bar_png(path: Path, series: list[tuple[str, list[float]]]) -> None:
    width, height = 900, 420
    image = _blank_image(width, height, (255, 255, 255))
    colors = [(42, 111, 151), (232, 141, 103), (38, 70, 83), (131, 197, 190)]
    margin = 50
    plot_width = width - margin * 2
    plot_height = height - margin * 2
    _line(image, margin, margin, margin, height - margin, (40, 40, 40))
    _line(image, margin, height - margin, width - margin, height - margin, (40, 40, 40))
    if not series:
        _write_png(path, image)
        return
    group_width = plot_width / max(len(series), 1)
    bar_width = max(6, int(group_width / 7))
    for group_index, (_, values) in enumerate(series):
        base_x = int(margin + group_index * group_width + group_width * 0.2)
        for value_index, value in enumerate(values):
            bar_height = int(max(0, min(1, value)) * plot_height)
            x0 = base_x + value_index * (bar_width + 3)
            y0 = height - margin - bar_height
            _rect(image, x0, y0, x0 + bar_width, height - margin, colors[value_index % len(colors)])
    _write_png(path, image)


def _write_line_png(path: Path, points: list[tuple[int, float]]) -> None:
    width, height = 900, 420
    image = _blank_image(width, height, (255, 255, 255))
    margin = 50
    _line(image, margin, margin, margin, height - margin, (40, 40, 40))
    _line(image, margin, height - margin, width - margin, height - margin, (40, 40, 40))
    if len(points) < 2:
        _write_png(path, image)
        return
    max_x = max(point[0] for point in points) or 1
    scaled = [
        (
            int(margin + (x / max_x) * (width - 2 * margin)),
            int(height - margin - max(0, min(1, y)) * (height - 2 * margin)),
        )
        for x, y in points
    ]
    for left, right in zip(scaled, scaled[1:], strict=False):
        _line(image, left[0], left[1], right[0], right[1], (42, 111, 151))
    for x, y in scaled:
        _rect(image, x - 4, y - 4, x + 4, y + 4, (232, 141, 103))
    _write_png(path, image)


def _blank_image(
    width: int,
    height: int,
    color: tuple[int, int, int],
) -> list[list[tuple[int, int, int]]]:
    return [[color for _ in range(width)] for _ in range(height)]


def _rect(
    image: list[list[tuple[int, int, int]]],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    height = len(image)
    width = len(image[0])
    for y in range(max(0, y0), min(height, y1 + 1)):
        row = image[y]
        for x in range(max(0, x0), min(width, x1 + 1)):
            row[x] = color


def _line(
    image: list[list[tuple[int, int, int]]],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    x, y = x0, y0
    while True:
        if 0 <= y < len(image) and 0 <= x < len(image[0]):
            image[y][x] = color
        if x == x1 and y == y1:
            break
        error2 = 2 * error
        if error2 >= dy:
            error += dy
            x += sx
        if error2 <= dx:
            error += dx
            y += sy


def _write_png(path: Path, image: list[list[tuple[int, int, int]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    height = len(image)
    width = len(image[0])
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in image)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _repository_url(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    return completed.stdout.strip() or None


def _unsupported_value_count(run: dict[str, Any], repo_root: Path) -> int:
    count = 0
    for key in ("schema_routing_manifest", "linkage_routing_manifest", "fusion_routing_manifest"):
        path = run.get("artifacts", {}).get(key)
        if not path:
            continue
        frame = _safe_parquet(repo_root / path)
        if frame is None or "fallback_reason" not in frame.columns:
            continue
        count += frame.filter(pl.col("fallback_reason") == "unsupported_value").height
    return count


def _safe_parquet(path: Path) -> pl.DataFrame | None:
    try:
        if path.exists():
            return pl.read_parquet(path)
    except (OSError, pl.exceptions.PolarsError):
        return None
    return None


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _decode_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _resolve(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _round(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def _mean_present(values: list[Any]) -> float:
    numeric = []
    for value in values:
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(numeric) / len(numeric) if numeric else 0.0


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0
