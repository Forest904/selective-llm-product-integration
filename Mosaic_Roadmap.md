# Mosaic Roadmap

**Product name:** Mosaic  
**Roadmap type:** Atemporal, dependency-ordered execution guide  
**Primary requirements source:** `Mosaic_PRD.md`  
**Architecture source:** `Project_Blueprint_Mosaic.md`  
**Grading source:** `LLM_Assisted_Big_Data_Integration_Assignment.pdf`

---

## 1. Roadmap Overview

This roadmap turns the Mosaic PRD into a concrete sequence of milestones. It is intentionally atemporal: milestones are ordered by dependency and implementation risk, not by calendar dates.

The academic research release is the first mandatory delivery gate. Website and workbench milestones are planned here because they are part of the full Mosaic vision, but they must not block the assignment-ready research system. The pipeline, command-line execution, metrics, report, and reproducible artifacts come first; the website becomes a client of that stable system.

### Roadmap Rules

- Complete academic assignment requirements before treating website or workbench milestones as required.
- Build the deterministic baseline before LLM assistance.
- Keep every pipeline stage executable without the website.
- Produce artifacts, metrics, and tests as each stage is built.
- Use the website to explain and operate the pipeline, never to duplicate hidden integration logic.
- Treat stretch work as optional unless it protects an acceptance gate.

### Source Documents

- `Mosaic_PRD.md`: authoritative product requirements.
- `Project_Blueprint_Mosaic.md`: architecture, data model, technical approach, and full sprint inventory.
- `LLM_Assisted_Big_Data_Integration_Assignment.pdf`: grading requirements and academic deliverables.

---

## 2. Execution Principles

### Pipeline-First

The pipeline is the product core. Every operation must be runnable through scripts, CLI commands, configuration files, and reproducible artifacts before the web application depends on it.

### Baseline-First

Pipeline A must be complete before Pipeline B is interpreted as successful. Deterministic schema alignment, normalization, blocking, matching, clustering, and fusion establish the reference point for every LLM comparison.

### Evaluation-First

Every stage needs metrics, acceptance checks, and error examples. Report figures and tables should be generated from artifacts, not assembled manually.

### Provenance-First

Every mapping, normalized value, candidate pair, match decision, cluster, claim, fused value, LLM response, and export must trace back to source data, configuration, code version, prompt/model version where applicable, and run ID.

### Selective LLM Use

The LLM is an adjudicator for uncertain cases, not the default decision-maker. Mosaic must measure when model calls help, when they fail, and what they cost.

### Website-As-Client

The web app consumes shared services and artifacts. It does not reimplement schema matching, linkage, clustering, fusion, evaluation, or reporting logic.

---

## 3. Milestone Map

| Milestone | Name | Primary outcome | Depends on | Unlocks |
| --- | --- | --- | --- | --- |
| M0 | Product and Repository Foundation | Reproducible project skeleton implemented | PRD and blueprint | M1, M2 fixture work |
| M1 | Reproducible Data Foundation | Selected benchmark subset, manifests, profiles, schema | M0 | M2 |
| M2 | Deterministic Baseline Pipeline | Pipeline A from raw sources to integrated entities | M1 | M3, M4 baseline results |
| M3 | LLM-Assisted Research System | Pipeline B with selective LLM use in schema, linkage, and fusion | M2 | M4 assisted results |
| M4 | Experiments, Report, and Academic Release | Assignment-ready PDF, repo, metrics, and final dataset | M2, M3 | M5, M6 |
| M5 | Educational Demo Website | Learning site and animated assignment pipeline | M4 artifacts | M7 public demo |
| M6 | Operational Integration Workbench | Backend, worker, database, and real review workflows | M4 artifacts, M5 UI foundation where reusable | M7 production hardening |
| M7 | Production Hardening and Public Demo | Deployable, documented, secure public-facing system | M5, M6 | Full Mosaic vision |

### Dependency Flow

```text
M0 Product/repo foundation
  -> M1 Data foundation
      -> M2 Deterministic baseline
          -> M3 LLM-assisted system
              -> M4 Academic release
                  -> M5 Educational demo website
                  -> M6 Operational workbench
                      -> M7 Production hardening and public demo
```

