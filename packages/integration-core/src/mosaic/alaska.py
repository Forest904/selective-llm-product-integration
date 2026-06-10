from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from mosaic.m1_models import CandidateMetrics, DatasetConfig, SourceInput
from mosaic.m1_utils import positive_pairs_from_cluster_sizes
from mosaic.profiling import (
    _mediated_coverage,
    _schema_heterogeneity,
    _semantic_roles,
)

ALASKA_REPO_URL = "https://github.com/merialdo/research.alaska"
ALASKA_VERTICALS = ("camera", "monitor", "notebook")


def alaska_extracted_root(repo_root: Path, vertical: str) -> Path:
    return repo_root / "data" / "raw" / "alaska" / vertical / "extracted"


def local_alaska_dataset_configs(repo_root: Path) -> list[DatasetConfig]:
    configs: list[DatasetConfig] = []
    for vertical in ALASKA_VERTICALS:
        extracted_root = alaska_extracted_root(repo_root, vertical)
        if not extracted_root.exists():
            continue
        config = create_dataset_config_from_alaska_dir(
            dataset_id=f"alaska_{vertical}_m1",
            vertical=vertical,
            extracted_root=extracted_root,
            repo_root=repo_root,
        )
        if config.sources:
            configs.append(config)
    return configs


def select_best_candidate(metrics: list[CandidateMetrics]) -> CandidateMetrics:
    if not metrics:
        raise ValueError("at least one candidate metric is required")
    gated_metrics = [metric for metric in metrics if metric.satisfies_assignment_gate]
    if not gated_metrics:
        raise ValueError("no local Alaska candidate satisfies the M1 assignment gates")
    return max(gated_metrics, key=lambda metric: metric.selection_score)


def local_alaska_candidate_metrics(config: DatasetConfig, repo_root: Path) -> CandidateMetrics:
    source_record_counts = {
        source.source_id: _count_json_files(repo_root / source.path) for source in config.sources
    }
    for source in config.sources:
        source_record_counts.setdefault(source.source_id, 0)
    profile_rows = _profile_mapping_gold(config.mapping_gold_path, repo_root)

    record_count = sum(source_record_counts.values())
    clusters = _read_clusters(config.ground_truth_path, repo_root)
    cluster_sizes = [len(records) for records in clusters.values()]
    labeled_record_count = len({spec_id for records in clusters.values() for spec_id in records})
    entity_count = len(cluster_sizes)
    positive_pair_count = positive_pairs_from_cluster_sizes(cluster_sizes)
    fusion_conflict_count = _count_fusion_conflicts(config, repo_root, clusters)
    source_count = len([count for count in source_record_counts.values() if count > 0])
    mediated_coverage = _mediated_coverage(profile_rows)
    schema_heterogeneity = _schema_heterogeneity(profile_rows)
    overlap_score = _overlap_score(cluster_sizes, record_count)
    model_sources = {
        str(row["source_id"])
        for row in profile_rows
        if "model identifier" in json.loads(str(row["semantic_role_suggestions"]))
    }
    title_sources = {
        str(row["source_id"])
        for row in profile_rows
        if "title" in json.loads(str(row["semantic_role_suggestions"]))
    }
    satisfies_gate = (
        source_count >= 3
        and record_count >= 1000
        and mediated_coverage >= 5
        and entity_count >= 200
        and positive_pair_count >= 300
        and fusion_conflict_count >= 100
    )
    score = _local_selection_score(
        source_count=source_count,
        record_count=record_count,
        entity_count=entity_count,
        positive_pair_count=positive_pair_count,
        mediated_coverage=mediated_coverage,
        schema_heterogeneity=schema_heterogeneity,
        overlap_score=overlap_score,
        model_number_coverage=len(model_sources) / source_count if source_count else 0,
        title_signal_coverage=len(title_sources) / source_count if source_count else 0,
        fusion_conflict_count=fusion_conflict_count,
        labeled_record_count=labeled_record_count,
    )
    return CandidateMetrics(
        vertical=config.vertical,
        source_count=source_count,
        record_count=record_count,
        attribute_count=len(profile_rows),
        entity_count=entity_count,
        labeled_record_count=labeled_record_count,
        positive_pair_count=positive_pair_count,
        mediated_attribute_coverage=mediated_coverage,
        missingness_rate=float("nan"),
        schema_heterogeneity=schema_heterogeneity,
        overlap_score=overlap_score,
        model_number_coverage=len(model_sources) / source_count if source_count else 0,
        title_signal_coverage=len(title_sources) / source_count if source_count else 0,
        fusion_conflict_count=fusion_conflict_count,
        satisfies_assignment_gate=satisfies_gate,
        selection_score=score,
        evidence_level="local_profile",
    )


