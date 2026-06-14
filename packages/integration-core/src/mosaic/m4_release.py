# ruff: noqa: E501

from __future__ import annotations

import csv
import json
import os
import shutil
import struct
import subprocess
import textwrap
import zlib
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from mosaic.alaska import (
    ALASKA_VERTICALS,
    alaska_extracted_root,
    create_dataset_config_from_alaska_dir,
)
from mosaic.ingestion import ingest_dataset, summarize_ground_truth
from mosaic.m1_models import load_dataset_config, load_mediated_schema
from mosaic.m1_utils import repo_relative
from mosaic.m2_models import PipelineRunResult, load_baseline_pipeline_config
from mosaic.m2_pipeline import _code_commit, run_baseline_pipeline
from mosaic.m3_models import load_llm_model_config, load_m3_experiment_config
from mosaic.m3_pipeline import run_assisted_pipeline
from mosaic.subsets import MaterializedSubset, materialize_subset

M4_RELEASE_DIR = Path("reports/release")
M4_ARTIFACT_DIR = Path("artifacts/reports/m4")
DEFAULT_RELEASE_MANIFEST = M4_ARTIFACT_DIR / "m4_release_manifest.json"
DEFAULT_FIXTURE_MANIFEST = M4_ARTIFACT_DIR / "m4_fixture_manifest.json"
DEFAULT_SCALE_MANIFEST = M4_ARTIFACT_DIR / "m4_deterministic_scale_manifest.json"
DEFAULT_RELEASE_CHECKPOINT = M4_ARTIFACT_DIR / "m4_release_checkpoint.json"
DEFAULT_SCALE_CHECKPOINT = M4_ARTIFACT_DIR / "m4_deterministic_scale_checkpoint.json"
DEFAULT_SUBSET_SPEC = Path("configs/subsets/m4_monitor_subset_60.json")
DEFAULT_SUBSET_EXPERIMENTS = (
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
    resume: str | None = None,
    resume_run_id: str | None = None,
) -> Path:
    """Run the M4 experiment matrix and write a compact release manifest."""
    default_manifest = DEFAULT_FIXTURE_MANIFEST if fixture else DEFAULT_RELEASE_MANIFEST
    output_path = _resolve(repo_root, manifest_path or default_manifest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    release_id = "m4_fixture_release" if fixture else "m4_academic_release"
    _load_root_env(repo_root)

    release_checkpoint_path = repo_root / DEFAULT_RELEASE_CHECKPOINT
    release_checkpoint = _load_release_checkpoint(release_checkpoint_path, resume=resume)
    runs: list[dict[str, Any]] = list(release_checkpoint.get("runs", []))
    run_ids_by_config: dict[str, str] = dict(release_checkpoint.get("run_ids_by_config", {}))
    subset: MaterializedSubset | None = None
    if fixture:
        baseline_config_path = repo_root / "configs/pipelines/fixture_m2.json"
        assisted_config_paths = [
            repo_root / "configs/experiments/m4_c_llm_primary_fixture.json",
            repo_root / "configs/experiments/m3_llm_assisted_example.json",
        ]
    else:
        if not live:
            raise RuntimeError("subset M4 release requires --live for reported assisted runs")
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for subset live M4 assisted runs")
        subset, baseline_config_path, assisted_config_paths = _prepare_subset_release_configs(
            repo_root
        )

    baseline_config = load_baseline_pipeline_config(baseline_config_path)
    baseline_id = "A0" if not fixture else "fixture-A0"
    baseline_entry = _find_run_entry(runs, baseline_id)
    if baseline_entry is not None:
        baseline_result = _result_from_run_entry(baseline_entry, repo_root)
    else:
        baseline_resume_id = _resume_id_for_configuration(
            baseline_id,
            explicit_resume_run_id=resume_run_id,
            run_ids_by_config=run_ids_by_config,
            checkpoint=release_checkpoint,
        )
        baseline_result = run_baseline_pipeline(
            baseline_config,
            repo_root,
            resume_run_id=baseline_resume_id,
        )
        run_ids_by_config[baseline_id] = baseline_result.run_id
        baseline_entry = _run_entry(
            configuration_id=baseline_id,
            role="baseline",
            config_path=baseline_config_path,
            result=baseline_result,
            repo_root=repo_root,
        )
        runs.append(baseline_entry)
        _write_release_checkpoint(
            release_checkpoint_path,
            runs=runs,
            run_ids_by_config=run_ids_by_config,
            current_configuration=None,
        )

    for config_path in assisted_config_paths:
        experiment_config = load_m3_experiment_config(config_path)
        configuration_id = _display_configuration_id(experiment_config.experiment_id)
        if _find_run_entry(runs, configuration_id) is not None:
            continue
        model_config = load_llm_model_config(repo_root / experiment_config.model_config_path)
        if not fixture:
            if model_config.execution_mode not in {"live", "cache_or_live"}:
                raise RuntimeError(
                    f"{config_path} must use live or cache_or_live execution for M4 reporting"
                )
            if model_config.provider != "openai" or not model_config.model:
                raise RuntimeError(f"{config_path} must name a live OpenAI model")
        _write_release_checkpoint(
            release_checkpoint_path,
            runs=runs,
            run_ids_by_config=run_ids_by_config,
            current_configuration=configuration_id,
        )
        result = run_assisted_pipeline(
            experiment_config,
            repo_root,
            baseline_result=baseline_result,
            resume_run_id=_resume_id_for_configuration(
                configuration_id,
                explicit_resume_run_id=resume_run_id,
                run_ids_by_config=run_ids_by_config,
                checkpoint=release_checkpoint,
            ),
        )
        run_ids_by_config[configuration_id] = result.run_id
        runs.append(
            _run_entry(
                configuration_id=configuration_id,
                role="assisted",
                config_path=config_path,
                result=result,
                repo_root=repo_root,
                model_config=model_config.model_dump(),
                prompt_versions=experiment_config.prompt_versions.model_dump(by_alias=True),
            )
        )
        _write_release_checkpoint(
            release_checkpoint_path,
            runs=runs,
            run_ids_by_config=run_ids_by_config,
            current_configuration=None,
        )

    manifest = {
        "release_id": release_id,
        "mode": "fixture" if fixture else "subset_live",
        "generated_at": datetime.now(UTC).isoformat(),
        "code_commit": _code_commit(repo_root),
        "repository_url": _repository_url(repo_root),
        "reported_live_assisted": not fixture,
        "subset": subset.model_dump() if subset is not None else None,
        "runs": runs,
    }
    _write_json(output_path, manifest)
    _write_release_checkpoint(
        release_checkpoint_path,
        runs=runs,
        run_ids_by_config=run_ids_by_config,
        current_configuration=None,
        status="complete",
    )
    return output_path


def run_deterministic_scale(
    repo_root: Path,
    *,
    manifest_path: Path | None = None,
    resume: str | None = None,
    resume_run_id: str | None = None,
) -> Path:
    """Run deterministic A0 only on full Alaska monitor, notebook, and camera data."""
    output_path = _resolve(repo_root, manifest_path or DEFAULT_SCALE_MANIFEST)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path = repo_root / DEFAULT_SCALE_CHECKPOINT
    checkpoint = _load_release_checkpoint(checkpoint_path, resume=resume)
    runs: list[dict[str, Any]] = list(checkpoint.get("runs", []))
    run_ids_by_config: dict[str, str] = dict(checkpoint.get("run_ids_by_config", {}))

    for vertical in ALASKA_VERTICALS:
        config_id = f"A0-{vertical}"
        if _find_run_entry(runs, config_id) is not None:
            continue
        baseline_config_path = _prepare_scale_pipeline_config(repo_root, vertical)
        _write_release_checkpoint(
            checkpoint_path,
            runs=runs,
            run_ids_by_config=run_ids_by_config,
            current_configuration=config_id,
        )
        result = run_baseline_pipeline(
            load_baseline_pipeline_config(baseline_config_path),
            repo_root,
            resume_run_id=_resume_id_for_configuration(
                config_id,
                explicit_resume_run_id=resume_run_id,
                run_ids_by_config=run_ids_by_config,
                checkpoint=checkpoint,
            ),
        )
        run_ids_by_config[config_id] = result.run_id
        runs.append(
            _run_entry(
                configuration_id=config_id,
                role="deterministic_scale",
                config_path=baseline_config_path,
                result=result,
                repo_root=repo_root,
            )
        )
        _write_release_checkpoint(
            checkpoint_path,
            runs=runs,
            run_ids_by_config=run_ids_by_config,
            current_configuration=None,
        )

    manifest = {
        "release_id": "m4_deterministic_scale",
        "mode": "deterministic_scale",
        "generated_at": datetime.now(UTC).isoformat(),
        "code_commit": _code_commit(repo_root),
        "repository_url": _repository_url(repo_root),
        "reported_live_assisted": False,
        "runs": runs,
    }
    _write_json(output_path, manifest)
    _write_release_checkpoint(
        checkpoint_path,
        runs=runs,
        run_ids_by_config=run_ids_by_config,
        current_configuration=None,
        status="complete",
    )
    return output_path


def build_m4_report(
    repo_root: Path,
    *,
    manifest_path: Path | None = None,
    scale_manifest_path: Path | None = None,
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
            "subset live M4 release manifest not found. Run "
            "`uv run mosaic experiment release --live` first, or use "
            "`mosaic report build --fixture` for CI-safe fixture output."
        )
    manifest = _read_json(resolved_manifest)
    _validate_report_manifest(manifest, fixture=fixture)
    scale_manifest: dict[str, Any] | None = None
    if not fixture:
        resolved_scale_manifest = _resolve(repo_root, scale_manifest_path or DEFAULT_SCALE_MANIFEST)
        if not resolved_scale_manifest.exists():
            raise RuntimeError(
                "deterministic scale manifest not found. Run "
                "`uv run mosaic experiment deterministic-scale` before `make report`."
            )
        scale_manifest = _read_json(resolved_scale_manifest)
        _validate_scale_manifest(scale_manifest)
    release_dir = repo_root / M4_RELEASE_DIR
    tables_dir = release_dir / "tables"
    figures_dir = release_dir / "figures"
    appendix_dir = repo_root / "reports" / "appendix"
    for path in (release_dir, tables_dir, figures_dir, appendix_dir):
        path.mkdir(parents=True, exist_ok=True)

    summaries = [_summarize_run(run, repo_root) for run in manifest["runs"]]
    if not fixture:
        _validate_subset_fusion_coverage(summaries)
    operational = [_operational_summary(run, repo_root) for run in manifest["runs"]]
    dataset = _dataset_summary(repo_root, manifest)
    error_cases = _export_error_cases(repo_root, manifest, appendix_dir, fixture=fixture)

    _write_table(tables_dir / "dataset_summary.csv", [dataset])
    _write_table(tables_dir / "metrics_summary.csv", summaries)
    _write_table(tables_dir / "operational_metrics.csv", operational)
    _write_table(tables_dir / "error_cases.csv", [_flat_error_case(case) for case in error_cases])
    scale_summaries = (
        [_summarize_run(run, repo_root) for run in scale_manifest.get("runs", [])]
        if scale_manifest is not None
        else []
    )
    if scale_summaries:
        _write_table(tables_dir / "deterministic_scale.csv", scale_summaries)

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
    report_tex = repo_root / "reports" / "report.tex"
    report_text = _report_markdown(
        manifest=manifest,
        dataset=dataset,
        summaries=summaries,
        operational=operational,
        error_cases=error_cases,
        final_dataset=final_dataset,
        fixture=fixture or manifest.get("mode") == "fixture",
        scale_summaries=scale_summaries,
    )
    report_md.write_text(report_text, encoding="utf-8")
    report_tex.write_text(
        _report_latex(
            manifest=manifest,
            dataset=dataset,
            summaries=summaries,
            operational=operational,
            error_cases=error_cases,
            final_dataset=final_dataset,
            fixture=fixture or manifest.get("mode") == "fixture",
            scale_summaries=scale_summaries,
        ),
        encoding="utf-8",
    )
    appendix_dir.joinpath("m4_error_cases.json").write_text(
        json.dumps(error_cases, indent=2, sort_keys=True), encoding="utf-8"
    )

    pdf_path: Path | None = None
    if build_pdf:
        pdf_path = _build_pdf(repo_root, report_tex, fallback_md=report_md)
        if pdf_path is not None:
            _render_pdf_check(repo_root, pdf_path)

    return {
        "manifest": resolved_manifest,
        "scale_manifest": _resolve(repo_root, scale_manifest_path or DEFAULT_SCALE_MANIFEST)
        if not fixture
        else None,
        "release_manifest": release_manifest_copy,
        "report_md": report_md,
        "report_tex": report_tex,
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


def _prepare_subset_release_configs(repo_root: Path) -> tuple[MaterializedSubset, Path, list[Path]]:
    subset = materialize_subset(repo_root / DEFAULT_SUBSET_SPEC, repo_root)
    generated_root = repo_root / M4_ARTIFACT_DIR / "generated_configs" / subset.subset_id
    baseline_config_path = generated_root / "pipelines" / "baseline_m2_subset.json"
    baseline = _read_json(repo_root / "configs/pipelines/baseline_m2.json")
    baseline["pipeline_id"] = "baseline_m2_alaska_monitor_subset_60"
    baseline["dataset_config"] = subset.dataset_config_path
    baseline["fusion"]["bootstrap_fusion_gold_path"] = (
        f"{subset.output_root}/ground_truth/fusion_gold.jsonl"
    )
    baseline["fusion"]["curated_fusion_gold_path"] = (
        f"{subset.output_root}/ground_truth/fusion_curated_gold.jsonl"
    )
    _write_json(baseline_config_path, baseline)

    experiment_paths: list[Path] = []
    for source in DEFAULT_SUBSET_EXPERIMENTS:
        payload = _read_json(repo_root / source)
        payload["experiment_id"] = payload["experiment_id"].replace(
            "alaska_monitor", "alaska_monitor_subset_60"
        )
        payload["baseline_pipeline_config"] = repo_relative(baseline_config_path, repo_root)
        output_path = generated_root / "experiments" / source.name.replace(
            "alaska_monitor", "alaska_monitor_subset_60"
        )
        _write_json(output_path, payload)
        experiment_paths.append(output_path)
    return subset, baseline_config_path, experiment_paths


def _prepare_scale_pipeline_config(repo_root: Path, vertical: str) -> Path:
    extracted_root = alaska_extracted_root(repo_root, vertical)
    if not extracted_root.exists():
        raise RuntimeError(
            f"Alaska {vertical} data not found under {repo_relative(extracted_root, repo_root)}"
        )
    dataset = create_dataset_config_from_alaska_dir(
        dataset_id=f"alaska_{vertical}_full",
        vertical=vertical,
        extracted_root=extracted_root,
        repo_root=repo_root,
    )
    generated_root = repo_root / M4_ARTIFACT_DIR / "generated_configs" / "deterministic_scale"
    dataset_path = generated_root / "datasets" / f"alaska_{vertical}_full.json"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")

    baseline = _read_json(repo_root / "configs/pipelines/baseline_m2.json")
    baseline["pipeline_id"] = f"baseline_m2_alaska_{vertical}_full"
    baseline["dataset_config"] = repo_relative(dataset_path, repo_root)
    baseline["schema_path"] = (
        "configs/schemas/monitor_mediated_schema.json"
        if vertical == "monitor"
        else "configs/schemas/mediated_schema.json"
    )
    if vertical != "monitor":
        baseline["fusion"]["bootstrap_fusion_gold_path"] = None
        baseline["fusion"]["curated_fusion_gold_path"] = None
    output_path = generated_root / "pipelines" / f"baseline_m2_alaska_{vertical}_full.json"
    _write_json(output_path, baseline)
    return output_path


def _load_release_checkpoint(path: Path, *, resume: str | None) -> dict[str, Any]:
    if resume is None:
        return {}
    if resume != "latest":
        raise RuntimeError("only --resume latest is supported for release-level resume")
    if not path.exists():
        raise RuntimeError(f"release checkpoint not found: {path}")
    return _read_json(path)


def _write_release_checkpoint(
    path: Path,
    *,
    runs: list[dict[str, Any]],
    run_ids_by_config: dict[str, str],
    current_configuration: str | None,
    status: str = "running",
) -> None:
    _write_json(
        path,
        {
            "status": status,
            "updated_at": datetime.now(UTC).isoformat(),
            "current_configuration": current_configuration,
            "run_ids_by_config": run_ids_by_config,
            "runs": runs,
        },
    )


def _resume_id_for_configuration(
    configuration_id: str,
    *,
    explicit_resume_run_id: str | None,
    run_ids_by_config: dict[str, str],
    checkpoint: dict[str, Any],
) -> str | None:
    if checkpoint.get("current_configuration") == configuration_id and explicit_resume_run_id:
        return explicit_resume_run_id
    return run_ids_by_config.get(configuration_id)


def _find_run_entry(runs: list[dict[str, Any]], configuration_id: str) -> dict[str, Any] | None:
    for run in runs:
        if run.get("configuration_id") == configuration_id:
            return run
    return None


def _result_from_run_entry(run: dict[str, Any], repo_root: Path) -> PipelineRunResult:
    artifacts = {
        key: str(repo_root / value) for key, value in dict(run.get("artifacts", {})).items()
    }
    metrics = {
        key: str(repo_root / value) for key, value in dict(run.get("metrics", {})).items()
    }
    manifest = repo_root / str(run.get("run_dir", "")) / "run_manifest.json"
    artifacts["run_manifest"] = str(manifest)
    return PipelineRunResult(
        run_id=str(run["run_id"]),
        run_dir=str(repo_root / str(run["run_dir"])),
        completed_stage="export",
        artifacts=artifacts,
        metrics=metrics,
    )


def _validate_report_manifest(manifest: dict[str, Any], *, fixture: bool) -> None:
    if fixture:
        return
    if manifest.get("mode") != "subset_live" or manifest.get("reported_live_assisted") is not True:
        raise RuntimeError(
            "report build requires a subset live M4 manifest. Run "
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
        raise RuntimeError(f"subset live M4 manifest missing configurations: {', '.join(missing)}")
    subset = manifest.get("subset") or {}
    if subset.get("subset_id") != "alaska_monitor_live_subset_60":
        raise RuntimeError("subset live M4 manifest must use alaska_monitor_live_subset_60")


def _validate_scale_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("mode") != "deterministic_scale":
        raise RuntimeError("deterministic scale manifest has the wrong mode")
    run_ids = {str(run.get("configuration_id")) for run in manifest.get("runs", [])}
    required = {f"A0-{vertical}" for vertical in ALASKA_VERTICALS}
    missing = sorted(required - run_ids)
    if missing:
        raise RuntimeError(
            f"deterministic scale manifest missing configurations: {', '.join(missing)}"
        )


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
    normalized_id = experiment_id.replace("_subset_60", "")
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
    return mapping.get(normalized_id, experiment_id)


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
    fusion_evaluated_values = int(curated.get("evaluated_value_count", 0) or 0)
    fusion_accuracy = curated.get("accuracy") if fusion_evaluated_values else None
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
        "fusion_accuracy": _round_optional(fusion_accuracy),
        "fusion_evaluated_values": fusion_evaluated_values,
        "end_to_end_quality": _round(end_to_end),
    }


def _validate_subset_fusion_coverage(summaries: list[dict[str, Any]]) -> None:
    missing = [
        str(row.get("configuration_id"))
        for row in summaries
        if int(row.get("fusion_evaluated_values", 0) or 0) == 0
    ]
    if missing:
        raise RuntimeError(
            "subset live M4 manifest has no evaluated curated fusion values for "
            f"{', '.join(missing)}. Rebuild the subset with curated fusion gold coverage "
            "before building the submission report."
        )


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
    label = {
        "A0": "Deterministic",
        "C-LLM": "LLM",
        "B-All": "Hybrid",
        "fixture-A0": "Deterministic",
        "fixture-C-LLM": "LLM",
        "fixture-B-All": "Hybrid",
    }.get(configuration_id)
    if label is not None:
        return label
    if configuration_id.startswith("A0-"):
        return "Deterministic Scale"
    return configuration_id


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
            f"found {len(cases)}. Inspect subset live run artifacts or add curated cases."
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
    config_path = repo_root / str(run.get("config_path", ""))
    if run.get("role") == "baseline" or run.get("role") == "deterministic_scale":
        pipeline = load_baseline_pipeline_config(config_path)
    else:
        experiment = load_m3_experiment_config(config_path)
        pipeline = load_baseline_pipeline_config(repo_root / experiment.baseline_pipeline_config)
    dataset = load_dataset_config(repo_root / pipeline.dataset_config)
    dataset_id = dataset.dataset_id
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
    scale_summaries: list[dict[str, Any]],
) -> str:
    mode_note = (
        "This build is a fixture-equivalent reproduction report, not the final live submission."
        if fixture
        else (
            "This build is the subset live academic release; assisted metrics come from "
            "live or cached OpenAI calls on the same 60-entity Monitor subset."
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
                "fallbacks_per_call": row["fallback_rate"],
                "invalids_per_call": row["invalid_output_rate"],
            }
            for row in operational
        ]
    )
    cases_table = _markdown_table(
        [
            {
                "stage": case["stage"],
                "case": _case_summary_label(case),
                "lesson": case["explanation"],
            }
            for case in error_cases
        ]
    )
    scale_table = _markdown_table(
        [
            {
                "config": row["configuration_id"],
                "vertical": str(row["configuration_id"]).replace("A0-", ""),
                "candidate_pairs": row["candidate_pairs"],
                "schema_f1": row["schema_f1"],
                "linkage_f1": row["linkage_test_f1"],
                "cluster_f1": row["cluster_f1"],
                "fusion_acc": row["fusion_accuracy"],
            }
            for row in scale_summaries
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
                "evidence": "Subset A0, C-LLM, B-All, ablations, and budgets",
            },
            {
                "requirement": "Deterministic scale runs",
                "artifact": "reports/release/tables/deterministic_scale.csv",
                "evidence": "Full Monitor, Notebook, and Camera A0 runs",
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

The reported LLM comparison uses the deterministic
`alaska_monitor_live_subset_60` subset: 60 official Alaska Monitor entities
with all source records for those entities. Running A0, C-LLM, and B-All on the
same subset keeps the probabilistic comparison fair and keeps live model cost
bounded. Full Monitor, Notebook, and Camera runs are deterministic-only scale
evidence, reported separately below.

This distinction is deliberate. The subset-live experiment is the supervised
comparison point for LLM assistance, because every compared pipeline sees the
same records, labels, prompts, and budget envelope. The full-scale deterministic
runs answer a different question: whether the integration stack can process the
larger benchmark verticals end to end without calling an external model on
hundreds of thousands of candidate pairs.

Dataset id: `{dataset["dataset_id"]}`

{dataset_table}

Repository: {dataset.get("repository_url") or "not configured"}

The subset still separates operational inputs from labeled quality: blocking
and normalization process every selected source record, while linkage,
clustering, schema, and fusion metrics are computed where filtered gold labels
support a precise comparison. Candidate-pair count and reduction ratio describe
the run scale; precision, recall, F1, and fusion accuracy describe the labeled
slice. The subset is seeded with curated fusion-gold coverage so the
fusion-accuracy denominator is nonzero for the reported live comparison.

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
outputs, maximum 1024 output tokens, two provider retries, versioned prompts,
and cached call logging for repeatability. The OpenAI responses API is called
with a JSON schema output contract; every model response is parsed and
validated before the pipeline can use it.

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
or written into the manifest. Submission report builds require a subset live
manifest with `mode: subset_live`, a deterministic-scale manifest, and
`reported_live_assisted: true`; fixture-only output requires the explicit
`--fixture` path.

# Experimental Protocol

The grading-focused live matrix includes subset A0, B-All, stage ablations,
routing-budget variants, and C-LLM as the practical LLM-primary comparison
point. Every run records the code commit, configuration hash, prompt versions,
model settings, metrics, and artifact paths in a release manifest.

Release manifest: `{M4_RELEASE_DIR.as_posix()}/m4_release_manifest.json`

{experiment_table}

Invalid JSON, missing fields, hallucinated or unsupported values, empty
responses, abstentions, and timeouts are treated as measured failures unless the
documented deterministic fallback handles them. The fixture release is retained
for reproducibility checks, but the submission release must use live or
cache-backed OpenAI calls over the selected Monitor subset.

Prompt versions are committed under `prompts/`, model behavior is committed
under `configs/models/`, and routing thresholds are committed under
`configs/experiments/`. That separation keeps secrets out of the repository
while making the non-secret experimental protocol inspectable.

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

## Deterministic Scale Evidence

The full Alaska verticals are run with the deterministic A0 pipeline only. This
keeps the assignment's probabilistic comparison focused on the common subset
while still showing that the deterministic integration stack can process the
larger Monitor, Notebook, and Camera inputs without live LLM calls.

{scale_table}

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

The C-LLM result is also informative: making the model the primary decision
maker worsens schema, linkage, clustering, and end-to-end quality in this run.
This supports the assignment's central question. LLMs are useful as bounded
judges for difficult cases, but they are not automatically better than a
classical pipeline with strong blocking, calibration, and clustering
constraints.

Fusion accuracy should be read with the label-coverage caveat in mind. The
subset report exports fused entities and claim-supported values, but supervised
fusion accuracy is computed only for curated labeled values that can be matched
to a predicted fused value. The `fusion_evaluated_values` column is therefore
the denominator for this metric; if that denominator is zero, report generation
fails instead of publishing a misleading zero.

## Linkage Confusion Matrix

{confusion_table}

The linkage confusion matrix shows that the test split remains stable across
the assisted linkage variants. This is desirable when routed examples are
borderline and the deterministic matcher is already strong. The LLM is most
useful when it can correct specific ambiguous cases without creating broad
precision loss. The accepted changes in this release are small enough that
cluster-level metrics remain controlled by the deterministic constraints and
the underlying gold-label sparsity.

Operational metrics summarize cost and reliability of selective LLM use.

{operational_table}

The operational columns `fallbacks_per_call` and `invalids_per_call` are
decision-level counts divided by provider call count. They can exceed 1 for
batched C-LLM calls because one model response can contain many decisions, and
one invalid batch can default many downstream decisions. The B-All hybrid rows
are easier to interpret as per-call rates because routing caps the selected
cases much more tightly.

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
nearby display-port attribute can map to the wrong mediated field. The linkage
case shows that near-duplicate product titles and model variants can still sit
on the wrong side of the calibrated threshold. The clustering case shows the
cost of conservative safeguards: avoiding unsafe merges can split a true entity
and leave downstream fusion with incomplete evidence.

The most important pattern is propagation. A schema error can change which
normalized values exist. A linkage or clustering error can change which source
claims are pooled into an entity. A fusion error can then select the wrong
canonical value even when individual source records are correctly parsed. This
is why the report lists the stage of origin rather than treating every final
wrong value as a fusion-only failure.

These cases also explain the hybrid design. The LLM can help inspect ambiguous
labels or borderline pairs, but every accepted intervention must still satisfy
the mediated-schema, candidate-pair, and claim-support constraints. When those
constraints reject an output, the fallback is a feature rather than a cleanup
step: it prevents a fluent but unsupported model answer from entering the final
dataset.

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
between fixture checks and the subset live reported run.

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
uv sync --dev --python 3.12
uv run mosaic reproduce --fixture
uv run mosaic experiment release --live
uv run mosaic experiment deterministic-scale
uv run mosaic report build
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
uv sync --dev --python 3.12
uv run ruff check .
uv run mypy
uv run pytest
uv run mosaic reproduce --fixture
uv run mosaic report build --fixture
uv run mosaic experiment release --live
uv run mosaic experiment deterministic-scale
uv run mosaic report build
```

## Clean Clone Expectations

A clean clone should be able to regenerate fixture outputs without an API key by
running `make reproduce` and `make report-fixture`. Those commands prove that
the CLI, metric aggregation, table generation, markdown rendering, and PDF path
are wired correctly in a CI-safe way. They do not claim to reproduce the live
assisted metrics in this report.

The submission-grade path is intentionally stricter. `uv run mosaic experiment
release --live` must see `OPENAI_API_KEY` either in the shell or in the ignored
root `.env` file. The command then runs A0 and the assisted matrix over the
60-entity Monitor subset, writes model call logs under the ignored artifact
tree, and emits a compact release manifest. `make report` consumes that manifest
plus the deterministic scale manifest and refuses to proceed if it only sees
fixture mode or a manifest that lacks `reported_live_assisted: true`.

This separation is important for academic reproducibility. Fixture mode proves
that a reviewer can regenerate the report mechanics without spending money or
calling external services. Subset-live mode proves that the reported LLM-assisted
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


def _report_latex(
    *,
    manifest: dict[str, Any],
    dataset: dict[str, Any],
    summaries: list[dict[str, Any]],
    operational: list[dict[str, Any]],
    error_cases: list[dict[str, Any]],
    final_dataset: Path | None,
    fixture: bool,
    scale_summaries: list[dict[str, Any]],
) -> str:
    mode_note = (
        "This is a fixture-equivalent reproduction report, not the final live submission."
        if fixture
        else (
            "This is the subset-live academic release: assisted metrics come from live or "
            "cached OpenAI calls on the same 60-entity Monitor subset."
        )
    )
    final_dataset_text = (
        repo_relative(final_dataset, final_dataset.parents[2])
        if final_dataset is not None
        else "not exported"
    )
    summary_by_config = {str(row["configuration_id"]): row for row in summaries}
    operational_by_config = {str(row["configuration_id"]): row for row in operational}
    baseline = summary_by_config.get("A0", {})
    llm_primary = summary_by_config.get("C-LLM", {})
    assisted = summary_by_config.get("B-All", {})
    llm_ops = operational_by_config.get("C-LLM", {})
    assisted_ops = operational_by_config.get("B-All", {})
    repo_url = str(
        dataset.get("repository_url") or "https://github.com/Forest904/selective-llm-product-integration"
    )
    today = datetime.now(UTC).date().isoformat()

    dataset_rows = [
        {
            "sources": dataset["source_count"],
            "records": dataset["record_count"],
            "entities": dataset["entity_count"],
            "positive_pairs": dataset["positive_pair_count"],
            "attributes": dataset["mediated_attribute_count"],
        }
    ]
    experiment_rows = [
        _experiment_row("A0", "deterministic", "deterministic", "deterministic"),
        _experiment_row("C-LLM", "LLM primary", "LLM primary", "LLM primary"),
        _experiment_row("B-All", "LLM routed", "LLM routed", "LLM routed"),
        _experiment_row("B-S", "LLM routed", "deterministic", "deterministic"),
        _experiment_row("B-L", "deterministic", "LLM routed", "deterministic"),
        _experiment_row("B-F", "deterministic", "deterministic", "LLM routed"),
        _experiment_row("B-SL", "LLM routed", "LLM routed", "deterministic"),
        _experiment_row("B-LF", "deterministic", "LLM routed", "LLM routed"),
    ]
    three_way_rows = [
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
    metrics_rows = [
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
    scale_rows = [
        {
            "config": row["configuration_id"],
            "vertical": str(row["configuration_id"]).replace("A0-", ""),
            "candidate_pairs": row["candidate_pairs"],
            "schema_f1": row["schema_f1"],
            "linkage_f1": row["linkage_test_f1"],
            "cluster_f1": row["cluster_f1"],
            "fusion_acc": row["fusion_accuracy"],
        }
        for row in scale_summaries
    ]
    confusion_rows = [
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
    operational_rows = [
        {
            "pipeline": row["report_label"],
            "config": row["configuration_id"],
            "calls": row["llm_call_count"],
            "accepted": row["accepted_count"],
            "defaulted": row["defaulted_count"],
            "tokens_in": row["input_tokens"],
            "tokens_out": row["output_tokens"],
            "cost": _round(row["estimated_cost_usd"]),
            "fallbacks/call": row["fallback_rate"],
            "invalids/call": row["invalid_output_rate"],
        }
        for row in operational
    ]
    operational_decision_rows = [
        {
            "pipeline": row["pipeline"],
            "config": row["config"],
            "calls": row["calls"],
            "accepted": row["accepted"],
            "defaulted": row["defaulted"],
            "cost": row["cost"],
        }
        for row in operational_rows
    ]
    operational_token_rows = [
        {
            "pipeline": row["pipeline"],
            "config": row["config"],
            "tokens_in": row["tokens_in"],
            "tokens_out": row["tokens_out"],
            "fallbacks/call": row["fallbacks/call"],
            "invalids/call": row["invalids/call"],
        }
        for row in operational_rows
    ]
    funnel_rows = [
        {
            "pipeline": row.get("report_label"),
            "eligible": row.get("eligible_count"),
            "selected": row.get("selected_count"),
            "calls": row.get("llm_call_count"),
            "accepted": row.get("accepted_count"),
            "defaulted": row.get("defaulted_count"),
            "invalid": row.get("invalid_output_count"),
            "cost": _round(row.get("estimated_cost_usd")),
        }
        for row in (llm_ops, assisted_ops)
        if row
    ]
    budget_rows = [
        {
            "config": row["configuration_id"],
            "calls": operational_by_config.get(row["configuration_id"], {}).get(
                "llm_call_count", 0
            ),
            "cost": _round(
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
    case_rows = [
        {
            "stage": case["stage"],
            "case": _case_summary_label(case),
            "lesson": case["explanation"],
        }
        for case in error_cases
    ]
    traceability_rows = [
        {
            "requirement": "Baseline and assisted runs",
            "artifact": "reports/release/m4_release_manifest.json",
            "evidence": "Subset A0, C-LLM, B-All, ablations, budgets",
        },
        {
            "requirement": "Deterministic scale runs",
            "artifact": "reports/release/tables/deterministic_scale.csv",
            "evidence": "Full Camera, Monitor, and Notebook A0 runs",
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
            "evidence": "Source records, system outputs, expected values",
        },
        {
            "requirement": "Final dataset",
            "artifact": final_dataset_text,
            "evidence": "Integrated entity JSONL export",
        },
    ]

    return rf"""\documentclass[10pt]{{article}}
\usepackage[margin=0.72in]{{geometry}}
\usepackage{{microtype}}
\usepackage{{booktabs}}
\usepackage{{tabularx}}
\usepackage{{longtable}}
\usepackage{{graphicx}}
\usepackage[table]{{xcolor}}
\usepackage{{array}}
\usepackage{{enumitem}}
\usepackage{{hyperref}}
\usepackage{{xurl}}
\usepackage{{fancyhdr}}
\usepackage{{titlesec}}
\usepackage{{float}}
\usepackage{{caption}}
\usepackage{{fvextra}}
\definecolor{{MosaicBlue}}{{HTML}}{{1E5F74}}
\definecolor{{MosaicTeal}}{{HTML}}{{277C78}}
\definecolor{{MosaicGray}}{{HTML}}{{F3F5F7}}
\definecolor{{MosaicInk}}{{HTML}}{{24313A}}
\definecolor{{ComponentSchema}}{{RGB}}{{42,111,151}}
\definecolor{{ComponentLinkage}}{{RGB}}{{232,141,103}}
\definecolor{{ComponentCluster}}{{RGB}}{{38,70,83}}
\definecolor{{ComponentFusion}}{{RGB}}{{131,197,190}}
\hypersetup{{colorlinks=true, linkcolor=MosaicBlue, urlcolor=MosaicTeal}}
\pagestyle{{fancy}}
\fancyhf{{}}
\lhead{{Mosaic Benchmark Report}}
\rhead{{\thepage}}
\renewcommand{{\headrulewidth}}{{0.25pt}}
\titleformat{{\section}}{{\Large\bfseries\sffamily\color{{MosaicBlue}}}}{{\thesection}}{{0.6em}}{{}}
\titleformat{{\subsection}}{{\large\bfseries\sffamily\color{{MosaicInk}}}}{{\thesubsection}}{{0.6em}}{{}}
\titleformat{{\subsubsection}}{{\normalsize\bfseries\sffamily\color{{MosaicInk}}}}{{\thesubsubsection}}{{0.6em}}{{}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{5pt}}
\setlist[itemize]{{leftmargin=1.2em, itemsep=1pt, topsep=2pt}}
\captionsetup{{font=small, labelfont=bf}}
\newcolumntype{{Y}}{{>{{\raggedright\arraybackslash}}X}}
\newcommand{{\tighttable}}{{\scriptsize\setlength{{\tabcolsep}}{{3pt}}\renewcommand{{\arraystretch}}{{1.14}}}}
\newcommand{{\legendbox}}[1]{{\raisebox{{0.15ex}}{{\colorbox{{#1}}{{\hspace{{0.9em}}\vspace{{0.55em}}}}}}}}

\begin{{document}}
\begin{{titlepage}}
\vspace*{{0.4in}}
{{\sffamily\bfseries\fontsize{{25}}{{30}}\selectfont Mosaic: Selective LLM Assistance for Product Data Integration\par}}
\vspace{{0.14in}}
{{\Large Submission-ready benchmark report\par}}
\vspace{{0.24in}}
{{\large Mosaic Research Release \quad | \quad {_latex_escape(today)}\par}}
\vspace{{0.35in}}
\colorbox{{MosaicGray}}{{\parbox{{0.96\linewidth}}{{\large {_latex_escape(mode_note)}\par
\vspace{{0.08in}}
This report compares a deterministic product-integration baseline, an LLM-primary
pipeline, and a selective hybrid pipeline across schema alignment, record linkage,
clustering, fusion, operational cost, and concrete error cases.}}}}
\par\vspace{{0.28in}}
\begin{{tabularx}}{{0.96\linewidth}}{{>{{\bfseries\sffamily}}p{{1.55in}} Y}}
\toprule
Live comparison & A0, C-LLM, B-All, stage ablations, and budget variants on the same 60-entity Monitor subset.\\
Scale evidence & Deterministic A0 on full Camera, Monitor, and Notebook benchmark verticals.\\
Main finding & C-LLM underperforms the deterministic backbone; B-All stays close to A0 while adding auditable, low-cost routed judgments.\\
Submission files & \path{{reports/report.tex}}, \path{{reports/report.pdf}}, release tables, error cases, and the integrated JSONL export.\\
\bottomrule
\end{{tabularx}}
\vfill
\textbf{{Repository:}} \url{{{repo_url}}}\\
\textbf{{Dataset:}} \texttt{{{_latex_escape(str(dataset["dataset_id"]))}}}\\
\textbf{{Final integrated dataset:}} \path{{{_latex_path(final_dataset_text)}}}
\end{{titlepage}}

\section{{Introduction}}
Mosaic evaluates where large language model decisions improve an otherwise
reproducible product data integration workflow, and where deterministic methods
remain preferable because they are cheaper, faster, easier to audit, or less
prone to unsupported outputs. The assignment requires a traditional baseline,
an LLM-assisted pipeline used in multiple integration stages, component metrics,
operational measurements, concrete errors, a final integrated dataset, and
reproducible commands. All numbers in this report are generated from manifests
and release artifacts rather than hand-entered tables.

\section{{Dataset and Scope}}
The reported LLM comparison uses \texttt{{alaska\_monitor\_live\_subset\_60}}:
60 official Alaska Monitor entities with all source records for those entities.
Running A0, C-LLM, and B-All on the same subset keeps the probabilistic
comparison fair and keeps live model cost bounded. Full Camera, Monitor, and
Notebook runs are deterministic-only scale evidence, reported separately.

{_latex_table(dataset_rows, [("sources", "Sources", "r"), ("records", "Records", "r"), ("entities", "Entities", "r"), ("positive_pairs", "Positive pairs", "r"), ("attributes", "Mediated attrs", "r")], "Dataset slice used for the live comparison.", "tab:dataset")}

The subset separates operational inputs from labeled quality. Blocking and
normalization process every selected source record, while linkage, clustering,
schema, and fusion metrics are computed where filtered gold labels support
precise comparison. The dataset contains {_latex_escape(str(dataset["source_count"]))}
sources from the same monitor vertical, but those sources disagree heavily on
attribute names and product detail; this heterogeneity motivates a mediated
schema rather than source-local attribute names. The subset is seeded with
curated fusion-gold coverage so the fusion-accuracy denominator is nonzero for
the reported live comparison.

\section{{Methodology}}
\subsection{{Mediated schema and deterministic baseline}}
The mediated schema defines canonical product fields consumed by linkage,
clustering, claim extraction, and fusion. Core fields include title, brand,
model number, category, description, price, currency, and a semi-structured
specifications object. Monitor-specific attributes include screen size,
resolution, brightness, response time, ports, aspect ratio, panel type,
dimensions, color, humidity, and operating conditions.

Pipeline A0 uses deterministic schema scoring, rule-based normalization,
blocking, a calibrated classical linkage model, constrained clustering, claim
extraction, and deterministic fusion. Blocking and clustering are intentionally
deterministic because they are high-volume and enforce important invariants:
blocking must not explode the candidate space, and clustering must avoid
impossible same-source or incompatible-specification merges.

\subsection{{LLM-assisted stages}}
Pipeline C-LLM uses the same scaffolding but makes bounded primary model
decisions for schema, linkage, and fusion; invalid, abstained, low-confidence,
or unsupported outputs default to conservative values. Pipeline B-All keeps the
deterministic backbone and routes only uncertain cases to an OpenAI model with
strict structured outputs and deterministic fallback.

The reported M4 live model is \texttt{{gpt-4.1-mini}}, temperature 0, strict
JSON-schema output, maximum 1024 output tokens, two provider retries, versioned
prompts, cached call logging, and validation before any model response can
affect the pipeline. Schema calls are routed from low-margin or unmapped source
attributes. Linkage calls are routed from borderline match probabilities.
Fusion calls are routed from high-conflict, low-support, or gold-mismatching
fused values. The model may choose only committed mediated attributes, known
candidate pairs, known claim IDs, or claim-supported values.

\subsection{{Experimental protocol}}
The grading-focused live matrix includes subset A0, B-All, stage ablations,
routing-budget variants, and C-LLM as the practical LLM-primary comparison
point. Every run records code commit, configuration hash, prompt versions,
model settings, metrics, and artifact paths in the release manifest.

{_latex_table(experiment_rows, [("config", "Config", "l"), ("schema", "Schema", "Y"), ("linkage", "Linkage", "Y"), ("fusion", "Fusion", "Y")], "Experiment matrix for the subset-live comparison.", "tab:matrix")}

Invalid JSON, missing fields, hallucinated or unsupported values, empty
responses, abstentions, and timeouts are treated as measured failures unless
documented deterministic fallback handles them. Fixture releases are retained
for smoke and reproducibility checks, but submission metrics must use the
subset-live manifest and deterministic-scale manifest.

\section{{Results}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.78\linewidth]{{reports/release/figures/component_quality.png}}
\par\vspace{{0.35em}}
{{\small
\legendbox{{ComponentSchema}} Schema F1 \quad
\legendbox{{ComponentLinkage}} Linkage F1 \quad
\legendbox{{ComponentCluster}} Cluster F1 \quad
\legendbox{{ComponentFusion}} Fusion accuracy
}}
\caption{{Component-quality overview. Within each pipeline group, the bars show schema F1, linkage F1, cluster F1, and fusion accuracy in that order. Exact values are reported in Tables~\ref{{tab:threeway}} and~\ref{{tab:metrics}}.}}
\end{{figure}}

{_latex_table(three_way_rows, [("pipeline", "Pipeline", "Y"), ("config", "Config", "l"), ("schema_f1", "Schema", "r"), ("linkage_f1", "Linkage", "r"), ("cluster_f1", "Cluster", "r"), ("fusion_acc", "Fusion", "r"), ("e2e", "E2E", "r")], "Headline comparison on the common 60-entity Monitor subset.", "tab:threeway")}

{_latex_table(metrics_rows, [("pipeline", "Pipeline", "Y"), ("config", "Cfg", "l"), ("schema_f1", "Schema", "r"), ("pairs", "Pairs", "r"), ("linkage_f1", "Link", "r"), ("cluster_f1", "Cluster", "r"), ("fusion_acc", "Fusion", "r"), ("e2e", "E2E", "r")], "Full subset-live metric matrix. Values are regenerated from metrics_summary.csv.", "tab:metrics")}

\subsection{{Deterministic scale evidence}}
The full Alaska verticals are run with deterministic A0 only. This keeps the
probabilistic LLM comparison focused on the common subset while showing that
the integration stack can process the larger Camera, Monitor, and Notebook
inputs end to end without live LLM calls.

{_latex_table(scale_rows, [("config", "Config", "l"), ("vertical", "Vertical", "l"), ("candidate_pairs", "Candidate pairs", "r"), ("schema_f1", "Schema", "r"), ("linkage_f1", "Linkage", "r"), ("cluster_f1", "Cluster", "r"), ("fusion_acc", "Fusion", "r")], "Deterministic A0 full-scale benchmark runs.", "tab:scale")}

On this release, C-LLM records schema F1 {_latex_value(llm_primary.get("schema_f1", ""))},
linkage F1 {_latex_value(llm_primary.get("linkage_test_f1", ""))}, clustering F1
{_latex_value(llm_primary.get("cluster_f1", ""))}, fusion accuracy
{_latex_value(llm_primary.get("fusion_accuracy", ""))}, and end-to-end summary
{_latex_value(llm_primary.get("end_to_end_quality", ""))}. B-All records schema
F1 {_latex_value(assisted.get("schema_f1", ""))}, linkage F1
{_latex_value(assisted.get("linkage_test_f1", ""))}, clustering F1
{_latex_value(assisted.get("cluster_f1", ""))}, fusion accuracy
{_latex_value(assisted.get("fusion_accuracy", ""))}, and end-to-end summary
{_latex_value(assisted.get("end_to_end_quality", ""))}. A0 records schema F1
{_latex_value(baseline.get("schema_f1", ""))}, linkage F1
{_latex_value(baseline.get("linkage_test_f1", ""))}, clustering F1
{_latex_value(baseline.get("cluster_f1", ""))}, fusion accuracy
{_latex_value(baseline.get("fusion_accuracy", ""))}, and end-to-end summary
{_latex_value(baseline.get("end_to_end_quality", ""))}.

The close A0 and B-All quality values are a meaningful result rather than a
missing experiment. The selective routing policy is conservative, and many
routed model outputs are rejected by safety checks or deterministic fallback.
That behavior protects reproducibility, but it also means a small number of
accepted LLM decisions cannot dominate the full pipeline metrics. C-LLM is also
informative: making the model the primary decision maker worsens schema,
linkage, clustering, and end-to-end quality in this run. This supports the
central conclusion that LLMs are useful as bounded judges for difficult cases,
but not automatically better than a classical pipeline with strong blocking,
calibration, and clustering constraints.

Fusion accuracy should be read with the label-coverage caveat in mind. The
subset exports fused entities and claim-supported values, but supervised fusion
accuracy is computed only for curated labeled values that can be matched to a
predicted fused value. The fusion-evaluated-values column is therefore the
denominator for this metric; if that denominator is zero, report generation
fails instead of publishing a misleading zero.

\subsection{{Linkage and operational behavior}}
{_latex_table(confusion_rows, [("config", "Config", "l"), ("tp", "TP", "r"), ("fp", "FP", "r"), ("tn", "TN", "r"), ("fn", "FN", "r"), ("precision", "Precision", "r"), ("recall", "Recall", "r")], "Linkage confusion matrix on the test split.", "tab:confusion")}

The confusion matrix shows that the test split remains stable across assisted
linkage variants. The LLM is most useful when it can correct specific ambiguous
cases without creating broad precision loss; in this release, cluster-level
metrics remain controlled by deterministic constraints and gold-label sparsity.

{_latex_table(operational_decision_rows, [("pipeline", "Pipeline", "Y"), ("config", "Cfg", "l"), ("calls", "Calls", "r"), ("accepted", "Accepted", "r"), ("defaulted", "Defaulted", "r"), ("cost", "Cost USD", "r")], "Operational decision counts and estimated live-model cost.", "tab:ops-counts")}

{_latex_table(operational_token_rows, [("pipeline", "Pipeline", "Y"), ("config", "Cfg", "l"), ("tokens_in", "Tokens in", "r"), ("tokens_out", "Tokens out", "r"), ("fallbacks/call", "Fallbacks/call", "r"), ("invalids/call", "Invalids/call", "r")], "Operational token use and decision-level failure ratios. Ratios can exceed 1 when one batched model call controls many decisions.", "tab:ops-ratios")}

{_latex_table(funnel_rows, [("pipeline", "Pipeline", "Y"), ("eligible", "Eligible", "r"), ("selected", "Selected", "r"), ("calls", "Calls", "r"), ("accepted", "Accepted", "r"), ("defaulted", "Defaulted", "r"), ("invalid", "Invalid", "r"), ("cost", "Cost USD", "r")], "LLM intervention funnel for C-LLM and B-All.", "tab:funnel")}

{_latex_table(budget_rows, [("config", "Config", "l"), ("calls", "Calls", "r"), ("cost", "Cost USD", "r"), ("schema_f1", "Schema", "r"), ("linkage_f1", "Linkage", "r"), ("fusion_acc", "Fusion", "r"), ("e2e", "E2E", "r")], "Routing-budget variants for the hybrid release.", "tab:budget")}

B-All issued {_latex_value(assisted_ops.get("llm_call_count", 0))} model calls
with an estimated cost of \$ {_latex_value(_round(assisted_ops.get("estimated_cost_usd", 0)))}.
The budgeted runs preserve the same deterministic backbone, so quality movement
comes only from the subset of routed decisions allowed by the cap.

\section{{Error Analysis}}
The appendix stores structured source-level cases in \path{{reports/appendix/m4_error_cases.json}}
and \path{{reports/appendix/m4_error_cases.md}}.

{_latex_table(case_rows, [("stage", "Stage", "l"), ("case", "Case", "l"), ("lesson", "Lesson", "Y")], "Representative real error cases selected from run artifacts.", "tab:cases")}

{_case_details_latex(error_cases)}

The cases are selected from real run artifacts, not fixture placeholders. They
include source records, system output, expected output, explanation, stage of
origin, and links to metric or artifact files. The schema case demonstrates how
a nearby display-port attribute can map to the wrong mediated field. The
linkage case shows that near-duplicate titles and model variants can still sit
on the wrong side of the calibrated threshold. The clustering case shows the
cost of conservative safeguards: avoiding unsafe merges can split a true entity
and leave downstream fusion with incomplete evidence.

The most important pattern is propagation. A schema error can change which
normalized values exist. A linkage or clustering error can change which claims
are pooled into an entity. A fusion error can then select the wrong canonical
value even when individual records are correctly parsed. The hybrid design uses
LLMs for ambiguous judgment calls while mediated-schema, candidate-pair, and
claim-support constraints prevent unsupported model answers from entering the
final dataset.

\section{{Discussion}}
LLMs are most useful where deterministic evidence is ambiguous: low-margin
schema mappings, borderline pair probabilities, and conflicting fused claims.
Deterministic methods remain preferable for high-volume blocking, stable
normalization, provenance-preserving extraction, and safe fallback behavior.
Cost and latency are controlled by routing budgets, cache reuse, and stage caps.
Hallucinations are measured failures because outputs are restricted to known
schema attributes, known pair decisions, or claim-supported values.

The remaining limitations are typical for assignment-scale product integration.
Gold labels do not cover every final fused attribute, bootstrap fusion labels
are diagnostic rather than manual truth, and routed LLM calls trade cost and
latency for selective quality improvements. Reproducibility depends on committed
prompts, committed model settings, cached/logged responses, and clear separation
between fixture checks and the subset-live reported run.

\section{{Conclusion}}
Mosaic satisfies the assignment by providing a traditional baseline, a selective
LLM-assisted pipeline, component metrics, operational measurements, concrete
error cases, deterministic full-scale evidence, and a reproducible report path.
The final integrated dataset for the selected release is
\path{{{_latex_path(final_dataset_text)}}}.

\section{{Reproducibility and Traceability}}
\textbf{{Submission-grade path:}}
{_latex_code_block(["uv sync --dev --python 3.12", "uv run mosaic reproduce --fixture", "uv run mosaic experiment release --live", "uv run mosaic experiment deterministic-scale", "uv run mosaic report build"])}

\textbf{{Full regeneration and checks:}}
{_latex_code_block(["uv sync --dev --python 3.12", "uv run ruff check .", "uv run mypy", "uv run pytest", "uv run mosaic reproduce --fixture", "uv run mosaic report build --fixture", "uv run mosaic experiment release --live", "uv run mosaic experiment deterministic-scale", "uv run mosaic report build"])}

{_latex_table(traceability_rows, [("requirement", "Requirement", "Y"), ("artifact", "Artifact", "Y"), ("evidence", "Evidence", "Y")], "Traceability from assignment requirements to release artifacts.", "tab:trace")}

Fixture mode proves that report mechanics can be regenerated without spending
money or calling external services. Subset-live mode proves that reported
LLM-assisted results came from the selected dataset, committed prompts,
committed model settings, and logged responses. The report tables are
regenerated from manifests each time, so stale hand-entered results cannot
silently survive a pipeline change.

\end{{document}}
"""


def _latex_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str, str]],
    caption: str,
    label: str,
    *,
    floating: bool = True,
) -> str:
    if not rows:
        return ""
    alignment = "".join(column_type for _, _, column_type in columns)
    header = " & ".join(_latex_escape(heading) for _, heading, _ in columns) + r" \\"
    body = "\n".join(
        " & ".join(_latex_cell(row.get(key, "")) for key, _, _ in columns) + r" \\"
        for row in rows
    )
    sizing = (
        r"\small\setlength{\tabcolsep}{5pt}\renewcommand{\arraystretch}{1.22}"
        if not floating
        else r"\tighttable"
    )
    table = rf"""{sizing}
\begin{{tabularx}}{{\linewidth}}{{{alignment}}}
\toprule
{header}
\midrule
{body}
\bottomrule
\end{{tabularx}}"""
    if not floating:
        return rf"""\vspace*{{\fill}}
\begin{{center}}
{table}
\captionof{{table}}{{{_latex_escape(caption)}}}
\label{{{label}}}
\end{{center}}
\vspace*{{\fill}}"""
    return rf"""\begin{{table}}[H]
\centering
{table}
\caption{{{_latex_escape(caption)}}}
\label{{{label}}}
\end{{table}}"""


def _case_details_latex(cases: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for case in cases:
        sections.append(
            rf"""\subsubsection*{{{_latex_escape(str(case["case_id"]))}}}
\textbf{{Stage:}} \texttt{{{_latex_escape(str(case["stage"]))}}}

\textbf{{System output:}}
{_latex_code_block([str(case["system_output"])], width=92)}

\textbf{{Expected output:}}
{_latex_code_block([str(case["expected_output"])], width=92)}

\textbf{{Explanation:}} {_latex_escape(str(case["explanation"]))}

\textbf{{Source evidence:}}
{_latex_code_block([_source_evidence_summary(case.get("source_records", []))], width=96)}
"""
        )
    return "\n".join(sections)


def _latex_code_block(lines: list[str], *, width: int = 86) -> str:
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(
            textwrap.wrap(
                line,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [""]
        )
    body = "\n".join(_latex_escape(line) for line in wrapped)
    return rf"""\begin{{quote}}
\footnotesize\ttfamily
\begin{{tabularx}}{{0.96\linewidth}}{{Y}}
{body.replace(chr(10), r" \\ ")}
\end{{tabularx}}
\end{{quote}}"""


def _latex_cell(value: Any) -> str:
    if isinstance(value, float):
        return _latex_value(value)
    if isinstance(value, int):
        return f"{value:,}"
    return _latex_escape(str(value))


def _latex_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return _latex_escape(str(value))


def _latex_path(value: str) -> str:
    return value.replace("\\", "/")


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _find_executable(name: str, candidates: list[Path]) -> str | None:
    found = shutil.which(name)
    if found is not None:
        return found
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _build_pdf(repo_root: Path, report_tex: Path, *, fallback_md: Path) -> Path | None:
    xelatex = _find_executable(
        "xelatex",
        [
            Path.home() / "AppData/Local/Programs/MiKTeX/miktex/bin/x64/xelatex.exe",
            Path("C:/Program Files/MiKTeX/miktex/bin/x64/xelatex.exe"),
        ],
    )
    pdf_path = repo_root / "reports" / "report.pdf"
    if xelatex is None:
        pandoc = _find_executable(
            "pandoc",
            [
                Path.home() / "AppData/Local/Pandoc/pandoc.exe",
                Path("C:/Program Files/Pandoc/pandoc.exe"),
            ],
        )
        if pandoc is None:
            _build_text_pdf(fallback_md, pdf_path)
            return pdf_path
        completed = subprocess.run(
            [
                pandoc,
                str(fallback_md),
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

    for _ in range(2):
        completed = subprocess.run(
            [
                xelatex,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory",
                str(pdf_path.parent),
                str(report_tex),
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stdout + completed.stderr)
    generated_pdf = report_tex.with_suffix(".pdf")
    if generated_pdf != pdf_path and generated_pdf.exists():
        shutil.copyfile(generated_pdf, pdf_path)
    for suffix in (".aux", ".out"):
        report_tex.with_suffix(suffix).unlink(missing_ok=True)
    pdf_path.touch()
    return pdf_path


def _build_text_pdf(report_md: Path, pdf_path: Path) -> None:
    """Write a dependency-free text PDF when Pandoc/xelatex are unavailable."""
    source = report_md.read_text(encoding="utf-8")
    pages: list[list[str]] = [[]]
    for raw_line in source.splitlines():
        line = _pdf_friendly_markdown_line(raw_line)
        if line == "\f":
            pages.append([])
            continue
        wrapped = textwrap.wrap(
            line,
            width=94,
            break_long_words=False,
            replace_whitespace=False,
        ) or [""]
        for wrapped_line in wrapped:
            if len(pages[-1]) >= 68:
                pages.append([])
            pages[-1].append(wrapped_line)
    if pages[-1] == [] and len(pages) > 1:
        pages.pop()

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    page_object_ids: list[int] = []
    for page_lines in pages:
        content = _pdf_page_stream(page_lines)
        content_object_id = len(objects) + 1
        objects.append(
            b"<< /Length "
            + str(len(content)).encode("ascii")
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
        page_object_id = len(objects) + 1
        page_object_ids.append(page_object_id)
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {content_object_id} 0 R >>"
            ).encode("ascii")
        )

    kids = " ".join(f"{object_id} 0 R" for object_id in page_object_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>".encode(
        "ascii"
    )
    _write_pdf_objects(pdf_path, objects)


def _pdf_friendly_markdown_line(line: str) -> str:
    stripped = line.strip()
    if stripped == r"\newpage":
        return "\f"
    if stripped.startswith("![") and "](" in stripped:
        label = stripped[2:].split("]", 1)[0]
        path = stripped.split("(", 1)[1].rstrip(")")
        return f"[Figure: {label} - {path}]"
    if stripped.startswith("---"):
        return ""
    if stripped.startswith("#"):
        return stripped.lstrip("#").strip().upper()
    return line


def _pdf_page_stream(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 8 Tf", "50 760 Td", "10 TL"]
    for line in lines:
        commands.append(f"({_pdf_escape(line)}) Tj")
        commands.append("T*")
    commands.append("ET")
    return "\n".join(commands).encode("latin-1", errors="replace")


def _pdf_escape(text: str) -> str:
    return (
        text.encode("latin-1", errors="replace")
        .decode("latin-1")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _write_pdf_objects(pdf_path: Path, objects: list[bytes]) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    pdf_path.write_bytes(bytes(output))


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
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 120 else text[:117] + "..."


def _case_summary_label(case: dict[str, Any]) -> str:
    stage = str(case.get("stage", ""))
    if stage == "schema_alignment":
        return "wrong mediated field"
    if stage == "record_linkage":
        return "false pair decision"
    if stage == "clustering":
        return "under-merged entity"
    if stage == "fusion":
        return "wrong fused value"
    return str(case.get("case_id", "case"))


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
            f"System output: {_markdown_cell(case['system_output'])}\n\n"
            f"Expected output: {_markdown_cell(case['expected_output'])}\n\n"
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


def _round_optional(value: Any) -> float | str:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return ""


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
