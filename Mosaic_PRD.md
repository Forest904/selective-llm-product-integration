# Mosaic Product Requirements Document

**Product name:** Mosaic  
**Academic title:** Selective LLM Assistance for End-to-End Product Data Integration  
**Repository:** `selective-llm-product-integration`  
**Primary sources:** `Project_Blueprint_Mosaic.md` and `LLM_Assisted_Big_Data_Integration_Assignment.pdf`  
**Assignment due date:** June 15, 2026  
**Submission:** PDF report and GitHub repository  
**PRD status:** Authoritative implementation requirements for the full Mosaic vision

---

## 1. Product Overview

Mosaic is a reproducible research system and educational product for studying end-to-end product data integration with selective LLM assistance. It compares a deterministic integration baseline with an LLM-assisted pipeline, then exposes the process through a website where users can learn how data integration works and visually inspect the project.

The central research question is:

> Can selective, uncertainty-aware LLM intervention improve end-to-end data integration quality while preserving cost control, reproducibility, provenance, and deterministic fallbacks?

Mosaic must integrate multiple heterogeneous, partially overlapping, and conflicting product sources. The system must implement the full integration workflow required by the assignment:

1. Schema alignment: map source attributes to a mediated schema.
2. Record linkage / entity resolution: identify records that refer to the same real-world product.
3. Data fusion / truth discovery: reconcile conflicting values into one integrated product representation.

The pipeline is the source of truth. Every research operation must run through scripts, configuration files, tests, and reproducible commands before it is exposed through the website. The website is a client of the stable pipeline and must not contain hidden or divergent versions of integration logic.

### Product Vision

Mosaic should eventually become a full-stack integration workbench where users can:

- register and inspect heterogeneous data sources;
- profile schemas, values, and data quality;
- define and version a mediated product schema;
- inspect deterministic and LLM-assisted schema mappings;
- run baseline and LLM-assisted pipelines;
- review uncertain candidate pairs;
- inspect entity clusters and rejected merge decisions;
- investigate conflicting claims;
- approve or override fusion decisions;
- compare experiments by quality, cost, latency, and failure rate;
- export final integrated datasets, metrics, prompts, and report artifacts.

### Academic Vision

For the assignment, Mosaic must produce a defensible research release:

- deterministic baseline pipeline with no LLM integration decisions;
- LLM-assisted pipeline using the LLM in at least three stages: schema alignment, record linkage, and data fusion;
- component-level and end-to-end evaluation;
- versioned prompts and model settings;
- logged LLM calls and failures;
- final integrated dataset;
- concise, polished PDF report;
- reproducible GitHub repository.

### Educational Website Vision

The first website release prioritizes an educational demo, not the full operational workbench. It must include a dedicated animated project page that visually reproduces the assignment pipeline from heterogeneous sources through final report artifacts.

Users should be able to step through each integration stage, inspect small examples, compare deterministic and LLM-assisted behavior, and understand uncertainty, abstention, provenance, and failure modes.

---

## 2. Assignment Traceability Matrix

The assignment PDF is the grading source. Mosaic must satisfy every listed requirement before the academic release is considered complete.

| Assignment requirement | Mosaic requirement | Required artifact | Required metric or evidence | Acceptance check |
| --- | --- | --- | --- | --- |
| Submit PDF report and GitHub repository | Produce a report-ready research release with all code, data instructions, prompts, configs, metrics, and final outputs | `reports/report.pdf`, GitHub repo, README, environment file | Reproduction instructions and GitHub link in report | A clean clone can reproduce the reported pipeline on the documented dataset or fixture |
| Use multiple heterogeneous, partially overlapping, possibly conflicting sources | Use a curated product benchmark subset with at least 3 heterogeneous sources | Dataset manifest, source metadata, raw records | Source count, record count, overlap profile, conflict count | Manifest verifies assignment minimums |
| Minimum 1,000 records | Select or sample at least 1,000 source records across all sources | Dataset profile report | Total raw record count | Profile output reports `record_count >= 1000` |
| Minimum 5 mediated attributes | Define a mediated product schema with at least 5 attributes; target the richer 8-attribute schema from the blueprint | `mediated_schema.json`, schema docs | Attribute count, descriptions, types | Schema validator confirms required attributes |
| Minimum 200 integrated entities | Select a subset with at least 200 ground-truth entities or equivalent cluster truth | Ground truth files, entity labels | Entity count | Ground truth summary reports `entity_count >= 200` |
| Minimum 300 positive pairs or equivalent cluster truth | Use official labels where available or construct documented labels | Pair labels or cluster labels | Positive pair count | Evaluation set reports `positive_pair_count >= 300` or accepted cluster equivalent |
| Minimum 100 conflicting attribute values requiring fusion | Identify conflicting source claims for fusion evaluation | Claim conflict inventory | Conflict count by attribute | Conflict report verifies `fusion_conflict_count >= 100` |
| Schema alignment phase | Implement deterministic schema matching and LLM-assisted ambiguous mapping adjudication | Mapping candidates, mapping decisions, mapping prompts | Accuracy or precision/recall/F1 | Metrics computed against gold or labeled mappings |
| Record linkage / entity resolution phase | Implement blocking, pairwise matching, and clustering | Candidate pairs, pair features, linkage decisions, clusters | Pairwise precision, recall, F1, candidate-pair count | Evaluation script reproduces linkage metrics |
| Data fusion / truth discovery phase | Implement deterministic fusion and LLM-assisted unresolved conflict adjudication | Attribute claims, fused values, final entities | Fusion accuracy for attributes with ground truth | Fusion evaluation report is reproducible |
| Traditional baseline | Pipeline A must make integration decisions without LLM use | Baseline run manifest and artifacts | Baseline metrics | Run config shows no LLM decision stages |
| LLM-assisted pipeline | Pipeline B must use an LLM in at least two stages; Mosaic requires three | Assisted run manifest, prompts, call logs | Assisted metrics, LLM call count, failure rates | Run config shows LLM use in schema alignment, linkage, and fusion |
| Structured LLM outputs | All LLM decision stages must use validated JSON or equivalent structured output | Prompt files, JSON schemas, validation logs | Invalid-output rate | Invalid, missing, hallucinated, and empty responses are counted as failures unless fallback policy applies |
| Include all prompts in repository | Version prompts by stage and experiment | `prompts/schema`, `prompts/linkage`, `prompts/fusion` | Prompt versions in run manifests | Every LLM call references a committed prompt version |
| Report model settings | Record provider, model, temperature, max tokens, number of runs, retries, cache mode | Model config files, LLM call logs | Model settings table | Report contains model settings used for every assisted run |
| Do not manually correct LLM outputs at evaluation time | Evaluation consumes raw validated outputs and documented fallbacks only | LLM logs, validation outputs | Failure counts and fallback counts | No evaluation script depends on manual edits to LLM responses |
| Compare baseline and LLM-assisted configurations | Run A0 and B-All at minimum | Experiment manifests, metrics tables | Side-by-side quality and operational metrics | Report includes baseline vs assisted tables or plots |
| Component metrics | Evaluate schema alignment, linkage, fusion, and end-to-end quality | Metrics scripts and outputs | Required metrics by component | `mosaic evaluate` regenerates metrics |
| Error analysis | Provide at least three concrete examples | Error case files, report appendix | Source records, system output, expected output, explanation | Report includes at least three complete error cases |
| Discussion | Explain where LLMs help, fail, or introduce new errors | Report discussion section | Cost, latency, hallucination, reproducibility analysis | Discussion explicitly addresses deterministic vs LLM tradeoffs |