def create_dataset_config_from_alaska_dir(
    *,
    dataset_id: str,
    vertical: str,
    extracted_root: Path,
    repo_root: Path,
) -> DatasetConfig:
    specs_root = extracted_root / f"{vertical}_specs"
    source_dirs = [
        path
        for path in sorted(specs_root.iterdir() if specs_root.exists() else [])
        if path.is_dir() and any(path.glob("*.json"))
    ]
    sources = [
        SourceInput(
            source_id=source_dir.name,
            name=source_dir.name,
            origin=ALASKA_REPO_URL,
            license="MIT",
            path=source_dir.relative_to(repo_root).as_posix(),
            format="alaska_json_dir",
        )
        for source_dir in source_dirs
    ]
    ground_truth_root = extracted_root / f"{vertical}_ground_truths"
    ground_truth_path = _find_first(
        ground_truth_root,
        [f"{vertical}_entity_resolution_gt.csv", "*entity*resolution*.csv", "*er*.csv"],
    )
    mapping_gold_path = _find_first(
        ground_truth_root,
        [f"{vertical}_schema_matching_gt.csv", "*schema*matching*.csv", "*sm*.csv"],
    )
    return DatasetConfig(
        dataset_id=dataset_id,
        benchmark="alaska",
        vertical=vertical,
        version="alaska_2021",
        description=f"Alaska {vertical} benchmark subset generated from local raw files.",
        sources=sources,
        ground_truth_path=(
            ground_truth_path.relative_to(repo_root).as_posix() if ground_truth_path else None
        ),
        mapping_gold_path=(
            mapping_gold_path.relative_to(repo_root).as_posix() if mapping_gold_path else None
        ),
    )


def write_dataset_config(config: DatasetConfig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return path


def _find_first(root: Path, patterns: list[str]) -> Path | None:
    if not root.exists():
        return None
    for pattern in patterns:
        matches = sorted(root.rglob(pattern))
        if matches:
            return matches[0]
    return None


def _count_json_files(source_dir: Path) -> int:
    return sum(1 for _ in source_dir.rglob("*.json"))


def _profile_mapping_gold(mapping_gold_path: str | None, repo_root: Path) -> list[dict[str, Any]]:
    if mapping_gold_path is None:
        return []
    path = repo_root / mapping_gold_path
    if not path.exists():
        return []
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(path.open(encoding="utf-8")):
        source_attribute_id = row.get("source_attribute_id", "")
        if "//" not in source_attribute_id:
            continue
        source_id, attribute = source_attribute_id.split("//", 1)
        key = (source_id, attribute)
        if key in seen:
            continue
        seen.add(key)
        target = row.get("target_attribute_name", "")
        role_text = f"{attribute} {target}".strip()
        rows.append(
            {
                "source_id": source_id,
                "attribute_name": attribute,
                "non_null_rate": 1.0,
                "semantic_role_suggestions": json.dumps(_semantic_roles(role_text, [])),
            }
        )
    return [
        {
            "source_id": str(row["source_id"]),
            "attribute_name": str(row["attribute_name"]),
            "non_null_rate": float(row["non_null_rate"]),
            "semantic_role_suggestions": str(row["semantic_role_suggestions"]),
        }
        for row in sorted(
            rows,
            key=lambda item: (str(item["source_id"]), str(item["attribute_name"])),
        )
    ]


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
    config: DatasetConfig,
    repo_root: Path,
    clusters: dict[str, set[str]],
) -> int:
    source_paths = {source.source_id: repo_root / source.path for source in config.sources}
    records = {
        spec_id: payload
        for spec_id in {spec_id for spec_ids in clusters.values() for spec_id in spec_ids}
        if (payload := _read_spec_payload(spec_id, source_paths)) is not None
    }
    conflicts = 0
    for spec_ids in clusters.values():
        attribute_values: dict[str, set[str]] = defaultdict(set)
        for spec_id in spec_ids:
            payload = records.get(spec_id, {})
            for attribute, value in payload.items():
                if value not in (None, ""):
                    attribute_values[attribute.lower()].add(str(value).strip().lower())
        conflicts += sum(1 for values in attribute_values.values() if len(values) > 1)
    return conflicts


def _read_spec_payload(
    spec_id: str,
    source_paths: dict[str, Path],
) -> dict[str, Any] | None:
    if "//" not in spec_id:
        return None
    source_id, record_id = spec_id.split("//", 1)
    source_path = source_paths.get(source_id)
    if source_path is None:
        return None
    file_path = source_path / f"{record_id}.json"
    if not file_path.exists():
        return None
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _overlap_score(cluster_sizes: list[int], record_count: int) -> float:
    if not record_count:
        return 0.0
    overlapping_records = sum(size for size in cluster_sizes if size > 1)
    return overlapping_records / record_count


def _local_selection_score(
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
    labeled_record_count: int,
) -> float:
    return round(
        min(source_count / 8, 1) * 8
        + min(record_count / 25000, 1) * 8
        + min(entity_count / 500, 1) * 20
        + min(positive_pair_count / 500, 1) * 15
        + min(mediated_coverage / 8, 1) * 10
        + schema_heterogeneity * 8
        + overlap_score * 10
        + min(labeled_record_count / 2500, 1) * 10
        + min(fusion_conflict_count / 5000, 1) * 8
        + model_number_coverage * 3
        + title_signal_coverage * 3,
        4,
    )
