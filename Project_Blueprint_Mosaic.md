# Project blueprint: **Mosaic**

**Repository:** `selective-llm-product-integration`
**Product name:** **Mosaic**
**Academic title:** **Selective LLM Assistance for End-to-End Product Data Integration**

Mosaic will be both:

1. a reproducible research project satisfying every assignment requirement; and
2. a full-stack integration workbench that lets users configure, execute, inspect, evaluate, and correct the pipeline through a web interface.

The web application remains explicitly downstream of the research system. The pipeline must first work completely through scripts, configuration files, tests, and reproducible experiment commands. The website becomes a client of that stable system rather than the place where pipeline logic is buried.

The assignment requires schema alignment, record linkage, and data fusion; a deterministic baseline; an LLM-assisted pipeline using the model in at least two stages; component-level evaluation; reproducible prompts and settings; error analysis; and a final integrated dataset. 

---

# 1. Product vision

## Research objective

The primary research question is:

> **Can selective, uncertainty-aware LLM intervention improve end-to-end data integration quality while preserving cost control, reproducibility, provenance, and deterministic fallbacks?**

Supporting questions:

* Where do deterministic methods outperform LLMs?
* Which uncertain cases benefit most from LLM review?
* How should the system decide whether an LLM call is worth making?
* Does LLM assistance improve component metrics without damaging end-to-end consistency?
* How much quality improvement is obtained per call, token, unit of latency, and estimated cost?
* How reliable are LLM confidence scores?
* How often does the model abstain, return invalid output, or propose unsupported values?
* How much can human review improve the system when reserved for high-impact cases?

## Product objective

The web application should let a user:

* register and inspect heterogeneous sources;
* profile source schemas and values;
* define or edit a mediated schema;
* inspect proposed schema mappings;
* run deterministic and LLM-assisted pipelines;
* review uncertain record pairs;
* inspect entity clusters;
* investigate conflicting claims;
* approve or override fusion decisions;
* compare experiments;
* examine costs, latency, errors, and confidence;
* export the final integrated dataset and research artifacts.

The lecture’s central pipeline remains the governing architecture:

```text
Heterogeneous sources
        │
        ▼
Schema alignment
        │
        ▼
Normalization
        │
        ▼
Blocking
        │
        ▼
Pairwise record linkage
        │
        ▼
Entity clustering
        │
        ▼
Claim extraction
        │
        ▼
Data fusion
        │
        ▼
Integrated entities with confidence,
provenance, evidence, and uncertainty
```

These stages must remain separately inspectable because errors in schema mapping can propagate into linkage, and linkage errors can cause unrelated records to be fused. 

---

# 2. Dataset and project scope

## Recommended benchmark

Use a curated subset of the **Alaska product integration benchmark**.

Select a coherent product domain with:

* multiple retailers;
* overlapping entities;
* heterogeneous schemas;
* meaningful model-number and title variation;
* conflicting specifications or prices;
* sufficient matching ground truth.

The final selection must be data-driven. A profiling program should evaluate candidate categories before you freeze the scope.

## Target scale

A strong initial research corpus would contain:

```text
Sources:                  3–8
Raw source records:       5,000–25,000
Ground-truth entities:    500+
Known positive pairs:     500+
Mediated attributes:      8+
Fusion conflicts:         200+
```

The implementation should not depend on these exact numbers. It should support the complete benchmark later.

## Dataset selection criteria

Score each candidate domain by:

```text
source_count
record_count
entity_count
positive_pair_count
cross-source overlap
attribute_count
missingness
model-number coverage
schema heterogeneity
conflicting-claim count
category purity
```

A domain with fewer records but stronger overlap and more meaningful conflicts can be more valuable than the largest domain.

## Scope boundaries

### Included

* source ingestion;
* source profiling;
* schema matching;
* canonical normalization;
* blocking;
* pairwise linkage;
* clustering;
* data fusion;
* provenance;
* uncertainty;
* LLM assistance;
* experiment tracking;
* evaluation;
* human review;
* web-based inspection and execution;
* exports and reporting.

### Initially excluded

* distributed streaming ingestion;
* real-time Kafka architecture;
* Kubernetes;
* multi-region deployment;
* fine-tuning a foundation model;
* a generalized no-code ETL platform;
* arbitrary SQL transformation authoring;
* integration across unrelated business domains.

These can become later extensions, but they should not distort the core research contribution.

---

# 3. System principles

## 3.1 Pipeline-first

Every operation must be executable without the website.

The web interface invokes the same application services as the CLI. It does not contain hidden versions of schema matching, linkage, or fusion logic.

## 3.2 Immutable raw data

Raw input files are never edited.

Every derived artifact records:

* input version;
* configuration version;
* code version;
* creation timestamp;
* parent artifacts;
* content checksum.

## 3.3 Preserve raw and normalized values

For every canonical value, retain:

```text
raw_value
normalized_value
normalization_method
confidence
source_record
source_attribute
```

The lecture specifically recommends normalizing early while retaining raw values and provenance. 

## 3.4 Selective LLM use

The LLM is not the default decision-maker.

It is used when:

* deterministic evidence is ambiguous;
* the expected value of adjudication exceeds its cost;
* a conflict cannot be safely resolved by rules;
* the output can be validated against explicit constraints.

## 3.5 Explicit abstention

Every decision layer supports:

```text
accept
reject
abstain
fallback
human_review
```

The system must not force false certainty.

## 3.6 Provenance by construction

Every schema mapping, record match, cluster membership, and fused value must be traceable to the evidence that produced it.

## 3.7 Configuration over hard-coding

Thresholds, feature weights, model settings, prompts, source policies, and fusion rules belong in versioned configuration.

## 3.8 Reproducibility

A completed experiment should be reproducible from:

```text
dataset manifest
code commit
configuration
prompt versions
model identifier
model settings
random seed
cached or logged model responses
```

---

# 4. Mediated schema

The mediated schema should be expressive enough for product integration but narrow enough to evaluate rigorously.

## Core product entity

```text
product_entity
--------------
entity_id
canonical_title
canonical_brand
canonical_model_number
canonical_category
canonical_description
canonical_price
canonical_currency
canonical_url
canonical_image_url
specifications
overall_confidence
source_count
created_at
updated_at
```

## Required canonical attributes

Use at least:

1. `title`
2. `brand`
3. `model_number`
4. `category`
5. `description`
6. `price`
7. `currency`
8. `specifications`

Optional additions:

* `gtin`
* `sku`
* `manufacturer_part_number`
* `availability`
* `condition`
* `product_url`
* `image_url`
* `release_date`

## Semi-structured specification model

Long-tail technical properties should not all become columns.

Example:

```json
{
  "screen_size": {
    "value": 15.6,
    "unit": "inch"
  },
  "storage_capacity": {
    "value": 512,
    "unit": "GB"
  },
  "weight": {
    "value": 1.8,
    "unit": "kg"
  },
  "color": {
    "value": "black"
  }
}
```

The system should still store each specification as an independent claim so that individual keys can be fused and evaluated.

---

# 5. Canonical data model

Use a claim-centric relational model. Parquet artifacts can mirror these tables during research execution; PostgreSQL can host the operational representation used by the website.

## 5.1 Projects

```text
project
-------
project_id
name
description
domain
mediated_schema_version
created_at
updated_at
```

## 5.2 Sources

```text
source
------
source_id
project_id
name
source_type
origin
retrieval_date
license
record_count
metadata
```

## 5.3 Raw records

```text
source_record
-------------
record_uid
source_id
source_record_id
raw_payload
raw_checksum
ingested_at
```

Identifier convention:

```text
record_uid = "{source_id}:{source_record_id}"
```

Never use row position as a stable identifier.

## 5.4 Source attributes

```text
source_attribute
----------------
source_attribute_id
source_id
attribute_name
inferred_type
non_null_rate
distinct_rate
uniqueness_rate
sample_values
value_statistics
```

## 5.5 Mediated attributes

```text
mediated_attribute
------------------
mediated_attribute_id
schema_version
name
description
data_type
cardinality
unit_family
required
allowed_values
```

