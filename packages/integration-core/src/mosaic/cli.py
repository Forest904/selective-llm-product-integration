from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Mosaic reproducible research pipeline CLI.")
report_app = typer.Typer(help="Report generation commands.")
app.add_typer(report_app, name="report")

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

    missing = _missing_paths()
    if missing:
        for relative in missing:
            typer.echo(f"missing: {relative}")
        raise typer.Exit(code=1)

    typer.echo("Fixture reproduction scaffold completed.")


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
