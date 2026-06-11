import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from mosaic.alaska import (
    local_alaska_candidate_metrics,
    local_alaska_dataset_configs,
    select_best_candidate,
    write_dataset_config,
)
from mosaic.ingestion import ingest_dataset
from mosaic.llm_gateway import LLMGateway
from mosaic.m1_models import load_dataset_config
from mosaic.m2_models import PipelineRunResult, load_baseline_pipeline_config
from mosaic.m2_pipeline import StageName, run_baseline_pipeline
from mosaic.m3_models import (
    FusionLLMDecision,
    LinkageLLMDecision,
    SchemaLLMDecision,
    load_llm_model_config,
    load_m3_experiment_config,
)
from mosaic.m3_pipeline import run_assisted_pipeline
from mosaic.m4_release import build_m4_report, run_m4_release
from mosaic.profiling import profile_dataset, write_profile_summary_table
from mosaic.schema_validation import validate_mediated_schema

app = typer.Typer(help="Mosaic reproducible research pipeline CLI.")
dataset_app = typer.Typer(help="Dataset discovery, selection, profiling, and ingestion.")
pipeline_app = typer.Typer(help="End-to-end pipeline execution commands.")
report_app = typer.Typer(help="Report generation commands.")
schema_app = typer.Typer(help="Mediated schema commands.")
claims_app = typer.Typer(help="Claim extraction commands.")
export_app = typer.Typer(help="Export commands.")
experiment_app = typer.Typer(help="Experiment execution commands.")
app.add_typer(dataset_app, name="dataset")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(report_app, name="report")
app.add_typer(schema_app, name="schema")
app.add_typer(claims_app, name="claims")
app.add_typer(export_app, name="export")
app.add_typer(experiment_app, name="experiment")

