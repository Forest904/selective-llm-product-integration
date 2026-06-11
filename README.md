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
make report-fixture
```

`make install` bootstraps `uv` through Python if it is not already available.
Fixture commands remain available for CI-safe reproduction, and M1 real-data
commands run once the local Alaska files are present. `make report-fixture`
builds the CI-safe fixture report. `make report` is reserved for the M4
academic release and fails unless the subset-live and deterministic-scale
manifests exist.

## Development Commands

```bash
make install     # install uv-managed Python dependencies
make lint        # run Ruff and mypy
make test        # run pytest
make reproduce   # run fixture reproduction scaffold
make report      # build the M4 submission report from subset-live and scale manifests
make report-fixture # build the fixture-equivalent report bundle
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

## M4 Academic Release

The assignment-ready release is generated in three explicit layers. The live
LLM comparison runs on a deterministic 60-entity Alaska Monitor subset; full
Monitor, Notebook, and Camera are run separately with the deterministic A0
pipeline only.

```bash
uv run mosaic maintenance clean-generated --yes
uv run mosaic experiment release --live
uv run mosaic experiment deterministic-scale
uv run mosaic report build
```

The live release command reads `OPENAI_API_KEY` from the shell environment or
from the ignored root `.env` file. It uses the committed M4 OpenAI model config
(`gpt-4.1-mini`, temperature `0`, strict structured outputs, cache-or-live
execution). The reported comparison includes subset Deterministic (`A0`), LLM
(`C-LLM`), and Hybrid (`B-All`) rows, plus subset ablations and routing-budget
runs. It writes a compact release manifest to
`artifacts/reports/m4/m4_release_manifest.json`; `mosaic report build` copies
the compact release bundle under `reports/release/`, writes `reports/report.md`,
exports `reports/release/final_integrated_dataset.jsonl`, and builds
`reports/report.pdf` when Pandoc and a LaTeX PDF engine are available.

Long live runs are resumable:

```bash
uv run mosaic experiment release --live --resume latest
uv run mosaic experiment deterministic-scale --resume latest
uv run mosaic experiment run configs/experiments/m4_c_llm_primary_alaska_monitor.json --resume latest
```

The release command creates run checkpoints and batch-level LLM progress files.
On resume, completed deterministic stages and completed LLM case batches are
reused instead of recomputed.

For a clean-clone or CI-safe fixture-equivalent check that does not make live
LLM calls:

```bash
uv run mosaic experiment release --fixture
uv run mosaic report build --fixture
# or
make report-fixture
```

The fixture report is explicitly labeled as reproduction evidence, not as the
reported live Pipeline B or C result. Fixture builds use
`artifacts/reports/m4/m4_fixture_manifest.json` by default so they do not
overwrite the subset-live release manifest.

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