M5 may begin after M4 artifacts are stable enough to provide real examples, charts, and error cases. M6 should wait until the pipeline has stable services and artifact contracts.

---

## 4. Detailed Milestones

## M0: Product And Repository Foundation

**Status:** Implemented and accepted.

### Goal

Prepare the repository and project conventions so the research system can be built reproducibly.

### Prerequisites

- `Mosaic_PRD.md` exists and is accepted as the requirements source.
- `Project_Blueprint_Mosaic.md` exists and is accepted as the architecture source.
- Assignment PDF is available for grading traceability.

### Implementation Checklist

- [x] Confirm PRD, roadmap, and blueprint are the governing project documents.
- [x] Establish the monorepo structure for research package, configs, prompts, data, artifacts, reports, tests, API, worker, and web.
- [x] Configure Python tooling: `uv`, `pyproject.toml`, Ruff, mypy, pytest, and a Typer CLI entry point named `mosaic`.
- [x] Configure frontend placeholders: root `package.json`, `pnpm-workspace.yaml`, and `apps/web/package.json` without initializing a full Next.js application.
- [x] Add `docker-compose.yml` skeleton for future PostgreSQL and Redis services, without making containers required for M0 checks.
- [x] Add `.env.example` with non-secret configuration names.
- [x] Add Makefile commands for install, lint, test, reproduce, dev, and report generation.
- [x] Add README reproduction skeleton and command documentation.
- [x] Add contribution notes, security notes, citation metadata, and basic development workflow.
- [x] Add CI skeleton for Python checks and fixture pipeline checks.
- [x] Add `data/README.md` explaining committed data, generated data, and download instructions.
- [x] Add `artifacts/README.md` explaining regenerated outputs and ignored large artifacts.
- [x] Define run ID conventions.
- [x] Define configuration hash conventions.
- [x] Define artifact naming conventions.
- [x] Define prompt version naming conventions.
- [x] Define where logs, metrics, figures, and report outputs live.

### Deliverables

- Working repository skeleton with `apps`, `packages`, `configs`, `prompts`, `data`, `artifacts`, `database`, `scripts`, `tests`, `reports`, and `.github/workflows`.
- Install, lint, test, reproduce, dev, and report commands in `Makefile`.
- Initial README, `.env.example`, contribution notes, security notes, and citation metadata.
- Initial risk register in `docs/risk_register.md`.
- Directory-level README files for data, artifacts, configs, prompts, reports, apps, and placeholder packages.
- Python CI skeleton in `.github/workflows/python.yml`.
- Fixture smoke tests for import, CLI help, `mosaic doctor`, `mosaic reproduce --fixture`, `mosaic report build`, and required scaffold paths.

### Implemented CLI And Commands

Reserved M0 command contract:

```bash
uv run mosaic doctor
uv run mosaic reproduce --fixture
uv run mosaic report build
```

Accepted aggregate commands:

```bash
make install
make lint
make test
make reproduce
make dev
make report
```

M0 intentionally keeps these as scaffold and fixture checks. Real dataset ingestion, experiment execution, and report generation are unlocked by later milestones.

### Implemented Conventions

- Run IDs use `run_YYYYMMDDTHHMMSSZ_<shortslug>`.
- Configuration hashes use canonical JSON/YAML serialization, SHA-256, and display as `cfg_<12 hex chars>`.
- Generated artifacts use `<stage>/<run_id>/<artifact_family>.<format>`.
- Prompt versions live in `prompts/<stage>/vYYYYMMDD_<slug>/`.
- Logs live in `artifacts/runs/<run_id>/logs/`.
- Metrics live in `artifacts/runs/<run_id>/metrics/`.
- Figures live in `artifacts/figures/`.
- Report sources live in `reports/`.
- Generated report outputs live in `artifacts/reports/`.

### Acceptance Gate

- [x] A clean clone can install dependencies and run the fixture test suite.
- [x] There is no ambiguity about where code, configs, prompts, data, artifacts, tests, and reports belong.
- [x] No secrets or raw credentials are committed.
- [x] `make install` succeeds.
- [x] `make lint` succeeds with Ruff and mypy.
- [x] `make test` succeeds with 5 passing tests.
- [x] `make reproduce` succeeds through the fixture reproduction scaffold.
- [x] `make dev` succeeds through the development scaffold check.
- [x] `make report` succeeds through the report generation scaffold.