## 5.6 Schema mapping proposals

```text
schema_mapping
--------------
mapping_id
source_attribute_id
mediated_attribute_id
pipeline
method
score
confidence
decision
evidence
prompt_version
model_identifier
review_status
```

## 5.7 Normalized records

```text
normalized_record
-----------------
record_uid
schema_version
normalized_payload
normalization_version
normalization_confidence
```

## 5.8 Normalized values

```text
normalized_value
----------------
normalized_value_id
record_uid
source_attribute_id
mediated_attribute_id
raw_value
canonical_value
canonical_unit
normalization_method
confidence
```

## 5.9 Candidate pairs

```text
candidate_pair
--------------
candidate_pair_id
left_record_uid
right_record_uid
blocking_rules
blocking_score
candidate_rank
ground_truth_label
split
```

## 5.10 Pairwise features

```text
pair_feature
------------
candidate_pair_id
feature_version
features
```

The `features` field can be JSON in PostgreSQL and a structured column in Parquet.

## 5.11 Linkage decisions

```text
linkage_decision
----------------
decision_id
candidate_pair_id
pipeline
baseline_score
llm_decision
llm_confidence
final_decision
final_confidence
evidence
abstained
fallback_used
prompt_version
latency_ms
estimated_cost
```

## 5.12 Entity clusters

```text
entity_cluster
--------------
entity_id
project_id
cluster_version
overall_confidence
member_count
created_at
```

```text
cluster_membership
------------------
entity_id
record_uid
membership_confidence
supporting_edges
cluster_method
```

## 5.13 Attribute claims

```text
attribute_claim
---------------
claim_id
entity_id
record_uid
source_id
mediated_attribute_id
raw_value
normalized_value
unit
observed_at
extraction_confidence
```

## 5.14 Fusion decisions

```text
fused_value
-----------
fused_value_id
entity_id
mediated_attribute_id
selected_value
selected_unit
fusion_method
confidence
supporting_claim_ids
contradicting_claim_ids
alternative_values
llm_used
abstained
review_status
```

## 5.15 Experiment runs

```text
experiment_run
--------------
run_id
project_id
configuration_hash
code_commit
dataset_version
prompt_versions
started_at
completed_at
status
metrics
artifact_location
```

## 5.16 Human review

```text
review_task
-----------
review_task_id
task_type
object_id
priority
uncertainty
impact_score
status
assigned_to
created_at
resolved_at
```

```text
review_decision
---------------
review_decision_id
review_task_id
reviewer
decision
evidence
comment
created_at
```

## 5.17 LLM calls

```text
llm_call
--------
request_id
run_id
stage
provider
model
prompt_version
input_hash
request_payload
raw_response
parsed_response
validation_status
retry_count
latency_ms
input_tokens
output_tokens
estimated_cost
created_at
```

---

# 6. Baseline integration pipeline

# 6.1 Source ingestion

Responsibilities:

* load supported source formats;
* validate required metadata;
* preserve raw payloads;
* assign stable record identifiers;
* detect malformed records;
* produce ingestion statistics;
* write versioned raw artifacts.

Initial file support:

```text
CSV
JSON
JSON Lines
Parquet
```

Later:

```text
relational database
REST API
web table
object storage
```

## Output artifacts

```text
sources.parquet
source_records.parquet
ingestion_errors.parquet
dataset_manifest.json
```

---

# 6.2 Source profiling

Profile each attribute using:

* inferred type;
* null rate;
* uniqueness;
* cardinality;
* string-length distribution;
* numeric distribution;
* frequent values;
* token patterns;
* unit patterns;
* URL, identifier, currency, or date likelihood;
* representative samples.

The profiler should also estimate whether an attribute appears to represent:

```text
brand
title
model identifier
price
currency
description
category
measurement
URL
free text
```

These estimates are evidence, not final mappings.

---

# 6.3 Deterministic schema alignment

Construct candidate mappings using four evidence families.

## Name evidence

* normalized exact equality;
* token overlap;
* character n-gram similarity;
* Jaro–Winkler;
* abbreviation dictionaries;
* domain synonyms.

Examples:

```text
manufacturer → brand
maker → brand
product_name → title
mpn → model_number
cost → price
```

## Type evidence

Infer and compare:

```text
string
integer
decimal
currency
identifier
measurement
URL
categorical
free_text
date
boolean
```

## Value evidence

Compare:

* normalized value overlap;
* numeric ranges;
* currency symbols;
* unit distributions;
* identifier formats;
* string lengths;
* value cardinalities;
* frequent tokens;
* uniqueness.

## Context evidence

Use:

* neighboring fields;
* co-occurring attributes;
* source-level schema context;
* candidate mapping coherence.

## Combined score

```text
mapping_score =
    w_name    × name_similarity
  + w_type    × type_compatibility
  + w_value   × value_compatibility
  + w_context × contextual_compatibility
```

Use maximum-weight bipartite matching where one-to-one behavior is appropriate, while allowing:

* one-to-many mappings;
* composite mappings;
* unmapped fields;
* multiple source fields contributing to one target field.

Never force every source attribute into the mediated schema.

---

# 6.4 Deterministic normalization

Implement typed normalizers:

```text
normalize_text
normalize_title
normalize_brand
normalize_model_number
normalize_category
normalize_price
normalize_currency
normalize_measurement
normalize_storage
normalize_dimension
normalize_weight
normalize_boolean
normalize_url
normalize_specification_key
```

Example:

```json
{
  "raw_value": "1 TB",
  "canonical_value": 1024,
  "canonical_unit": "GB",
  "normalization_method": "binary_storage_to_gb",
  "confidence": 1.0
}
```

Normalization rules must be:

* deterministic;
* versioned;
* tested;
* reversible where possible;
* provenance-preserving.

---

# 6.5 Blocking

All-pairs comparison is quadratic, so candidate generation is a first-class system component. The lecture recommends measuring both candidate reduction and true-match retention. 

Use a union of blocking strategies.

## Pass A: strong identifiers

```text
brand + model_number
GTIN
manufacturer_part_number
```

## Pass B: rare model tokens

Use normalized alphanumeric model fragments such as:

```text
wh1000xm5
smg991b
xps9310
```

## Pass C: title token blocks

Use rare informative title tokens after stopword removal.

## Pass D: character signatures

Use:

* q-gram indexing;
* MinHash;
* locality-sensitive hashing.

## Pass E: category-aware retrieval

Within compatible categories, retrieve top title-similar records.

## Pass F: specification signatures

Block using combinations such as:

```text
brand + capacity
brand + screen size
brand + product family
```

## Blocking output

Each candidate pair records every rule that generated it.

Required metrics:

```text
candidate_pair_count
positive_pairs_retained
pair_completeness
reduction_ratio
candidates_per_record
duplicate_candidate_rate
runtime
memory
```

---

# 6.6 Pairwise feature engineering

Create interpretable features.

## Title features

```text
exact_normalized_title
token_jaccard
character_cosine
jaro_winkler
token_containment
embedding_similarity
```

## Brand features

```text
brand_exact
brand_alias_match
brand_similarity
brand_conflict
```

## Identifier features

```text
model_exact
model_normalized_exact
model_token_overlap
model_edit_distance
strong_identifier_conflict
```

## Category features

```text
category_exact
category_hierarchy_distance
category_compatibility
```

## Description features

```text
tfidf_cosine
embedding_similarity
rare_token_overlap
```

## Price features

```text
absolute_difference
relative_difference
currency_compatibility
price_band_match
```

## Specification features

```text
spec_key_jaccard
numeric_spec_agreement
categorical_spec_agreement
unit_compatibility
conflict_count
```

## General features

```text
missing_attribute_count
source_pair
record_completeness
blocking_rule_count
```

---

# 6.7 Traditional pairwise matching

Implement two baselines.

## Transparent rule system

Examples:

```text
MATCH when:
model numbers agree strongly
AND brands are compatible
AND no strong variant conflict exists
```

```text
NON_MATCH when:
strong model identifiers conflict
OR brands are incompatible
OR product capacities define distinct variants
```

## Classical supervised model

Primary:

```text
logistic regression
```

Optional stronger model:

```text
gradient-boosted trees
```

Logistic regression remains useful because:

* feature contributions are inspectable;
* probabilities can be calibrated;
* error analysis is easier;
* it forms a clean traditional baseline.

## Leakage-safe splitting

Split by real-world entity, not pair row.

Suggested proportions:

```text
training:    60%
validation:  20%
test:        20%
```

All records belonging to one ground-truth entity stay in one split.

Additional experiment:

> Train on some source pairs and evaluate on an unseen source pair.

This tests retailer-independent generalization.

---

# 6.8 Clustering

Do not blindly convert thresholded edges into connected components. A weak bridge can cause chaining and merge unrelated products. 

Use constraint-aware agglomeration:

1. sort accepted edges by confidence;
2. initialize one cluster per record;
3. inspect edges in descending order;
4. propose cluster merges;
5. validate merge constraints;
6. accept or reject the merge;
7. compute cluster confidence;
8. retain rejected-edge explanations.

Possible constraints:

```text
maximum one record per source
compatible strong identifiers
compatible brands
compatible product variants
maximum cluster size
minimum cross-cluster edge support
```

Retain a simple connected-components implementation as a comparison baseline.

---

# 6.9 Claim extraction

Once clusters exist, transform each record value into an explicit claim.

Example:

```text
Entity E42
  Source A claims storage = 512 GB
  Source B claims storage = 512 GB
  Source C claims storage = 1 TB
```

Claims preserve:

* source;
* record;
* original attribute;
* raw value;
* normalized value;
* observation time;
* extraction confidence.

This claim layer decouples clustering from fusion and supports later truth-discovery extensions.

---

# 6.10 Deterministic fusion

Use attribute-specific policies.

| Attribute                 | Initial policy                                 |
| ------------------------- | ---------------------------------------------- |
| Brand                     | normalized weighted mode                       |
| Model number              | strongest identifier consensus                 |
| Title                     | medoid or highest-quality representative       |
| Category                  | weighted mode                                  |
| Description               | most complete non-duplicate description        |
| Price                     | most recent valid price or robust median       |
| Currency                  | direct source value or deterministic inference |
| Numeric specification     | tolerance-aware median                         |
| Categorical specification | weighted mode                                  |
| URL                       | preferred source or highest-quality valid URL  |

Initial source weights can be uniform.

Advanced source weights can be estimated by:

```text
source
source × attribute
source × category
```

The lecture explains why majority voting is insufficient when sources are inaccurate, stale, or dependent. 

---

# 7. LLM-assisted pipeline

# 7.1 LLM gateway

All model calls pass through one provider-neutral abstraction.

Responsibilities:

* prompt rendering;
* structured-output enforcement;
* schema validation;
* retry policy;
* timeout handling;
* caching;
* cost estimation;
* token counting;
* tracing;
* fallback execution;
* provider substitution.

Every call logs:

```text
request_id
run_id
stage
provider
model
prompt_version
settings
input_hash
request_payload
raw_response
parsed_response
validation_result
retry_count
latency
token usage
estimated cost
```

Recommended primary research settings:

```text
temperature = 0
structured output = required
retries = bounded
cache = enabled
```

Invalid JSON, missing fields, hallucinated values, and empty responses must be counted as failures unless a documented fallback is applied. 

---

# 7.2 LLM-assisted schema alignment

Invoke the model only when deterministic evidence is uncertain.

Possible routing rules:

```text
top_candidate_score < acceptance_threshold
```

or:

```text
top_score - second_score < ambiguity_margin
```

or:

```text
type evidence conflicts with name evidence
```

## Prompt input

* source attribute name;
* source description, where available;
* inferred type;
* representative values;
* neighboring source attributes;
* target schema definitions;
* deterministic candidate scores.

## Structured output

```json
{
  "source_attribute": "maker",
  "target_attribute": "brand",
  "decision": "match",
  "confidence": 0.93,
  "supporting_evidence": [
    "sample values are manufacturer names",
    "the adjacent field contains product models"
  ],
  "abstain": false
}
```

The model may choose only:

* a provided target attribute;
* `UNMAPPED`;
* `ABSTAIN`.

It cannot invent a new target field during evaluation.

---

# 7.3 LLM-assisted normalization

Use the LLM only for values that deterministic normalizers cannot safely classify.

Examples:

* ambiguous bundled titles;
* mixed unit expressions;
* noisy category descriptions;
* combined specifications;
* abbreviated manufacturer names;
* poorly delimited product descriptions.

Output:

```json
{
  "normalization_type": "model_number",
  "canonical_value": "WH-1000XM5",
  "confidence": 0.89,
  "evidence_span": "Sony WH1000 XM5",
  "abstain": false
}
```

A normalized value must be derivable from the source text. Unsupported additions are rejected.

---

# 7.4 LLM-assisted record linkage

Only uncertain pairs should be sent to the model.

Starting uncertainty band:

```text
0.35 ≤ baseline_probability ≤ 0.75
```

The validation set determines the final thresholds.

## Prompt input

* normalized record A;
* normalized record B;
* selected raw values;
* pairwise features;
* agreements;
* conflicts;
* missing fields;
* deterministic score.

## Output

```json
{
  "decision": "match",
  "confidence": 0.86,
  "supporting_evidence": [
    "brands agree",
    "model identifiers differ only by punctuation",
    "screen and storage specifications agree"
  ],
  "contradicting_evidence": [
    "listed prices differ"
  ],
  "abstain": false
}
```

## Final decision policy

```text
if deterministic prediction is high-confidence:
    accept deterministic decision

else if valid LLM output exceeds confidence threshold:
    use LLM decision

else if the LLM abstains:
    use documented fallback or queue human review

else if output is invalid:
    record failure and use documented fallback

else:
    leave unresolved
```

---

# 7.5 LLM-assisted fusion

Invoke the model only when deterministic fusion is unresolved.

Triggers:

* weighted vote tie;
* low consensus;
* incompatible normalizations;
* conflicting units;
* competing descriptions;
* recency and source reliability disagree;
* potential bundle-versus-base-product issue;
* variant-specific claims may have been mixed.

## Input

```json
{
  "attribute": "storage_capacity",
  "candidate_claims": [
    {
      "claim_id": "c1",
      "source": "source_a",
      "raw_value": "1 TB",
      "normalized_value": "1024 GB"
    },
    {
      "claim_id": "c2",
      "source": "source_b",
      "raw_value": "1000 GB",
      "normalized_value": "1000 GB"
    }
  ],
  "allowed_outputs": [
    "1024 GB",
    "1000 GB",
    "ABSTAIN"
  ]
}
```

## Output

```json
{
  "selected_value": "1024 GB",
  "confidence": 0.74,
  "supporting_claim_ids": ["c1"],
  "contradicting_claim_ids": ["c2"],
  "reason": "The selected value follows the documented binary normalization.",
  "abstain": false
}
```

Guardrails:

* the output must be source-supported or deterministically derivable;
* supporting claim IDs must exist;
* incompatible units cause rejection;
* invented values cause rejection;
* explanations are evidence metadata, not proof of correctness.

---

# 7.6 Cost-aware routing

This is the strongest originality extension.

Train a routing model that estimates:

[
P(\text{LLM fixes the baseline}\mid x)
]

Possible routing features:

```text
baseline confidence
classification margin
feature conflict count
missingness
identifier disagreement
brand disagreement
title similarity
price difference
source pair
record completeness
```

Conceptual policy:

```text
call LLM when:

expected_error_reduction × error_cost
>
llm_call_cost + latency_penalty
```

This creates a quality-cost frontier rather than treating model usage as unlimited.

---

# 7.7 Confidence calibration and selective prediction

Evaluate confidence from both the classical model and LLM.

Metrics:

```text
Brier score
expected calibration error
reliability curves
coverage
selective risk
accuracy at confidence thresholds
```

A well-designed system should improve accuracy as low-confidence cases are abstained upon.

---

# 8. Ground truth and annotation

## Existing benchmark labels

Use official schema and linkage labels wherever available.

## Fusion labels

