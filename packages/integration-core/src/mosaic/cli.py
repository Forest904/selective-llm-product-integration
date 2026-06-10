from pathlib import Path
from typing import Annotated

import typer

from mosaic.alaska import (
    local_alaska_candidate_metrics,
    local_alaska_dataset_configs,
    select_best_candidate,
    write_dataset_config,
)
from mosaic.ingestion import ingest_dataset
from mosaic.m1_models import load_dataset_config
from mosaic.profiling import profile_dataset, write_profile_summary_table
from mosaic.schema_validation import validate_mediated_schema

app = typer.Typer(help="Mosaic reproducible research pipeline CLI.")
dataset_app = typer.Typer(help="Dataset discovery, selection, profiling, and ingestion.")
report_app = typer.Typer(help="Report generation commands.")
schema_app = typer.Typer(help="Mediated schema commands.")
app.add_typer(dataset_app, name="dataset")
app.add_typer(report_app, name="report")
app.add_typer(schema_app, name="schema")

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


@report_app.command("build")
def report_build() -> None:
    """Reserve report generation and verify report source/output homes."""
    root = _repo_root()
    required = (root / "reports", root / "artifacts" / "reports")
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        for relative in missing:
            typer.echo(f"missing: {relative}")
        raise typer.Exit(code=1)

    typer.echo("Report generation scaffold completed.")


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