### Risks / Watchpoints

- Overbuilding the web skeleton before the research pipeline exists. Current mitigation: web remains placeholder-only in M0.
- Committing generated artifacts that should be reproducible. Current mitigation: `.gitignore` excludes generated data, artifacts, logs, caches, local env files, and frontend build outputs while preserving README and `.gitkeep` placeholders.
- Leaving environment setup implicit. Current mitigation: README, `.env.example`, Makefile targets, CI, and scaffold checks document the setup path.
- Local shells may carry an unrelated active virtual environment. Current mitigation: `uv` ignores the mismatched environment and uses the project `.venv`.

### Unlocks

- Dataset discovery and ingestion.
- Small fixture tests for pipeline components.
- Reproducibility conventions for all later milestones.

---

## M1: Reproducible Data Foundation

### Goal

Select, ingest, profile, and document the benchmark subset that satisfies the assignment requirements.

### Prerequisites

- M0 accepted.
- Data directories, config directories, and artifact conventions exist.
- Benchmark source access is understood or documented.

### Implementation Checklist

- Implement dataset discovery/profiling script.
- Download or locate Alaska benchmark candidates.
- Evaluate candidate categories against assignment minimums.
- Compute source count, total record count, entity count, positive pair count or equivalent cluster truth, mediated attribute coverage, overlap, missingness, and conflict count.
- Profile source schema heterogeneity.
- Profile model-number coverage and title variation.
- Profile candidate fusion conflicts.
- Rank candidate domains using documented scoring.
- Select final subset or document benchmark fallback if Alaska is unsuitable.
- Create dataset candidate report.
- Implement immutable ingestion for CSV, JSON, JSON Lines, and Parquet.
- Generate stable `record_uid` values with the convention `{source_id}:{source_record_id}`.
- Reject row position as a stable identifier.
- Calculate raw checksums.
- Validate malformed rows and write ingestion errors.
- Create `dataset_manifest.json`.
- Generate source profiles and profiling summaries.
- Infer source attribute types and semantic-role suggestions.
- Define mediated schema with the PRD's 8 target attributes: title, brand, model number, category, description, price, currency, and specifications.
- Add schema validation and schema documentation.
- Define mapping gold format for schema evaluation.
- Define fusion annotation format if official fusion truth is incomplete.

### Deliverables

- Dataset candidate report.
- Selection score table.
- Selected dataset manifest.
- Source metadata artifacts.
- Ingested raw/source artifacts.
- Ingestion error artifact.
- Source profile artifacts.
- Profiling summary tables or plots.
- `mediated_schema.json`.
- Schema documentation.
- Ground-truth summary.

### Acceptance Gate

- Dataset satisfies at least 3 heterogeneous sources, 1,000 source records, 5 mediated attributes, 200 integrated entities, 300 positive pairs or equivalent cluster truth, and 100 fusion conflicts.
- Every raw record has stable provenance and checksum metadata.
- Every source attribute has a profile and representative samples.
- The selected subset is justified by data, not preference.

### Risks / Watchpoints

- Alaska subset may not satisfy every minimum for the chosen category.
- Fusion ground truth may be partial or absent.
- Source attributes may be too sparse for meaningful schema alignment.
- Candidate subset may be large enough for blocking but too expensive for naive LLM use.

### Unlocks

- Deterministic schema alignment.
- Normalization.
- Blocking and linkage evaluation.
- Fusion conflict analysis.

---

## M2: Deterministic Baseline Pipeline

### Goal

Implement Pipeline A end to end with no LLM decisions.

### Prerequisites

- M1 accepted.
- Selected dataset and mediated schema are stable enough for implementation.
- Ground truth format is available for schema, linkage, and fusion evaluation.

### Implementation Checklist

