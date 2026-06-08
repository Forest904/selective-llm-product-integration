from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from mosaic.m1_models import (
    DatasetConfig,
    DatasetManifest,
    GroundTruthSummary,
    IngestedRecord,
    IngestionError,
    SourceInput,
    SourceManifest,
)
from mosaic.m1_utils import (
    canonical_json,
    positive_pairs_from_cluster_sizes,
    repo_relative,
    sha256_file,
    sha256_text,
    stable_record_uid,
)

RawRow = tuple[str, str, str]


def iter_source_records(source: SourceInput, repo_root: Path) -> Iterator[RawRow]:
    path = (repo_root / source.path).resolve()
    match source.format:
        case "alaska_json_dir":
            yield from _iter_alaska_json_dir(path, source)
        case "json":
            yield from _iter_json(path, source)
        case "jsonl":
            yield from _iter_jsonl(path, source)
        case "csv":
            yield from _iter_csv(path, source)
        case "parquet":
            yield from _iter_parquet(path, source)


def ingest_dataset(
    config: DatasetConfig,
    repo_root: Path,
    output_root: Path | None = None,
) -> DatasetManifest:
    dataset_root = output_root or repo_root / "data" / "interim" / "m1" / config.dataset_id
    dataset_root.mkdir(parents=True, exist_ok=True)
    manifest_dir = repo_root / "data" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    records: list[IngestedRecord] = []
    errors: list[IngestionError] = []
    source_manifests: list[SourceManifest] = []
    ingested_at = datetime.now(UTC).isoformat()

    for source in config.sources:
        source_record_count = 0
        input_path = (repo_root / source.path).resolve()
        input_checksum = sha256_file(input_path) if input_path.is_file() else None
        try:
            rows = iter_source_records(source, repo_root)
            for source_record_id, raw_payload, error_message in rows:
                if error_message:
                    errors.append(
                        IngestionError(
                            source_id=source.source_id,
                            input_path=repo_relative(input_path, repo_root),
                            source_record_id=source_record_id or None,
                            error_type="malformed_row",
                            message=error_message,
                        )
                    )
                    continue
                try:
                    record_uid = stable_record_uid(source.source_id, source_record_id)
                except ValueError as exc:
                    errors.append(
                        IngestionError(
                            source_id=source.source_id,
                            input_path=repo_relative(input_path, repo_root),
                            source_record_id=source_record_id or None,
                            error_type="unstable_identifier",
                            message=str(exc),
                        )
                    )
                    continue
                records.append(
                    IngestedRecord(
                        record_uid=record_uid,
                        source_id=source.source_id,
                        source_record_id=source_record_id,
                        raw_payload=raw_payload,
                        raw_checksum=sha256_text(raw_payload),
                        ingested_at=ingested_at,
                    )
                )
                source_record_count += 1
        except FileNotFoundError as exc:
            errors.append(
                IngestionError(
                    source_id=source.source_id,
                    input_path=repo_relative(input_path, repo_root),
                    source_record_id=None,
                    error_type="missing_input",
                    message=str(exc),
                )
            )

        source_manifests.append(
            SourceManifest(
                source_id=source.source_id,
                name=source.name or source.source_id,
                source_type=source.source_type,
                origin=source.origin,
                retrieval_date=source.retrieval_date or ingested_at,
                license=source.license,
                record_count=source_record_count,
                input_path=repo_relative(input_path, repo_root),
                input_checksum=input_checksum,
            )
        )

    records_path = dataset_root / "source_records.parquet"
    sources_path = dataset_root / "sources.parquet"
    errors_path = dataset_root / "ingestion_errors.parquet"
    _write_parquet(records_path, [record.model_dump() for record in records])
    _write_parquet(sources_path, [source.model_dump() for source in source_manifests])
    _write_parquet(errors_path, [error.model_dump() for error in errors])

    ground_truth = summarize_ground_truth(config.ground_truth_path, repo_root)
    manifest = DatasetManifest(
        dataset_id=config.dataset_id,
        benchmark=config.benchmark,
        vertical=config.vertical,
        version=config.version,
        sources=source_manifests,
        total_record_count=len(records),
        raw_artifacts={
            "sources": repo_relative(sources_path, repo_root),
            "source_records": repo_relative(records_path, repo_root),
            "ingestion_errors": repo_relative(errors_path, repo_root),
        },
        ground_truth=ground_truth,
    )
    (manifest_dir / "dataset_manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return manifest


def summarize_ground_truth(ground_truth_path: str | None, repo_root: Path) -> GroundTruthSummary:
    if ground_truth_path is None:
        return GroundTruthSummary()
    path = repo_root / ground_truth_path
    if not path.exists():
        return GroundTruthSummary()

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    clusters: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        entity_id = row.get("entity_id")
        spec_id = row.get("spec_id") or row.get("record_uid")
        if entity_id and spec_id:
            clusters[entity_id].add(spec_id)
    cluster_sizes = [len(records) for records in clusters.values()]
    return GroundTruthSummary(
        entity_count=len(clusters),
        labeled_record_count=sum(cluster_sizes),
        positive_pair_count=positive_pairs_from_cluster_sizes(cluster_sizes),
    )


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    if rows:
        pl.DataFrame(rows).write_parquet(path)
        return
    pl.DataFrame().write_parquet(path)


def _iter_alaska_json_dir(path: Path, source: SourceInput) -> Iterator[RawRow]:
    if not path.exists():
        raise FileNotFoundError(path)
    for file_path in sorted(path.rglob("*.json")):
        source_record_id = file_path.relative_to(path).with_suffix("").as_posix()
        text = file_path.read_text(encoding="utf-8")
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            yield source_record_id, "", str(exc)
            continue
        yield source_record_id, text.strip(), ""


def _iter_json(path: Path, source: SourceInput) -> Iterator[RawRow]:
    if not source.id_field:
        raise ValueError("json ingestion requires id_field")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else [payload]
    for row in rows:
        if not isinstance(row, dict):
            yield "", "", "JSON row must be an object"
            continue
        source_record_id = str(row.get(source.id_field, ""))
        yield source_record_id, canonical_json(row), ""


def _iter_jsonl(path: Path, source: SourceInput) -> Iterator[RawRow]:
    if not source.id_field:
        raise ValueError("jsonl ingestion requires id_field")
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                yield f"line_{line_number}", "", str(exc)
                continue
            if not isinstance(row, dict):
                yield f"line_{line_number}", "", "JSONL row must be an object"
                continue
            source_record_id = str(row.get(source.id_field, ""))
            yield source_record_id, canonical_json(row), ""


def _iter_csv(path: Path, source: SourceInput) -> Iterator[RawRow]:
    if not source.id_field:
        raise ValueError("csv ingestion requires id_field")
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            source_record_id = str(row.get(source.id_field, ""))
            yield source_record_id, canonical_json(row), ""


def _iter_parquet(path: Path, source: SourceInput) -> Iterator[RawRow]:
    if not source.id_field:
        raise ValueError("parquet ingestion requires id_field")
    dataframe = pl.read_parquet(path)
    for row in dataframe.iter_rows(named=True):
        source_record_id = str(row.get(source.id_field, ""))
        yield source_record_id, canonical_json(row), ""