Construct a documented fusion evaluation subset if full truth is unavailable.

Stratify by:

* attribute;
* source combination;
* entity cluster size;
* numeric versus textual value;
* conflict severity;
* deterministic confidence;
* potential ambiguity.

Fusion annotations should support:

```text
single correct value
multiple valid values
ambiguous
insufficient evidence
not applicable
```

Schema:

```text
entity_id
attribute
candidate_claims
gold_value
acceptable_alternatives
annotation_status
annotation_notes
annotator
adjudicator
```

Do not force genuine ambiguity into a single artificial truth.

---

# 9. Experimental design

## Primary configurations

| Configuration | Schema        | Linkage       | Fusion        |
| ------------- | ------------- | ------------- | ------------- |
| A0            | Deterministic | Deterministic | Deterministic |
| B-All         | Selective LLM | Selective LLM | Selective LLM |

## Stage ablations

| Configuration | Purpose                                    |
| ------------- | ------------------------------------------ |
| B-S           | LLM schema alignment only                  |
| B-N           | LLM normalization only                     |
| B-L           | LLM linkage only                           |
| B-F           | LLM fusion only                            |
| B-SL          | Schema and linkage                         |
| B-LF          | Linkage and fusion                         |
| B-SLF         | Schema, linkage, and fusion                |
| B-NoAbstain   | Forced LLM decisions                       |
| B-NoFeatures  | LLM without deterministic feature evidence |
| B-NoFallback  | Measure raw model failure consequences     |

## Routing-budget experiment

Evaluate:

```text
0%
5%
10%
20%
30%
50%
100%
```

of eligible uncertain cases.

Compare:

```text
quality versus LLM calls
quality versus tokens
quality versus cost
quality versus latency
quality versus abstention rate
```

## Prompt experiment

On a controlled subset, compare:

* zero-shot;
* few-shot;
* evidence-first;
* decision-first;
* with deterministic features;
* without deterministic features.

## Model comparison

Optional:

* small low-cost hosted model;
* stronger hosted model;
* local open model.

Keep prompt format and evaluation cases constant.

---

# 10. Metrics

## Schema alignment

```text
accuracy
precision
recall
F1
coverage
abstention rate
invalid-output rate
confidence calibration
```

Break down by:

* exact synonyms;
* abbreviations;
* ambiguous names;
* incompatible types;
* one-to-many mappings;
* unmapped attributes.

## Blocking

```text
candidate count
pair completeness
reduction ratio
candidates per record
positive pairs retained
runtime
memory
```

## Pairwise linkage

```text
precision
recall
F1
PR-AUC
ROC-AUC
confusion matrix
calibration
```

Break down by:

* source pair;
* missing model number;
* title variation;
* brand disagreement;
* product variant;
* bundle status;
* category.

## Clustering

```text
pairwise cluster precision
pairwise cluster recall
pairwise cluster F1
B-cubed precision
B-cubed recall
B-cubed F1
exact-cluster accuracy
cluster purity
```

## Fusion

```text
attribute-level value accuracy
macro value accuracy
coverage
abstention
unsupported-value rate
source-support rate
```

For numeric values:

```text
MAE
relative error
accuracy within tolerance
```

## End-to-end

```text
integrated entity correctness
attribute completeness
consistency
provenance completeness
unresolved decision rate
```

## Operational

```text
LLM calls
input tokens
output tokens
estimated cost
p50 latency
p95 latency
cache hit rate
invalid output rate
retry rate
fallback rate
human-review volume
```

The assignment explicitly welcomes cost, latency, reduction ratio, completeness, and hallucination measurements in addition to required component metrics. 

---

# 11. Technology stack

# Research and data layer

```text
Python 3.12
Polars
PyArrow
Parquet
DuckDB
scikit-learn
RapidFuzz
datasketch
NetworkX
Pydantic
MLflow
Typer
pytest
Ruff
mypy
uv
```

DuckDB is suitable for analytical access to Parquet artifacts and provides direct support for querying Parquet data. ([DuckDB][1])

MLflow Tracking records experiment parameters, code versions, metrics, and output artifacts, making it appropriate for comparing deterministic and assisted pipeline runs. ([MLflow AI Platform][2])

# Backend

```text
FastAPI
Pydantic
SQLAlchemy
Alembic
PostgreSQL
PostgreSQL-backed job orchestration
```

FastAPI keeps the API layer in Python, allowing the web service to reuse the pipeline’s domain models and validation schemas rather than duplicating them in another backend language. Its documented development workflow includes an integrated CLI and Uvicorn-based server. ([FastAPI][3])

## Backend responsibilities

* authentication and authorization;
* project management;
* dataset upload;
* pipeline job orchestration;
* experiment queries;
* review task APIs;
* provenance APIs;
* export generation;
* live job updates;
* audit trail.

# Frontend

```text
Next.js
React
TypeScript
App Router
TanStack Query
TanStack Table
React Hook Form
Zod
Tailwind CSS
shadcn/ui
Plotly or ECharts
```

Next.js App Router provides the file-system routing and React server/client architecture suitable for the project’s dashboard and investigation views. ([Next.js][4])

# Storage

```text
PostgreSQL
Parquet
local filesystem or S3-compatible object storage
```

Use each for a distinct role:

* **PostgreSQL:** operational metadata, users, decisions, reviews;
* **PostgreSQL job tables:** pending work, claimed jobs, progress, retries, cancellation, failures, and artifact links;
* **Parquet:** large immutable pipeline artifacts;
* **object storage:** datasets, exports, logs, model artifacts;
* **DuckDB:** analytical queries across Parquet outputs.

# Deployment

Initial:

```text
Docker Compose
```

Production-oriented:

```text
frontend container
API container
worker container
PostgreSQL
object storage
reverse proxy
```

Cloud deployment remains provider-neutral.

---

# 12. Monorepo structure

```text
selective-llm-product-integration/
├── README.md
├── LICENSE
├── CITATION.cff
├── CONTRIBUTING.md
├── SECURITY.md
├── Makefile
├── docker-compose.yml
├── .env.example
├── .gitignore
│
├── pyproject.toml
├── uv.lock
├── package.json
├── pnpm-workspace.yaml
│
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── dependencies.py
│   │   │   ├── routers/
│   │   │   ├── services/
│   │   │   ├── repositories/
│   │   │   ├── models/
│   │   │   ├── schemas/
│   │   │   └── security/
│   │   └── tests/
│   │
│   ├── worker/
│   │   ├── worker.py
│   │   ├── tasks/
│   │   └── tests/
│   │
│   └── web/
│       ├── app/
│       ├── components/
│       ├── features/
│       ├── hooks/
│       ├── lib/
│       ├── public/
│       ├── tests/
│       └── package.json
│
├── packages/
│   ├── integration-core/
│   │   └── src/mosaic/
│   │       ├── ingestion/
│   │       ├── profiling/
│   │       ├── alignment/
│   │       ├── normalization/
│   │       ├── blocking/
│   │       ├── matching/
│   │       ├── clustering/
│   │       ├── claims/
│   │       ├── fusion/
│   │       ├── llm/
│   │       ├── evaluation/
│   │       ├── provenance/
│   │       └── reporting/
│   │
│   ├── ui/
│   ├── api-client/
│   └── shared-types/
│
├── configs/
│   ├── datasets/
│   ├── schemas/
│   ├── pipelines/
│   ├── models/
│   ├── thresholds/
│   └── experiments/
│
├── prompts/
│   ├── schema/
│   ├── normalization/
│   ├── linkage/
│   └── fusion/
│
├── data/
│   ├── README.md
│   ├── manifests/
│   ├── raw/
│   ├── interim/
│   ├── processed/
│   ├── ground_truth/
│   └── fixtures/
│
├── artifacts/
│   ├── runs/
│   ├── models/
│   ├── figures/
│   ├── tables/
│   ├── errors/
│   ├── exports/
│   └── reports/
│
├── database/
│   ├── migrations/
│   └── seeds/
│
├── notebooks/
│   ├── 01_dataset_selection.ipynb
│   ├── 02_schema_analysis.ipynb
│   ├── 03_linkage_analysis.ipynb
│   ├── 04_fusion_analysis.ipynb
│   └── 05_error_analysis.ipynb
│
├── scripts/
│   ├── validate_dataset_access.py
│   ├── profile_candidates.py
│   ├── run_experiment.py
│   ├── validate_artifacts.py
│   ├── seed_demo_project.py
│   └── build_report.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── end_to_end/
│   ├── contract/
│   └── golden/
│
├── reports/
│   ├── report.md
│   ├── references.bib
│   └── appendix/
│
└── .github/
    └── workflows/
        ├── python.yml
        ├── web.yml
        ├── integration.yml
        ├── docker.yml
        └── reproducibility.yml
```

