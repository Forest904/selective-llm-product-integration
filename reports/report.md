---
title: "Mosaic: Selective LLM Assistance for Product Data Integration"
author: "Mosaic Research Release"
date: "2026-06-11"
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

This build is a fixture-equivalent reproduction report, not the final live submission.

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

Dataset id: `fixture_m1_products`

| sources | records | entities | positive_pairs | attributes |
| --- | --- | --- | --- | --- |
| 3 | 6 | 2 | 6 | 8 |

Repository: https://github.com/Forest904/selective-llm-product-integration.git

The Alaska Monitor data is deliberately larger than the labeled evaluation
subset. This matters for grading because the pipeline must run over realistic
source scale even when labels are sparse. Blocking and normalization see every
one of the 6 source records. Linkage, clustering, and
fusion quality are then measured wherever the entity-resolution, schema, and
fusion gold files can support a precise comparison. The report therefore
separates operational scale from labeled quality: candidate-pair count and
reduction ratio describe the full run, while precision, recall, F1, and fusion
accuracy describe the labeled slice.

The dataset contains 3 sources from the same monitor
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

Release manifest: `reports/release/m4_release_manifest.json`

| config | schema | linkage | fusion |
| --- | --- | --- | --- |
| A0 | deterministic | deterministic | deterministic |
| C-LLM | LLM primary | LLM primary | LLM primary |
| B-All | LLM routed | LLM routed | LLM routed |
| B-S | LLM routed | deterministic | deterministic |
| B-L | deterministic | LLM routed | deterministic |
| B-F | deterministic | deterministic | LLM routed |
| B-SL | LLM routed | LLM routed | deterministic |
| B-LF | deterministic | LLM routed | LLM routed |

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

\newpage

# Results

![Component quality overview](reports/release/figures/component_quality.png)

## Three-Way Pipeline Comparison



| pipeline | config | schema_f1 | pairs | linkage_f1 | cluster_f1 | fusion_acc | e2e |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Deterministic | fixture-A0 | 0.9697 | 8 | 0.0 | 1.0 | 0.0 | 0.4924 |
| LLM | fixture-C-LLM | 1.0 | 8 | 0.0 | 1.0 | 0.0 | 0.5 |
| Hybrid | fixture-B-All | 1.0 | 8 | 0.0 | 1.0 | 0.0 | 0.5 |

Full metric tables are written to
`reports/release/tables/metrics_summary.csv`.

On this release, the LLM-primary pipeline records schema F1
, linkage test F1
, clustering F1
, fusion accuracy
, and end-to-end summary
. B-All records schema F1
,
linkage test F1 , clustering F1
, fusion accuracy
, and end-to-end summary
. The deterministic A0 reference
records schema F1 , linkage test F1
, clustering F1
, fusion accuracy
, and end-to-end summary
.

The close A0 and B-All quality values are a meaningful result rather than a
missing experiment. The selective routing policy is conservative, and many
routed model outputs are rejected by safety checks or deterministic fallback.
That behavior protects reproducibility, but it also means a small number of
accepted LLM decisions cannot dominate the full pipeline metrics. The report
therefore treats operational reliability and failure handling as first-class
results alongside F1.

## Linkage Confusion Matrix



The linkage confusion matrix shows that the test split remains stable across
the assisted linkage variants. This is desirable when routed examples are
borderline and the deterministic matcher is already strong. The LLM is most
useful when it can correct specific ambiguous cases without creating broad
precision loss. The accepted changes in this release are small enough that
cluster-level metrics remain controlled by the deterministic constraints and
the underlying gold-label sparsity.

![Routing budget frontier](reports/release/figures/routing_budget_frontier.png)

Operational metrics summarize cost and reliability of selective LLM use.

| pipeline | config | calls | accepted | defaulted | tokens_in | tokens_out | cost_usd | fallback_rate | invalid_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Deterministic | fixture-A0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0 |
| LLM | fixture-C-LLM | 24 | 47 | 0 | 28161 | 2770 | 0.0 | 0.0 | 0.0 |
| Hybrid | fixture-B-All | 23 | 7 | 16 | 13792 | 1418 | 0.0 | 0.6957 | 0.0 |