- Build deterministic schema alignment with name, type, value, and context evidence.
- Support unmapped attributes and non-forced mappings.
- Produce mapping candidates, accepted baseline mappings, score decompositions, and schema metrics.
- Build deterministic normalizers for title, brand, model number, category, price, currency, measurements, URLs, and specifications.
- Preserve raw values, canonical values, units, normalization method, and confidence.
- Implement multi-pass blocking with rule attribution.
- Include identifier blocks, rare model tokens, title token blocks, character signatures, category-aware retrieval, and specification signatures where feasible.
- Compute blocking metrics, including candidate-pair count, pair completeness, reduction ratio, candidates per record, duplicate candidate rate, runtime, and memory where available.
- Generate pairwise linkage features.
- Implement transparent match/non-match rule baseline.
- Implement logistic regression matcher as the main classical model.
- Calibrate thresholds using validation data.
- Use entity-safe train/validation/test splits.
- Prevent ground-truth leakage into features or prompts.
- Implement constraint-aware agglomerative clustering.
- Retain connected-components clustering as a comparison baseline.
- Log accepted and rejected cluster merges.
- Extract attribute claims from clusters.
- Implement deterministic attribute-specific fusion policies.
- Export baseline integrated entities.
- Compute baseline component and end-to-end metrics.
- Add unit tests for normalizers, schema scoring, blocking keys, similarity features, clustering constraints, and fusion rules.
- Add invariant tests for pair validity, cluster membership, claim references, and fused-value support.
- Add golden tests for obvious match, obvious non-match, punctuation-only model difference, variant conflict, bundle confusion, ambiguous schema field, wrong unit, stale price, and copied specification error.
- Add stage integration tests for ingestion to profiling, profiling to mapping, normalization to blocking, blocking to matching, matching to clustering, clustering to claims, and claims to fusion.

### Deliverables

- Baseline mapping outputs.
- Schema evaluation metrics.
- Normalized records and values.
- Candidate pairs and blocking metrics.
- Pairwise feature artifacts.
- Pair predictions.
- Linkage metrics.
- Entity clusters and memberships.
- Cluster metrics.
- Attribute claims.
- Fused values.
- Baseline integrated entities.
- Fusion metrics.
- Baseline error candidates.
- Baseline pipeline tests.

### Acceptance Gate

- CLI can run from raw sources to final integrated entities with no LLM use.
- Baseline artifacts are reproducible from committed configs and documented data inputs.
- Required assignment metrics can be computed for baseline pipeline components.
- Every final baseline value can be traced to source claims.

### Risks / Watchpoints

- Blocking false negatives can cap linkage recall.
- Logistic regression may need careful feature scaling and calibration.
- Connected-components clustering may over-merge through weak bridges.
- Majority fusion may select stale or copied values.

### Unlocks

- LLM-assisted schema, linkage, and fusion adjudication.
- Baseline comparison tables.
- Error analysis for deterministic failure modes.

---

## M3: LLM-Assisted Research System

### Goal

Implement Pipeline B with selective LLM use in schema alignment, record linkage, and data fusion.

### Prerequisites

- M2 accepted.
- Baseline outputs expose uncertainty, scores, conflicts, and candidate cases.
- Prompt directory and model config conventions exist.

### Implementation Checklist

- Build provider-neutral LLM gateway.
- Add prompt rendering.
- Add structured JSON validation.
- Add retry, timeout, cache, token counting, cost estimation, and logging.
- Add input hashing so repeated calls can be cached and traced.
- Create versioned prompt files for schema alignment, record linkage, and fusion.
- Create JSON schemas or Pydantic models for every structured LLM output.
- Create model configuration files with provider, model identifier, temperature, max tokens, retry count, timeout, cache mode, and structured-output mode.
- Implement LLM-assisted schema alignment only for uncertain mappings.
- Enforce allowed schema outputs: known target attribute, `UNMAPPED`, or `ABSTAIN`.
- Implement LLM-assisted record linkage only for borderline candidate pairs.
- Tune the uncertainty band on validation data.
- Implement LLM-assisted fusion only for unresolved claim conflicts.
- Restrict fusion outputs to allowed values or `ABSTAIN`.
- Reject invented values, unsupported values, incompatible units, and unknown claim IDs.
- Implement abstention and deterministic fallback policy.
- Record invalid JSON, missing fields, hallucinated or unsupported values, empty responses, timeouts, fallbacks, and abstentions.
- Add LLM call artifacts to experiment manifests.
- Implement cost-aware routing experiment support.
- Generate quality-cost metrics for routed cases.
- Add tests for structured-output parsing, validation failures, fallback behavior, unsupported values, unknown IDs, and prompt input leakage.
- Keep LLM-assisted normalization clearly labeled as stretch/backlog.