---

# 13. CLI contract

The full project must remain operable from the command line.

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

Full reproduction:

```bash
make reproduce
```

Website development:

```bash
make dev
```

Complete test suite:

```bash
make test
```

---

# 14. Web application information architecture

# 14.1 Landing page

Purpose:

* explain the system;
* show its integration workflow;
* provide a demo project;
* distinguish baseline, LLM assistance, and human review.

# 14.2 Project dashboard

Show:

```text
source count
record count
schema mappings
candidate pairs
predicted matches
entity count
unresolved conflicts
review queue size
latest experiment
pipeline status
LLM cost
```

# 14.3 Source catalog

Users can:

* register a source;
* upload data;
* inspect ingestion status;
* see schema and profile statistics;
* view malformed records;
* compare source coverage.

# 14.4 Source profile view

Display:

* columns;
* inferred types;
* null rates;
* uniqueness;
* distributions;
* samples;
* detected units;
* semantic-role suggestions.

# 14.5 Mediated schema editor

Users can:

* create attributes;
* edit descriptions;
* specify types;
* define allowed units;
* set cardinality;
* version the schema;
* compare schema versions.

# 14.6 Schema mapping workbench

For each source attribute, show:

* candidate target attributes;
* baseline scores;
* LLM recommendation;
* sample values;
* evidence;
* confidence;
* accepted mapping;
* reviewer override.

The screen should make deterministic and LLM evidence visibly distinct.

# 14.7 Normalization explorer

Show:

```text
raw value
normalized value
normalization method
unit conversion
confidence
validation result
```

Allow filtering by low confidence or rejected transformations.

# 14.8 Blocking explorer

Show:

* candidate volume by blocking rule;
* overlap among blocking rules;
* reduction ratio;
* pair completeness;
* candidates per record;
* missed positive pairs;
* overproductive blocks.

# 14.9 Pair review workbench

Two records appear side by side.

Show:

* raw fields;
* normalized fields;
* highlighted agreements;
* highlighted conflicts;
* pairwise feature values;
* baseline score;
* LLM decision;
* supporting evidence;
* ground truth in evaluation mode;
* reviewer decision.

Review controls:

```text
Match
Non-match
Unsure
Defer
```

# 14.10 Cluster explorer

Users can:

* inspect cluster members;
* see supporting edges;
* view rejected edges;
* split a cluster;
* merge compatible clusters;
* inspect constraint violations;
* trace cluster history.

# 14.11 Fusion and provenance view

For each entity attribute:

* list all claims;
* show source;
* show normalized values;
* show source weights;
* show deterministic vote;
* show LLM adjudication;
* display selected value;
* list alternatives;
* show confidence;
* allow review.

# 14.12 Integrated entity browser

Search and browse canonical products.

Show:

* canonical record;
* member source records;
* provenance;
* confidence;
* unresolved fields;
* transformation history.

# 14.13 Experiment dashboard

Compare runs by:

* schema metrics;
* linkage metrics;
* clustering metrics;
* fusion metrics;
* costs;
* latency;
* abstentions;
* invalid outputs;
* prompt version;
* model;
* configuration.

# 14.14 Error analysis center

Filter errors by taxonomy.

Examples:

```text
blocking false negative
identifier conflict
bundle confusion
variant confusion
schema homonym
wrong unit
majority wrong
unsupported LLM value
clustering chain
```

Each case should be exportable for the report.

# 14.15 Prompt and model registry

Show:

* prompt versions;
* structured-output schemas;
* model settings;
* usage by experiment;
* validation failures;
* cost summaries.

Prompt editing should be a later administrative capability, not required for ordinary users.

# 14.16 Job monitor

Show:

* queued jobs;
* active stage;
* processed records;
* warnings;
* failures;
* retry counts;
* logs;
* generated artifacts.

# 14.17 Export center

Exports:

```text
integrated entities CSV
integrated entities Parquet
JSON with provenance
schema mappings
pair predictions
clusters
claims
fusion decisions
metrics
error examples
experiment manifest
```

---

# 15. API surface

## Projects

```text
GET    /projects
POST   /projects
GET    /projects/{project_id}
PATCH  /projects/{project_id}
```

## Sources

```text
POST   /projects/{project_id}/sources
GET    /projects/{project_id}/sources
GET    /sources/{source_id}
POST   /sources/{source_id}/ingest
GET    /sources/{source_id}/profile
```

## Schema

```text
GET    /projects/{project_id}/schemas
POST   /projects/{project_id}/schemas
POST   /schemas/{schema_id}/mapping-runs
GET    /mapping-runs/{run_id}
PATCH  /schema-mappings/{mapping_id}
```

## Pipeline

```text
POST   /projects/{project_id}/pipeline-runs
GET    /pipeline-runs/{run_id}
POST   /pipeline-runs/{run_id}/cancel
GET    /pipeline-runs/{run_id}/artifacts
```

## Linkage

```text
GET    /projects/{project_id}/candidate-pairs
GET    /candidate-pairs/{pair_id}
POST   /candidate-pairs/{pair_id}/review
```

## Clusters

```text
GET    /projects/{project_id}/clusters
GET    /clusters/{entity_id}
POST   /clusters/{entity_id}/split
POST   /clusters/merge
```

## Fusion

```text
GET    /entities/{entity_id}/claims
GET    /entities/{entity_id}/fusion
POST   /fused-values/{fused_value_id}/review
```

## Experiments

```text
GET    /projects/{project_id}/experiments
POST   /projects/{project_id}/experiments
GET    /experiments/{run_id}
GET    /experiments/{run_id}/metrics
GET    /experiments/compare
```

## Review

```text
GET    /projects/{project_id}/review-tasks
POST   /review-tasks/{task_id}/claim
POST   /review-tasks/{task_id}/resolve
```

## Exports

```text
POST   /projects/{project_id}/exports
GET    /exports/{export_id}
```

---

# 16. Security and governance

Even for an academic system, establish sound boundaries.

## Authentication

Later web sprints should support:

* local account or external identity provider;
* session management;
* protected API routes.

## Roles

```text
viewer
reviewer
project_admin
system_admin
```

## Audit logging

Record:

* schema edits;
* manual mapping changes;
* pair decisions;
* cluster edits;
* fusion overrides;
* prompt changes;
* model configuration changes;
* export creation.

## Secret handling

Never commit:

```text
API keys
database credentials
object-storage secrets
session secrets
```

Use environment variables and secret managers.

## Prompt-injection defenses

Source text is untrusted data.

LLM prompts should:

* delimit source content;
* state that embedded instructions are data;
* use enumerated outputs;
* enforce JSON schemas;
* reject unsupported fields;
* validate all identifiers against known inputs.

---

# 17. Testing strategy

## Unit tests

Cover:

* normalizers;
* type inference;
* schema scores;
* blocking keys;
* similarity features;
* classifiers;
* clustering constraints;
* fusion rules;
* structured-output validation;
* routing policies.

## Property and invariant tests

Examples:

```text
A candidate pair cannot contain the same record twice.
A clustered record belongs to exactly one active cluster.
Every fused value has supporting claims.
Every claim references an existing source record.
No LLM-selected claim ID may be unknown.
No ground-truth label may enter an inference prompt.
Every experiment has a configuration hash.
Every export is tied to one completed run.
```

## Golden-case tests

Maintain a small curated suite:

* obvious match;
* obvious non-match;
* punctuation-only model difference;
* different product capacity;
* bundle versus standalone item;
* accessory versus primary product;
* ambiguous schema field;
* conflicting unit;
* stale price;
* copied specification error.

## Integration tests

Test complete stage transitions:

```text
ingestion → profiling
profiling → schema mapping
normalization → blocking
blocking → matching
matching → clustering
clustering → claims
claims → fusion
```

## API contract tests

Verify:

* request validation;
* response schemas;
* authorization;
* pagination;
* error behavior;
* idempotency.

## Frontend tests

Use:

* component tests;
* state-management tests;
* end-to-end browser tests;
* accessibility checks.

## Reproducibility test

CI runs the entire pipeline against a small fixture dataset and verifies expected artifacts and metric ranges.

---

# 18. Error taxonomy

## Schema errors

```text
synonym failure
homonym failure
wrong type
wrong granularity
unit confusion
composite-field failure
forced mapping
missed mapping
```

## Normalization errors

```text
incorrect parsing
incorrect unit conversion
information loss
variant collapse
unsupported canonical value
```

## Blocking errors

```text
missed positive pair
overly broad block
identifier formatting failure
category constraint failure
```

## Linkage errors

```text
common-title collision
missing identifier
brand alias failure
bundle confusion
accessory confusion
variant confusion
price overreliance
source-specific formatting
```

## Clustering errors

```text
chaining
over-merge
under-merge
one-per-source violation
inconsistent identifier cluster
```

## Fusion errors

```text
majority wrong
stale value selected
copied value overcounted
unit mismatch
variant-specific values mixed
unsupported LLM output
multiple valid values collapsed
```

## LLM operational errors

```text
invalid JSON
missing field
hallucinated value
unknown claim ID
empty response
timeout
inconsistent repeated answer
overconfidence
failure to abstain
```

The final report must contain at least three concrete source-level error examples, expected outputs, system outputs, and explanations. 

---

# 19. Atemporal sprint roadmap

Each sprint represents one coherent product feature or capability. Sprints are sequential dependency stages, not calendar commitments.

---

## Sprint 1 — Product charter and architecture decisions

### Objective

Freeze the problem definition and system boundaries.

### Work

* finalize project name;
* define research questions;
* define product users;
* document included and excluded scope;
* record architectural decisions;
* define quality attributes;
* establish coding conventions.

### Deliverables

```text
README skeleton
project charter
architecture decision records
system context diagram
initial risk register
```

### Exit criteria

* one agreed research objective;
* one agreed product objective;
* no ambiguity about pipeline-first architecture;
* website explicitly depends on stable pipeline services.

---

## Sprint 2 — Repository and engineering foundation

### Objective

Create the monorepo and development standards.

### Work

* initialize Python package;
* initialize frontend workspace;
* configure `uv`;
* configure `pnpm`;
* configure Ruff, mypy, pytest;
* configure TypeScript linting;
* add pre-commit hooks;
* add CI;
* add Docker Compose skeleton.

### Deliverables

* monorepo structure;
* passing empty CI;
* development commands;
* environment template;
* contribution guide.

### Exit criteria

```bash
make install
make lint
make test
```

all succeed in a clean environment.

---

## Sprint 3 — Dataset discovery and profiling prototype

### Objective

Choose the benchmark subset scientifically.

### Work

* locate manually provided candidate Alaska data;
* inspect source/category availability;
* calculate overlap and ground-truth coverage;
* profile conflicts and missingness;
* rank candidate domains.

### Deliverables

```text
dataset candidate report
profiling notebook
selection score table
recommended scope
```

### Exit criteria

The selected subset satisfies or exceeds every assignment minimum and has enough difficult cases for meaningful LLM evaluation.

---

## Sprint 4 — Dataset ingestion and manifests

### Objective

Implement immutable, reproducible source ingestion.

### Work

* support primary file formats;
* define source manifests;
* create stable record IDs;
* calculate checksums;
* validate malformed rows;
* write Parquet outputs.

### Deliverables

```text
source metadata
raw records
ingestion errors
dataset manifest
manual dataset access instructions
```

### Exit criteria

A clean clone can reproduce the exact raw and ingested dataset from documented instructions.

---

## Sprint 5 — Source profiling engine

### Objective

Generate reusable schema and value statistics.

### Work

* infer data types;
* calculate null and uniqueness rates;
* detect identifiers, currencies, units, URLs;
* extract representative samples;
* generate value distributions.

### Deliverables

```text
source_attributes.parquet
profile summaries
profile visualizations
profiling tests
```

### Exit criteria

Every source attribute has a validated profile and sample set.

---

## Sprint 6 — Mediated schema and schema versioning

### Objective

Define the canonical product representation.

### Work

* specify core attributes;
* define descriptions and types;
* specify unit families;
* define semi-structured specifications;
* create JSON Schema;
* create schema versioning rules.

### Deliverables

```text
mediated_schema.json
schema documentation
schema validation code
mapping gold format
```

### Exit criteria

All integrated outputs can be validated against the mediated schema.

---

## Sprint 7 — Deterministic schema alignment

### Objective

Implement the traditional schema-matching baseline.

### Work

* name similarity;
* type compatibility;
* value evidence;
* context coherence;
* candidate ranking;
* assignment optimization;
* unmapped support.

### Deliverables

```text
mapping candidates
accepted baseline mappings
schema evaluation metrics
mapping error report
```

### Exit criteria

The baseline produces reproducible mappings and reports precision, recall, and F1.

---

## Sprint 8 — Canonical normalization engine

### Objective

Normalize mapped values while retaining raw evidence.

### Work

* brand aliases;
* model-number normalization;
* title normalization;
* price and currency parsing;
* measurement conversion;
* specification-key normalization;
* confidence and rule metadata.

### Deliverables

```text
normalized records
normalized values
normalization rule registry
unit tests
```

### Exit criteria

Every canonical value can be traced to its raw source and normalization method.

---

## Sprint 9 — Multi-pass blocking

### Objective

Reduce the candidate space without losing true matches.

### Work

* identifier blocks;
* rare-token blocks;
* title signatures;
* MinHash or q-gram retrieval;
* category-aware candidates;
* candidate deduplication.

### Deliverables

```text
candidate_pairs.parquet
blocking metrics
blocking-rule contribution report
missed-positive analysis
```

### Exit criteria

Pair completeness and reduction ratio meet documented validation targets.

---

## Sprint 10 — Pairwise feature generation

### Objective

Create the complete linkage feature representation.

### Work

* textual similarities;
* identifier agreement;
* brand and category compatibility;
* numeric differences;
* specification agreement;
* missingness;
* source-pair indicators.

### Deliverables

```text
pair_features.parquet
feature dictionary
feature validation tests
feature-distribution report
```

### Exit criteria

Feature computation is deterministic and has no ground-truth leakage.

---

## Sprint 11 — Traditional record-linkage baseline

### Objective

Produce interpretable pairwise match predictions.

### Work

* implement rule baseline;
* train logistic regression;
* calibrate thresholds;
* evaluate on entity-safe splits;
* inspect feature contributions.

### Deliverables

```text
trained model
pair predictions
linkage metrics
calibration analysis
error examples
```

### Exit criteria

Precision, recall, F1, candidate count, and evaluation split are fully reproducible.

---

## Sprint 12 — Constraint-aware entity clustering

### Objective

Convert pairwise predictions into coherent entities.

### Work

* connected-components comparison;
* constrained agglomeration;
* cluster confidence;
* rejected merge logging;
* cluster metrics.

### Deliverables

```text
entity clusters
cluster memberships
cluster evaluation
chaining-error analysis
```

### Exit criteria

Clusters satisfy hard constraints and outperform or explain differences from simple connected components.

---

## Sprint 13 — Claim extraction

### Objective

Convert linked records into explicit source claims.

### Work

* generate one claim per entity/attribute/source value;
* preserve normalization metadata;
* attach timestamps where available;
* validate claim lineage.

### Deliverables

```text
attribute_claims.parquet
claim lineage report
claim validation tests
```

### Exit criteria

Every fusion input is represented by a traceable claim.