### Grading Alignment

| Grading criterion | Weight | Mosaic strategy |
| --- | ---: | --- |
| Implementation | 25% | Build a complete deterministic baseline and a validated LLM-assisted pipeline with immutable artifacts and CLI execution |
| Metrics | 20% | Compute required component metrics plus optional cost, latency, reduction ratio, completeness, abstention, invalid-output, and hallucination/unsupported-value rates |
| Experimental design | 20% | Version dataset manifests, prompts, model settings, thresholds, code commit, random seed, and run configs |
| Error analysis | 20% | Save concrete error cases, trace stage of origin, and discuss deterministic and LLM failure modes |
| Presentation and code quality | 10% | Produce a polished report, organized repository, typed validation models, tests, and reproduction docs |
| Originality | 5% | Add selective uncertainty-aware LLM routing and quality-cost analysis |

---

## 3. Users And Use Cases

### Primary Academic Evaluator

The evaluator needs to verify that the submission satisfies the assignment and that reported claims are reproducible.

Required capabilities:

- read a concise report with clear methodology, results, and discussion;
- inspect the GitHub repository structure;
- run setup and reproduction commands;
- verify dataset selection and ground truth;
- regenerate metrics and final integrated outputs;
- inspect all prompts, model settings, and failure policies.

Success criteria:

- no hidden manual steps are required for the reported results;
- every reported number is tied to a run manifest and evaluation script;
- assignment minimums are visibly satisfied;
- LLM usage is controlled, logged, and evaluated rather than anecdotal.

### Student Or Researcher

The researcher needs to develop, run, and compare integration experiments.

Required capabilities:

- profile candidate datasets and choose a benchmark subset;
- configure baseline and LLM-assisted runs;
- tune blocking, matching, clustering, fusion, and routing thresholds;
- run stage-specific ablations;
- inspect cost-quality tradeoffs;
- export report-ready tables, plots, and error cases.

Success criteria:

- experiments can be repeated with stable artifacts;
- changes in prompts, thresholds, or models create new traceable runs;
- component metrics make failure origins visible.

### Educational Website Visitor

The visitor wants to learn data integration concepts through a guided, visual experience.

Required capabilities:

- step through an animated version of the Mosaic assignment pipeline;
- inspect toy source records and see how they become canonical entities;
- compare deterministic and LLM-assisted decisions;
- see why blocking is necessary;
- understand abstention, uncertainty, cost, and provenance;
- view report-style outputs at the end of the demo.

Success criteria:

- the visitor understands the relationship between schema alignment, linkage, clustering, and fusion;
- the demo communicates that LLMs help selectively, not universally;
- the animated project page is visually polished and self-contained.

### Reviewer Or Operator

The reviewer uses the later workbench to inspect and correct uncertain integration decisions.

Required capabilities:

- review ambiguous schema mappings;
- judge uncertain candidate pairs;
- inspect clusters and rejected edges;
- review conflicting claims and fusion decisions;
- override decisions with comments;
- preserve a full audit trail.

Success criteria:

- every human decision is recorded;
- manual actions preserve provenance;
- unsafe cluster or fusion edits are blocked or explicitly flagged.

---

## 4. Core Research Product Requirements

### 4.1 Dataset Discovery And Selection

Mosaic should use a curated subset of the Alaska product integration benchmark by default. The final choice must be data-driven. If profiling shows that another public benchmark better satisfies the assignment, the PRD allows replacement only if the replacement satisfies every assignment minimum and supports meaningful schema alignment, linkage, and fusion evaluation.

The dataset selection workflow must:

- locate manually provided candidate benchmark files;
- identify available sources, categories, labels, and attributes;
- compute dataset size, source count, entity count, positive pair count, and conflict count;
- profile overlap between sources;
- profile schema heterogeneity;
- score candidate product domains;
- recommend one final subset;
- document the selection decision.

Candidate selection criteria:

- source count;
- record count;
- entity count;
- positive pair count or equivalent cluster truth;
- cross-source overlap;
- attribute count;
- missingness;
- model-number coverage;
- schema heterogeneity;
- conflicting-claim count;
- category purity;
- expected difficulty for LLM analysis.

The selected academic subset must satisfy at least:

- 3 heterogeneous sources;
- 1,000 raw source records;
- 5 mediated attributes;
- 200 integrated entities;
- 300 known positive pairs or equivalent cluster-level truth;
- 100 conflicting attribute values requiring fusion.

Mosaic should target the stronger blueprint scale when feasible:

- 3 to 8 sources;
- 5,000 to 25,000 raw source records;
- 500 or more ground-truth entities;
- 500 or more known positive pairs;
- 8 or more mediated attributes;
- 200 or more fusion conflicts.