### Deliverables

- LLM gateway.
- Prompt files.
- Model config files.
- Structured output schemas.
- Response cache.
- LLM call logs.
- Assisted schema mapping artifacts.
- Assisted linkage artifacts.
- Assisted fusion artifacts.
- Failure-policy documentation.
- Routing metrics.
- Quality-cost outputs.
- LLM validation tests.

### Acceptance Gate

- Assisted pipeline uses LLMs in schema alignment, record linkage, and fusion.
- Every accepted LLM decision is validated, logged, reproducible, and source-supported.
- Invalid and unsupported outputs are counted as failures unless a documented fallback applies.
- No manual correction of LLM outputs is needed or allowed during evaluation.

### Risks / Watchpoints

- LLM responses may be invalid or overconfident.
- Prompt inputs may accidentally include ground truth.
- Unrestricted LLM calls may make experiments too expensive.
- Model-specific behavior can hurt reproducibility unless responses are cached or logged.

### Unlocks

- Baseline versus assisted comparison.
- Stage ablations.
- Routing-budget experiments.
- LLM failure analysis.

---

## M4: Experiments, Report, And Academic Release

### Goal

Produce the assignment-ready research release: PDF report, GitHub-ready repository, reproducible metrics, and final integrated dataset.

### Prerequisites

- M2 accepted.
- M3 accepted.
- Dataset, prompts, model settings, and evaluation scripts are stable.

### Implementation Checklist

- Run baseline configuration A0.
- Run LLM-assisted configuration B-All.
- Run stage ablations where feasible: schema-only, linkage-only, fusion-only, schema-linkage, linkage-fusion, and schema-linkage-fusion.
- Run no-abstention or no-fallback experiment if feasible and safe to interpret.
- Run routing-budget experiments for eligible uncertain cases.
- Generate schema alignment metrics.
- Generate blocking metrics, including candidate-pair count after blocking.
- Generate linkage precision, recall, F1, and confusion matrix.
- Generate clustering metrics where labels support them.
- Generate fusion accuracy for attributes with ground truth.
- Generate end-to-end quality summary.
- Generate optional operational metrics: reduction ratio, completeness, LLM calls, tokens, cost, latency, cache hit rate, invalid-output rate, abstention rate, fallback rate, and unsupported-value rate.
- Select at least three concrete error cases.
- For each error case, capture source records, system output, expected output, explanation, and stage of origin.
- Build report-ready tables and plots.
- Write concise 10 to 15 page report plus appendix.
- Include methodology, experimental protocol, results, error analysis, discussion, and GitHub link.
- Export final integrated dataset.
- Build reproducibility bundle or documented regeneration scripts.
- Verify README reproduction commands.
- Run final test suite.
- Run final reproducibility check on fixture or full documented dataset.
- Freeze academic release artifacts.

### Deliverables

- Experiment manifests.
- Metrics tables.
- Figures and plots.
- Error case appendix.
- Final integrated dataset.
- Report source.
- `reports/report.pdf`.
- GitHub-ready repository.
- Reproduction guide.

### Acceptance Gate

- Every assignment requirement is traceable to an artifact, metric, or report section.
- A clean clone can regenerate reported outputs or documented fixture-equivalent outputs.
- The report clearly explains where LLMs help, where deterministic methods remain preferable, and how cost, latency, hallucinations, and reproducibility affect design.

### Risks / Watchpoints

- Report may become too broad and dilute grading clarity.
- Optional experiments may distract from required metrics.
- Error examples may be too abstract unless source-level records are included.
- Reproducibility may fail if data download or LLM response handling is underdocumented.

### Unlocks