---

## Sprint 14 — Deterministic data fusion

### Objective

Implement the complete baseline fusion layer.

### Work

* attribute-specific rules;
* weighted voting;
* medoid title selection;
* numeric robust aggregation;
* source-quality hooks;
* uncertainty and alternatives.

### Deliverables

```text
fused values
integrated entities
fusion metrics
conflict inventory
```

### Exit criteria

The traditional pipeline runs from raw sources to final integrated entities without any LLM use.

This is the first major project milestone: all assignment stages are operational in baseline form.

---

## Sprint 15 — LLM gateway and structured-output infrastructure

### Objective

Add reliable, observable, provider-neutral model access.

### Work

* client abstraction;
* JSON schemas;
* Pydantic validation;
* caching;
* retry policy;
* tracing;
* token and cost accounting;
* failure classification.

### Deliverables

```text
LLM gateway
response cache
call logs
validation tests
failure-policy documentation
```

### Exit criteria

Invalid and unsupported outputs are rejected automatically, and all calls are fully logged.

---

## Sprint 16 — LLM-assisted schema alignment

### Objective

Adjudicate ambiguous mappings.

### Work

* define uncertainty routing;
* create versioned prompt;
* enforce target enumeration;
* add abstention;
* compare against baseline.

### Deliverables

```text
schema prompt
mapping output schema
assisted mapping results
schema ablation metrics
```

### Exit criteria

The contribution of LLM schema alignment is measurable independently.

---

## Sprint 17 — LLM-assisted normalization

### Objective

Handle normalization cases not safely covered by rules.

### Work

* route uncertain values;
* require evidence spans;
* validate derivability;
* compare rule and LLM outputs;
* measure unsupported-value rate.

### Deliverables

```text
normalization prompt
assisted normalization results
failure analysis
```

### Exit criteria

No accepted LLM normalization lacks source support.

---

## Sprint 18 — LLM-assisted record linkage

### Objective

Adjudicate borderline candidate pairs.

### Work

* tune uncertainty band;
* build record-comparison prompt;
* expose deterministic evidence;
* support abstention;
* implement fallback;
* evaluate difficult subsets.

### Deliverables

```text
linkage prompt
assisted pair decisions
band-selection analysis
linkage ablation metrics
```

### Exit criteria

Baseline-only and assisted decisions are independently traceable and comparable.

---

## Sprint 19 — LLM-assisted fusion

### Objective

Resolve difficult claim conflicts.

### Work

* identify unresolved conflicts;
* restrict allowed outputs;
* validate claim references;
* reject invented values;
* measure fusion improvement and failures.

### Deliverables

```text
fusion prompt
assisted fused values
fusion ablation metrics
unsupported-output analysis
```

### Exit criteria

Every accepted LLM fusion decision references valid supporting claims.

---

## Sprint 20 — Cost-aware routing

### Objective

Optimize when the LLM should be invoked.

### Work

* define correction labels;
* train routing model;
* incorporate cost and latency;
* compare fixed bands and learned routing;
* generate cost-quality curves.

### Deliverables

```text
routing model
routing policy
budget experiments
quality-cost frontier
```

### Exit criteria

The project can defend its LLM-call policy quantitatively.

---

## Sprint 21 — Full experiment suite

### Objective

Execute the required comparisons and ablations.

### Work

* baseline run;
* all-stage assisted run;
* stage-specific runs;
* no-abstention experiment;
* routing-budget experiment;
* prompt sensitivity subset;
* optional model comparison.

### Deliverables

```text
MLflow experiment collection
metrics tables
plots
run manifests
statistical summaries
```

### Exit criteria

Every reported result can be traced to a versioned experiment run.

---

## Sprint 22 — Error analysis and final research artifacts

### Objective

Complete the academic deliverables.

### Work

* select representative errors;
* classify failures;
* trace stage of origin;
* export tables and figures;
* build final integrated dataset;
* write reproduction documentation;
* generate report.

### Deliverables

```text
PDF report
GitHub-ready repository
final integrated dataset
error-analysis appendix
reproduction guide
```

### Exit criteria

Every assignment requirement is satisfied before work on the website begins.

The assignment emphasizes correct implementation, metrics, experimental design, error analysis, code quality, and originality; the system should therefore freeze a reproducible research release at this point. 

---

# Website phase

## Sprint 23 — Operational database

### Objective

Move research metadata into an application-grade persistence layer.

### Work

* define SQLAlchemy models;
* create PostgreSQL schema;
* add migrations;
* persist projects, sources, runs, reviews, and provenance;
* reference Parquet/object artifacts.

### Deliverables

```text
database models
Alembic migrations
seed data
repository layer
```

### Exit criteria

A demo research run can be reconstructed through database and artifact references.

---

## Sprint 24 — Backend API foundation

### Objective

Expose stable application services.

### Work

* create FastAPI application;
* implement project and source APIs;
* add pagination;
* add error contracts;
* generate OpenAPI specification;
* add API tests.

### Deliverables

```text
API server
OpenAPI schema
typed API client generation
contract tests
```

### Exit criteria

Core metadata is available through documented, tested endpoints.

---

## Sprint 25 — Background job orchestration

### Objective

Run long pipeline operations safely from the application.

### Work

* configure PostgreSQL-backed job tables;
* create worker;
* define stage jobs;
* claim pending jobs from PostgreSQL;
* support retries and cancellation;
* persist progress;
* stream status to clients.

### Deliverables

```text
worker service
job state model
job APIs
progress events
failure recovery tests
```

### Exit criteria

A user can start and monitor a complete pipeline without blocking an HTTP request.

---

## Sprint 26 — Frontend shell and design system

### Objective

Create the application foundation.

### Work

* configure Next.js;
* create layout and navigation;
* define design tokens;
* build reusable UI components;
* configure query client;
* establish loading and error states;
* add accessibility baseline.

### Deliverables

```text
application shell
navigation
component library
API client integration
```

### Exit criteria

The web client can authenticate later and display live backend data.

---

## Sprint 27 — Project dashboard

### Objective

Provide a command center for each integration project.

### Work

* project summary;
* pipeline status;
* source counts;
* unresolved work;
* latest metrics;
* cost and latency summary;
* recent activity.

### Deliverables

```text
dashboard page
summary API
status widgets
activity timeline
```

### Exit criteria

A user can understand the state of a project from one screen.

---

## Sprint 28 — Source ingestion user experience

### Objective

Let users register, upload, and inspect sources.

### Work

* source creation form;
* file upload;
* manifest configuration;
* validation feedback;
* ingestion progress;
* malformed-record view.

### Deliverables

```text
source catalog
upload workflow
ingestion status page
error table
```

### Exit criteria

A new source can be ingested without command-line intervention.

---

## Sprint 29 — Data profiling interface

### Objective

Make source characteristics visually inspectable.

### Work

* column statistics;
* type suggestions;
* null and uniqueness charts;
* sample values;
* numeric and categorical distributions;
* source comparison.

### Deliverables

```text
profile explorer
attribute detail view
source comparison view
```

### Exit criteria

A user can understand why a source attribute received its inferred type.

---

## Sprint 30 — Mediated schema editor

### Objective

Allow controlled schema authoring and versioning.

### Work

* add and edit attributes;
* define descriptions and types;
* define units and cardinalities;
* validate schema;
* publish schema version;
* compare versions.

### Deliverables

```text
schema editor
version history
schema validation UI
```

### Exit criteria

A schema change creates a versioned, auditable artifact.

---

## Sprint 31 — Schema mapping workbench

### Objective

Review deterministic and LLM-assisted mapping proposals.

### Work

* source attribute list;
* candidate target ranking;
* value samples;
* score decomposition;
* LLM evidence;
* accept, reject, remap, abstain;
* bulk actions.

### Deliverables

```text
mapping review screen
review APIs
mapping audit log
```

### Exit criteria

A reviewer can resolve all ambiguous mappings without editing files manually.

---

## Sprint 32 — Normalization explorer

### Objective

Inspect and debug canonical transformations.

### Work

