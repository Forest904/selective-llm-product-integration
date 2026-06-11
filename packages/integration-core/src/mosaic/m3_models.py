from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StructuredOutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    strict: bool = True


class PricingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_usd_per_1m_tokens: float = 0.0
    output_usd_per_1m_tokens: float = 0.0


class LLMModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "fake"] = "openai"
    model: str = ""
    execution_mode: Literal["fake", "cache_or_live", "live"] = "fake"
    temperature: float = 0.0
    max_output_tokens: int = 1024
    timeout_seconds: int = 60
    max_retries: int = 2
    cache_mode: Literal["off", "read", "write", "read_write"] = "read_write"
    cache_root: str = "artifacts/llm_cache"
    call_log_root: str = "artifacts/llm_calls"
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)
    pricing: PricingConfig = Field(default_factory=PricingConfig)


class LLMAssistanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_enabled: bool = Field(default=True, alias="schema")
    linkage: bool = True
    fusion: bool = True
    normalization: bool = False


class PromptVersionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_prompt: str = Field(
        default="prompts/schema/v20260610_m3_assisted", alias="schema"
    )
    linkage: str = "prompts/linkage/v20260610_m3_assisted"
    fusion: str = "prompts/fusion/v20260610_m3_assisted"


class RoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_call_budget: int | None = None
    daily_cost_budget_usd: float | None = None
    per_run_call_budget: int | None = 50
    per_run_cost_budget_usd: float | None = None
    schema_low_margin_threshold: float = 0.08
    schema_unmapped_min_score: float = 0.35
    schema_confidence_threshold: float = 0.7
    linkage_min_probability: float = 0.35
    linkage_max_probability: float = 0.75
    linkage_confidence_threshold: float = 0.72
    fusion_confidence_threshold: float = 0.7
    max_cases_per_stage: int | None = 25
    schema_batch_size: int = 10
    linkage_batch_size: int = 10
    fusion_batch_size: int = 5
    primary_linkage_case_cap: int = 5000
    primary_fusion_case_cap: int = 1000


class FallbackPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invalid_json: Literal["deterministic", "primary_default"] = "deterministic"
    missing_fields: Literal["deterministic", "primary_default"] = "deterministic"
    unsupported_output: Literal["deterministic", "primary_default"] = "deterministic"
    abstention: Literal["deterministic", "primary_default"] = "deterministic"
    timeout: Literal["deterministic", "primary_default"] = "deterministic"


class M3ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = "m3_llm_assisted_example"
    baseline_pipeline_config: str = "configs/pipelines/fixture_m2.json"
    model_config_path: str = Field(
        default="configs/models/openai_m3_example.json", alias="model_config"
    )
    artifact_root: str = "artifacts/runs"
    decision_mode: Literal["assist", "primary"] = "assist"
    llm_assistance: LLMAssistanceConfig = Field(default_factory=LLMAssistanceConfig)
    prompt_versions: PromptVersionConfig = Field(default_factory=PromptVersionConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    fallback_policy: FallbackPolicyConfig = Field(default_factory=FallbackPolicyConfig)


class SchemaLLMDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_attribute: str
    target_attribute: str
    decision: Literal["match", "unmapped", "abstain"]
    confidence: float
    supporting_evidence: list[str]
    abstain: bool = False

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value


class SchemaLLMBatchDecisionItem(SchemaLLMDecision):
    case_id: str


class SchemaLLMBatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[SchemaLLMBatchDecisionItem]


class LinkageLLMDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["match", "non_match", "abstain"]
    confidence: float
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    abstain: bool = False

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value


class LinkageLLMBatchDecisionItem(LinkageLLMDecision):
    case_id: str


class LinkageLLMBatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[LinkageLLMBatchDecisionItem]


class FusionLLMDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_value: str
    confidence: float
    supporting_claim_ids: list[str]
    contradicting_claim_ids: list[str]
    reason: str
    abstain: bool = False

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value


class FusionLLMBatchDecisionItem(FusionLLMDecision):
    case_id: str


class FusionLLMBatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[FusionLLMBatchDecisionItem]


class LLMCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    stage: str
    prompt_version: str
    input_hash: str
    raw_response: str
    parsed_response: dict[str, Any] | None
    validation_status: Literal["valid", "invalid", "timeout", "error"]
    failure_type: str | None = None
    retry_count: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cache_status: Literal["hit", "miss", "write", "disabled"] = "disabled"


def load_m3_experiment_config(path: Path) -> M3ExperimentConfig:
    return M3ExperimentConfig.model_validate_json(path.read_text(encoding="utf-8"))


def load_llm_model_config(path: Path) -> LLMModelConfig:
    return LLMModelConfig.model_validate_json(path.read_text(encoding="utf-8"))