REQUIRED_SCAFFOLD_PATHS = (
    ".env.example",
    ".github/workflows/python.yml",
    "Makefile",
    "pyproject.toml",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/risk_register.md",
    "apps/api",
    "apps/worker",
    "apps/web",
    "packages/integration-core/src/mosaic",
    "configs/datasets",
    "configs/schemas",
    "configs/pipelines",
    "configs/models",
    "configs/thresholds",
    "configs/experiments",
    "prompts/schema",
    "prompts/normalization",
    "prompts/linkage",
    "prompts/fusion",
    "data/README.md",
    "artifacts/README.md",
    "artifacts/reports",
    "reports",
    "tests",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _missing_paths() -> list[str]:
    root = _repo_root()
    return [relative for relative in REQUIRED_SCAFFOLD_PATHS if not (root / relative).exists()]


@app.command()
def doctor(
    dev: Annotated[bool, typer.Option(help="Include development scaffold checks.")] = False,
) -> None:
    """Validate that the M0 scaffold is present."""
    missing = _missing_paths()
    if missing:
        for relative in missing:
            typer.echo(f"missing: {relative}")
        raise typer.Exit(code=1)

    mode = "development" if dev else "standard"
    typer.echo(f"Mosaic M0 scaffold ready ({mode}).")


@app.command()
def reproduce(
    fixture: Annotated[
        bool,
        typer.Option(help="Run the fixture/scaffold reproduction check for M0."),
    ] = False,
) -> None:
    """Reserve the full reproduction contract and run the M0 fixture check."""
    if not fixture:
        typer.echo("M0 supports fixture reproduction only. Use --fixture.")
        raise typer.Exit(code=1)

    root = _repo_root()
    missing = _missing_paths()
    if missing:
        for relative in missing:
            typer.echo(f"missing: {relative}")
        raise typer.Exit(code=1)

    fixture_config = root / "configs" / "datasets" / "fixture_dataset.json"
    if fixture_config.exists():
        config = load_dataset_config(fixture_config)
        ingest_dataset(config, root)
        profile_dataset(config, root, evidence_level="fixture")

    fixture_pipeline_config = root / "configs" / "pipelines" / "fixture_m2.json"
    if fixture_pipeline_config.exists():
        pipeline_config = load_baseline_pipeline_config(fixture_pipeline_config)
        result = run_baseline_pipeline(pipeline_config, root)
        typer.echo(f"Fixture baseline pipeline completed: {result.run_id}")

    typer.echo("Fixture reproduction scaffold completed.")


@dataset_app.command("select")
def dataset_select(
    benchmark: Annotated[str, typer.Option(help="Benchmark to rank.")] = "alaska",
) -> None:
    """Profile local candidate domains and write the M1 score table/report."""
    if benchmark != "alaska":
        typer.echo(f"unsupported benchmark: {benchmark}")
        raise typer.Exit(code=1)

    root = _repo_root()
    local_configs = local_alaska_dataset_configs(root)
    if not local_configs:
        typer.echo(
            "local Alaska records were not found. Place the benchmark under "
            "data/raw/alaska/<vertical>/extracted/ and rerun this command."
        )
        raise typer.Exit(code=1)

    local_metrics = []
    configs_by_vertical = {config.vertical: config for config in local_configs}
    for dataset_config in local_configs:
        local_metrics.append(local_alaska_candidate_metrics(dataset_config, root))

    table_path = write_profile_summary_table(local_metrics, root)
    try:
        selected = select_best_candidate(local_metrics)
    except ValueError as exc:
        typer.echo(str(exc))
        typer.echo(f"wrote local selection score table: {table_path.relative_to(root)}")
        raise typer.Exit(code=1) from exc
    selected_path = write_dataset_config(
        configs_by_vertical[selected.vertical],
        root / "configs" / "datasets" / "selected_dataset.json",
    )
    typer.echo(f"wrote selected dataset config: {selected_path.relative_to(root)}")
    typer.echo(
        f"selected Alaska vertical: {selected.vertical} "
        f"(gate={selected.satisfies_assignment_gate}, score={selected.selection_score})"
    )
    typer.echo(f"wrote local selection score table: {table_path.relative_to(root)}")


@dataset_app.command("ingest")
def dataset_ingest(
    config: Annotated[
        Path | None,
        typer.Option(help="Dataset config JSON path."),
    ] = None,
    fixture: Annotated[bool, typer.Option(help="Use the committed M1 fixture config.")] = False,
) -> None:
    """Ingest source records into immutable Parquet artifacts."""
    root = _repo_root()
    config_path = _resolve_dataset_config(root, config, fixture)
    dataset_config = load_dataset_config(config_path)
    manifest = ingest_dataset(dataset_config, root)
    typer.echo(
        f"ingested {manifest.total_record_count} records into "
        f"{manifest.raw_artifacts['source_records']}"
    )


@dataset_app.command("profile")
def dataset_profile(
    config: Annotated[
        Path | None,
        typer.Option(help="Dataset config JSON path."),
    ] = None,
    fixture: Annotated[bool, typer.Option(help="Use the committed M1 fixture config.")] = False,
) -> None:
    """Profile ingested source records."""
    root = _repo_root()
    config_path = _resolve_dataset_config(root, config, fixture)
    dataset_config = load_dataset_config(config_path)
    records_path = (
        root / "data" / "interim" / "m1" / dataset_config.dataset_id / "source_records.parquet"
    )
    if not records_path.exists():
        ingest_dataset(dataset_config, root)
    result = profile_dataset(
        dataset_config,
        root,
        evidence_level="fixture" if fixture else "local_profile",
    )
    typer.echo(f"wrote source profiles: {result.source_attributes_path.relative_to(root)}")


@schema_app.command("validate")
def schema_validate(
    schema: Annotated[
        Path,
        typer.Option(help="Mediated schema JSON path."),
    ] = Path("configs/schemas/mediated_schema.json"),
) -> None:
    """Validate the mediated schema contract."""
    root = _repo_root()
    schema_path = schema if schema.is_absolute() else root / schema
    mediated_schema = validate_mediated_schema(schema_path)
    typer.echo(
        f"validated mediated schema {mediated_schema.schema_version} "
        f"with {len(mediated_schema.attributes)} attributes"
    )


@schema_app.command("propose")
def schema_propose(
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Run deterministic schema proposal and write mapping artifacts."""
    result = _run_pipeline_stage(config, "schema")
    typer.echo(f"wrote schema mapping artifacts for {result.run_id}")


@schema_app.command("evaluate")
def schema_evaluate(
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Run deterministic schema proposal and schema metrics."""
    result = _run_pipeline_stage(config, "schema")
    typer.echo(f"wrote schema metrics for {result.run_id}")


@app.command("normalize")
def normalize(
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Normalize mapped source records with deterministic rules."""
    result = _run_pipeline_stage(config, "normalize")
    typer.echo(f"wrote normalized records for {result.run_id}")


@app.command("block")
def block(
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Generate deterministic candidate pairs with blocking rule attribution."""
    result = _run_pipeline_stage(config, "block")
    typer.echo(f"wrote candidate pairs for {result.run_id}")


@app.command("match")
def match(
    pipeline: Annotated[
        str,
        typer.Option(help="Matching pipeline to run."),
    ] = "baseline",
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Generate pairwise features and baseline match predictions."""
    if pipeline not in {"baseline", "llm-assisted"}:
        typer.echo("supported pipelines: baseline, llm-assisted")
        raise typer.Exit(code=1)
    if pipeline == "llm-assisted":
        result = _run_assisted_pipeline_stage(config, "match")
        typer.echo(f"wrote assisted pair predictions for {result.run_id}")
    else:
        result = _run_pipeline_stage(config, "match")
        typer.echo(f"wrote pair predictions for {result.run_id}")


@app.command("cluster")
def cluster(
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Build baseline entity clusters."""
    result = _run_pipeline_stage(config, "cluster")
    typer.echo(f"wrote entity clusters for {result.run_id}")


@claims_app.command("extract")
def claims_extract(
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Extract attribute claims from baseline clusters."""
    result = _run_pipeline_stage(config, "claims")
    typer.echo(f"wrote attribute claims for {result.run_id}")


@app.command("fuse")
def fuse(
    pipeline: Annotated[
        str,
        typer.Option(help="Fusion pipeline to run."),
    ] = "baseline",
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Fuse deterministic claims into baseline integrated entities."""
    if pipeline not in {"baseline", "llm-assisted"}:
        typer.echo("supported pipelines: baseline, llm-assisted")
        raise typer.Exit(code=1)
    if pipeline == "llm-assisted":
        result = _run_assisted_pipeline_stage(config, "export")
        typer.echo(f"wrote assisted fused values for {result.run_id}")
    else:
        result = _run_pipeline_stage(config, "fuse")
        typer.echo(f"wrote fused values for {result.run_id}")


@app.command("evaluate")
def evaluate(
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Run baseline pipeline through component metric generation."""
    result = _run_pipeline_stage(config, "evaluate")
    typer.echo(f"wrote baseline metrics for {result.run_id}")


@export_app.command("integrated")
def export_integrated(
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Export baseline integrated entities."""
    result = _run_pipeline_stage(config, "export")
    typer.echo(f"wrote integrated entity export for {result.run_id}")


@pipeline_app.command("run")
def pipeline_run(
    config: Annotated[
        Path,
        typer.Option(help="Baseline pipeline config JSON path."),
    ] = Path("configs/pipelines/baseline_m2.json"),
) -> None:
    """Run a baseline pipeline config or an M3 assisted experiment config."""
    if _looks_like_m3_experiment_config(config):
        result = _run_assisted_pipeline_stage(config, "export")
        typer.echo(f"assisted pipeline completed: {result.run_id}")
    else:
        result = _run_pipeline_stage(config, "export")
        typer.echo(f"baseline pipeline completed: {result.run_id}")


@experiment_app.command("run")
def experiment_run(
    config: Annotated[
        Path,
        typer.Argument(help="Experiment config JSON path."),
    ] = Path("configs/experiments/m3_llm_assisted_example.json"),
) -> None:
    """Run an experiment configuration."""
    result = _run_assisted_pipeline_stage(config, "export")
    typer.echo(f"experiment completed: {result.run_id}")


@experiment_app.command("live-smoke")
def experiment_live_smoke(
    config: Annotated[
        Path,
        typer.Argument(help="Experiment config JSON path."),
    ] = Path("configs/experiments/m3_llm_assisted_example.json"),
) -> None:
    """Run one live schema/linkage/fusion LLM call when explicitly configured."""
    root = _repo_root()
    config_path = config if config.is_absolute() else root / config
    experiment_config = load_m3_experiment_config(config_path)
    model_config = load_llm_model_config(root / experiment_config.model_config_path)
    if model_config.execution_mode not in {"live", "cache_or_live"}:
        typer.echo("live smoke skipped: execution_mode is not live or cache_or_live")
        return
    if not model_config.model:
        typer.echo("live smoke skipped: model is not configured")
        return
    if not os.environ.get("OPENAI_API_KEY"):
        typer.echo("live smoke skipped: OPENAI_API_KEY is not set")
        return

    run_id = "run_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ_live_smoke")
    gateway = LLMGateway(model_config, root, run_id)
    calls: list[tuple[str, str, type[BaseModel], str, dict[str, Any]]] = [
        (
            "schema",
            experiment_config.prompt_versions.schema_prompt,
            SchemaLLMDecision,
            "mosaic_schema_decision",
            {
                "attribute_name": "maker",
                "deterministic_candidates": [
                    {"target_attribute_name": "brand", "score_total": 0.82}
                ],
                "allowed_targets": ["brand", "UNMAPPED", "ABSTAIN"],
            },
        ),
        (
            "linkage",
            experiment_config.prompt_versions.linkage,
            LinkageLLMDecision,
            "mosaic_linkage_decision",
            {
                "candidate_pair_id": "smoke_pair",
                "left_record": {"brand": "AOC", "model_number": "24B1"},
                "right_record": {"brand": "AOC", "model_number": "24B1"},
                "match_probability": 0.52,
            },
        ),
        (
            "fusion",
            experiment_config.prompt_versions.fusion,
            FusionLLMDecision,
            "mosaic_fusion_decision",
            {
                "entity_id": "smoke_entity",
                "attribute": "brand",
                "candidate_claims": [
                    {
                        "claim_id": "c1",
                        "source_id": "source_a",
                        "raw_value": "AOC",
                        "normalized_value": "AOC",
                        "unit": None,
                    }
                ],
                "allowed_outputs": ["AOC", "ABSTAIN"],
            },
        ),
    ]
    for stage, prompt_version, output_model, schema_name, payload in calls:
        result = gateway.call_structured(
            stage=stage,
            prompt_version=prompt_version,
            template_path=root / prompt_version / "template.md",
            payload=payload,
            output_model=output_model,
            schema_name=schema_name,
        )
        if result.validation_status != "valid":
            typer.echo(f"live smoke failed at {stage}: {result.failure_type}")
            raise typer.Exit(code=1)
    typer.echo(f"live smoke completed: {run_id}")


@experiment_app.command("release")
def experiment_release(
    live: Annotated[
        bool,
        typer.Option(help="Run the full reported M4 matrix with live/cache-or-live OpenAI calls."),
    ] = False,
    fixture: Annotated[
        bool,
        typer.Option(help="Run the fixture-equivalent release matrix for CI-safe reproduction."),
    ] = False,
    manifest: Annotated[
        Path | None,
        typer.Option(help="Output release manifest path."),
    ] = None,
) -> None:
    """Run the M4 academic release experiment matrix."""
    if live and fixture:
        typer.echo("choose either --live or --fixture, not both")
        raise typer.Exit(code=1)
    root = _repo_root()
    try:
        manifest_path = run_m4_release(root, live=live, fixture=fixture, manifest_path=manifest)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote M4 release manifest: {manifest_path.relative_to(root)}")


@report_app.command("build")
def report_build(
    manifest: Annotated[
        Path | None,
        typer.Option(help="M4 release manifest to build from."),
    ] = None,
    fixture: Annotated[
        bool,
        typer.Option(help="Force fixture-equivalent report generation."),
    ] = False,
    no_pdf: Annotated[
        bool,
        typer.Option(help="Skip PDF generation and render check."),
    ] = False,
) -> None:
    """Build M4 release tables, figures, report source, and PDF when possible."""
    root = _repo_root()
    try:
        outputs = build_m4_report(
            root,
            manifest_path=manifest,
            fixture=fixture,
            build_pdf=not no_pdf,
        )
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    for label, path in outputs.items():
        if path is not None:
            typer.echo(f"{label}: {path.relative_to(root)}")


def _resolve_dataset_config(root: Path, config: Path | None, fixture: bool) -> Path:
    if fixture:
        return root / "configs" / "datasets" / "fixture_dataset.json"
    if config is None:
        resolved = root / "configs" / "datasets" / "selected_dataset.json"
    else:
        resolved = config if config.is_absolute() else root / config
    if not resolved.exists():
        raise typer.BadParameter(
            f"dataset config not found: {resolved}. Place Alaska under "
            "`data/raw/alaska/<vertical>/extracted/`, run `mosaic dataset select`, "
            "or pass `--fixture` for fixture-only checks."
        )
    return resolved


def _run_pipeline_stage(config: Path, stage: StageName) -> PipelineRunResult:
    root = _repo_root()
    config_path = config if config.is_absolute() else root / config
    pipeline_config = load_baseline_pipeline_config(config_path)
    return run_baseline_pipeline(pipeline_config, root, stop_after=stage)


def _run_assisted_pipeline_stage(config: Path, stage: StageName) -> PipelineRunResult:
    root = _repo_root()
    config_path = config if config.is_absolute() else root / config
    experiment_config = load_m3_experiment_config(config_path)
    return run_assisted_pipeline(experiment_config, root, stop_after=stage)


def _looks_like_m3_experiment_config(config: Path) -> bool:
    root = _repo_root()
    config_path = config if config.is_absolute() else root / config
    if not config_path.exists():
        return False
    return '"llm_assistance"' in config_path.read_text(encoding="utf-8")