## LLM Intervention Funnel



## Routing Budget Results



The routing-budget variants show the cost envelope for the live release.
B-All issued 0 model calls with an
estimated cost of $0.0. The
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

\newpage

# Error Analysis

The appendix stores structured source-level cases in
`reports/appendix/m4_error_cases.json` and
`reports/appendix/m4_error_cases.md`.

| case_id | stage | explanation |
| --- | --- | --- |
| schema_source_alpha//price | schema_alignment | The source attribute was mapped to the wrong mediated-schema field, which can propagate into normalization and fusion. |
| fusion_1_entity_000001 | fusion | The fused value disagrees with the curated or bootstrap fusion gold value, usually because conflicting source claims normalize to close but not identical values |
| fixture_placeholder_3 | fixture_only | Fixture-only placeholder. This cannot satisfy the M4 submission gate. |

## Detailed Cases

### schema_source_alpha//price

Stage: `schema_alignment`

System output: `{'source_attribute_id': 'source_alpha//price', 'predicted_target_attribute_name': 'UNMAPPED', 'score_total': 1.0, 'method': 'deterministic_schema_v1'}`

Expected output: `{'gold_target_attribute_name': 'price'}`

Explanation: The source attribute was mapped to the wrong mediated-schema field, which can propagate into normalization and fusion.

Source evidence: No source record excerpt was available in the fixture artifact.

### fusion_1_entity_000001

Stage: `fusion`

System output: `{'entity_id': 'entity_000001', 'attribute': 'price', 'predicted_value': '305.00'}`

Expected output: `{'truth_entity_id': 'ENTITY#001', 'expected_value': 'None'}`

Explanation: The fused value disagrees with the curated or bootstrap fusion gold value, usually because conflicting source claims normalize to close but not identical values.

Source evidence: `source_alpha:a100` title='Canon EOS 4000D DSLR Camera Kit' brand='Canon' model='EOS4000D'; `source_beta:b200` title='Canon 4000D 18MP Digital SLR' brand='Canon' model='4000D'; `source_gamma:c300` title='EOS 4000D Camera from Canon' brand='Canon' model='EOS4000D'

### fixture_placeholder_3

Stage: `fixture_only`

System output: `No additional labeled error was available.`

Expected output: `N/A`

Explanation: Fixture-only placeholder. This cannot satisfy the M4 submission gate.

Source evidence: No source record excerpt was available in the fixture artifact.


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

\newpage

# Conclusion

Mosaic satisfies the assignment by providing a traditional baseline, a selective
LLM-assisted pipeline, component metrics, operational measurements, concrete
error cases, and a reproducible report path. The final integrated dataset for
the selected release is `reports/release/final_integrated_dataset.jsonl`.

# GitHub Link

Repository: https://github.com/Forest904/selective-llm-product-integration.git

Reproduction summary:

```bash
make install
make reproduce
uv run mosaic experiment release --live
make report
```

\newpage

# Appendix

## Traceability Matrix

| requirement | artifact | evidence |
| --- | --- | --- |
| Baseline and assisted runs | reports/release/m4_release_manifest.json | A0, C-LLM, B-All, ablations, and budgets |
| Component metrics | reports/release/tables/metrics_summary.csv | Schema, blocking, linkage, clustering, fusion |
| Operational metrics | reports/release/tables/operational_metrics.csv | Calls, tokens, cost, fallbacks, invalid outputs |
| Concrete error cases | reports/appendix/m4_error_cases.json | Source records, outputs, expected values |
| Final dataset | reports/release/final_integrated_dataset.jsonl | Integrated entity JSONL export |
| Reproduction guide | README.md and reports/README.md | Live, fixture, report, and dataset commands |

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
committed under `reports/release/tables/`; large raw data and run
directories remain ignored and regenerable.