### 4.2 Immutable Ingestion And Profiling

Raw input files must never be edited. Ingestion must produce stable, versioned artifacts with checksums and source metadata.

Required ingestion behavior:

- support CSV, JSON, JSON Lines, and Parquet for the research release;
- preserve raw payloads;
- assign stable record identifiers using `record_uid = "{source_id}:{source_record_id}"`;
- reject row position as a stable identifier;
- validate malformed records and report ingestion errors;
- record source metadata including origin, retrieval date, license, and record count;
- write immutable raw artifacts and a dataset manifest.

Required output artifacts:

- `sources.parquet`;
- `source_records.parquet`;
- `ingestion_errors.parquet`;
- `dataset_manifest.json`.

Profiling must compute, per source attribute:

- inferred type;
- null rate;
- uniqueness rate;
- cardinality;
- string length distribution;
- numeric distribution;
- frequent values;
- representative samples;
- token patterns;
- unit patterns;
- URL, identifier, currency, date, measurement, or free-text likelihood;
- semantic-role suggestions such as brand, title, model identifier, price, currency, description, category, measurement, URL, or specification.

Profiling suggestions are evidence, not final mappings.

### 4.3 Mediated Schema

The mediated schema must be expressive enough for product integration but narrow enough for rigorous evaluation.

The assignment requires at least 5 relevant mediated attributes. Mosaic targets the following 8 required canonical attributes:

1. `title`
2. `brand`
3. `model_number`
4. `category`
5. `description`
6. `price`
7. `currency`
8. `specifications`

Optional canonical attributes:

- `gtin`;
- `sku`;
- `manufacturer_part_number`;
- `availability`;
- `condition`;
- `product_url`;
- `image_url`;
- `release_date`.

The canonical product entity must support:

- canonical title;
- canonical brand;
- canonical model number;
- canonical category;
- canonical description;
- canonical price;
- canonical currency;
- canonical URL;
- canonical image URL;
- semi-structured specifications;
- overall confidence;
- source count;
- creation and update metadata.

Long-tail technical properties must be stored in a semi-structured specification model while still preserving each specification as an independent claim for fusion and evaluation.

### 4.4 Deterministic Baseline Pipeline

Pipeline A is the traditional baseline. It must not use an LLM for integration decisions.

Required stages:

1. Source ingestion.
2. Source profiling.
3. Deterministic schema alignment.
4. Deterministic normalization.
5. Blocking.
6. Pairwise feature engineering.
7. Pairwise matching.
8. Entity clustering.
9. Claim extraction.
10. Deterministic data fusion.
11. Evaluation and reporting.

#### Deterministic Schema Alignment

The baseline must construct candidate mappings using:

- name evidence, including exact equality, token overlap, character n-grams, Jaro-Winkler similarity, abbreviations, and domain synonyms;
- type evidence, including string, integer, decimal, currency, identifier, measurement, URL, categorical, free text, date, and boolean types;
- value evidence, including normalized overlap, numeric ranges, currency symbols, unit distributions, identifier formats, string lengths, cardinalities, frequent tokens, and uniqueness;
- context evidence, including neighboring fields, co-occurring attributes, source-level schema context, and mapping coherence.

The schema matcher must:

- rank candidate mediated attributes;
- support unmapped attributes;
- support one-to-many, many-to-one, and composite mappings where needed;
- avoid forcing every source attribute into the mediated schema;
- produce score decompositions and evidence for evaluation and review.

#### Deterministic Normalization

The baseline must normalize mapped values while preserving raw values and methods.

Required normalizers:

- text;
- title;
- brand;
- model number;
- category;
- price;
- currency;
- measurement;
- storage;
- dimension;
- weight;
- boolean;
- URL;
- specification key.

Normalization rules must be deterministic, versioned, tested, reversible where practical, and provenance-preserving.

#### Blocking

Blocking is mandatory. The system must not compare all pairs except in tiny fixture tests.

The baseline must use a union of blocking strategies:

- strong identifiers such as brand plus model number, GTIN, or manufacturer part number;
- rare normalized model tokens;
- rare informative title tokens;
- q-gram, MinHash, or locality-sensitive signatures;
- category-aware retrieval;
- specification signatures such as brand plus capacity, screen size, or product family.

Each candidate pair must record every blocking rule that generated it.

Required blocking metrics:

- candidate pair count;
- positive pairs retained;
- pair completeness;
- reduction ratio;
- candidates per record;
- duplicate candidate rate;
- runtime;
- memory where available.

#### Pairwise Feature Engineering

Pairwise matching must use interpretable features:

- title similarities;
- brand agreement and alias handling;
- model identifier agreement and conflicts;
- category compatibility;
- description similarity;
- price difference;
- specification agreement;
- missingness;
- source-pair indicators;
- blocking rule count.

Ground-truth labels must never enter inference prompts or features.

#### Pairwise Matching

The baseline must include:

- a transparent rule system for obvious matches and non-matches;
- a classical supervised model, with logistic regression as the primary model;
- calibrated thresholds;
- entity-safe train/validation/test splits.

Splits must keep all records belonging to one ground-truth entity in the same split. The default split is:

- training: 60%;
- validation: 20%;
- test: 20%.

An optional generalization experiment may train on some source pairs and evaluate on an unseen source pair.

#### Clustering

The primary clustering method must be constraint-aware agglomeration, not blind connected components. A connected-components implementation should remain as a comparison baseline.

Cluster merge constraints must include:

- maximum one record per source when appropriate;
- compatible strong identifiers;
- compatible brands;
- compatible product variants;
- maximum cluster size;
- minimum cross-cluster edge support when needed.

Every accepted and rejected merge must preserve evidence and confidence.

#### Claim Extraction

After clustering, each normalized source value must become an explicit attribute claim.

Claims must preserve:

- entity;
- source;
- source record;
- original source attribute;
- raw value;
- normalized value;
- unit;
- observation time where available;
- extraction confidence.

The claim layer must decouple clustering from fusion and support provenance for every fused value.

#### Deterministic Fusion