- Educational website with real project outputs.
- Workbench backed by stable artifacts and service contracts.
- Public demo narrative.

---

## M5: Educational Demo Website

### Goal

Create the first website version as an educational demo centered on the Mosaic assignment project.

### Prerequisites

- M4 accepted or enough M4 artifacts are stable for demo content.
- Report tables, figures, selected error cases, and final dataset preview are available.
- Frontend skeleton exists or is ready to create.

### Implementation Checklist

- Build frontend shell and design system.
- Create app navigation for learning hub, animated pipeline, concept explorer, experiment results, error gallery, and final dataset preview.
- Create learning hub that introduces Mosaic and data integration concepts.
- Build animated assignment pipeline page.
- Include pipeline stages: sources, schema alignment, normalization, blocking, record linkage, clustering, claim extraction, fusion, integrated entities, metrics, report, and export.
- Add controls: play/pause, step forward/back, stage selector, baseline versus LLM toggle, uncertainty overlay, provenance overlay, and reset.
- Use small toy data with 3 sources, 6 to 12 records, 2 to 3 products, one schema synonym, one borderline pair, one fusion conflict, and one LLM abstention or invalid-output example.
- For every stage, show input objects, transformation or decision, output objects, deterministic evidence, LLM evidence when applicable, uncertainty/confidence, provenance, and common error mode.
- Build concept modules for schema alignment, blocking, record linkage, clustering, fusion, LLM routing, and provenance.
- Add experiment results page using M4 report outputs.
- Add error gallery using M4 saved error cases.
- Add final dataset preview using exported integrated entities or demo subset.
- Ensure deterministic evidence, LLM evidence, uncertainty, and provenance are visually distinct.
- Add empty, loading, and error states.
- Verify responsive layout on desktop and mobile.
- Verify keyboard access and labels for controls.
- Add frontend tests for stage navigation, toggles, overlays, responsive layout, and accessibility basics.

### Deliverables

- Educational website MVP.
- Animated assignment pipeline page.
- Concept explorer modules.
- Experiment results page.
- Error gallery.
- Final dataset preview.
- Frontend test coverage for core demo flows.

### Acceptance Gate

- A visitor can understand Mosaic's full assignment pipeline without running code.
- The animated page accurately shows how source records become integrated entities and report artifacts.
- Deterministic evidence, LLM evidence, uncertainty, and provenance are visually distinct.
- The demo works on desktop and mobile without overlap, clipping, or unreadable text.

### Risks / Watchpoints

- Animation can become decorative instead of explanatory.
- Website may accidentally imply that LLM decisions are always correct.
- Toy examples may oversimplify fusion or clustering.
- UI polish can consume time better spent strengthening report artifacts if M4 is not finished.

### Unlocks

- Public-facing explanation of the project.
- Reusable UI components for later workbench views.
- Demo material for documentation and portfolio presentation.

---

## M6: Operational Integration Workbench

### Goal

Expose real project execution and review workflows through backend services and the web application.

### Prerequisites

- M4 accepted.
- Stable artifact schemas and pipeline service boundaries exist.
- M5 UI foundation can be reused where practical.

### Implementation Checklist

- Add PostgreSQL operational schema and migrations.
- Add SQLAlchemy models or equivalent persistence models.
- Add repository layer that references large Parquet/object artifacts rather than duplicating them unnecessarily.
- Add backend API endpoints for projects, sources, schemas, pipeline runs, linkage, clusters, fusion, experiments, review, and exports.
- Generate or document OpenAPI schema.
- Add typed API client for frontend usage.
- Add worker or job orchestration for long-running pipeline stages.
- Add job progress, retries, cancellation, warnings, failure states, and artifact links.
- Build project dashboard.
- Build source catalog and profile views.
- Build mediated schema editor.
- Build schema mapping workbench.
- Build normalization explorer.
- Build blocking analytics.
- Build pair review workbench.
- Build cluster explorer.
- Build fusion and provenance workbench.
- Build integrated entity browser.
- Build experiment dashboard.
- Build error analysis center.
- Build export and reporting center.
- Add audit-friendly review decision records.
- Add API contract tests.
- Add browser tests for critical workbench flows.
- Ensure web features consume shared pipeline/backend outputs rather than duplicate logic.