* raw versus normalized values;
* rule filters;
* confidence filters;
* unit conversion display;
* rejected transformation queue;
* source-value search.

### Deliverables

```text
normalization table
value detail drawer
error filters
```

### Exit criteria

A normalization failure can be traced to its precise rule or LLM response.

---

## Sprint 33 — Blocking analytics

### Objective

Make candidate generation understandable.

### Work

* rule contribution;
* candidate overlap;
* pair-completeness chart;
* reduction ratio;
* missed positives;
* oversized block inspection.

### Deliverables

```text
blocking dashboard
rule comparison views
candidate explorer
```

### Exit criteria

A user can identify which blocking rule caused either excessive work or missed matches.

---

## Sprint 34 — Pairwise review workbench

### Objective

Enable efficient human record-linkage review.

### Work

* side-by-side records;
* agreement highlighting;
* feature values;
* baseline and LLM decisions;
* keyboard shortcuts;
* review queue navigation;
* reviewer comments.

### Deliverables

```text
pair review page
review state
decision history
review productivity metrics
```

### Exit criteria

A reviewer can process uncertain candidate pairs quickly and consistently.

---

## Sprint 35 — Cluster explorer and editor

### Objective

Visualize and correct entity clusters.

### Work

* member list;
* supporting-edge graph;
* confidence;
* conflicts;
* merge;
* split;
* constraint validation;
* cluster history.

### Deliverables

```text
cluster detail page
cluster graph
merge/split workflows
```

### Exit criteria

Manual cluster changes preserve a complete audit trail and cannot violate hard constraints silently.

---

## Sprint 36 — Fusion and provenance workbench

### Objective

Explain every integrated value.

### Work

* claim list;
* weighted votes;
* source quality;
* LLM decision;
* alternative values;
* supporting evidence;
* manual override;
* confidence explanation.

### Deliverables

```text
fusion review page
claim provenance panel
override workflow
```

### Exit criteria

Every canonical attribute can be traced from selected value to source claim.

---

## Sprint 37 — Integrated entity browser

### Objective

Expose the final dataset as a usable product catalog.

### Work

* search;
* filtering;
* pagination;
* entity details;
* source membership;
* confidence;
* unresolved fields;
* provenance links.

### Deliverables

```text
entity catalog
entity detail page
search API
```

### Exit criteria

A user can browse and inspect the integrated dataset without understanding internal pipeline files.

---

## Sprint 38 — Experiment comparison dashboard

### Objective

Present the research results interactively.

### Work

* run selector;
* metric comparison;
* configuration diff;
* cost and latency plots;
* error subsets;
* prompt/model filters;
* artifact links.

### Deliverables

```text
experiment dashboard
run comparison table
quality-cost charts
```

### Exit criteria

The principal report tables and plots can be reproduced from the dashboard.

---

## Sprint 39 — Error analysis center

### Objective

Turn failures into structured investigative cases.

### Work

* error taxonomy;
* saved cases;
* stage-of-origin tracing;
* expected versus predicted views;
* notes;
* export to report format.

### Deliverables

```text
error case browser
taxonomy filters
report export
```

### Exit criteria

At least three report-ready errors can be generated directly from saved application cases.

---

## Sprint 40 — Authentication, authorization, and audit trail

### Objective

Make the website safe for multiple users.

### Work

* authentication;
* project membership;
* roles;
* protected routes;
* review assignment;
* audit events;
* session management.

### Deliverables

```text
identity integration
RBAC
audit log
security tests
```

### Exit criteria

Viewers, reviewers, and administrators have appropriately separated capabilities.

---

## Sprint 41 — Export and reporting center

### Objective

Generate complete project artifacts from the website.

### Work

* export formats;
* background export jobs;
* signed or protected downloads;
* experiment manifest generation;
* report table generation;
* final dataset packaging.

### Deliverables

```text
export center
artifact bundles
research-release package
```

### Exit criteria

A project administrator can produce all submission and analysis artifacts from one workflow.

---

## Sprint 42 — Production hardening

### Objective

Make the complete application deployable and reliable.

### Work

* health checks;
* structured logging;
* metrics;
* tracing;
* backup strategy;
* migration procedure;
* rate limiting;
* file-size limits;
* dependency scanning;
* performance testing;
* accessibility testing.

### Deliverables

```text
deployment manifests
operations guide
backup and restore procedure
observability dashboards
security checklist
```

### Exit criteria

The platform can be deployed, monitored, upgraded, and restored using documented procedures.

---

## Sprint 43 — Public demo and documentation

### Objective

Present Mosaic as a polished portfolio and research system.

### Work

* seed demo dataset;
* guided walkthrough;
* architecture diagrams;
* screenshots;
* API examples;
* technical documentation;
* research findings;
* demo deployment.

### Deliverables

```text
public demo
technical documentation
user guide
architecture guide
research summary
```

### Exit criteria

A new visitor can understand the problem, run the demo, inspect results, and reproduce the research.

---

# 20. Milestones without dates

## Milestone A — Reproducible data foundation

Completed after:

* repository;
* dataset selection;
* ingestion;
* profiling;
* mediated schema.

## Milestone B — Traditional integration baseline

Completed after:

* deterministic schema alignment;
* normalization;
* blocking;
* pairwise matching;
* clustering;
* deterministic fusion.

At this point, the full traditional pipeline is operational.

## Milestone C — LLM-assisted research system

Completed after:

* LLM gateway;
* assisted alignment;
* assisted normalization;
* assisted linkage;
* assisted fusion;
* cost-aware routing.

## Milestone D — Academic completion

Completed after:

* experiments;
* metrics;
* error analysis;
* report;
* final integrated dataset;
* reproducible repository.

Every assignment requirement must be complete here.

## Milestone E — Integration workbench

Completed after:

* API;
* worker;
* frontend shell;
* source management;
* pipeline execution;
* mapping, matching, clustering, and fusion workbenches.

## Milestone F — Production-ready platform

Completed after:

* authentication;
* authorization;
* audit;
* exports;
* observability;
* deployment hardening;
* public documentation.

---

# 21. Final definition of done

The complete project is finished when:

### Research

* at least three heterogeneous sources are integrated;
* the minimum data and ground-truth requirements are exceeded;
* baseline and LLM-assisted pipelines are reproducible;
* LLMs are evaluated in multiple stages;
* all prompts and configurations are versioned;
* invalid outputs are measured;
* schema, linkage, clustering, fusion, and end-to-end metrics are reported;
* cost and latency are measured;
* a structured error analysis exists;
* the final integrated dataset is exportable.

### Engineering

* the pipeline runs entirely from the CLI;
* each stage produces immutable artifacts;
* every decision preserves provenance;
* tests cover core logic and invariants;
* CI validates a fixture pipeline;
* configuration is separated from code;
* experiments are tracked and comparable.

### Website

* users can create projects and ingest sources;
* users can inspect profiles and mappings;
* users can execute pipeline runs;
* users can review uncertain pairs;
* users can inspect and edit clusters;
* users can review fusion conflicts;
* users can browse integrated entities;
* users can compare experiments;
* users can export results;
* all human actions are audited.

### Scientific contribution

The final project should be able to make a defensible claim resembling:

> Deterministic methods remain preferable for high-confidence mappings, standardized values, exact identifiers, and straightforward fusion. Selective LLM assistance improves semantically ambiguous decisions, but unrestricted use increases cost, latency, and unsupported interpretations. Uncertainty-aware routing, abstention, structured validation, and deterministic fallbacks capture most of the quality gain while maintaining reproducibility and provenance.

That conclusion directly matches the assignment’s real objective: understanding where LLMs help, where they fail, and how they should be combined with classical integration methods. 

[1]: https://duckdb.org/docs/current/?utm_source=chatgpt.com "Documentation"
[2]: https://mlflow.org/docs/latest/ml/tracking/?utm_source=chatgpt.com "ML Experiment Tracking | MLflow AI Platform"
[3]: https://fastapi.tiangolo.com/?utm_source=chatgpt.com "FastAPI - FastAPI"
[4]: https://nextjs.org/docs/app?utm_source=chatgpt.com "Next.js Docs: App Router"
