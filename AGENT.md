# AGENT.md

## Project Snapshot

**Project name:** Mosaic  
**Academic title:** Selective LLM Assistance for End-to-End Product Data Integration  
**Repository:** `selective-llm-product-integration`

Mosaic is a reproducible research project and future educational/product workbench for product data integration. It compares a deterministic baseline with selective LLM assistance for schema alignment, record linkage/entity resolution, and data fusion/truth discovery.

The first delivery gate is the academic release: reproducible pipeline, metrics, final integrated dataset, PDF report, and GitHub repository. The website follows as a learning demo and, later, a full integration workbench.

## Source-Of-Truth Documents

Read these before substantive changes:

- `Mosaic_PRD.md`: authoritative product requirements.
- `Mosaic_Roadmap.md`: execution order and milestone gates.
- `Project_Blueprint_Mosaic.md`: architecture, data model, stack, CLI, API, and detailed blueprint.
- `LLM_Assisted_Big_Data_Integration_Assignment.pdf`: grading source.
- `README.md`: short repo summary.

This file is only the quick orientation layer.

## Core Intent

Research question:

> Can selective, uncertainty-aware LLM intervention improve end-to-end data integration quality while preserving cost control, reproducibility, provenance, and deterministic fallbacks?

Core workflow:

1. Schema alignment.
2. Normalization.
3. Blocking.
4. Record linkage/entity resolution.
5. Clustering.
6. Claim extraction.
7. Data fusion/truth discovery.
8. Evaluation and reporting.

## Non-Negotiable Principles

- **Pipeline-first:** every research operation must run without the website.
- **Baseline-first:** deterministic Pipeline A comes before LLM-assisted Pipeline B.
- **Evaluation-first:** every stage needs artifacts, metrics, and acceptance checks.
- **Provenance-first:** every decision traces to source data, config, code/run ID, and prompt/model version where applicable.
- **Selective LLM use:** the LLM adjudicates uncertain cases; it is not the default decision-maker.
- **Website-as-client:** web features consume shared pipeline/backend services and artifacts.
- **Configuration over hard-coding:** thresholds, prompts, model settings, and pipeline choices belong in versioned config.
- **No false certainty:** support abstention, fallback, and review where appropriate.
- **No manual correction of LLM outputs during evaluation:** invalid or unsupported outputs are measured unless a documented fallback applies.

## Academic Requirements Summary

The assignment release must include:

- PDF report and GitHub repository.
- At least 3 heterogeneous sources, 1,000 records, 5 mediated attributes, 200 integrated entities, 300 positive pairs or equivalent cluster truth, and 100 fusion conflicts.
- Deterministic baseline pipeline with no LLM integration decisions.
- LLM-assisted pipeline using the LLM in schema alignment, record linkage, and data fusion.
- Structured LLM outputs, committed prompts/configs, logged model settings/calls/failures, and no manual output correction during evaluation.
- Component metrics for schema alignment, record linkage, data fusion, and end-to-end quality.
- At least three concrete source-level error examples.
- Final integrated dataset or scripts to regenerate it.

For exact traceability, consult `Mosaic_PRD.md`.

## Planned Tech Stack

Follow the blueprint stack unless a deliberate architecture decision changes it:

- **Research/data:** Python 3.12, Polars, PyArrow/Parquet, DuckDB, scikit-learn, RapidFuzz, datasketch, NetworkX, Pydantic, MLflow, Typer, pytest, Ruff, mypy, uv.
- **Backend:** FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, Redis, Celery or Dramatiq.
- **Frontend:** Next.js, React, TypeScript, App Router, TanStack Query/Table, React Hook Form, Zod, Tailwind CSS, shadcn/ui, Plotly or ECharts.
- **Storage/execution:** PostgreSQL for operational metadata, Parquet for immutable artifacts, filesystem or S3-compatible object storage for datasets/exports/logs, Redis for queue state, DuckDB for analytics, Docker Compose for initial deployment.

## Planned Repo Structure

The repo is currently documentation-first. The planned structure includes:

- Root docs and config: `README.md`, `AGENT.md`, `Mosaic_PRD.md`, `Mosaic_Roadmap.md`, `Project_Blueprint_Mosaic.md`, assignment PDF, `Makefile`, `pyproject.toml`, `package.json`, `docker-compose.yml`, `.env.example`.
- Apps: `apps/api`, `apps/worker`, `apps/web`.
- Packages: `packages/integration-core`, `packages/ui`, `packages/api-client`, `packages/shared-types`.
- Project assets: `configs`, `prompts`, `data`, `artifacts`, `database`, `notebooks`, `scripts`, `tests`, `reports`, `.github/workflows`.

Create implementation directories intentionally and milestone-by-milestone; do not scaffold the whole tree without need.

## Important Commands

The full project must remain operable from the CLI. Planned command families:

- `uv run mosaic dataset ...`
- `uv run mosaic schema ...`
- `uv run mosaic normalize`
- `uv run mosaic block`
- `uv run mosaic match --pipeline baseline|llm-assisted`
- `uv run mosaic cluster`
- `uv run mosaic claims extract`
- `uv run mosaic fuse --pipeline baseline|llm-assisted`
- `uv run mosaic evaluate`
- `uv run mosaic experiment run ...`
- `uv run mosaic report build`
- `uv run mosaic export integrated`

Planned aggregate commands: `make install`, `make lint`, `make test`, `make reproduce`, `make dev`.

Do not add website-only flows that bypass shared pipeline contracts.

## How Agents Should Work Here

- Start with `Mosaic_PRD.md` and `Mosaic_Roadmap.md`.
- Identify the active milestone before changing files.
- Keep changes narrow, reproducible, and milestone-aligned.
- Preserve user changes; do not revert unrelated work.
- Prefer scripts, typed models, tests, and versioned configs over one-off manual steps.
- Keep raw data immutable and generated bulk artifacts out of git unless explicitly required.
- Commit prompts and model configs, never secrets.
- Validate LLM outputs through structured schemas.
- Ensure report metrics can be regenerated by code.
- Keep the web app downstream of pipeline services and artifacts.

## Current State

The repository currently contains planning and requirements documents, not the full implementation tree.

Present root files include `README.md`, `Project_Blueprint_Mosaic.md`, `Mosaic_PRD.md`, `Mosaic_Roadmap.md`, `LLM_Assisted_Big_Data_Integration_Assignment.pdf`, and `.gitignore`.

Implementation directories such as `packages`, `apps`, `configs`, `prompts`, `data`, `artifacts`, `scripts`, `tests`, and `reports` are planned by the roadmap and should be created intentionally as work begins.
