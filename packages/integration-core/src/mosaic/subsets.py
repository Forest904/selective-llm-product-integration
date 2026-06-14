from __future__ import annotations

import csv
import json
import os
import shutil
import stat
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from mosaic.ingestion import ingest_dataset
from mosaic.m1_models import DatasetConfig, SourceInput, load_dataset_config
from mosaic.m1_utils import canonical_json, repo_relative, sha256_text


class SubsetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subset_id: str
    base_dataset_config: str
    entity_count: int
    random_seed: int = 13
    required_entity_ids: list[str] = []
    strategy: Literal["entity_balanced"] = "entity_balanced"
    output_root: str


class MaterializedSubset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subset_id: str
    dataset_config_path: str
    dataset_id: str
    selected_entity_count: int
    selected_record_count: int
    selected_source_count: int
    subset_hash: str
    output_root: str
    selected_entities_path: str


def load_subset_spec(path: Path) -> SubsetSpec:
    return SubsetSpec.model_validate_json(path.read_text(encoding="utf-8"))


def materialize_subset(spec_path: Path, repo_root: Path) -> MaterializedSubset:
    spec = load_subset_spec(spec_path)
    base_config = load_dataset_config(repo_root / spec.base_dataset_config)
    if base_config.ground_truth_path is None:
        raise RuntimeError("subset generation requires entity-resolution ground truth")

    output_root = repo_root / spec.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    selected_entities = _select_entities(
        repo_root / base_config.ground_truth_path,
        entity_count=spec.entity_count,
        seed=spec.random_seed,
        required_entity_ids=spec.required_entity_ids,
    )
    selected_entity_set = set(selected_entities)
    selected_specs = _selected_specs(repo_root / base_config.ground_truth_path, selected_entity_set)
    selected_records = {spec_id for specs in selected_specs.values() for spec_id in specs}

    specs_root = output_root / "specs"
    if specs_root.exists():
        _remove_tree(specs_root)
    sources = _copy_selected_records(base_config, repo_root, specs_root, selected_records)

    ground_truth_path = output_root / "ground_truth" / "entity_resolution_gt.csv"
    mapping_gold_path = output_root / "ground_truth" / "schema_matching_gt.csv"
    fusion_gold_path = output_root / "ground_truth" / "fusion_gold.jsonl"
    curated_fusion_gold_path = output_root / "ground_truth" / "fusion_curated_gold.jsonl"
    selected_entities_path = output_root / "selected_entities.json"

    _write_ground_truth(ground_truth_path, selected_specs)
    _write_mapping_gold(
        repo_root / base_config.mapping_gold_path if base_config.mapping_gold_path else None,
        mapping_gold_path,
        {source.source_id for source in sources},
    )
    _write_fusion_gold(
        repo_root / "data" / "ground_truth" / "monitor_fusion_gold.jsonl",
        fusion_gold_path,
        selected_entity_set,
    )
    _write_fusion_gold(
        repo_root / "data" / "ground_truth" / "monitor_fusion_curated_gold.jsonl",
        curated_fusion_gold_path,
        selected_entity_set,
    )
    selected_entities_path.write_text(
        json.dumps(selected_entities, indent=2), encoding="utf-8"
    )

    dataset = DatasetConfig(
        dataset_id=spec.subset_id,
        benchmark=base_config.benchmark,
        vertical=base_config.vertical,
        version=f"{base_config.version}_subset_{spec.entity_count}_seed_{spec.random_seed}",
        description=(
            f"Entity-balanced {spec.entity_count}-entity subset of {base_config.dataset_id} "
            "for M4 live LLM comparison."
        ),
        sources=sources,
        ground_truth_path=repo_relative(ground_truth_path, repo_root),
        mapping_gold_path=repo_relative(mapping_gold_path, repo_root),
    )
    dataset_config_path = output_root / "dataset_config.json"
    dataset_config_path.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
    manifest = ingest_dataset(dataset, repo_root)

    subset_hash = sha256_text(
        canonical_json(
            {
                "spec": spec.model_dump(),
                "entities": selected_entities,
                "records": sorted(selected_records),
                "dataset_config": dataset.model_dump(),
            }
        )
    )
    metadata = MaterializedSubset(
        subset_id=spec.subset_id,
        dataset_config_path=repo_relative(dataset_config_path, repo_root),
        dataset_id=dataset.dataset_id,
        selected_entity_count=len(selected_entities),
        selected_record_count=manifest.total_record_count,
        selected_source_count=len(sources),
        subset_hash=subset_hash,
        output_root=repo_relative(output_root, repo_root),
        selected_entities_path=repo_relative(selected_entities_path, repo_root),
    )
    (output_root / "subset_manifest.json").write_text(
        metadata.model_dump_json(indent=2), encoding="utf-8"
    )
    return metadata