### Deliverables

- API service.
- Worker service.
- Operational database and migrations.
- Typed API client.
- Project dashboard.
- Source/profile views.
- Schema editor.
- Mapping, normalization, blocking, pair review, cluster, fusion, entity, experiment, error, and export views.
- API contract tests.
- Browser tests for core flows.

### Acceptance Gate

- A user can create or inspect a project, run or monitor pipeline work, review uncertain decisions, inspect provenance, compare experiments, and export results.
- Long-running work does not block HTTP requests.
- Manual review actions are persisted and traceable.

### Risks / Watchpoints

- Database schema may drift from research artifact schemas.
- Job orchestration can become complex if retry and cancellation semantics are not constrained.
- UI may expose edits before validation rules are strong enough.
- Workbench scope can grow into a general ETL platform, which is outside Mosaic's core.

### Unlocks

- Multi-user hardening.
- Production deployment.
- Full public demo with operational workflows.

---

## M7: Production Hardening And Public Demo

### Goal

Make Mosaic deployable, reliable, safe, and presentable as a public research and portfolio system.

### Prerequisites

- M5 accepted.
- M6 accepted or a narrower demo deployment surface is explicitly chosen.
- Deployment target is known.

### Implementation Checklist

- Add authentication.
- Add authorization and roles: viewer, reviewer, project admin, and system admin.
- Protect API routes and frontend routes.
- Add audit logging for schema edits, mapping changes, pair decisions, cluster edits, fusion overrides, prompt changes, model config changes, and exports.
- Add secret handling documentation and guardrails.
- Ensure no API keys, database credentials, object-storage secrets, or session secrets are committed.
- Add prompt-injection defenses for source text in LLM prompts.
- Add health checks.
- Add structured logging.
- Add metrics and tracing.
- Add backup and restore documentation.
- Add migration procedure.
- Add dependency scanning.
- Add file-size limits.
- Add rate limiting.
- Add performance testing.
- Add accessibility testing.
- Build public demo dataset and walkthrough.
- Write user guide.
- Write architecture guide.
- Write API examples.
- Write research summary.
- Prepare screenshots or demo media.

### Deliverables

- Hardened deployment.
- Auth and RBAC.
- Audit log.
- Operations guide.
- Backup and restore procedure.
- Observability dashboards or documented metrics.
- Public demo dataset.
- User guide.
- Architecture guide.
- API examples.
- Research summary.

### Acceptance Gate

- Mosaic can be deployed, monitored, upgraded, restored, and demonstrated to a new visitor.
- Secrets are handled outside the repository.
- Public demo explains the research contribution and lets users inspect the system safely.

### Risks / Watchpoints

- Authentication can slow down demo iteration if introduced too early.
- Production hardening can sprawl without a clear deployment target.
- Public demos need curated data and safeguards against expensive model calls.
- Operational docs must stay aligned with actual commands and deployment files.

### Unlocks

- Full Mosaic vision.
- Portfolio/public presentation.
- Future research extensions.

---

## 5. Cross-Cutting Workstreams

### Testing And CI

- Add tests at the same time as core logic.
- Keep fixture datasets small and deterministic.
- Run unit, invariant, golden, integration, API contract, frontend, and reproducibility tests as relevant.
- CI should validate at least a fixture pipeline before the academic release.
- Browser and accessibility checks become required for website milestones.

### Data, Provenance, And Artifacts

- Raw data is immutable.
- Derived artifacts record input version, config version, code version, parent artifacts, timestamp, and checksum.
- Large generated artifacts should be reproducible and ignored unless they are required for submission.
- Every final integrated entity must trace back to source records and claims.

### Prompt And Model Governance

- All prompts live in committed versioned prompt directories.
- All model configs are committed without secrets.
- Every LLM call records prompt version, model identifier, settings, input hash, raw response, parsed response, validation status, retries, latency, tokens, and estimated cost.
- Invalid outputs are measured, not hidden.
- Manual correction of LLM outputs during evaluation is forbidden.

### Reporting And Visualization

