from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Literal

import polars as pl

from mosaic.m1_models import CandidateMetrics, DatasetConfig
from mosaic.m1_utils import positive_pairs_from_cluster_sizes, repo_relative

MODEL_PATTERN = re.compile(r"\b[A-Z]{1,5}[- ]?\d{2,5}[A-Z0-9-]*\b", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"^-?\d+(\.\d+)?$")
CURRENCY_PATTERN = re.compile(r"([$€£]|usd|eur|gbp)\b", re.IGNORECASE)
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
UNIT_PATTERN = re.compile(r"\b(mm|cm|inch|inches|kg|g|gb|tb|hz|mp|mah|w)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ProfileResult:
    source_attributes_path: Path
    summary_path: Path
    fusion_conflict_count: int
    metrics: CandidateMetrics


def profile_dataset(
    config: DatasetConfig,
    repo_root: Path,
    ingested_root: Path | None = None,
    artifacts_root: Path | None = None,
    evidence_level: Literal["published_metadata", "local_profile", "fixture"] = "local_profile",
) -> ProfileResult:
    dataset_root = ingested_root or repo_root / "data" / "interim" / "m1" / config.dataset_id
    artifacts_dir = artifacts_root or repo_root / "artifacts" / "tables"
    reports_dir = repo_root / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    records_path = dataset_root / "source_records.parquet"
    if not records_path.exists():
        raise FileNotFoundError(records_path)

    records = pl.read_parquet(records_path).to_dicts()
    parsed_records = [_parse_record(record) for record in records]
    profile_rows = _attribute_profiles(parsed_records)
    source_attributes_path = artifacts_dir / f"{config.dataset_id}_source_attributes.parquet"
    pl.DataFrame(profile_rows).write_parquet(source_attributes_path)

    ground_truth = _read_clusters(config.ground_truth_path, repo_root)
    fusion_conflict_count = _count_fusion_conflicts(parsed_records, ground_truth)
    metrics = _candidate_metrics(
        config=config,
        parsed_records=parsed_records,
        profile_rows=profile_rows,
        cluster_sizes=[len(records) for records in ground_truth.values()],
        fusion_conflict_count=fusion_conflict_count,
        evidence_level=evidence_level,
    )
    summary_path = reports_dir / f"{config.dataset_id}_profiling_summary.md"
    summary_path.write_text(_summary_markdown(config, metrics), encoding="utf-8")
    return ProfileResult(source_attributes_path, summary_path, fusion_conflict_count, metrics)


def _parse_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(str(record["raw_payload"]))
    return {
        "record_uid": str(record["record_uid"]),
        "source_id": str(record["source_id"]),
        "source_record_id": str(record["source_record_id"]),
        "payload": payload,
    }


def _attribute_profiles(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        records_by_source[record["source_id"]].append(record)

    rows: list[dict[str, Any]] = []
    for source_id, source_records in sorted(records_by_source.items()):
        attributes = sorted(
            {
                attribute
                for record in source_records
                for attribute in record["payload"]
                if record["payload"].get(attribute) not in (None, "")
            }
        )
        for attribute in attributes:
            values = [
                str(record["payload"].get(attribute))
                for record in source_records
                if record["payload"].get(attribute) not in (None, "")
            ]
            rows.append(_profile_attribute(source_id, attribute, values, len(source_records)))
    return rows


def _profile_attribute(
    source_id: str,
    attribute: str,
    values: list[str],
    source_record_count: int,
) -> dict[str, Any]:
    distinct_values = set(values)
    lengths = [len(value) for value in values]
    numeric_values = [float(value) for value in values if NUMBER_PATTERN.match(value.strip())]
    frequent_values = Counter(values).most_common(5)
    return {
        "source_attribute_id": f"{source_id}//{attribute}",
        "source_id": source_id,
        "attribute_name": attribute,
        "inferred_type": _infer_type(attribute, values),
        "non_null_rate": len(values) / source_record_count if source_record_count else 0.0,
        "null_rate": 1 - (len(values) / source_record_count if source_record_count else 0.0),
        "uniqueness_rate": len(distinct_values) / len(values) if values else 0.0,
        "cardinality": len(distinct_values),
        "string_length_min": min(lengths) if lengths else None,
        "string_length_avg": mean(lengths) if lengths else None,
        "string_length_max": max(lengths) if lengths else None,
        "numeric_min": min(numeric_values) if numeric_values else None,
        "numeric_avg": mean(numeric_values) if numeric_values else None,
        "numeric_max": max(numeric_values) if numeric_values else None,
        "frequent_values": json.dumps(frequent_values),
        "representative_samples": json.dumps(values[:5]),
        "token_patterns": json.dumps(_token_patterns(values)),
        "unit_patterns": json.dumps(sorted(set(UNIT_PATTERN.findall(" ".join(values))))),
        "semantic_role_suggestions": json.dumps(_semantic_roles(attribute, values)),
    }


def _infer_type(attribute: str, values: list[str]) -> str:
    joined = " ".join(values[:50])
    if all(NUMBER_PATTERN.match(value.strip()) for value in values if value.strip()):
        return "number"
    if CURRENCY_PATTERN.search(attribute) or CURRENCY_PATTERN.search(joined):
        return "currency_or_price"
    if URL_PATTERN.search(joined):
        return "url"
    if UNIT_PATTERN.search(joined):
        return "measurement"
    if values and mean([len(value) for value in values]) > 80:
        return "free_text"
    return "string"


def _semantic_roles(attribute: str, values: list[str]) -> list[str]:
    name = attribute.lower()
    joined = " ".join(values[:50])
    roles: list[str] = []
    if "title" in name or name in {"name", "product name"}:
        roles.append("title")
    if "brand" in name or "manufacturer" in name or "maker" in name:
        roles.append("brand")
    if "model" in name or MODEL_PATTERN.search(joined):
        roles.append("model identifier")
    if "price" in name or CURRENCY_PATTERN.search(joined):
        roles.append("price")
    if "currency" in name:
        roles.append("currency")
    if "description" in name or "features" in name:
        roles.append("description")
    if "category" in name or "type" in name:
        roles.append("category")
    if UNIT_PATTERN.search(joined):
        roles.append("measurement")
    if URL_PATTERN.search(joined):
        roles.append("URL")
    if not roles:
        roles.append("specification")
    return roles


def _token_patterns(values: list[str]) -> dict[str, int]:
    patterns = {
        "has_model_like_token": 0,
        "has_number": 0,
        "has_unit": 0,
        "has_currency": 0,
        "has_url": 0,
    }
    for value in values:
        patterns["has_model_like_token"] += int(bool(MODEL_PATTERN.search(value)))
        patterns["has_number"] += int(any(character.isdigit() for character in value))
        patterns["has_unit"] += int(bool(UNIT_PATTERN.search(value)))
        patterns["has_currency"] += int(bool(CURRENCY_PATTERN.search(value)))
        patterns["has_url"] += int(bool(URL_PATTERN.search(value)))
    return patterns


def _read_clusters(ground_truth_path: str | None, repo_root: Path) -> dict[str, set[str]]:
    if ground_truth_path is None:
        return {}
    path = repo_root / ground_truth_path
    if not path.exists():
        return {}
    clusters: dict[str, set[str]] = defaultdict(set)
    for row in csv.DictReader(path.open(encoding="utf-8")):
        entity_id = row.get("entity_id")
        spec_id = row.get("spec_id") or row.get("record_uid")
        if entity_id and spec_id:
            clusters[entity_id].add(spec_id)
    return clusters


def _count_fusion_conflicts(
    records: list[dict[str, Any]],
    clusters: dict[str, set[str]],
) -> int:
    if not clusters:
        return 0
    by_reference: dict[str, dict[str, Any]] = {}
    for record in records:
        by_reference[record["record_uid"]] = record
        by_reference[f"{record['source_id']}//{record['source_record_id']}"] = record

    conflicts = 0
    for spec_ids in clusters.values():
        attribute_values: dict[str, set[str]] = defaultdict(set)
        for spec_id in spec_ids:
            matched_record = by_reference.get(spec_id)
            if matched_record is None:
                continue
            for attribute, value in matched_record["payload"].items():
                if value not in (None, ""):
                    attribute_values[attribute.lower()].add(str(value).strip().lower())
        conflicts += sum(1 for values in attribute_values.values() if len(values) > 1)
    return conflicts


def _candidate_metrics(
    config: DatasetConfig,
    parsed_records: list[dict[str, Any]],
    profile_rows: list[dict[str, Any]],
    cluster_sizes: list[int],
    fusion_conflict_count: int,
    evidence_level: Literal["published_metadata", "local_profile", "fixture"],
) -> CandidateMetrics:
    source_count = len({record["source_id"] for record in parsed_records})
    record_count = len(parsed_records)
    entity_count = len(cluster_sizes)
    positive_pair_count = positive_pairs_from_cluster_sizes(cluster_sizes)
    non_null_rates = [float(row["non_null_rate"]) for row in profile_rows]
    model_roles = [
        row
        for row in profile_rows
        if "model identifier" in json.loads(str(row["semantic_role_suggestions"]))
    ]
    title_roles = [
        row for row in profile_rows if "title" in json.loads(str(row["semantic_role_suggestions"]))
    ]
    mediated_coverage = _mediated_coverage(profile_rows)
    schema_heterogeneity = _schema_heterogeneity(profile_rows)
    missingness_rate = 1 - mean(non_null_rates) if non_null_rates else 1.0
    satisfies_gate = (
        source_count >= 3
        and record_count >= 1000
        and mediated_coverage >= 5
        and entity_count >= 200
        and positive_pair_count >= 300
        and fusion_conflict_count >= 100
    )
    score = _selection_score(
        source_count=source_count,
        record_count=record_count,
        entity_count=entity_count,
        positive_pair_count=positive_pair_count,
        mediated_coverage=mediated_coverage,
        schema_heterogeneity=schema_heterogeneity,
        overlap_score=_overlap_score(cluster_sizes, record_count),
        model_number_coverage=len(model_roles) / len(profile_rows) if profile_rows else 0,
        title_signal_coverage=len(title_roles) / source_count if source_count else 0,
        fusion_conflict_count=fusion_conflict_count,
    )
    return CandidateMetrics(
        vertical=config.vertical,
        source_count=source_count,
        record_count=record_count,
        attribute_count=len(profile_rows),
        entity_count=entity_count,
        labeled_record_count=sum(cluster_sizes),
        positive_pair_count=positive_pair_count,
        mediated_attribute_coverage=mediated_coverage,
        missingness_rate=missingness_rate,
        schema_heterogeneity=schema_heterogeneity,
        overlap_score=_overlap_score(cluster_sizes, record_count),
        model_number_coverage=len(model_roles) / len(profile_rows) if profile_rows else 0,
        title_signal_coverage=len(title_roles) / source_count if source_count else 0,
        fusion_conflict_count=fusion_conflict_count,
        satisfies_assignment_gate=satisfies_gate,
        selection_score=score,
        evidence_level=evidence_level,
    )


def _mediated_coverage(profile_rows: list[dict[str, Any]]) -> int:
    roles = {
        role
        for row in profile_rows
        for role in json.loads(str(row["semantic_role_suggestions"]))
    }
    covered = 0
    covered += int("title" in roles)
    covered += int("brand" in roles)
    covered += int("model identifier" in roles)
    covered += int("category" in roles)
    covered += int("description" in roles)
    covered += int("price" in roles)
    covered += int("currency" in roles)
    covered += int("specification" in roles or "measurement" in roles)
    return covered


def _schema_heterogeneity(profile_rows: list[dict[str, Any]]) -> float:
    attributes_by_source: dict[str, set[str]] = defaultdict(set)
    for row in profile_rows:
        attributes_by_source[str(row["source_id"])].add(str(row["attribute_name"]).lower())
    sources = list(attributes_by_source.values())
    if len(sources) < 2:
        return 0.0
    distances: list[float] = []
    for index, left in enumerate(sources):
        for right in sources[index + 1 :]:
            union = left | right
            distances.append(1 - (len(left & right) / len(union) if union else 0.0))
    return mean(distances) if distances else 0.0


def _overlap_score(cluster_sizes: list[int], record_count: int) -> float:
    if not record_count:
        return 0.0
    overlapping_records = sum(size for size in cluster_sizes if size > 1)
    return overlapping_records / record_count


def _selection_score(
    *,
    source_count: int,
    record_count: int,
    entity_count: int,
    positive_pair_count: int,
    mediated_coverage: int,
    schema_heterogeneity: float,
    overlap_score: float,
    model_number_coverage: float,
    title_signal_coverage: float,
    fusion_conflict_count: int,
) -> float:
    return round(
        min(source_count / 8, 1) * 10
        + min(record_count / 25000, 1) * 10
        + min(entity_count / 500, 1) * 15
        + min(positive_pair_count / 500, 1) * 15
        + min(mediated_coverage / 8, 1) * 15
        + schema_heterogeneity * 10
        + overlap_score * 10
        + model_number_coverage * 5
        + min(title_signal_coverage, 1) * 5
        + min(fusion_conflict_count / 200, 1) * 5,
        4,
    )


def _summary_markdown(config: DatasetConfig, metrics: CandidateMetrics) -> str:
    return f"""# {config.dataset_id} Profiling Summary

## Dataset

- Benchmark: `{config.benchmark}`
- Vertical: `{config.vertical}`
- Sources: {metrics.source_count}
- Source records: {metrics.record_count}
- Source attributes: {metrics.attribute_count}

## Ground Truth And Conflicts

- Entities: {metrics.entity_count}
- Labeled records: {metrics.labeled_record_count}
- Positive-pair equivalent: {metrics.positive_pair_count}
- Candidate fusion conflicts: {metrics.fusion_conflict_count}

## Selection Signals

- Mediated attribute coverage estimate: {metrics.mediated_attribute_coverage}/8
- Missingness rate: {metrics.missingness_rate:.3f}
- Schema heterogeneity: {metrics.schema_heterogeneity:.3f}
- Overlap score: {metrics.overlap_score:.3f}
- Model-number coverage: {metrics.model_number_coverage:.3f}
- Title signal coverage: {metrics.title_signal_coverage:.3f}
- Assignment gate satisfied: {metrics.satisfies_assignment_gate}
- Selection score: {metrics.selection_score}
"""


def write_profile_summary_table(
    metrics: list[CandidateMetrics],
    repo_root: Path,
    output_path: Path | None = None,
) -> Path:
    path = output_path or repo_root / "artifacts" / "tables" / "m1_selection_score_table.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame([metric.model_dump() for metric in metrics]).write_parquet(path)
    report_path = repo_root / "reports" / "dataset_candidate_report.md"
    report_path.write_text(_candidate_report(metrics, path, repo_root), encoding="utf-8")
    return path


def _candidate_report(metrics: list[CandidateMetrics], table_path: Path, repo_root: Path) -> str:
    rows = "\n".join(
        "| "
        + " | ".join(
            [
                metric.vertical,
                str(metric.source_count),
                str(metric.record_count),
                str(metric.entity_count),
                str(metric.positive_pair_count),
                str(metric.fusion_conflict_count),
                str(metric.satisfies_assignment_gate),
                f"{metric.selection_score:.4f}",
            ]
        )
        + " |"
        for metric in sorted(metrics, key=lambda item: item.selection_score, reverse=True)
    )
    selected = max(metrics, key=lambda item: item.selection_score) if metrics else None
    fallback = ""
    if selected and not any(metric.satisfies_assignment_gate for metric in metrics):
        fallback = (
            "\n## Benchmark Fallback Watchpoint\n\n"
            "No candidate satisfies every assignment gate with the currently available evidence. "
            "Manually place and profile local Alaska records before relaxing the "
            "benchmark choice.\n"
        )
    return f"""# Dataset Candidate Report

M1 ranks candidate product domains with hard assignment gates first and a documented
selection score second.

Score table artifact: `{repo_relative(table_path, repo_root)}`

| Vertical | Sources | Records | Entities | Positive pairs | Fusion conflicts | Gate | Score |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
{rows}

## Recommendation

Selected candidate: `{selected.vertical if selected else "none"}`.
{fallback}
"""
