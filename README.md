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
Fixture commands remain available for CI-safe reproduction, and M1 real-data
commands run once the local Alaska files are present.

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
uv run mosaic dataset select --benchmark alaska
uv run mosaic dataset ingest --config configs/datasets/selected_dataset.json
uv run mosaic dataset profile --config configs/datasets/selected_dataset.json
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
commands. For M1, place Alaska files under:

```text
data/raw/alaska/camera/extracted/
data/raw/alaska/notebook/extracted/
data/raw/alaska/monitor/extracted/
```

Each vertical directory should contain `{vertical}_specs/` and
`{vertical}_ground_truths/`. The M1 selection command profiles local evidence
and writes `configs/datasets/selected_dataset.json`; Monitor is the selected
subset when all three local Alaska verticals are available. See `data/README.md`,
`configs/datasets/README.md`, and `artifacts/README.md` for what belongs in git
and what must be regenerated.