- Report tables and plots come from metrics artifacts.
- Error cases are saved as structured artifacts before they appear in the report.
- The educational website should reuse report outputs where possible.
- Visual explanations must preserve the actual pipeline order and not imply unsupported capabilities.

### Documentation

- README explains setup, reproduction, dataset access, experiment execution, metric regeneration, and report building.
- Dataset docs distinguish full input data from labeled evaluation subsets.
- Prompt docs explain stage, schema, allowed outputs, and failure policy.
- Roadmap and PRD should be updated when the project makes a deliberate scope change.

### Security And Secret Handling

- Never commit API keys, database credentials, object-storage secrets, or session secrets.
- Use environment variables and `.env.example`.
- Treat source text as untrusted input in LLM prompts.
- Delimit source content and require enumerated structured outputs.
- Validate all LLM-returned IDs against known inputs.

---

## 6. Release Gates

## Academic Release Gate

Required before submission:

- Dataset satisfies assignment minimums.
- Pipeline A runs end to end without LLM decisions.
- Pipeline B uses LLMs in schema alignment, record linkage, and fusion.
- Prompts and model settings are committed.
- Invalid outputs, abstentions, fallbacks, cost, and latency are measured.
- Schema, linkage, fusion, and end-to-end metrics are generated.
- At least three concrete source-level error cases are documented.
- Final integrated dataset is exportable.
- Report PDF is polished and includes GitHub link.
- README reproduction commands are verified.

## Educational Demo Gate

Required before treating the website as a usable learning product:

- Learning hub exists.
- Animated assignment pipeline page exists.
- Concept modules exist for the major integration stages.
- Experiment results and error gallery use research artifacts.
- Deterministic evidence, LLM evidence, uncertainty, and provenance are visually distinct.
- Desktop and mobile layouts are verified.

## Workbench MVP Gate

Required before treating Mosaic as an operational application:

- Backend API exposes core project, source, pipeline, review, experiment, and export flows.
- Worker can run long pipeline jobs.
- Operational database stores metadata and review actions.
- Users can inspect profiles, mappings, pairs, clusters, fusion decisions, entities, experiments, and exports.
- Manual actions preserve audit-ready provenance.

## Production/Public Demo Gate

Required before public launch:

- Auth, RBAC, audit logging, secret handling, and prompt-injection defenses are in place.
- Health checks, logging, metrics, backups, migrations, and deployment docs exist.
- Public demo data and walkthrough exist.
- User guide, architecture guide, API examples, and research summary exist.

---

## 7. Backlog And Stretch Extensions

These items may improve Mosaic but must not block the academic release unless explicitly promoted into scope.

### LLM-Assisted Normalization

Use the LLM for noisy values that deterministic normalizers cannot safely classify. Require evidence spans and reject unsupported canonical values.

### Prompt Sensitivity Experiments

Compare zero-shot, few-shot, evidence-first, decision-first, with deterministic features, and without deterministic features on a controlled subset.

### Model Comparison

Compare a smaller low-cost model, a stronger hosted model, and possibly a local model while keeping prompt format and evaluation cases constant.

### Source-Quality Estimation

Estimate source reliability by source, attribute, or category and use it during fusion.

### Copy Detection

Detect copied or dependent source values and discount redundant evidence during fusion.

### Temporal Fusion

Handle values that evolve over time, such as price or availability, using recency-aware policies.

### Human-In-The-Loop Feedback

Add reviewer feedback loops that update thresholds, routing policy, or source quality estimates.

### Advanced Deployment

Add object storage, reverse proxy configuration, richer observability, cloud deployment, and scalable worker pools.

---

## 8. Roadmap Maintenance

This roadmap should be updated when:

- assignment interpretation changes;
- dataset selection changes;
- a milestone acceptance gate is intentionally relaxed or strengthened;
- a stretch feature becomes required;
- repository structure changes materially;
- API or artifact contracts change;
- website scope changes from educational demo to operational workbench.

When updating the roadmap, keep milestone IDs stable where possible so implementation notes, issues, commits, and report references remain understandable.

---

## 9. Immediate Next Step

Begin with M0. Do not start broad website implementation before M1 through M4 are on track, because the website depends on stable research artifacts and the academic release is the first required gate.