Fusion must use attribute-specific policies:

| Attribute | Initial deterministic policy |
| --- | --- |
| Brand | Normalized weighted mode |
| Model number | Strongest identifier consensus |
| Title | Medoid or highest-quality representative |
| Category | Weighted mode |
| Description | Most complete non-duplicate description |
| Price | Most recent valid price or robust median |
| Currency | Direct source value or deterministic inference |
| Numeric specification | Tolerance-aware median |
| Categorical specification | Weighted mode |
| URL | Preferred source or highest-quality valid URL |

Every fused value must record:

- selected value;
- selected unit;
- fusion method;
- confidence;
- supporting claim IDs;
- contradicting claim IDs;
- alternatives;
- abstention status;
- review status.

### 4.5 LLM-Assisted Pipeline

Pipeline B must use an LLM in three required stages:

1. LLM-assisted schema alignment.
2. LLM-assisted record linkage.
3. LLM-assisted data fusion.

LLM-assisted normalization is a stretch feature and must not block the academic release.

#### LLM Gateway

All model calls must pass through one provider-neutral gateway.

The gateway must handle:

- prompt rendering;
- structured-output enforcement;
- schema validation;
- retry policy;
- timeout handling;
- caching;
- cost estimation;
- token counting;
- tracing;
- fallback execution;
- provider substitution.

Every LLM call must log:

- request ID;
- run ID;
- stage;
- provider;
- model;
- prompt version;
- settings;
- input hash;
- request payload;
- raw response;
- parsed response;
- validation result;
- retry count;
- latency;
- input tokens;
- output tokens;
- estimated cost;
- creation timestamp.

Default research settings:

- temperature: 0;
- structured output: required;
- retries: bounded;
- cache: enabled;
- manual correction during evaluation: forbidden.

Invalid JSON, missing fields, hallucinated values, unsupported values, unknown IDs, and empty responses must be counted as failures unless a documented fallback is applied.

#### LLM-Assisted Schema Alignment

The LLM may only adjudicate uncertain mappings. It must not replace deterministic schema matching.

Routing triggers may include:

- top deterministic candidate score below acceptance threshold;
- small margin between first and second candidate;
- type evidence conflicts with name evidence;
- candidate mapping appears composite or ambiguous;
- deterministic method returns `UNMAPPED` with medium evidence for a target.

Prompt input must include:

- source attribute name;
- source description where available;
- inferred type;
- representative values;
- neighboring source attributes;
- target schema definitions;
- deterministic candidate scores.

Structured output must include:

- source attribute;
- target attribute from an allowed enumeration;
- decision;
- confidence;
- supporting evidence;
- abstention flag.

Allowed target choices are:

- one provided mediated attribute;
- `UNMAPPED`;
- `ABSTAIN`.

The model must not invent new target fields during evaluation.

#### LLM-Assisted Record Linkage

The LLM may only judge difficult or borderline candidate pairs generated by blocking.

Starting uncertainty band:

- send pairs to the LLM only when baseline probability is approximately between 0.35 and 0.75;
- tune the final band on validation data.

Prompt input must include:

- normalized record A;
- normalized record B;
- selected raw values;
- pairwise feature values;
- agreements;
- conflicts;
- missing fields;
- deterministic score.

Structured output must include:

- `match` or `non_match`;
- confidence;
- supporting evidence;
- contradicting evidence;
- abstention flag.

Final decision policy:

1. Use deterministic prediction when deterministic confidence is high.
2. Use valid LLM output when it exceeds the configured confidence threshold.
3. If the LLM abstains, use documented fallback or queue human review.
4. If output is invalid, record failure and use documented fallback.
5. Leave unresolved cases unresolved rather than forcing false certainty.

#### LLM-Assisted Data Fusion

The LLM may only adjudicate unresolved or ambiguous claim conflicts.

Routing triggers may include:

- weighted vote tie;
- low consensus;
- incompatible normalizations;
- conflicting units;
- competing descriptions;
- recency and source reliability disagreement;
- potential bundle-versus-base-product conflict;
- possible mixed product variants.

Prompt input must include:

- attribute name;
- candidate claims;
- source names or source IDs;
- raw values;
- normalized values;
- allowed output values;
- deterministic fusion evidence;
- confidence and conflict summary.

Structured output must include:

- selected value from allowed outputs or `ABSTAIN`;
- confidence;
- supporting claim IDs;
- contradicting claim IDs;
- reason;
- abstention flag.

Guardrails:

- selected values must be source-supported or deterministically derivable;
- supporting claim IDs must exist;
- incompatible units cause rejection;
- invented values cause rejection;
- explanations are metadata, not proof of correctness.

### 4.6 Cost-Aware Selective Routing

Selective routing is Mosaic's primary originality extension. The system must measure when an LLM call is worth making.

The routing model or policy should estimate:

`P(LLM fixes the baseline | case_features)`

Possible routing features:

- baseline confidence;
- classification margin;
- feature conflict count;
- missingness;
- identifier disagreement;
- brand disagreement;
- title similarity;
- price difference;
- source pair;
- record completeness;
- conflict severity;
- stage type.

Conceptual policy:

`call LLM when expected_error_reduction * error_cost > llm_call_cost + latency_penalty`

Required routing outputs:

- eligible case count;
- selected case count;
- LLM call count;
- tokens;
- estimated cost;
- latency;
- quality improvement;
- abstention rate;
- invalid-output rate;
- fallback rate.

Budget experiments should evaluate at least:

- 0%;
- 5%;
- 10%;
- 20%;
- 30%;
- 50%;
- 100%;

of eligible uncertain cases.

### 4.7 Provenance, Abstention, And Reproducibility

Every decision layer must support:

- accept;
- reject;
- abstain;
- fallback;
- human review.

The system must never force false certainty.

Every schema mapping, normalized value, candidate pair, linkage decision, cluster membership, claim, and fused value must be traceable to:

- raw source data;
- normalized evidence;
- deterministic features or rules;
- LLM prompt and response when used;
- configuration version;
- code version;
- run ID;
- timestamp;
- confidence;
- fallback or abstention status.

