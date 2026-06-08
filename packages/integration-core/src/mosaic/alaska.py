from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mosaic.m1_models import CandidateMetrics, DatasetConfig, SourceInput
from mosaic.m1_utils import positive_pairs_from_cluster_sizes
from mosaic.profiling import write_profile_summary_table

ALASKA_REPO_URL = "https://github.com/merialdo/research.alaska"
ALASKA_PAPER_URL = "https://arxiv.org/abs/2101.11259"

PUBLISHED_ALASKA_CANDIDATES: dict[str, dict[str, Any]] = {
    "camera": {
        "source_count": 24,
        "record_count": 29787,
        "attribute_count": 4660,
        "entity_count": 103,
        "labeled_record_count": 3865,
        "target_attribute_count": 56,
        "labeled_attribute_count": 687,
    },
    "monitor": {
        "source_count": 26,
        "record_count": 16662,
        "attribute_count": 1687,
        "entity_count": 232,
        "labeled_record_count": 2273,
        "target_attribute_count": 87,
        "labeled_attribute_count": 1026,
    },
    "notebook": {
        "source_count": 27,
        "record_count": 23167,
        "attribute_count": 3099,
        "entity_count": 208,
        "labeled_record_count": 1143,
        "target_attribute_count": 44,
        "labeled_attribute_count": 960,
    },
}


def published_candidate_metrics() -> list[CandidateMetrics]:
    metrics: list[CandidateMetrics] = []
    for vertical, values in PUBLISHED_ALASKA_CANDIDATES.items():
        entity_count = int(values["entity_count"])
        labeled_record_count = int(values["labeled_record_count"])
        positive_pair_floor = _minimum_positive_pairs(labeled_record_count, entity_count)
        source_count = int(values["source_count"])
        record_count = int(values["record_count"])
        target_attribute_count = int(values["target_attribute_count"])
        mediated_coverage = min(target_attribute_count, 8)
        schema_heterogeneity = min(int(values["attribute_count"]) / 5000, 1.0)
        overlap_score = labeled_record_count / record_count
        fusion_conflict_count = 0
        score = _published_selection_score(
            source_count=source_count,
            record_count=record_count,
            entity_count=entity_count,
            positive_pair_count=positive_pair_floor,
            mediated_coverage=mediated_coverage,
            schema_heterogeneity=schema_heterogeneity,
            overlap_score=overlap_score,
        )
        metrics.append(
            CandidateMetrics(
                vertical=vertical,
                source_count=source_count,
                record_count=record_count,
                attribute_count=int(values["attribute_count"]),
                entity_count=entity_count,
                labeled_record_count=labeled_record_count,
                positive_pair_count=positive_pair_floor,
                mediated_attribute_coverage=mediated_coverage,
                missingness_rate=0.0,
                schema_heterogeneity=schema_heterogeneity,
                overlap_score=overlap_score,
                model_number_coverage=0.0,
                title_signal_coverage=0.0,
                fusion_conflict_count=fusion_conflict_count,
                satisfies_assignment_gate=False,
                selection_score=score,
                evidence_level="published_metadata",
            )
        )
    return metrics


def write_published_selection(repo_root: Path) -> Path:
    return write_profile_summary_table(published_candidate_metrics(), repo_root)


def create_dataset_config_from_alaska_dir(
    *,
    dataset_id: str,
    vertical: str,
    extracted_root: Path,
    repo_root: Path,
) -> DatasetConfig:
    source_dirs = [
        path
        for path in sorted(extracted_root.rglob("*"))
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
    ground_truth_path = _find_first(
        extracted_root,
        ["*entity*resolution*.csv", "*er*.csv", "*gt*.csv"],
    )
    mapping_gold_path = _find_first(extracted_root, ["*schema*matching*.csv", "*sm*.csv"])
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


def write_candidate_config(path: Path) -> Path:
    payload = {
        "benchmark": "alaska",
        "paper_url": ALASKA_PAPER_URL,
        "repository_url": ALASKA_REPO_URL,
        "candidates": PUBLISHED_ALASKA_CANDIDATES,
        "notes": [
            "Published metadata is used for provisional ranking.",
            "Benchmark archives must be obtained manually before real-data ingestion.",
            "Local profiling is required before the assignment gate is accepted.",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _minimum_positive_pairs(labeled_record_count: int, entity_count: int) -> int:
    if labeled_record_count <= entity_count or entity_count <= 0:
        return 0
    base_size = labeled_record_count // entity_count
    remainder = labeled_record_count % entity_count
    cluster_sizes = [base_size + 1] * remainder + [base_size] * (entity_count - remainder)
    return positive_pairs_from_cluster_sizes(cluster_sizes)


def _published_selection_score(
    *,
    source_count: int,
    record_count: int,
    entity_count: int,
    positive_pair_count: int,
    mediated_coverage: int,
    schema_heterogeneity: float,
    overlap_score: float,
) -> float:
    score = (
        min(source_count / 8, 1) * 10
        + min(record_count / 25000, 1) * 10
        + min(entity_count / 500, 1) * 15
        + min(positive_pair_count / 500, 1) * 15
        + min(mediated_coverage / 8, 1) * 15
        + schema_heterogeneity * 10
        + overlap_score * 10
    )
    if source_count < 3:
        score -= 20
    if record_count < 1000:
        score -= 20
    if entity_count < 200:
        score -= 30
    if positive_pair_count < 300:
        score -= 20
    if mediated_coverage < 5:
        score -= 20
    return round(score, 4)


def _find_first(root: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        matches = sorted(root.rglob(pattern))
        if matches:
            return matches[0]
    return None
