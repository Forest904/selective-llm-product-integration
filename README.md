# Mosaic

Selective LLM Assistance for End-to-End Product Data Integration.

Mosaic is a reproducible research project comparing a deterministic product
integration pipeline with selective, uncertainty-aware LLM assistance for schema
alignment, record linkage, and data fusion.

## Governing Documents

- `Mosaic_PRD.md` is the authoritative product requirements source.
- `Mosaic_Roadmap.md` defines milestone order and acceptance gates.
- `Project_Blueprint_Mosaic.md` defines architecture, stack, CLI, and artifact
  conventions.
- `LLM_Assisted_Big_Data_Integration_Assignment.pdf` is retained for grading
  traceability.

## Repository Shape

The repository is research-first. Pipeline code lives in
`packages/integration-core`, shared configuration lives in `configs`, prompts
live in `prompts`, and reproducible outputs live under `artifacts`.

The web/API/worker directories are present as placeholders so later milestones
have a stable home. They must remain downstream of the command-line research
pipeline.

## Quick Start

Install Python 3.12 or newer, then run:

```bash
make install
make lint
make test
make reproduce
make report
```

`make install` bootstraps `uv` through Python if it is not already available.
The current milestone provides fixture/scaffold commands only; later milestones
will replace those placeholders with real dataset and pipeline execution.

## Development Commands

```bash
make install     # install uv-managed Python dependencies
make lint        # run Ruff and mypy
make test        # run pytest
make reproduce   # run fixture reproduction scaffold
make report      # run report generation scaffold
make dev         # verify development scaffold readiness
```

The reserved Mosaic CLI contract starts here:

```bash
uv run mosaic doctor
uv run mosaic reproduce --fixture
uv run mosaic report build
```

## Reproducibility Conventions

- Run IDs use `run_YYYYMMDDTHHMMSSZ_<shortslug>`.
- Configuration hashes use canonical JSON/YAML serialization, SHA-256, and the
  display form `cfg_<12 hex chars>`.
- Generated artifacts use `<stage>/<run_id>/<artifact_family>.<format>`.
- Prompt versions live in `prompts/<stage>/vYYYYMMDD_<slug>/`.
- Logs live in `artifacts/runs/<run_id>/logs/`; metrics live in
  `artifacts/runs/<run_id>/metrics/`; generated reports live in
  `artifacts/reports/`.

## Data And Artifacts

Raw benchmark datasets and generated artifacts are not committed by default.
Users must obtain the selected benchmark data before running real-data pipeline
commands. For M1, place Alaska Notebook or Monitor files under one of:

```text
data/raw/alaska/notebook/extracted/
data/raw/alaska/monitor/extracted/
```

The official Alaska short links may be expired, so benchmark access is treated
as a project startup prerequisite rather than an automated CLI step. See
`data/README.md`, `configs/datasets/README.md`, and `artifacts/README.md` for
what belongs in git and what must be regenerated.