def _select_entities(
    path: Path, *, entity_count: int, seed: int, required_entity_ids: list[str] | None = None
) -> list[str]:
    clusters = _read_clusters(path)
    required = list(dict.fromkeys(required_entity_ids or []))
    missing = [entity_id for entity_id in required if entity_id not in clusters]
    if missing:
        raise RuntimeError(
            f"required subset entities not found in {path}: {', '.join(sorted(missing))}"
        )
    if len(required) > entity_count:
        raise RuntimeError(
            f"required {len(required)} subset entities but entity_count is {entity_count}"
        )
    scored = []
    for entity_id, specs in clusters.items():
        sources = {spec_id.split("//", 1)[0] for spec_id in specs if "//" in spec_id}
        tie_break = sha256_text(f"{seed}|{entity_id}")[:16]
        scored.append((-len(sources), -len(specs), tie_break, entity_id))
    scored.sort()
    selected_set = set(required)
    for *_prefix, entity_id in scored:
        if len(selected_set) >= entity_count:
            break
        selected_set.add(entity_id)
    selected = sorted(selected_set)
    if len(selected) != entity_count:
        raise RuntimeError(
            f"requested {entity_count} entities but only selected {len(selected)} from {path}"
        )
    return selected


def _read_clusters(path: Path) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            entity_id = row.get("entity_id")
            spec_id = row.get("spec_id") or row.get("record_uid")
            if entity_id and spec_id:
                clusters[entity_id].append(spec_id)
    return dict(clusters)


def _selected_specs(path: Path, selected_entities: set[str]) -> dict[str, list[str]]:
    clusters = _read_clusters(path)
    return {
        entity_id: sorted(specs)
        for entity_id, specs in sorted(clusters.items())
        if entity_id in selected_entities
    }


def _copy_selected_records(
    base_config: DatasetConfig,
    repo_root: Path,
    specs_root: Path,
    selected_records: set[str],
) -> list[SourceInput]:
    selected_by_source: dict[str, set[str]] = defaultdict(set)
    for spec_id in selected_records:
        if "//" not in spec_id:
            continue
        source_id, record_id = spec_id.split("//", 1)
        selected_by_source[source_id].add(record_id)

    sources: list[SourceInput] = []
    source_by_id = {source.source_id: source for source in base_config.sources}
    for source_id in sorted(selected_by_source):
        source = source_by_id.get(source_id)
        if source is None:
            continue
        destination = specs_root / source_id
        destination.mkdir(parents=True, exist_ok=True)
        input_root = repo_root / source.path
        copied = 0
        for record_id in sorted(selected_by_source[source_id]):
            source_file = input_root / f"{record_id}.json"
            if not source_file.exists():
                continue
            target_file = destination / f"{record_id}.json"
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, target_file)
            copied += 1
        if copied:
            sources.append(
                SourceInput(
                    source_id=source.source_id,
                    name=source.name,
                    source_type=source.source_type,
                    origin=source.origin,
                    license=source.license,
                    retrieval_date=source.retrieval_date,
                    path=repo_relative(destination, repo_root),
                    format="alaska_json_dir",
                    id_field=None,
                )
            )
    return sources


def _remove_tree(path: Path) -> None:
    def clear_readonly_and_retry(function: Any, target: str, _error: BaseException) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    shutil.rmtree(path, onexc=clear_readonly_and_retry)


def _write_ground_truth(path: Path, selected_specs: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["entity_id", "spec_id"])
        writer.writeheader()
        for entity_id, specs in selected_specs.items():
            for spec_id in specs:
                writer.writerow({"entity_id": entity_id, "spec_id": spec_id})


def _write_mapping_gold(source: Path | None, destination: Path, selected_sources: set[str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source is None or not source.exists():
        destination.write_text("source_attribute_id,target_attribute_name\n", encoding="utf-8")
        return
    with source.open(encoding="utf-8", newline="") as src, destination.open(
        "w", encoding="utf-8", newline=""
    ) as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            source_attribute_id = str(row.get("source_attribute_id", ""))
            source_id = source_attribute_id.split("//", 1)[0]
            if source_id in selected_sources:
                writer.writerow(row)


def _write_fusion_gold(source: Path, destination: Path, selected_entities: set[str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        destination.write_text("", encoding="utf-8")
        return
    rows: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("entity_id") in selected_entities:
            rows.append(row)
    destination.write_text(
        "\n".join(canonical_json(row) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