A completed experiment must be reproducible from:

- dataset manifest;
- code commit;
- configuration;
- prompt versions;
- model identifier;
- model settings;
- random seed;
- cached or logged model responses;
- evaluation script version.

---

## 5. Report Requirements

The academic report must be concise, polished, and grading-traceable. Target length is 10 to 15 pages plus appendix.

### Required Report Sections

1. **Introduction**
   - State the problem and research question.
   - Explain why product data integration is difficult.
   - Summarize the deterministic versus selective LLM comparison.

2. **Dataset And Scope**
   - Name the benchmark and selected subset.
   - Report source count, record count, entity count, positive pair count, mediated attributes, and conflict count.
   - Distinguish full input dataset from labeled evaluation subset if they differ.
   - Document collection, sampling, and ground-truth construction if any labels are constructed manually.

3. **Mediated Schema**
   - Define the canonical product schema.
   - Explain required attributes and semi-structured specifications.
   - Show examples of heterogeneous source attributes mapping into the mediated schema.

4. **Methodology**
   - Describe Pipeline A: deterministic baseline.
   - Describe Pipeline B: LLM-assisted integration.
   - Explain prompts, output formats, blocking, matching, clustering, and fusion strategies.
   - Explain abstention, fallback, validation, and provenance.

5. **Experimental Protocol**
   - Report dataset sizes, splits, ground truth, parameters, thresholds, model settings, prompt versions, number of LLM calls, number of runs, cache policy, and failure policy.
   - State that invalid JSON, missing fields, hallucinated values, unsupported values, and empty responses are treated as failures unless fallback is documented.

6. **Results**
   - Include quantitative tables or plots comparing baseline and LLM-assisted configurations.
   - Report required component metrics.
   - Include optional operational metrics where useful: cost, latency, token usage, reduction ratio, completeness, abstention rate, invalid-output rate, fallback rate, unsupported-value rate.

7. **Error Analysis**
   - Include at least three concrete source-level examples.
   - Each example must show source records, system output, expected output, explanation of the error, and stage of origin.
   - Cover at least two different error categories when possible.

8. **Discussion**
   - Explain where LLMs help.
   - Explain where deterministic methods remain preferable.
   - Discuss cost, latency, hallucinations, unsupported values, reproducibility, and provenance.
   - State limitations and future work.

9. **Conclusion**
   - Summarize whether selective LLM assistance improved integration quality and at what cost.
   - Connect the conclusion back to the assignment objective.

10. **GitHub Link**
   - Include the repository URL and reproduction instructions summary.

### Required Tables And Figures

The report must include:

- dataset summary table;
- mediated schema table;
- pipeline architecture figure;
- baseline versus LLM-assisted configuration table;
- schema alignment metrics table;
- blocking metrics table;
- linkage metrics table;
- fusion metrics table;
- operational metrics table for LLM calls, tokens, cost, latency, invalid outputs, abstentions, and fallbacks;
- at least one quality-cost plot or table for selective routing;
- at least three error analysis case tables.

### Report Polish Requirements

The PDF must:

- have consistent headings, numbering, and captions;
- use readable tables with units and clear metric definitions;
- avoid unresolved placeholders;
- include source citations for benchmark and major tools where appropriate;
- include enough detail for reproduction without overloading the main text;
- move long prompts, extra metrics, and additional error cases into an appendix when needed.

---

## 6. Educational Website Requirements

The first website version is an educational demo. Its goal is to help users learn data integration and understand the Mosaic assignment project. It does not need to run arbitrary real datasets in the browser.

### 6.1 Information Architecture

Required first-release pages:

1. **Home / Learning Hub**
   - Introduce Mosaic.
   - Explain data integration in approachable terms.
   - Provide entry points to the animated pipeline, concept modules, and project results.

2. **Animated Assignment Pipeline**
   - Dedicated page visually reproducing the Mosaic assignment project.
   - This is the centerpiece of the educational demo.

3. **Concept Explorer**
   - Short interactive modules for schema alignment, blocking, record linkage, clustering, fusion, LLM assistance, uncertainty, and provenance.

4. **Experiment Results**
   - Show report-style metrics and charts from the research release.
   - Compare baseline and LLM-assisted runs.

5. **Error Gallery**
   - Present the report's concrete error cases in an interactive format.

6. **Final Dataset Preview**
   - Show integrated product entities with source membership and confidence.

### 6.2 Animated Assignment Pipeline Page

The animated page must visually reproduce the assignment project from raw sources to final report artifacts.

Required stages:

1. Heterogeneous sources.
2. Schema alignment.
3. Normalization.
4. Blocking.
5. Record linkage.
6. Entity clustering.
7. Claim extraction.
8. Data fusion.
9. Integrated entities.
10. Metrics, report, and exports.

For each stage, the page must show:

- a short stage title;
- one concrete toy example;
- input objects;
- transformation or decision;
- output objects;
- deterministic evidence;
- LLM evidence when applicable;
- uncertainty or confidence;
- provenance link to prior stage;
- one common error mode.

The animation should communicate flow and causality:

- source records should visually move into schema mapping;
- mapped attributes should become normalized canonical fields;
- blocking should reduce the candidate space;
- record pairs should become match or non-match decisions;
- accepted edges should form clusters;
- cluster values should become claims;
- conflicting claims should be fused into canonical values;
- final products should connect to metrics and report outputs.

The page must include controls:

- play / pause animation;
- step forward and backward;
- stage selector;
- baseline versus LLM-assisted toggle;
- uncertainty overlay toggle;
- provenance overlay toggle;
- reset demo.

The page must use demo data that is small enough to understand:

- 3 toy sources;
- 6 to 12 toy records;
- 2 or 3 true products;
- at least one schema synonym;
- at least one borderline pair;
- at least one fusion conflict;
- at least one LLM abstention or invalid-output example.

### 6.3 Concept Explorer

Concept modules must be educationally interactive.

Required modules:

- **Schema Alignment:** users match source attributes to canonical fields and compare their choices with deterministic and LLM recommendations.
- **Blocking:** users adjust a threshold or blocking rule and see candidate count, missed matches, and reduction ratio change.
- **Record Linkage:** users inspect two records side by side and decide match, non-match, or unsure.
- **Clustering:** users see how pairwise decisions become entity clusters and how one bad bridge can over-merge products.
- **Fusion:** users pick a canonical value from conflicting claims and inspect supporting and contradicting evidence.
- **LLM Routing:** users see why only uncertain cases are sent to the model and how call budget affects quality and cost.
- **Provenance:** users trace one final value back to source records, raw values, normalized values, and decision evidence.

### 6.4 Educational Design Requirements

The educational website must:

- prioritize clarity over marketing copy;
- avoid hiding key interactions below decorative content;
- use dense but readable operational UI for data views;
- use animation only when it clarifies process flow;
- include empty, loading, and error states;
- work on desktop and mobile without overlap or clipping;
- provide accessible labels for controls;
- avoid making the LLM appear magically authoritative;
- visibly distinguish deterministic evidence, LLM evidence, and human review.

---

## 7. Full Workbench Requirements

The full workbench is a later phase after the academic release and educational demo. It should expose real project execution and review workflows through the web application.

### 7.1 Project Dashboard

Show:

- source count;
- record count;
- schema mapping status;
- candidate pair count;
- predicted match count;
- entity count;
- unresolved conflicts;
- review queue size;
- latest experiment;
- pipeline status;
- LLM cost and latency summary;
- recent activity.

Acceptance criterion:

- a user can understand the state of one integration project from a single screen.

### 7.2 Source Catalog And Profiling Views

Users must be able to:

- register a source;
- upload data;
- inspect ingestion status;
- view malformed records;
- inspect schema and profile statistics;
- compare source coverage.

Profile views must show:

- columns;
- inferred types;
- null rates;
- uniqueness;
- distributions;
- samples;
- detected units;
- semantic-role suggestions.

Acceptance criterion:

- a user can understand why a source attribute received its inferred type and semantic suggestion.

### 7.3 Mediated Schema Editor

Users must be able to:

- create attributes;
- edit descriptions;
- specify types;
- define allowed units;
- set cardinality;
- version the schema;
- compare schema versions.

Acceptance criterion:

- every schema change creates a versioned, auditable artifact.

### 7.4 Schema Mapping Workbench

For each source attribute, show:

- candidate target attributes;
- deterministic scores;
- score decomposition;
- sample values;
- LLM recommendation;
- LLM evidence;
- confidence;
- accepted mapping;
- reviewer override.

Required actions:

- accept;
- reject;
- remap;
- mark unmapped;
- abstain;
- add comment.

Acceptance criterion:

- a reviewer can resolve ambiguous mappings without editing files manually.

### 7.5 Pair Review Workbench

Two records must appear side by side.

Show:

- raw fields;
- normalized fields;
- highlighted agreements;
- highlighted conflicts;
- pairwise feature values;
- baseline score;
- LLM decision;
- supporting and contradicting evidence;
- ground truth in evaluation mode only;
- reviewer decision history.

Required controls:

- match;
- non-match;
- unsure;
- defer;
- comment;
- next task.

Acceptance criterion:

- a reviewer can process uncertain candidate pairs quickly and consistently.

### 7.6 Cluster Explorer

Users must be able to:

- inspect cluster members;
- see supporting edges;
- view rejected edges;
- inspect constraint violations;
- split a cluster;
- merge compatible clusters;
- trace cluster history.

Acceptance criterion:

- manual cluster changes preserve a complete audit trail and cannot silently violate hard constraints.

### 7.7 Fusion And Provenance Workbench

For each entity attribute, show:

- all source claims;
- raw values;
- normalized values;
- source weights;
- deterministic vote or rule;
- LLM adjudication when used;
- selected value;
- alternatives;
- confidence;
- supporting and contradicting claim IDs.

Required actions:

- approve;
- override;
- abstain;
- queue review;
- add comment.

Acceptance criterion:

- every canonical attribute can be traced from selected value back to raw source evidence.

### 7.8 Integrated Entity Browser

Users must be able to:

- search canonical products;
- filter by source count, confidence, category, and unresolved fields;
- open entity details;
- inspect member source records;
- inspect provenance;
- export selected records.

Acceptance criterion:

- a user can browse and inspect the integrated dataset without understanding internal pipeline files.

### 7.9 Experiment Dashboard

Users must be able to compare runs by:

- schema metrics;
- linkage metrics;
- clustering metrics;
- fusion metrics;
- end-to-end metrics;
- costs;
- latency;
- abstentions;
- invalid outputs;
- prompt version;
- model;
- configuration.

Acceptance criterion:

- the principal report tables and plots can be reproduced from the dashboard.

### 7.10 Error Analysis Center

Users must be able to:

- filter errors by taxonomy;
- inspect saved cases;
- compare expected and predicted outputs;
- trace stage of origin;
- add notes;
- export cases to report format.

Required error categories:

- schema synonym failure;
- schema homonym failure;
- wrong type;
- composite-field failure;
- missed positive pair;
- overly broad block;
- common-title collision;
- brand alias failure;
- bundle confusion;
- variant confusion;
- clustering chain;
- over-merge;
- under-merge;
- majority wrong;
- stale value selected;
- copied value overcounted;
- unit mismatch;
- unsupported LLM output;
- invalid JSON;
- hallucinated value;
- timeout;
- overconfidence;
- failure to abstain.

Acceptance criterion:

- at least three report-ready errors can be exported directly from saved application cases.

### 7.11 Export And Reporting Center

Exports must include:

- integrated entities CSV;
- integrated entities Parquet;
- JSON with provenance;
- schema mappings;
- pair predictions;
- clusters;
- claims;
- fusion decisions;
- metrics;
- error examples;
- experiment manifest;
- report tables;
- research-release bundle.

Acceptance criterion:

- a project administrator can produce all submission and analysis artifacts from one workflow.

---

## 8. Interfaces And Artifacts

### 8.1 CLI Contract

The full research project must remain operable from the command line.

Required commands:

```bash
uv run mosaic dataset select
uv run mosaic dataset ingest
uv run mosaic dataset profile
uv run mosaic schema propose
uv run mosaic schema evaluate
uv run mosaic normalize
uv run mosaic block
uv run mosaic match --pipeline baseline
uv run mosaic match --pipeline llm-assisted
uv run mosaic cluster
uv run mosaic claims extract
uv run mosaic fuse --pipeline baseline
uv run mosaic fuse --pipeline llm-assisted
uv run mosaic evaluate
uv run mosaic experiment run configs/experiments/b_all.yaml
uv run mosaic report build
uv run mosaic export integrated
```

Required aggregate commands:

```bash
make reproduce
make dev
make test
```

Acceptance criteria:

- `make reproduce` regenerates the academic artifacts from documented inputs;
- `make test` runs unit, integration, golden, and fixture checks;
- CLI and website invoke shared application services, not duplicate logic.

### 8.2 Backend API Surface

The backend should follow these endpoint groups.

Projects:

```text
GET    /projects
POST   /projects
GET    /projects/{project_id}
PATCH  /projects/{project_id}
```

Sources:

```text
POST   /projects/{project_id}/sources
GET    /projects/{project_id}/sources
GET    /sources/{source_id}
POST   /sources/{source_id}/ingest
GET    /sources/{source_id}/profile
```

Schema:

```text
GET    /projects/{project_id}/schemas
POST   /projects/{project_id}/schemas
POST   /schemas/{schema_id}/mapping-runs
GET    /mapping-runs/{run_id}
PATCH  /schema-mappings/{mapping_id}
```

Pipeline:

```text
POST   /projects/{project_id}/pipeline-runs
GET    /pipeline-runs/{run_id}
POST   /pipeline-runs/{run_id}/cancel
GET    /pipeline-runs/{run_id}/artifacts
```

Linkage:

```text
GET    /projects/{project_id}/candidate-pairs
GET    /candidate-pairs/{pair_id}
POST   /candidate-pairs/{pair_id}/review
```

Clusters:

```text
GET    /projects/{project_id}/clusters
GET    /clusters/{entity_id}
POST   /clusters/{entity_id}/split
POST   /clusters/merge
```

Fusion:

```text
GET    /entities/{entity_id}/claims
GET    /entities/{entity_id}/fusion
POST   /fused-values/{fused_value_id}/review
```

Experiments:

```text
GET    /projects/{project_id}/experiments
POST   /projects/{project_id}/experiments
GET    /experiments/{run_id}
GET    /experiments/{run_id}/metrics
GET    /experiments/compare
```

Review:

```text
GET    /projects/{project_id}/review-tasks
POST   /review-tasks/{task_id}/claim
POST   /review-tasks/{task_id}/resolve
```

Exports:

```text
POST   /projects/{project_id}/exports
GET    /exports/{export_id}
```

### 8.3 Research Artifacts

Research artifacts must use versioned Parquet, JSON, CSV, Markdown, and PDF outputs.

Required artifact families:

- dataset manifests;
- source metadata;
- raw records;
- source profiles;
- mediated schemas;
- schema mapping candidates and decisions;
- normalized records;
- normalized values;
- candidate pairs;
- pairwise features;
- linkage decisions;
- clusters and memberships;
- attribute claims;
- fused values;
- integrated entities;
- experiment manifests;
- metrics tables;
- plots;
- error cases;
- prompts;
- model configs;
- LLM call logs;
- final report.

Every derived artifact must record:

- input version;
- configuration version;
- code version;
- creation timestamp;
- parent artifacts;
- content checksum.

### 8.4 Prompt And Model Artifacts

Prompts must live in versioned directories:

```text
prompts/schema/
prompts/linkage/
prompts/fusion/
prompts/normalization/    # stretch
```

Each prompt version must include:

- template text;
- intended stage;
- expected JSON schema;
- allowed output values;
- prompt version ID;
- examples when used;
- validation notes.

Model configuration files must include:

- provider;
- model identifier;
- temperature;
- maximum tokens;
- retry count;
- timeout;
- cache mode;
- structured-output mode;
- date used;
- known limitations.

### 8.5 Experiment Records

Every experiment run must record:

- run ID;
- project ID;
- configuration hash;
- code commit;
- dataset version;
- prompt versions;
- model settings;
- random seed;
- start and completion timestamps;
- status;
- metrics;
- artifact location;
- LLM call count;
- tokens;
- estimated cost;
- latency summary;
- invalid-output count;
- abstention count;
- fallback count.

---

## 9. Testing And Acceptance Criteria

### 9.1 Unit Tests

Unit tests must cover:

- normalizers;
- type inference;
- schema scores;
- blocking keys;
- similarity features;
- pairwise classifiers;
- clustering constraints;
- fusion rules;
- structured-output validation;
- LLM failure classification;
- routing policies;
- provenance validators.

### 9.2 Property And Invariant Tests

Required invariants:

- a candidate pair cannot contain the same record twice;
- a clustered record belongs to exactly one active cluster;
- every fused value has supporting claims unless explicitly abstained;
- every claim references an existing source record;
- no LLM-selected claim ID may be unknown;
- no ground-truth label may enter an inference prompt;
- every experiment has a configuration hash;
- every export is tied to one completed run;
- every LLM decision references a prompt version;
- every final integrated entity references at least one source record.

### 9.3 Golden Tests

Maintain a curated fixture suite for:

- obvious match;
- obvious non-match;
- punctuation-only model difference;
- different product capacity;
- bundle versus standalone item;
- accessory versus primary product;
- ambiguous schema field;
- conflicting unit;
- stale price;
- copied specification error;
- unsupported LLM value;
- invalid JSON response;
- LLM abstention.

### 9.4 Integration Tests

Test complete stage transitions:

- ingestion to profiling;
- profiling to schema mapping;
- schema mapping to normalization;
- normalization to blocking;
- blocking to matching;
- matching to clustering;
- clustering to claims;
- claims to fusion;
- fusion to integrated entities;
- experiment run to metrics;
- metrics to report tables.

### 9.5 End-To-End Reproducibility Test

CI must run the complete pipeline against a small fixture dataset and verify:

- expected artifacts exist;
- artifact schemas are valid;
- metric ranges are within expected bounds;
- final integrated entities are generated;
- prompts and model configs are discoverable;
- report tables can be regenerated.

### 9.6 Website Tests

The educational website must be checked for:

- animated pipeline clarity;
- stage navigation;
- baseline versus LLM toggle behavior;
- provenance overlay behavior;
- uncertainty overlay behavior;
- responsive layout on desktop and mobile;
- empty states;
- loading states;
- error states;
- accessibility labels;
- keyboard navigation for key controls.

The full workbench must additionally include:

- API contract tests;
- review workflow tests;
- export workflow tests;
- authorization tests once auth exists;
- browser end-to-end tests for critical flows.

### 9.7 Academic Release Definition Of Done

The academic release is done when:

- assignment minimum dataset requirements are satisfied or exceeded;
- deterministic baseline runs end to end without LLM decisions;
- LLM-assisted pipeline uses schema alignment, record linkage, and fusion;
- all prompts and model settings are committed;
- all LLM calls are logged and validated;
- invalid outputs and fallbacks are measured;
- schema, linkage, fusion, and end-to-end metrics are reported;
- at least three complete error cases are included;
- final integrated dataset is exportable;
- report PDF is polished and complete;
- README explains reproduction;
- evaluation scripts regenerate reported metrics.

### 9.8 Full Product Definition Of Done

The full Mosaic vision is done when:

- users can create projects and ingest sources;
- users can inspect profiles and mappings;
- users can execute pipeline runs;
- users can review uncertain pairs;
- users can inspect and edit clusters;
- users can review fusion conflicts;
- users can browse integrated entities;
- users can compare experiments;
- users can export results;
- educational users can step through the animated assignment pipeline;
- all human actions are audited;
- deployment and operational documentation exist.

---

## 10. Phasing

### Phase 1: Academic Research Release

Goal: satisfy every assignment requirement and produce the PDF report and GitHub repository.

Required outcomes:

- dataset selected and documented;
- immutable ingestion and profiling complete;
- mediated schema defined;
- deterministic baseline implemented;
- LLM gateway implemented;
- LLM-assisted schema alignment, record linkage, and fusion implemented;
- selective routing measured;
- experiments executed;
- metrics generated;
- error analysis completed;
- final integrated dataset exported;
- report PDF generated;
- reproduction instructions verified.

Non-goals:

- arbitrary user uploads through the website;
- production authentication;
- full multi-user workbench;
- real-time streaming architecture;
- fine-tuning a foundation model.

### Phase 2: Educational Demo Website

Goal: make the research project understandable and visually compelling.

Required outcomes:

- learning hub;
- animated assignment pipeline page;
- concept explorer modules;
- experiment results page;
- error gallery;
- final dataset preview;
- responsive, accessible UI.

Non-goals:

- full operational pipeline execution from the browser;
- complex role management;
- unrestricted dataset authoring.

### Phase 3: Operational Integration Workbench

Goal: expose real pipeline execution, inspection, review, and export workflows through the web application.

Required outcomes:

- backend API;
- background worker;
- operational database;
- project dashboard;
- source catalog;
- schema editor;
- mapping workbench;
- normalization explorer;
- blocking analytics;
- pair review;
- cluster explorer;
- fusion workbench;
- entity browser;
- experiment dashboard;
- export center.

### Phase 4: Production Hardening And Public Demo

Goal: make Mosaic deployable, maintainable, and presentable as a polished research and portfolio system.

Required outcomes:

- authentication;
- authorization;
- audit trail;
- structured logging;
- health checks;
- metrics and tracing;
- backup and restore procedure;
- dependency scanning;
- performance testing;
- accessibility testing;
- public demo dataset;
- user guide;
- architecture guide;
- research summary.

---

## 11. Assumptions And Defaults

- The PRD describes the full Mosaic vision, not only the June 15 assignment MVP.
- The assignment PDF is the grading source.
- `Project_Blueprint_Mosaic.md` is the architectural source.
- The academic report target is 10 to 15 pages plus appendix.
- The required LLM-assisted stages are schema alignment, record linkage, and data fusion.
- LLM-assisted normalization is optional/stretch.
- The first website release is an educational demo centered on the animated assignment pipeline.
- The Alaska product integration benchmark is the default dataset direction unless profiling proves another benchmark is better.
- Python remains the primary research and backend language.
- The website must call shared services rather than reimplementing pipeline logic.
- Cost-aware selective routing is the main originality extension.
- Deterministic fallbacks, abstention, validation, and provenance are mandatory product principles.

---

## 12. Open Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Alaska subset does not satisfy all minimums after profiling | Assignment failure | Profile multiple domains early and allow benchmark replacement if necessary |
| Ground truth for fusion is incomplete | Fusion metric weakness | Build a documented labeled subset with clear ambiguity categories |
| LLM outputs are noisy or invalid | Lower assisted performance and reproducibility risk | Enforce structured output, validation, caching, failure accounting, and fallbacks |
| LLM calls become too expensive or slow | Cannot run enough experiments | Use selective routing, caching, budget experiments, and small controlled subsets |
| Blocking misses true matches | Linkage recall loss | Measure pair completeness and maintain missed-positive analysis |
| Clustering chains unrelated records | Fusion corruption | Use constraint-aware clustering and rejected-edge explanations |
| Report becomes too broad | Lower presentation quality | Keep main report concise and move details to appendices |
| Website scope competes with academic deadline | Assignment risk | Complete Phase 1 before treating the workbench as required |

---

## 13. Final Research Claim To Support

Mosaic should be able to defend a conclusion like:

> Deterministic methods remain preferable for high-confidence mappings, standardized values, exact identifiers, and straightforward fusion. Selective LLM assistance improves semantically ambiguous decisions, but unrestricted use increases cost, latency, and unsupported interpretations. Uncertainty-aware routing, abstention, structured validation, and deterministic fallbacks capture most of the quality gain while maintaining reproducibility and provenance.

The project succeeds when that claim is supported by reproducible implementation, component metrics, operational measurements, concrete error analysis, and a polished report.
