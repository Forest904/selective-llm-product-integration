from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REQUIRED_MEDIATED_ATTRIBUTES = {
    "title",
    "brand",
    "model_number",
    "category",
    "description",
    "price",
    "currency",
    "specifications",
}


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    name: str | None = None
    source_type: str = "web_source"
    origin: str
    license: str = "unknown"
    retrieval_date: str | None = None
    path: str
    format: Literal["csv", "json", "jsonl", "parquet", "alaska_json_dir"]
    id_field: str | None = None


class DatasetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    benchmark: str
    vertical: str
    version: str = "m1"
    description: str = ""
    sources: list[SourceInput]
    ground_truth_path: str | None = None
    mapping_gold_path: str | None = None


class SourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    name: str
    source_type: str
    origin: str
    retrieval_date: str
    license: str
    record_count: int
    input_path: str
    input_checksum: str | None = None


class GroundTruthSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_count: int = 0
    labeled_record_count: int = 0
    positive_pair_count: int = 0


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    benchmark: str
    vertical: str
    version: str
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    sources: list[SourceManifest]
    total_record_count: int
    record_uid_convention: str = "{source_id}:{source_record_id}"
    raw_artifacts: dict[str, str]
    ground_truth: GroundTruthSummary

    @model_validator(mode="after")
    def total_matches_sources(self) -> DatasetManifest:
        source_total = sum(source.record_count for source in self.sources)
        if self.total_record_count != source_total:
            raise ValueError("total_record_count must equal the sum of source record counts")
        return self


class MediatedAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    type: str
    description: str
    required: bool
    nullable: bool
    normalization: str


class MediatedSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    domain: str
    attributes: list[MediatedAttribute]
    specifications_shape: dict[str, Any]

    @field_validator("attributes")
    @classmethod
    def includes_required_attributes(
        cls, attributes: list[MediatedAttribute]
    ) -> list[MediatedAttribute]:
        names = {attribute.name for attribute in attributes}
        missing = REQUIRED_MEDIATED_ATTRIBUTES - names
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"mediated schema missing required attributes: {missing_text}")
        return attributes


class CandidateMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vertical: str
    source_count: int
    record_count: int
    attribute_count: int
    entity_count: int
    labeled_record_count: int
    positive_pair_count: int
    mediated_attribute_coverage: int
    missingness_rate: float
    schema_heterogeneity: float
    overlap_score: float
    model_number_coverage: float
    title_signal_coverage: float
    fusion_conflict_count: int
    satisfies_assignment_gate: bool
    selection_score: float
    evidence_level: Literal["published_metadata", "local_profile", "fixture"]


class IngestedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_uid: str
    source_id: str
    source_record_id: str
    raw_payload: str
    raw_checksum: str
    ingested_at: str


class IngestionError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    input_path: str
    source_record_id: str | None
    error_type: str
    message: str


def load_dataset_config(path: Path) -> DatasetConfig:
    return DatasetConfig.model_validate_json(path.read_text(encoding="utf-8"))


def load_mediated_schema(path: Path) -> MediatedSchema:
    return MediatedSchema.model_validate_json(path.read_text(encoding="utf-8"))
