from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SchemaScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_weight: float = 0.45
    type_weight: float = 0.2
    value_weight: float = 0.25
    context_weight: float = 0.1
    accept_threshold: float = 0.58
    accept_margin: float = 0.05


class BlockingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_block_size: int = 250
    rare_token_max_frequency: int = 80
    title_token_limit: int = 6
    qgram_size: int = 3


class MatcherConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train_fraction: float = 0.6
    validation_fraction: float = 0.2
    test_fraction: float = 0.2
    default_threshold: float = 0.5
    threshold_grid: list[float] = Field(
        default_factory=lambda: [round(value / 100, 2) for value in range(20, 91, 5)]
    )


class ClusteringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_match_probability: float = 0.5
    cluster_min_match_probability: float = 0.72
    enforce_brand_constraint: bool = True
    enforce_model_constraint: bool = True
    enforce_same_source_constraint: bool = True
    enforce_spec_signature_constraint: bool = True
    max_cluster_size: int = 30


class FusionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bootstrap_fusion_gold_path: str | None = None
    curated_fusion_gold_path: str | None = None
    numeric_tolerance: float = 0.05


class BaselinePipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pipeline_id: str = "baseline_m2"
    dataset_config: str
    schema_path: str
    random_seed: int = 13
    artifact_root: str = "artifacts/runs"
    llm_decisions: Literal[False] = False
    schema_stage: SchemaScoringConfig = Field(default_factory=SchemaScoringConfig, alias="schema")
    blocking: BlockingConfig = Field(default_factory=BlockingConfig)
    matcher: MatcherConfig = Field(default_factory=MatcherConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)


class PipelineRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_dir: str
    completed_stage: str
    artifacts: dict[str, str]
    metrics: dict[str, str]


class MappingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_attribute_id: str
    source_id: str
    attribute_name: str
    target_attribute_name: str
    rank: int
    score_name: float
    score_type: float
    score_value: float
    score_context: float
    score_total: float
    evidence: str


class AcceptedSchemaMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_attribute_id: str
    source_id: str
    attribute_name: str
    target_attribute_name: str
    decision: Literal["accepted", "unmapped"]
    score_total: float
    score_margin: float
    method: str


class NormalizedValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_value_id: str
    record_uid: str
    source_attribute_id: str
    mediated_attribute_name: str
    raw_value: str
    canonical_value: str
    canonical_unit: str | None
    normalization_method: str
    confidence: float


class CandidatePair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_pair_id: str
    left_record_uid: str
    right_record_uid: str
    blocking_rules: str
    blocking_score: float
    ground_truth_label: int | None
    split: str


class PairPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_pair_id: str
    left_record_uid: str
    right_record_uid: str
    split: str
    ground_truth_label: int | None
    match_probability: float
    match_prediction: int
    threshold: float
    rule_score: float
    rule_prediction: int
    model_status: str


class EntityCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    cluster_method: str
    member_count: int
    source_count: int
    overall_confidence: float
    member_record_uids: str
    ground_truth_entity_ids: str
    primary_ground_truth_entity_id: str | None


class AttributeClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    entity_id: str
    record_uid: str
    source_id: str
    source_attribute_id: str
    mediated_attribute_name: str
    raw_value: str
    normalized_value: str
    unit: str | None
    extraction_confidence: float


class FusedValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fused_value_id: str
    entity_id: str
    mediated_attribute_name: str
    selected_value: str
    selected_unit: str | None
    fusion_method: str
    confidence: float
    supporting_claim_ids: str
    contradicting_claim_ids: str
    alternative_values: str
    llm_used: bool
    abstained: bool


class IntegratedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    cluster_method: str
    member_count: int
    source_count: int
    canonical_payload: str
    provenance: str
    overall_confidence: float


class StageMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    metrics: dict[str, Any]


def load_baseline_pipeline_config(path: Path) -> BaselinePipelineConfig:
    return BaselinePipelineConfig.model_validate_json(path.read_text(encoding="utf-8"))
