from __future__ import annotations

import csv
import json
import math
import re
import subprocess
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from random import Random
from statistics import mean, median
from typing import Any, Literal, TypedDict

import polars as pl
from pydantic import BaseModel
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from mosaic.checkpoints import RunCheckpoint, checkpoint_hash
from mosaic.ingestion import ingest_dataset
from mosaic.m1_models import (
    DatasetConfig,
    MediatedSchema,
    load_dataset_config,
    load_mediated_schema,
)
from mosaic.m1_utils import canonical_json, repo_relative, sha256_text
from mosaic.m2_models import (
    AcceptedSchemaMapping,
    AttributeClaim,
    BaselinePipelineConfig,
    CandidatePair,
    EntityCluster,
    FusedValue,
    IntegratedEntity,
    MappingCandidate,
    PairPrediction,
    PipelineRunResult,
)
from mosaic.profiling import profile_dataset

StageName = Literal[
    "schema",
    "normalize",
    "block",
    "match",
    "cluster",
    "claims",
    "fuse",
    "evaluate",
    "export",
]


class GroundTruthLookup(TypedDict):
    record_to_entity: dict[str, str]
    entity_to_records: dict[str, set[str]]

CORE_ATTRIBUTES = {
    "title",
    "brand",
    "model_number",
    "category",
    "description",
    "price",
    "currency",
    "specifications",
}
MODEL_PATTERN = re.compile(r"\b[A-Z]{0,6}\d{2,6}[A-Z0-9-]*\b", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
NUMBER_UNIT_PATTERN = re.compile(
    r"(?P<number>-?\d+(?:[.,]\d+)?)\s*(?P<unit>\"|inch|inches|in|hz|ms|mp|megapixels|gb|tb|mm|cm|kg|g|w|cd/m2|cd/m²|nits)?",
    re.IGNORECASE,
)
PRICE_PATTERN = re.compile(r"(?P<currency>[$€£]|usd|eur|gbp)?\s*(?P<amount>\d+(?:[.,]\d+)?)", re.I)

ATTRIBUTE_SYNONYMS: dict[str, set[str]] = {
    "title": {"page title", "product title", "product name", "name", "title"},
    "brand": {"brand", "manufacturer", "maker", "vendor"},
    "model_number": {"model", "model number", "model_id", "mpn", "part", "part number"},
    "category": {"category", "department", "product type", "type"},
    "description": {"description", "short description", "features", "feature"},
    "price": {"price", "sale price", "amount", "cost"},
    "currency": {"currency"},
    "screen_size_diagonal": {"screen size", "display size", "diagonal size"},
    "supported_resolution": {"recommended resolution", "resolution", "native resolution"},
    "screen_brightness": {"brightness"},
    "response_time": {"response time"},
    "contrast_ratio_static": {"contrast ratio"},
    "supported_aspect_ratio": {"aspect ratio"},
    "has_speakers": {"builtin speakers", "speakers"},
    "has_dvi_port": {"dvi"},
    "has_hdmi_port": {"hdmi"},
    "has_vga_port": {"vga"},
    "has_displayport": {"displayport"},
    "screen_type": {"ips", "led", "panel type"},
    "color": {"color", "colour", "body colour"},
    "monitor_weight": {"weight", "weight approximate"},
    "monitor_weight_with_stand": {"weight with stand", "weight with stand approximate"},
    "monitor_width_with_stand": {"width with stand", "dimensions w x d x h with stand"},
    "monitor_height_with_stand": {"height with stand"},
    "monitor_depth_with_stand": {"depth with stand"},
    "number_of_colors": {"display colors", "number of colours", "colour support"},
    "vertical_refresh_rate_range": {
        "refresh rate",
        "standard refresh rate",
        "vertical scan range",
    },
    "power_consumption_standy": {
        "power consumption standby",
        "power consumption stand-by",
        "standby power consumption",
    },
    "working_humidity": {"operating relative humidity", "operating relative humidity hh"},
    "working_temperature_range": {"operating temperature", "temperature operating"},
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "monitor",
    "camera",
    "digital",
    "body",
    "kit",
    "pcpartpicker",
    "canada",
}


def run_baseline_pipeline(
    config: BaselinePipelineConfig,
    repo_root: Path,
    *,
    stop_after: StageName = "export",
    resume_run_id: str | None = None,
) -> PipelineRunResult:
    dataset_config = load_dataset_config(repo_root / config.dataset_config)
    run_id = resume_run_id or _new_run_id(config.pipeline_id)
    run_dir = repo_root / config.artifact_root / run_id
    _stage_dir(run_dir, "logs")
    _stage_dir(run_dir, "metrics")
    checkpoint = RunCheckpoint(
        repo_root=repo_root,
        run_dir=run_dir,
        run_id=run_id,
        config_hash=f"cfg_{sha256_text(config.model_dump_json())[:12]}",
        dataset_hash=checkpoint_hash(dataset_config.model_dump()),
        resume=resume_run_id is not None,
    )

    artifacts: dict[str, str] = {
        key: str(repo_root / value) for key, value in checkpoint.artifacts.items()
    }
    metrics: dict[str, str] = {
        key: str(repo_root / value) for key, value in checkpoint.metrics.items()
    }

    records_path = _ensure_m1_artifacts(dataset_config, repo_root)
    schema = load_mediated_schema(repo_root / config.schema_path)
    profile_path = (
        repo_root
        / "artifacts"
        / "tables"
        / f"{dataset_config.dataset_id}_source_attributes.parquet"
    )

    if not checkpoint.is_stage_complete("schema", required=["accepted_schema_mappings"]):
        checkpoint.start_stage("schema")
        schema_outputs = propose_schema_mappings(
            config=config,
            dataset_config=dataset_config,
            schema=schema,
            repo_root=repo_root,
            profile_path=profile_path,
            run_dir=run_dir,
        )
        artifacts.update(schema_outputs["artifacts"])
        metrics.update(schema_outputs["metrics"])
        checkpoint.complete_stage("schema", artifacts=artifacts, metrics=metrics)
    if stop_after == "schema":
        return _finish_result(
            run_id, run_dir, stop_after, artifacts, metrics, config, repo_root, checkpoint
        )

    if not checkpoint.is_stage_complete("normalize", required=["normalized_records"]):
        checkpoint.start_stage("normalize")
        normalize_outputs = normalize_records(
            config=config,
            dataset_config=dataset_config,
            schema=schema,
            repo_root=repo_root,
            records_path=records_path,
            accepted_mappings_path=Path(artifacts["accepted_schema_mappings"]),
            run_dir=run_dir,
        )
        artifacts.update(normalize_outputs["artifacts"])
        metrics.update(normalize_outputs["metrics"])
        checkpoint.complete_stage("normalize", artifacts=artifacts, metrics=metrics)
    if stop_after == "normalize":
        return _finish_result(
            run_id, run_dir, stop_after, artifacts, metrics, config, repo_root, checkpoint
        )

    if not checkpoint.is_stage_complete("block", required=["candidate_pairs"]):
        checkpoint.start_stage("block")
        blocking_outputs = generate_candidate_pairs(
            config=config,
            dataset_config=dataset_config,
            repo_root=repo_root,
            records_path=records_path,
            normalized_records_path=Path(artifacts["normalized_records"]),
            run_dir=run_dir,
        )
        artifacts.update(blocking_outputs["artifacts"])
        metrics.update(blocking_outputs["metrics"])
        checkpoint.complete_stage("block", artifacts=artifacts, metrics=metrics)
    if stop_after == "block":
        return _finish_result(
            run_id, run_dir, stop_after, artifacts, metrics, config, repo_root, checkpoint
        )

    if not checkpoint.is_stage_complete("match", required=["pair_predictions"]):
        checkpoint.start_stage("match")
        match_outputs = match_candidate_pairs(
            config=config,
            repo_root=repo_root,
            normalized_records_path=Path(artifacts["normalized_records"]),
            candidate_pairs_path=Path(artifacts["candidate_pairs"]),
            run_dir=run_dir,
        )
        artifacts.update(match_outputs["artifacts"])
        metrics.update(match_outputs["metrics"])
        checkpoint.complete_stage("match", artifacts=artifacts, metrics=metrics)
    if stop_after == "match":
        return _finish_result(
            run_id, run_dir, stop_after, artifacts, metrics, config, repo_root, checkpoint
        )

    if not checkpoint.is_stage_complete("cluster", required=["cluster_memberships"]):
        checkpoint.start_stage("cluster")
        cluster_outputs = cluster_records(
            config=config,
            dataset_config=dataset_config,
            repo_root=repo_root,
            normalized_records_path=Path(artifacts["normalized_records"]),
            pair_predictions_path=Path(artifacts["pair_predictions"]),
            run_dir=run_dir,
        )
        artifacts.update(cluster_outputs["artifacts"])
        metrics.update(cluster_outputs["metrics"])
        checkpoint.complete_stage("cluster", artifacts=artifacts, metrics=metrics)
    if stop_after == "cluster":
        return _finish_result(
            run_id, run_dir, stop_after, artifacts, metrics, config, repo_root, checkpoint
        )

    if not checkpoint.is_stage_complete("claims", required=["attribute_claims"]):
        checkpoint.start_stage("claims")
        claim_outputs = extract_claims(
            repo_root=repo_root,
            normalized_values_path=Path(artifacts["normalized_values"]),
            memberships_path=Path(artifacts["cluster_memberships"]),
            run_dir=run_dir,
        )
        artifacts.update(claim_outputs["artifacts"])
        metrics.update(claim_outputs["metrics"])
        checkpoint.complete_stage("claims", artifacts=artifacts, metrics=metrics)
    if stop_after == "claims":
        return _finish_result(
            run_id, run_dir, stop_after, artifacts, metrics, config, repo_root, checkpoint
        )

    if not checkpoint.is_stage_complete("fuse", required=["integrated_entities_jsonl"]):
        checkpoint.start_stage("fuse")
        fuse_outputs = fuse_claims(
            config=config,
            repo_root=repo_root,
            claims_path=Path(artifacts["attribute_claims"]),
            clusters_path=Path(artifacts["clusters"]),
            run_dir=run_dir,
        )
        artifacts.update(fuse_outputs["artifacts"])
        metrics.update(fuse_outputs["metrics"])
        checkpoint.complete_stage("fuse", artifacts=artifacts, metrics=metrics)
    if stop_after in {"fuse", "evaluate", "export"}:
        return _finish_result(
            run_id, run_dir, stop_after, artifacts, metrics, config, repo_root, checkpoint
        )

    return _finish_result(
        run_id, run_dir, stop_after, artifacts, metrics, config, repo_root, checkpoint
    )


def propose_schema_mappings(
    *,
    config: BaselinePipelineConfig,
    dataset_config: DatasetConfig,
    schema: MediatedSchema,
    repo_root: Path,
    profile_path: Path,
    run_dir: Path,
) -> dict[str, dict[str, str]]:
    rows = pl.read_parquet(profile_path).to_dicts()
    attributes = [attribute.name for attribute in schema.attributes]
    exact_target_by_key = {
        normalize_specification_key(attribute): attribute for attribute in attributes
    }
    candidate_rows: list[dict[str, Any]] = []
    accepted_rows: list[dict[str, Any]] = []

    for row in rows:
        source_attribute_id = str(row["source_attribute_id"])
        attribute_name = str(row["attribute_name"])
        scored = [
            _score_mapping(row, target, schema, config)
            for target in attributes
            if target != "specifications" or _is_specification_candidate(row)
        ]
        exact_target = exact_target_by_key.get(normalize_specification_key(attribute_name))
        if exact_target is not None:
            scored.append(_exact_name_mapping_score(row, exact_target))
        scored.sort(key=lambda item: item["score_total"], reverse=True)
        for rank, candidate in enumerate(scored[:8], start=1):
            candidate_rows.append(
                {
                    "source_attribute_id": source_attribute_id,
                    "source_id": str(row["source_id"]),
                    "attribute_name": attribute_name,
                    "target_attribute_name": candidate["target_attribute_name"],
                    "rank": rank,
                    **candidate,
                }
            )

        best = scored[0] if scored else _unmapped_score()
        second_score = scored[1]["score_total"] if len(scored) > 1 else 0.0
        margin = float(best["score_total"]) - float(second_score)
        accepted = (
            float(best["score_total"]) >= config.schema_stage.accept_threshold
            and margin >= config.schema_stage.accept_margin
        )
        target = str(best["target_attribute_name"]) if accepted else "UNMAPPED"
        accepted_rows.append(
            {
                "source_attribute_id": source_attribute_id,
                "source_id": str(row["source_id"]),
                "attribute_name": attribute_name,
                "target_attribute_name": target,
                "decision": "accepted" if accepted else "unmapped",
                "score_total": float(best["score_total"]) if scored else 0.0,
                "score_margin": margin,
                "method": "deterministic_schema_v1",
            }
        )

    stage_dir = _stage_dir(run_dir, "schema")
    candidates_path = stage_dir / "mapping_candidates.parquet"
    accepted_path = stage_dir / "accepted_schema_mappings.parquet"
    _write_validated_parquet(candidates_path, candidate_rows, MappingCandidate)
    _write_validated_parquet(accepted_path, accepted_rows, AcceptedSchemaMapping)
    metrics_path = stage_dir / "schema_metrics.json"
    error_paths = _write_schema_error_artifacts(
        stage_dir,
        accepted_rows,
        candidate_rows,
        dataset_config.mapping_gold_path,
        repo_root,
    )
    metrics_payload = _schema_metrics(accepted_rows, dataset_config.mapping_gold_path, repo_root)
    _write_json(metrics_path, metrics_payload)

    return {
        "artifacts": {
            "mapping_candidates": str(candidates_path),
            "accepted_schema_mappings": str(accepted_path),
            **{name: str(path) for name, path in error_paths.items()},
        },
        "metrics": {"schema_metrics": str(metrics_path)},
    }


def normalize_records(
    *,
    config: BaselinePipelineConfig,
    dataset_config: DatasetConfig,
    schema: MediatedSchema,
    repo_root: Path,
    records_path: Path,
    accepted_mappings_path: Path,
    run_dir: Path,
) -> dict[str, dict[str, str]]:
    del config, dataset_config
    records = pl.read_parquet(records_path).to_dicts()
    mapping_rows = pl.read_parquet(accepted_mappings_path).to_dicts()
    mappings = {
        str(row["source_attribute_id"]): str(row["target_attribute_name"])
        for row in mapping_rows
        if str(row["decision"]) == "accepted"
    }
    schema_attributes = {attribute.name: attribute for attribute in schema.attributes}

    normalized_values: list[dict[str, Any]] = []
    normalized_records: list[dict[str, Any]] = []
    for record in records:
        record_uid = str(record["record_uid"])
        source_id = str(record["source_id"])
        payload = json.loads(str(record["raw_payload"]))
        normalized_payload: dict[str, Any] = {}
        specifications: dict[str, Any] = {}
        confidences: list[float] = []
        for attribute_name, raw in payload.items():
            if raw in (None, ""):
                continue
            source_attribute_id = f"{source_id}//{attribute_name}"
            target = mappings.get(source_attribute_id)
            if target is None:
                target = "specifications" if "specifications" in schema_attributes else "UNMAPPED"
            if target == "UNMAPPED":
                continue
            normalized = normalize_value(target, str(raw), attribute_name)
            confidences.append(normalized["confidence"])
            value_id = sha256_text(f"{record_uid}|{source_attribute_id}|{target}|{raw}")[:24]
            row = {
                "normalized_value_id": value_id,
                "record_uid": record_uid,
                "source_id": source_id,
                "source_record_id": str(record["source_record_id"]),
                "source_attribute_id": source_attribute_id,
                "source_attribute_name": str(attribute_name),
                "mediated_attribute_name": target,
                "raw_value": str(raw),
                "canonical_value": normalized["canonical_value"],
                "canonical_unit": normalized["canonical_unit"],
                "normalization_method": normalized["normalization_method"],
                "confidence": normalized["confidence"],
            }
            normalized_values.append(row)
            if target == "specifications":
                specifications[normalize_specification_key(attribute_name)] = {
                    "raw_value": str(raw),
                    "normalized_value": normalized["canonical_value"],
                    "unit": normalized["canonical_unit"],
                    "source_claim_ids": [value_id],
                }
            elif target not in normalized_payload:
                normalized_payload[target] = normalized["canonical_value"]
            elif target in {"title", "description"} and len(str(raw)) > len(
                str(normalized_payload[target])
            ):
                normalized_payload[target] = normalized["canonical_value"]
        if specifications:
            normalized_payload["specifications"] = specifications
        normalized_records.append(
            {
                "record_uid": record_uid,
                "source_id": source_id,
                "source_record_id": str(record["source_record_id"]),
                "normalized_payload": canonical_json(normalized_payload),
                "normalization_version": "deterministic_normalization_v1",
                "normalization_confidence": mean(confidences) if confidences else 0.0,
            }
        )

    stage_dir = _stage_dir(run_dir, "normalization")
    values_path = stage_dir / "normalized_values.parquet"
    records_out_path = stage_dir / "normalized_records.parquet"
    metrics_path = stage_dir / "normalization_metrics.json"
    _write_parquet(values_path, normalized_values)
    _write_parquet(records_out_path, normalized_records)
    _write_json(
        metrics_path,
        {
            "record_count": len(normalized_records),
            "normalized_value_count": len(normalized_values),
            "average_confidence": mean([row["confidence"] for row in normalized_values])
            if normalized_values
            else 0.0,
        },
    )
    return {
        "artifacts": {
            "normalized_records": str(records_out_path),
            "normalized_values": str(values_path),
        },
        "metrics": {"normalization_metrics": str(metrics_path)},
    }


def normalize_value(
    mediated_attribute_name: str,
    raw_value: str,
    source_attribute_name: str = "",
) -> dict[str, Any]:
    raw = raw_value.strip()
    target = mediated_attribute_name.lower()
    if target == "title":
        return _normalization_result(_collapse_space(raw), None, "title_text", 0.98)
    if target == "brand":
        return _normalization_result(_title_case_brand(raw), None, "brand_alias_case", 0.98)
    if target == "model_number":
        return _normalization_result(normalize_model_number(raw), None, "model_number", 0.95)
    if target == "category":
        return _normalization_result(_normalize_category(raw), None, "category_vocab", 0.9)
    if target == "description":
        return _normalization_result(_collapse_space(raw), None, "description_text", 0.95)
    if target == "price":
        price = normalize_price(raw)
        return _normalization_result(price["amount"], price["currency"], "price_decimal", 0.9)
    if target == "currency":
        return _normalization_result(normalize_currency(raw), None, "currency_code", 0.95)
    if _looks_boolean_attribute(target, source_attribute_name):
        return _normalization_result(_normalize_boolean(raw), None, "boolean", 0.9)
    measurement = normalize_measurement(raw, source_attribute_name or mediated_attribute_name)
    if measurement is not None:
        return _normalization_result(
            measurement["value"], measurement["unit"], measurement["method"], 0.88
        )
    return _normalization_result(_collapse_space(raw).lower(), None, "normalized_text", 0.8)


def normalize_model_number(raw_value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", raw_value).upper()


def normalize_currency(raw_value: str) -> str:
    value = raw_value.strip().lower()
    if "$" in value or "usd" in value:
        return "USD"
    if "€" in value or "eur" in value:
        return "EUR"
    if "£" in value or "gbp" in value:
        return "GBP"
    return value.upper()


def normalize_price(raw_value: str) -> dict[str, str | None]:
    match = PRICE_PATTERN.search(raw_value)
    if match is None:
        return {"amount": raw_value.strip(), "currency": None}
    amount = match.group("amount").replace(",", ".")
    currency_token = match.group("currency") or ""
    return {"amount": f"{float(amount):.2f}", "currency": normalize_currency(currency_token)}


def normalize_measurement(raw_value: str, attribute_name: str) -> dict[str, str] | None:
    text = raw_value.strip().lower().replace("″", '"')
    match = NUMBER_UNIT_PATTERN.search(text)
    if match is None:
        return None
    number = match.group("number").replace(",", ".")
    unit = _canonical_unit(match.group("unit"), attribute_name)
    if unit is None and not _measurement_like_attribute(attribute_name):
        return None
    try:
        value = float(number)
    except ValueError:
        return None
    if unit == "GB" and "tb" in text:
        value *= 1024
    rendered = f"{value:.4f}".rstrip("0").rstrip(".")
    return {"value": rendered, "unit": unit or "", "method": "measurement_parse"}


def normalize_specification_key(raw_value: str) -> str:
    return "_".join(token.lower() for token in TOKEN_PATTERN.findall(raw_value.replace("_", " ")))


def generate_candidate_pairs(
    *,
    config: BaselinePipelineConfig,
    dataset_config: DatasetConfig,
    repo_root: Path,
    records_path: Path,
    normalized_records_path: Path,
    run_dir: Path,
) -> dict[str, dict[str, str]]:
    start = time.perf_counter()
    normalized_rows = pl.read_parquet(normalized_records_path).to_dicts()
    records = _record_lookup(normalized_rows)
    ground_truth = _ground_truth_lookup(dataset_config.ground_truth_path, repo_root, records_path)
    split_by_record = _entity_safe_splits(
        records.keys(), ground_truth["record_to_entity"], config.random_seed
    )
    total_positive_pairs = _total_positive_pairs(ground_truth["entity_to_records"])

    blocks: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    title_token_counts = Counter(
        token
        for record in records.values()
        for token in _informative_tokens(record.get("title", ""))
    )
    for record_uid, record in records.items():
        for rule, key in _blocking_keys(record, title_token_counts, config):
            blocks[rule][key].add(record_uid)

    attempts = 0
    pair_rules: dict[tuple[str, str], set[str]] = defaultdict(set)
    skipped_oversized_blocks = 0
    for rule, keyed_records in blocks.items():
        for key, members in keyed_records.items():
            del key
            if len(members) < 2:
                continue
            if len(members) > config.blocking.max_block_size:
                skipped_oversized_blocks += 1
                continue
            for left, right in combinations(sorted(members), 2):
                attempts += 1
                pair = _pair_key(left, right)
                pair_rules[pair].add(rule)

    candidate_rows: list[dict[str, Any]] = []
    positive_retained = 0
    for index, ((left, right), rules) in enumerate(sorted(pair_rules.items()), start=1):
        left_entity = ground_truth["record_to_entity"].get(left)
        right_entity = ground_truth["record_to_entity"].get(right)
        label = _pair_label(left_entity, right_entity)
        if label == 1:
            positive_retained += 1
        candidate_rows.append(
            {
                "candidate_pair_id": f"pair_{index:08d}",
                "left_record_uid": left,
                "right_record_uid": right,
                "blocking_rules": json.dumps(sorted(rules)),
                "blocking_score": float(len(rules)),
                "ground_truth_label": label,
                "split": _pair_split(left, right, split_by_record),
            }
        )

    elapsed = time.perf_counter() - start
    pair_count = len(candidate_rows)
    record_count = len(records)
    all_pair_count = record_count * (record_count - 1) // 2
    metrics_payload = {
        "record_count": record_count,
        "candidate_pair_count": pair_count,
        "positive_pairs_retained": positive_retained,
        "total_positive_pairs": total_positive_pairs,
        "pair_completeness": positive_retained / total_positive_pairs
        if total_positive_pairs
        else 0.0,
        "reduction_ratio": 1 - (pair_count / all_pair_count if all_pair_count else 0.0),
        "candidates_per_record": pair_count / record_count if record_count else 0.0,
        "duplicate_candidate_rate": 1 - (pair_count / attempts if attempts else 1.0),
        "runtime_seconds": elapsed,
        "memory_bytes": None,
        "skipped_oversized_blocks": skipped_oversized_blocks,
    }

    stage_dir = _stage_dir(run_dir, "blocking")
    pairs_path = stage_dir / "candidate_pairs.parquet"
    metrics_path = stage_dir / "blocking_metrics.json"
    _write_validated_parquet(pairs_path, candidate_rows, CandidatePair)
    _write_json(metrics_path, metrics_payload)
    return {
        "artifacts": {"candidate_pairs": str(pairs_path)},
        "metrics": {"blocking_metrics": str(metrics_path)},
    }


def match_candidate_pairs(
    *,
    config: BaselinePipelineConfig,
    repo_root: Path,
    normalized_records_path: Path,
    candidate_pairs_path: Path,
    run_dir: Path,
) -> dict[str, dict[str, str]]:
    del repo_root
    records = _record_lookup(pl.read_parquet(normalized_records_path).to_dicts())
    pairs = pl.read_parquet(candidate_pairs_path).to_dicts()
    feature_rows: list[dict[str, Any]] = []
    feature_names = _feature_names()
    for pair in pairs:
        left = records[str(pair["left_record_uid"])]
        right = records[str(pair["right_record_uid"])]
        features = _pair_features(left, right, json.loads(str(pair["blocking_rules"])))
        feature_rows.append(
            {
                "candidate_pair_id": str(pair["candidate_pair_id"]),
                "left_record_uid": str(pair["left_record_uid"]),
                "right_record_uid": str(pair["right_record_uid"]),
                "split": str(pair["split"]),
                "ground_truth_label": pair.get("ground_truth_label"),
                **features,
            }
        )

    model = None
    model_status = "trained"
    train_rows = [
        row
        for row in feature_rows
        if row["split"] == "train" and row["ground_truth_label"] is not None
    ]
    labels = [int(row["ground_truth_label"]) for row in train_rows]
    if len(set(labels)) >= 2 and len(train_rows) >= 4:
        x_train = [[float(row[name]) for name in feature_names] for row in train_rows]
        model = make_pipeline(StandardScaler(), LogisticRegression(random_state=config.random_seed))
        model.fit(x_train, labels)
    else:
        model_status = "rule_fallback_insufficient_training_labels"

    prediction_rows: list[dict[str, Any]] = []
    probabilities: dict[str, float] = {}
    for row in feature_rows:
        rule_score = _rule_match_score(row)
        if model is not None:
            probability = float(
                model.predict_proba([[float(row[name]) for name in feature_names]])[0][1]
            )
            probability = (probability * 0.8) + (rule_score * 0.2)
        else:
            probability = rule_score
        probabilities[str(row["candidate_pair_id"])] = probability

    threshold = _calibrate_threshold(feature_rows, probabilities, config)
    for row in feature_rows:
        probability = probabilities[str(row["candidate_pair_id"])]
        rule_score = _rule_match_score(row)
        prediction_rows.append(
            {
                "candidate_pair_id": row["candidate_pair_id"],
                "left_record_uid": row["left_record_uid"],
                "right_record_uid": row["right_record_uid"],
                "split": row["split"],
                "ground_truth_label": row["ground_truth_label"],
                "rule_score": rule_score,
                "rule_prediction": int(rule_score >= 0.5),
                "match_probability": probability,
                "match_prediction": int(probability >= threshold),
                "threshold": threshold,
                "model_status": model_status,
            }
        )

    stage_dir = _stage_dir(run_dir, "matching")
    features_path = stage_dir / "pair_features.parquet"
    predictions_path = stage_dir / "pair_predictions.parquet"
    metrics_path = stage_dir / "linkage_metrics.json"
    _write_parquet(features_path, feature_rows)
    _write_validated_parquet(predictions_path, prediction_rows, PairPrediction)
    _write_json(
        metrics_path,
        {
            "model_status": model_status,
            "calibrated_threshold": threshold,
            "metrics_by_split": _classification_metrics(prediction_rows),
        },
    )
    return {
        "artifacts": {
            "pair_features": str(features_path),
            "pair_predictions": str(predictions_path),
        },
        "metrics": {"linkage_metrics": str(metrics_path)},
    }


def cluster_records(
    *,
    config: BaselinePipelineConfig,
    dataset_config: DatasetConfig,
    repo_root: Path,
    normalized_records_path: Path,
    pair_predictions_path: Path,
    run_dir: Path,
) -> dict[str, dict[str, str]]:
    normalized_rows = pl.read_parquet(normalized_records_path).to_dicts()
    records = _record_lookup(normalized_rows)
    predictions = pl.read_parquet(pair_predictions_path).to_dicts()
    comparison_edges = [
        row
        for row in predictions
        if int(row["match_prediction"]) == 1
        and float(row["match_probability"]) >= config.clustering.min_match_probability
    ]
    agglomerative_edges = [
        row
        for row in comparison_edges
        if float(row["match_probability"]) >= config.clustering.cluster_min_match_probability
    ]

    connected_clusters = _connected_components(records.keys(), comparison_edges)
    parent = {record_uid: record_uid for record_uid in records}
    members_by_root = {record_uid: {record_uid} for record_uid in records}
    merge_log: list[dict[str, Any]] = []
    for row in sorted(
        agglomerative_edges, key=lambda item: float(item["match_probability"]), reverse=True
    ):
        left = str(row["left_record_uid"])
        right = str(row["right_record_uid"])
        left_root = _find(parent, left)
        right_root = _find(parent, right)
        if left_root == right_root:
            continue
        left_members = members_by_root[left_root]
        right_members = members_by_root[right_root]
        compatible, reason = _clusters_compatible(left_members, right_members, records, config)
        merge_log.append(
            {
                "left_record_uid": left,
                "right_record_uid": right,
                "left_cluster_root": left_root,
                "right_cluster_root": right_root,
                "match_probability": float(row["match_probability"]),
                "decision": "accepted" if compatible else "rejected",
                "reason": reason,
            }
        )
        if compatible:
            if len(left_members) < len(right_members):
                left_root, right_root = right_root, left_root
                left_members, right_members = right_members, left_members
            parent[right_root] = left_root
            left_members.update(right_members)
            del members_by_root[right_root]

    clusters = _clusters_from_parent(parent)
    ground_truth = _ground_truth_lookup(dataset_config.ground_truth_path, repo_root, None)
    record_to_entity = ground_truth["record_to_entity"]
    cluster_rows, membership_rows = _cluster_artifact_rows(
        clusters, records, record_to_truth_entity=record_to_entity
    )
    cc_rows, _ = _cluster_artifact_rows(
        connected_clusters, records, prefix="cc", record_to_truth_entity=record_to_entity
    )
    metrics_payload = {
        "agglomerative": _cluster_pair_metrics(clusters, record_to_entity),
        "connected_components": _cluster_pair_metrics(
            connected_clusters, record_to_entity
        ),
        "cluster_count": len(clusters),
        "connected_components_cluster_count": len(connected_clusters),
        "accepted_merges": sum(1 for row in merge_log if row["decision"] == "accepted"),
        "rejected_merges": sum(1 for row in merge_log if row["decision"] == "rejected"),
        "cluster_min_match_probability": config.clustering.cluster_min_match_probability,
    }

    stage_dir = _stage_dir(run_dir, "clustering")
    clusters_path = stage_dir / "clusters.parquet"
    memberships_path = stage_dir / "cluster_memberships.parquet"
    cc_path = stage_dir / "connected_components_clusters.parquet"
    merge_log_path = stage_dir / "cluster_merge_log.parquet"
    evidence_path = stage_dir / "cluster_evidence_summary.parquet"
    error_paths = _write_cluster_error_artifacts(
        stage_dir=stage_dir,
        clusters=clusters,
        records=records,
        record_to_entity=record_to_entity,
        merge_log=merge_log,
    )
    metrics_path = stage_dir / "cluster_metrics.json"
    _write_validated_parquet(clusters_path, cluster_rows, EntityCluster)
    _write_parquet(memberships_path, membership_rows)
    _write_parquet(cc_path, cc_rows)
    _write_parquet(merge_log_path, merge_log)
    _write_parquet(evidence_path, _cluster_evidence_rows(clusters, records, record_to_entity))
    _write_json(metrics_path, metrics_payload)
    return {
        "artifacts": {
            "clusters": str(clusters_path),
            "cluster_memberships": str(memberships_path),
            "connected_components_clusters": str(cc_path),
            "cluster_merge_log": str(merge_log_path),
            "cluster_evidence_summary": str(evidence_path),
            **{name: str(path) for name, path in error_paths.items()},
        },
        "metrics": {"cluster_metrics": str(metrics_path)},
    }


def extract_claims(
    *,
    repo_root: Path,
    normalized_values_path: Path,
    memberships_path: Path,
    run_dir: Path,
) -> dict[str, dict[str, str]]:
    del repo_root
    values = pl.read_parquet(normalized_values_path).to_dicts()
    memberships = pl.read_parquet(memberships_path).to_dicts()
    entity_by_record = {
        str(row["record_uid"]): str(row["entity_id"])
        for row in memberships
        if str(row["cluster_method"]) == "constraint_agglomerative"
    }
    claim_rows: list[dict[str, Any]] = []
    for value in values:
        record_uid = str(value["record_uid"])
        entity_id = entity_by_record.get(record_uid)
        if entity_id is None:
            continue
        claim_seed = (
            f"{entity_id}|{record_uid}|{value['source_attribute_id']}|"
            f"{value['mediated_attribute_name']}|{value['raw_value']}"
        )
        claim_rows.append(
            {
                "claim_id": f"claim_{sha256_text(claim_seed)[:20]}",
                "entity_id": entity_id,
                "record_uid": record_uid,
                "source_id": str(value["source_id"]),
                "source_attribute_id": str(value["source_attribute_id"]),
                "mediated_attribute_name": str(value["mediated_attribute_name"]),
                "raw_value": str(value["raw_value"]),
                "normalized_value": str(value["canonical_value"]),
                "unit": value.get("canonical_unit"),
                "extraction_confidence": float(value["confidence"]),
            }
        )

    stage_dir = _stage_dir(run_dir, "claims")
    claims_path = stage_dir / "attribute_claims.parquet"
    metrics_path = stage_dir / "claim_metrics.json"
    _write_validated_parquet(claims_path, claim_rows, AttributeClaim)
    _write_json(
        metrics_path,
        {
            "claim_count": len(claim_rows),
            "record_count_with_claims": len({row["record_uid"] for row in claim_rows}),
            "entity_count_with_claims": len({row["entity_id"] for row in claim_rows}),
        },
    )
    return {
        "artifacts": {"attribute_claims": str(claims_path)},
        "metrics": {"claim_metrics": str(metrics_path)},
    }


def fuse_claims(
    *,
    config: BaselinePipelineConfig,
    repo_root: Path,
    claims_path: Path,
    clusters_path: Path,
    run_dir: Path,
) -> dict[str, dict[str, str]]:
    claims = pl.read_parquet(claims_path).to_dicts()
    clusters = pl.read_parquet(clusters_path).to_dicts()
    claims_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        claims_by_key[(str(claim["entity_id"]), str(claim["mediated_attribute_name"]))].append(
            claim
        )

    fused_rows: list[dict[str, Any]] = []
    for (entity_id, attribute), group in sorted(claims_by_key.items()):
        fused = _fuse_group(attribute, group, config)
        fused_rows.append(
            {
                "fused_value_id": f"fused_{sha256_text(entity_id + attribute)[:20]}",
                "entity_id": entity_id,
                "mediated_attribute_name": attribute,
                "selected_value": fused["selected_value"],
                "selected_unit": fused["selected_unit"],
                "fusion_method": fused["fusion_method"],
                "confidence": fused["confidence"],
                "supporting_claim_ids": json.dumps(fused["supporting_claim_ids"]),
                "contradicting_claim_ids": json.dumps(fused["contradicting_claim_ids"]),
                "alternative_values": json.dumps(fused["alternative_values"]),
                "llm_used": False,
                "abstained": False,
            }
        )

    integrated_rows = _integrated_entities(clusters, fused_rows)
    stage_dir = _stage_dir(run_dir, "fusion")
    fused_path = stage_dir / "fused_values.parquet"
    entities_path = stage_dir / "integrated_entities.parquet"
    export_path = stage_dir / "integrated_entities.jsonl"
    metrics_path = stage_dir / "fusion_metrics.json"
    error_path = stage_dir / "baseline_error_candidates.parquet"
    curated_error_path = stage_dir / "fusion_curated_errors.parquet"
    unsupported_path = stage_dir / "fusion_unsupported_values.parquet"
    high_conflict_path = stage_dir / "fusion_high_conflict_attributes.parquet"
    _write_validated_parquet(fused_path, fused_rows, FusedValue)
    _write_validated_parquet(entities_path, integrated_rows, IntegratedEntity)
    export_text = "\n".join(canonical_json(row) for row in integrated_rows)
    export_path.write_text(export_text + ("\n" if integrated_rows else ""), encoding="utf-8")
    fusion_metrics = _fusion_metrics(
        fused_rows,
        repo_root / config.fusion.bootstrap_fusion_gold_path
        if config.fusion.bootstrap_fusion_gold_path is not None
        else None,
        repo_root / config.fusion.curated_fusion_gold_path
        if config.fusion.curated_fusion_gold_path is not None
        else None,
        clusters,
    )
    _write_json(metrics_path, fusion_metrics)
    _write_parquet(error_path, _baseline_error_candidates(fused_rows))
    _write_parquet(curated_error_path, _fusion_gold_errors(fused_rows, clusters, fusion_metrics))
    _write_parquet(unsupported_path, _unsupported_fused_values(fused_rows))
    _write_parquet(high_conflict_path, _high_conflict_fused_values(fused_rows))
    return {
        "artifacts": {
            "fused_values": str(fused_path),
            "integrated_entities": str(entities_path),
            "integrated_entities_jsonl": str(export_path),
            "baseline_error_candidates": str(error_path),
            "fusion_curated_errors": str(curated_error_path),
            "fusion_unsupported_values": str(unsupported_path),
            "fusion_high_conflict_attributes": str(high_conflict_path),
        },
        "metrics": {"fusion_metrics": str(metrics_path)},
    }


def _ensure_m1_artifacts(dataset_config: DatasetConfig, repo_root: Path) -> Path:
    records_path = (
        repo_root
        / "data"
        / "interim"
        / "m1"
        / dataset_config.dataset_id
        / "source_records.parquet"
    )
    if not records_path.exists():
        ingest_dataset(dataset_config, repo_root)
    profile_path = (
        repo_root
        / "artifacts"
        / "tables"
        / f"{dataset_config.dataset_id}_source_attributes.parquet"
    )
    if not profile_path.exists():
        profile_dataset(
            dataset_config,
            repo_root,
            evidence_level="fixture" if dataset_config.benchmark == "fixture" else "local_profile",
        )
    return records_path


def _score_mapping(
    row: dict[str, Any],
    target: str,
    schema: MediatedSchema,
    config: BaselinePipelineConfig,
) -> dict[str, Any]:
    source_name = str(row["attribute_name"])
    target_tokens = _tokens(target)
    source_tokens = _tokens(source_name)
    synonym_names = ATTRIBUTE_SYNONYMS.get(target, set())
    name_score = max(
        _jaccard(source_tokens, target_tokens),
        max((_name_similarity(source_name, synonym) for synonym in synonym_names), default=0.0),
    )
    if normalize_specification_key(source_name) == normalize_specification_key(target):
        name_score = 1.0
    type_score = _type_score(str(row["inferred_type"]), target, schema)
    value_score = _value_score(row, target)
    context_score = _context_score(row, target)
    total = (
        config.schema_stage.name_weight * name_score
        + config.schema_stage.type_weight * type_score
        + config.schema_stage.value_weight * value_score
        + config.schema_stage.context_weight * context_score
    )
    return {
        "target_attribute_name": target,
        "score_name": round(name_score, 6),
        "score_type": round(type_score, 6),
        "score_value": round(value_score, 6),
        "score_context": round(context_score, 6),
        "score_total": round(total, 6),
        "evidence": json.dumps(
            {
                "source_attribute": source_name,
                "semantic_roles": row.get("semantic_role_suggestions"),
                "unit_patterns": row.get("unit_patterns"),
            }
        ),
    }


def _exact_name_mapping_score(row: dict[str, Any], target: str) -> dict[str, Any]:
    return {
        "target_attribute_name": target,
        "score_name": 1.0,
        "score_type": 1.0,
        "score_value": 1.0,
        "score_context": 1.0,
        "score_total": 1.0,
        "evidence": json.dumps(
            {
                "source_attribute": str(row["attribute_name"]),
                "match_type": "exact_normalized_attribute_name",
            }
        ),
    }


def _unmapped_score() -> dict[str, Any]:
    return {
        "target_attribute_name": "UNMAPPED",
        "score_name": 0.0,
        "score_type": 0.0,
        "score_value": 0.0,
        "score_context": 0.0,
        "score_total": 0.0,
        "evidence": "{}",
    }


def _schema_metrics(
    accepted_rows: list[dict[str, Any]], mapping_gold_path: str | None, repo_root: Path
) -> dict[str, Any]:
    if mapping_gold_path is None or not (repo_root / mapping_gold_path).exists():
        return {"gold_available": False, "evaluated_mapping_count": 0}
    gold: dict[str, str] = {}
    with (repo_root / mapping_gold_path).open(encoding="utf-8") as file:
        for row in csv.DictReader(file):
            gold[str(row["source_attribute_id"])] = str(row["target_attribute_name"])
    predictions = {
        str(row["source_attribute_id"]): str(row["target_attribute_name"])
        for row in accepted_rows
        if str(row["decision"]) == "accepted"
    }
    all_metrics = _mapping_metrics_for_scope(predictions, gold, set(gold))
    core_keys = {key for key, value in gold.items() if value in CORE_ATTRIBUTES}
    detail_keys = set(gold) - core_keys
    return {
        "gold_available": True,
        "gold_mapping_count": len(gold),
        "accepted_mapping_count": len(predictions),
        **all_metrics,
        "core_schema_metrics": _mapping_metrics_for_scope(predictions, gold, core_keys),
        "monitor_detail_schema_metrics": _mapping_metrics_for_scope(
            predictions, gold, detail_keys
        ),
    }


def _mapping_metrics_for_scope(
    predictions: dict[str, str], gold: dict[str, str], scope_keys: set[str]
) -> dict[str, float | int]:
    scoped_predictions = {key: value for key, value in predictions.items() if key in scope_keys}
    true_positive = sum(1 for key, value in scoped_predictions.items() if gold.get(key) == value)
    false_positive = sum(
        1 for key, value in scoped_predictions.items() if gold.get(key) != value
    )
    false_negative = sum(1 for key in scope_keys if predictions.get(key) != gold[key])
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": _safe_div(true_positive, true_positive + false_positive),
        "recall": _safe_div(true_positive, true_positive + false_negative),
        "f1": _f1(true_positive, false_positive, false_negative),
    }


def _write_schema_error_artifacts(
    stage_dir: Path,
    accepted_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    mapping_gold_path: str | None,
    repo_root: Path,
) -> dict[str, Path]:
    paths = {
        "schema_false_positives": stage_dir / "schema_false_positives.parquet",
        "schema_false_negatives": stage_dir / "schema_false_negatives.parquet",
        "schema_ambiguous_candidates": stage_dir / "schema_ambiguous_candidates.parquet",
        "schema_unmapped_gold": stage_dir / "schema_unmapped_gold.parquet",
    }
    if mapping_gold_path is None or not (repo_root / mapping_gold_path).exists():
        for path in paths.values():
            _write_parquet(path, [])
        return paths
    gold = _read_mapping_gold(repo_root / mapping_gold_path)
    predictions = {str(row["source_attribute_id"]): row for row in accepted_rows}
    false_positives: list[dict[str, Any]] = []
    false_negatives: list[dict[str, Any]] = []
    unmapped_gold: list[dict[str, Any]] = []
    for source_attribute_id, predicted in sorted(predictions.items()):
        gold_target = gold.get(source_attribute_id)
        predicted_target = str(predicted["target_attribute_name"])
        if gold_target is not None and predicted_target != gold_target:
            false_positives.append(
                {
                    **predicted,
                    "gold_target_attribute_name": gold_target,
                    "error_type": "wrong_mapping_or_unmapped",
                }
            )
    for source_attribute_id, gold_target in sorted(gold.items()):
        maybe_predicted = predictions.get(source_attribute_id)
        predicted_target = (
            str(maybe_predicted["target_attribute_name"])
            if maybe_predicted is not None
            else "MISSING"
        )
        if predicted_target != gold_target:
            row = {
                "source_attribute_id": source_attribute_id,
                "gold_target_attribute_name": gold_target,
                "predicted_target_attribute_name": predicted_target,
            }
            false_negatives.append(row)
            if predicted_target == "UNMAPPED":
                unmapped_gold.append(row)

    by_attribute: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        if int(row["rank"]) <= 2:
            by_attribute[str(row["source_attribute_id"])].append(row)
    ambiguous = []
    for rows in by_attribute.values():
        rows.sort(key=lambda row: int(row["rank"]))
        score_gap = abs(float(rows[0]["score_total"]) - float(rows[1]["score_total"]))
        if len(rows) == 2 and score_gap <= 0.05:
            ambiguous.append(
                {
                    "source_attribute_id": rows[0]["source_attribute_id"],
                    "attribute_name": rows[0]["attribute_name"],
                    "top_target": rows[0]["target_attribute_name"],
                    "top_score": rows[0]["score_total"],
                    "second_target": rows[1]["target_attribute_name"],
                    "second_score": rows[1]["score_total"],
                    "score_gap": float(rows[0]["score_total"]) - float(rows[1]["score_total"]),
                }
            )

    _write_parquet(paths["schema_false_positives"], false_positives)
    _write_parquet(paths["schema_false_negatives"], false_negatives)
    _write_parquet(paths["schema_ambiguous_candidates"], ambiguous)
    _write_parquet(paths["schema_unmapped_gold"], unmapped_gold)
    return paths


def _read_mapping_gold(path: Path) -> dict[str, str]:
    gold: dict[str, str] = {}
    with path.open(encoding="utf-8") as file:
        for row in csv.DictReader(file):
            gold[str(row["source_attribute_id"])] = str(row["target_attribute_name"])
    return gold


def _record_lookup(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for row in rows:
        payload = json.loads(str(row["normalized_payload"]))
        flattened = {
            str(key): str(value)
            for key, value in payload.items()
            if key != "specifications" and value is not None
        }
        specs = payload.get("specifications", {})
        if isinstance(specs, dict):
            for key, value in specs.items():
                if isinstance(value, dict):
                    flattened[f"spec_{key}"] = str(value.get("normalized_value", ""))
        flattened["record_uid"] = str(row["record_uid"])
        flattened["source_id"] = str(row["source_id"])
        flattened["source_record_id"] = str(row["source_record_id"])
        records[str(row["record_uid"])] = flattened
    return records


def _ground_truth_lookup(
    ground_truth_path: str | None, repo_root: Path, records_path: Path | None
) -> GroundTruthLookup:
    uid_by_gt_reference: dict[str, str] = {}
    if records_path is not None and records_path.exists():
        for row in pl.read_parquet(records_path).to_dicts():
            uid = str(row["record_uid"])
            source_id = str(row["source_id"])
            source_record_id = str(row["source_record_id"])
            uid_by_gt_reference[f"{source_id}//{source_record_id}"] = uid
    record_to_entity: dict[str, str] = {}
    entity_to_records: dict[str, set[str]] = defaultdict(set)
    if ground_truth_path is None or not (repo_root / ground_truth_path).exists():
        return {"record_to_entity": record_to_entity, "entity_to_records": entity_to_records}
    with (repo_root / ground_truth_path).open(encoding="utf-8") as file:
        for row in csv.DictReader(file):
            entity_id = str(row.get("entity_id") or "")
            spec_id = str(row.get("spec_id") or row.get("record_uid") or "")
            if not entity_id or not spec_id:
                continue
            uid = uid_by_gt_reference.get(spec_id, spec_id.replace("//", ":"))
            record_to_entity[uid] = entity_id
            entity_to_records[entity_id].add(uid)
    return {"record_to_entity": record_to_entity, "entity_to_records": entity_to_records}


def _entity_safe_splits(
    record_uids: Iterable[str], record_to_entity: dict[str, str], seed: int
) -> dict[str, str]:
    random = Random(seed)
    entities = sorted({record_to_entity[uid] for uid in record_uids if uid in record_to_entity})
    random.shuffle(entities)
    entity_split: dict[str, str] = {}
    total = len(entities)
    for index, entity_id in enumerate(entities):
        ratio = index / total if total else 0.0
        if ratio < 0.6:
            entity_split[entity_id] = "train"
        elif ratio < 0.8:
            entity_split[entity_id] = "validation"
        else:
            entity_split[entity_id] = "test"
    splits: dict[str, str] = {}
    for uid in record_uids:
        record_entity_id = record_to_entity.get(uid)
        if record_entity_id is not None:
            splits[uid] = entity_split.get(record_entity_id, "train")
        else:
            splits[uid] = ["train", "validation", "test"][int(sha256_text(uid), 16) % 3]
    return splits


def _blocking_keys(
    record: dict[str, str],
    title_token_counts: Counter[str],
    config: BaselinePipelineConfig,
) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    brand = record.get("brand", "").lower()
    model = normalize_model_number(record.get("model_number", ""))
    title = record.get("title", "")
    category = record.get("category", "").lower()
    if brand and model:
        keys.append(("brand_model", f"{brand}|{model}"))
    model_context = " ".join([record.get("model_number", ""), title])
    for token in _model_tokens(model_context):
        keys.append(("rare_model_token", token))
    for token in _informative_tokens(title)[: config.blocking.title_token_limit]:
        if title_token_counts[token] <= config.blocking.rare_token_max_frequency:
            keys.append(("rare_title_token", token))
            if category:
                keys.append(("category_title_token", f"{category}|{token}"))
    compact_title = "".join(_tokens(title))
    for qgram in _qgrams(compact_title, config.blocking.qgram_size)[:4]:
        keys.append(("character_signature", qgram))
    screen = record.get("screen_size_diagonal") or record.get("spec_screen_size")
    resolution = record.get("supported_resolution") or record.get("spec_recommended_resolution")
    if brand and screen:
        keys.append(("spec_signature", f"{brand}|screen|{screen}"))
    if brand and resolution:
        keys.append(("spec_signature", f"{brand}|resolution|{resolution}"))
    return keys


def _pair_features(
    left: dict[str, str], right: dict[str, str], blocking_rules: Sequence[str]
) -> dict[str, float]:
    title_left = left.get("title", "")
    title_right = right.get("title", "")
    brand_left = left.get("brand", "").lower()
    brand_right = right.get("brand", "").lower()
    model_left = normalize_model_number(left.get("model_number", ""))
    model_right = normalize_model_number(right.get("model_number", ""))
    category_left = left.get("category", "").lower()
    category_right = right.get("category", "").lower()
    price_left = _as_float(left.get("price"))
    price_right = _as_float(right.get("price"))
    spec_left = {key for key in left if key.startswith("spec_") or key not in CORE_ATTRIBUTES}
    spec_right = {key for key in right if key.startswith("spec_") or key not in CORE_ATTRIBUTES}
    return {
        "title_token_jaccard": _jaccard(_tokens(title_left), _tokens(title_right)),
        "title_char_similarity": _char_similarity(title_left, title_right),
        "brand_exact": float(bool(brand_left and brand_left == brand_right)),
        "brand_conflict": float(bool(brand_left and brand_right and brand_left != brand_right)),
        "model_exact": float(bool(model_left and model_left == model_right)),
        "model_token_overlap": _jaccard(_model_tokens(model_left), _model_tokens(model_right)),
        "model_conflict": float(bool(model_left and model_right and model_left != model_right)),
        "category_exact": float(bool(category_left and category_left == category_right)),
        "price_relative_similarity": _price_similarity(price_left, price_right),
        "spec_key_jaccard": _jaccard(spec_left, spec_right),
        "blocking_rule_count": float(len(set(blocking_rules))),
        "same_source": float(left.get("source_id") == right.get("source_id")),
    }


def _feature_names() -> list[str]:
    return [
        "title_token_jaccard",
        "title_char_similarity",
        "brand_exact",
        "brand_conflict",
        "model_exact",
        "model_token_overlap",
        "model_conflict",
        "category_exact",
        "price_relative_similarity",
        "spec_key_jaccard",
        "blocking_rule_count",
        "same_source",
    ]


def _rule_match_score(row: dict[str, Any]) -> float:
    if float(row["brand_conflict"]) or float(row["model_conflict"]):
        return 0.05
    if float(row["model_exact"]) and (
        float(row["brand_exact"]) or float(row["title_token_jaccard"]) > 0.25
    ):
        return 0.95
    if float(row["brand_exact"]) and float(row["title_token_jaccard"]) > 0.5:
        return 0.8
    if float(row["title_token_jaccard"]) > 0.65 and float(row["spec_key_jaccard"]) > 0.2:
        return 0.7
    score = float(row["title_token_jaccard"]) * 0.7
    score += float(row["spec_key_jaccard"]) * 0.2
    return max(0.05, min(0.6, score))


def _calibrate_threshold(
    feature_rows: list[dict[str, Any]],
    probabilities: dict[str, float],
    config: BaselinePipelineConfig,
) -> float:
    validation_rows = [
        row
        for row in feature_rows
        if row["split"] == "validation" and row["ground_truth_label"] is not None
    ]
    if not validation_rows:
        return config.matcher.default_threshold
    best_threshold = config.matcher.default_threshold
    best_f1 = -1.0
    for threshold in config.matcher.threshold_grid:
        true_positive = false_positive = false_negative = 0
        for row in validation_rows:
            predicted = int(probabilities[str(row["candidate_pair_id"])] >= threshold)
            actual = int(row["ground_truth_label"])
            true_positive += int(predicted == 1 and actual == 1)
            false_positive += int(predicted == 1 and actual == 0)
            false_negative += int(predicted == 0 and actual == 1)
        score = _f1(true_positive, false_positive, false_negative)
        if score > best_f1:
            best_f1 = score
            best_threshold = threshold
    return best_threshold


def _classification_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for split in ["train", "validation", "test", "heldout_cross_split"]:
        split_rows = [
            row
            for row in rows
            if row["split"] == split and row.get("ground_truth_label") is not None
        ]
        true_positive = false_positive = false_negative = true_negative = 0
        for row in split_rows:
            predicted = int(row["match_prediction"])
            actual = int(row["ground_truth_label"])
            true_positive += int(predicted == 1 and actual == 1)
            false_positive += int(predicted == 1 and actual == 0)
            false_negative += int(predicted == 0 and actual == 1)
            true_negative += int(predicted == 0 and actual == 0)
        result[split] = {
            "count": len(split_rows),
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
            "precision": _safe_div(true_positive, true_positive + false_positive),
            "recall": _safe_div(true_positive, true_positive + false_negative),
            "f1": _f1(true_positive, false_positive, false_negative),
        }
    return result


def _connected_components(
    record_uids: Iterable[str], edges: list[dict[str, Any]]
) -> dict[str, set[str]]:
    parent = {uid: uid for uid in record_uids}
    for row in edges:
        left = str(row["left_record_uid"])
        right = str(row["right_record_uid"])
        left_root = _find(parent, left)
        right_root = _find(parent, right)
        if left_root != right_root:
            parent[right_root] = left_root
    return _clusters_from_parent(parent)


def _clusters_compatible(
    left_members: set[str],
    right_members: set[str],
    records: dict[str, dict[str, str]],
    config: BaselinePipelineConfig,
) -> tuple[bool, str]:
    merged_size = len(left_members) + len(right_members)
    if merged_size > config.clustering.max_cluster_size:
        return False, "max_cluster_size"
    if config.clustering.enforce_same_source_constraint:
        left_sources = _nonempty({records[uid].get("source_id", "") for uid in left_members})
        right_sources = _nonempty({records[uid].get("source_id", "") for uid in right_members})
        if left_sources & right_sources:
            return False, "same_source_duplicate"
    left_brands = _nonempty({records[uid].get("brand", "").lower() for uid in left_members})
    right_brands = _nonempty({records[uid].get("brand", "").lower() for uid in right_members})
    if config.clustering.enforce_brand_constraint and left_brands and right_brands:
        if left_brands.isdisjoint(right_brands):
            return False, "brand_conflict"
    left_models = _model_family_set(records[uid].get("model_number", "") for uid in left_members)
    right_models = _model_family_set(records[uid].get("model_number", "") for uid in right_members)
    if config.clustering.enforce_model_constraint and left_models and right_models:
        if left_models.isdisjoint(right_models):
            return False, "model_conflict"
    if config.clustering.enforce_spec_signature_constraint:
        compatible, reason = _spec_signatures_compatible(left_members, right_members, records)
        if not compatible:
            return False, reason
    return True, "compatible"


def _spec_signatures_compatible(
    left_members: set[str], right_members: set[str], records: dict[str, dict[str, str]]
) -> tuple[bool, str]:
    for field, reason in [
        ("screen_size_diagonal", "screen_size_conflict"),
        ("supported_resolution", "resolution_conflict"),
        ("spec_screen_size", "screen_size_conflict"),
        ("spec_recommended_resolution", "resolution_conflict"),
    ]:
        left_values = _nonempty({records[uid].get(field, "") for uid in left_members})
        right_values = _nonempty({records[uid].get(field, "") for uid in right_members})
        if left_values and right_values and left_values.isdisjoint(right_values):
            return False, reason
    return True, "compatible"


def _cluster_evidence_rows(
    clusters: dict[str, set[str]],
    records: dict[str, dict[str, str]],
    record_to_entity: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster_index, members in enumerate(
        sorted(clusters.values(), key=lambda item: sorted(item)[0]), start=1
    ):
        entity_counts = Counter(record_to_entity.get(uid, "") for uid in members)
        entity_counts.pop("", None)
        rows.append(
            {
                "entity_id": f"entity_{cluster_index:06d}",
                "member_count": len(members),
                "source_ids": json.dumps(
                    sorted(_nonempty({records[uid].get("source_id", "") for uid in members}))
                ),
                "brands": json.dumps(
                    sorted(_nonempty({records[uid].get("brand", "") for uid in members}))
                ),
                "model_families": json.dumps(sorted(_cluster_model_families(members, records))),
                "screen_sizes": json.dumps(
                    sorted(_cluster_values(members, records, "screen_size_diagonal"))
                ),
                "resolutions": json.dumps(
                    sorted(_cluster_values(members, records, "supported_resolution"))
                ),
                "ground_truth_entity_ids": json.dumps(sorted(entity_counts)),
                "ground_truth_entity_count": len(entity_counts),
            }
        )
    return rows


def _cluster_values(
    members: set[str], records: dict[str, dict[str, str]], field: str
) -> set[str]:
    return _nonempty({records[uid].get(field, "") for uid in members})


def _cluster_model_families(
    members: set[str], records: dict[str, dict[str, str]]
) -> set[str]:
    return _model_family_set(records[uid].get("model_number", "") for uid in members)


def _write_cluster_error_artifacts(
    *,
    stage_dir: Path,
    clusters: dict[str, set[str]],
    records: dict[str, dict[str, str]],
    record_to_entity: dict[str, str],
    merge_log: list[dict[str, Any]],
) -> dict[str, Path]:
    paths = {
        "cluster_overmerge_errors": stage_dir / "cluster_overmerge_errors.parquet",
        "cluster_undermerge_errors": stage_dir / "cluster_undermerge_errors.parquet",
        "cluster_weak_bridge_merges": stage_dir / "cluster_weak_bridge_merges.parquet",
        "cluster_largest_clusters": stage_dir / "cluster_largest_clusters.parquet",
    }
    cluster_rows, _ = _cluster_artifact_rows(
        clusters, records, record_to_truth_entity=record_to_entity
    )
    overmerged = [
        {
            "entity_id": row["entity_id"],
            "member_count": row["member_count"],
            "source_count": row["source_count"],
            "ground_truth_entity_ids": row["ground_truth_entity_ids"],
            "ground_truth_entity_count": len(json.loads(str(row["ground_truth_entity_ids"]))),
            "member_record_uids": row["member_record_uids"],
        }
        for row in cluster_rows
        if len(json.loads(str(row["ground_truth_entity_ids"]))) > 1
    ]
    by_truth: dict[str, set[str]] = defaultdict(set)
    cluster_by_member: dict[str, str] = {}
    for row in cluster_rows:
        for uid in json.loads(str(row["member_record_uids"])):
            cluster_by_member[str(uid)] = str(row["entity_id"])
    for record_uid, truth_entity in record_to_entity.items():
        predicted = cluster_by_member.get(record_uid)
        if predicted is not None:
            by_truth[truth_entity].add(predicted)
    undermerged = [
        {
            "ground_truth_entity_id": truth_entity,
            "predicted_cluster_count": len(predicted_clusters),
            "predicted_entity_ids": json.dumps(sorted(predicted_clusters)),
        }
        for truth_entity, predicted_clusters in sorted(by_truth.items())
        if len(predicted_clusters) > 1
    ]
    weak_bridges = [
        row
        for row in merge_log
        if row["decision"] == "accepted" and float(row["match_probability"]) < 0.85
    ]
    largest = sorted(cluster_rows, key=lambda row: int(row["member_count"]), reverse=True)[:25]
    _write_parquet(paths["cluster_overmerge_errors"], overmerged)
    _write_parquet(paths["cluster_undermerge_errors"], undermerged)
    _write_parquet(paths["cluster_weak_bridge_merges"], weak_bridges)
    _write_parquet(paths["cluster_largest_clusters"], largest)
    return paths


def _cluster_artifact_rows(
    clusters: dict[str, set[str]],
    records: dict[str, dict[str, str]],
    *,
    prefix: str = "entity",
    record_to_truth_entity: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cluster_rows: list[dict[str, Any]] = []
    membership_rows: list[dict[str, Any]] = []
    sorted_clusters = sorted(clusters.values(), key=lambda item: sorted(item)[0])
    for index, members in enumerate(sorted_clusters, start=1):
        entity_id = f"{prefix}_{index:06d}"
        member_list = sorted(members)
        source_count = len({records[uid].get("source_id", "") for uid in members})
        confidence = min(1.0, 0.45 + (0.1 * max(len(members) - 1, 0)))
        truth_ids = Counter(
            (record_to_truth_entity or {}).get(uid, "") for uid in members
        )
        truth_ids.pop("", None)
        primary_truth = truth_ids.most_common(1)[0][0] if truth_ids else None
        cluster_rows.append(
            {
                "entity_id": entity_id,
                "cluster_method": "constraint_agglomerative"
                if prefix == "entity"
                else "connected_components",
                "member_count": len(members),
                "source_count": source_count,
                "overall_confidence": confidence,
                "member_record_uids": json.dumps(member_list),
                "ground_truth_entity_ids": json.dumps(sorted(truth_ids)),
                "primary_ground_truth_entity_id": primary_truth,
            }
        )
        for uid in member_list:
            membership_rows.append(
                {
                    "entity_id": entity_id,
                    "record_uid": uid,
                    "membership_confidence": confidence,
                    "supporting_edges": "[]",
                    "cluster_method": "constraint_agglomerative"
                    if prefix == "entity"
                    else "connected_components",
                }
            )
    return cluster_rows, membership_rows


def _cluster_pair_metrics(
    clusters: dict[str, set[str]], record_to_entity: dict[str, str]
) -> dict[str, float | int]:
    predicted_pairs = {
        _pair_key(left, right)
        for members in clusters.values()
        for left, right in combinations(sorted(members), 2)
    }
    truth_pairs = {
        _pair_key(left, right)
        for left, right in combinations(sorted(record_to_entity), 2)
        if record_to_entity[left] == record_to_entity[right]
    }
    true_positive = len(predicted_pairs & truth_pairs)
    false_positive = len(predicted_pairs - truth_pairs)
    false_negative = len(truth_pairs - predicted_pairs)
    return {
        "predicted_pair_count": len(predicted_pairs),
        "truth_pair_count": len(truth_pairs),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": _safe_div(true_positive, true_positive + false_positive),
        "recall": _safe_div(true_positive, true_positive + false_negative),
        "f1": _f1(true_positive, false_positive, false_negative),
    }


def _fuse_group(
    attribute: str, claims: list[dict[str, Any]], config: BaselinePipelineConfig
) -> dict[str, Any]:
    del config
    values = [str(claim["normalized_value"]) for claim in claims if claim["normalized_value"] != ""]
    units = [str(claim.get("unit") or "") for claim in claims]
    selected_value: str
    method: str
    if attribute in {"title", "description"}:
        selected_value = _text_medoid(values)
        method = "text_medoid"
    elif _all_numbers(values):
        selected_value = _select_numeric_value(values)
        method = "numeric_median"
    else:
        selected_value = Counter(values).most_common(1)[0][0] if values else ""
        method = "majority_vote"
    selected_unit = Counter([unit for unit in units if unit]).most_common(1)
    supporting = [
        str(claim["claim_id"])
        for claim in claims
        if str(claim["normalized_value"]) == selected_value
    ]
    contradicting = [
        str(claim["claim_id"])
        for claim in claims
        if str(claim["normalized_value"]) != selected_value
    ]
    alternatives = sorted({str(claim["normalized_value"]) for claim in claims})
    return {
        "selected_value": selected_value,
        "selected_unit": selected_unit[0][0] if selected_unit else None,
        "fusion_method": method,
        "confidence": len(supporting) / len(claims) if claims else 0.0,
        "supporting_claim_ids": supporting,
        "contradicting_claim_ids": contradicting,
        "alternative_values": alternatives,
    }


def _integrated_entities(
    clusters: list[dict[str, Any]], fused_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    fused_by_entity: dict[str, dict[str, Any]] = defaultdict(dict)
    provenance_by_entity: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in fused_rows:
        entity_id = str(row["entity_id"])
        attribute = str(row["mediated_attribute_name"])
        fused_by_entity[entity_id][attribute] = row["selected_value"]
        provenance_by_entity[entity_id][attribute] = {
            "fused_value_id": row["fused_value_id"],
            "supporting_claim_ids": json.loads(str(row["supporting_claim_ids"])),
            "contradicting_claim_ids": json.loads(str(row["contradicting_claim_ids"])),
        }
    rows: list[dict[str, Any]] = []
    for cluster in clusters:
        entity_id = str(cluster["entity_id"])
        rows.append(
            {
                "entity_id": entity_id,
                "cluster_method": str(cluster["cluster_method"]),
                "member_count": int(cluster["member_count"]),
                "source_count": int(cluster["source_count"]),
                "canonical_payload": canonical_json(fused_by_entity.get(entity_id, {})),
                "provenance": canonical_json(provenance_by_entity.get(entity_id, {})),
                "overall_confidence": float(cluster["overall_confidence"]),
            }
        )
    return rows


def _fusion_metrics(
    fused_rows: list[dict[str, Any]],
    bootstrap_gold_path: Path | None,
    curated_gold_path: Path | None,
    clusters: list[dict[str, Any]],
) -> dict[str, Any]:
    bootstrap = _fusion_metrics_for_gold(fused_rows, bootstrap_gold_path, clusters)
    curated = _fusion_metrics_for_gold(fused_rows, curated_gold_path, clusters)
    primary = curated if curated_gold_path is not None else bootstrap
    return {
        "gold_available": primary["gold_available"],
        "evaluated_value_count": primary["evaluated_value_count"],
        "correct_value_count": primary["correct_value_count"],
        "accuracy": primary["accuracy"],
        "bootstrap_fusion_metrics": bootstrap,
        "curated_fusion_metrics": curated,
    }


def _fusion_metrics_for_gold(
    fused_rows: list[dict[str, Any]], gold_path: Path | None, clusters: list[dict[str, Any]]
) -> dict[str, Any]:
    if gold_path is None or not gold_path.exists():
        return {
            "gold_available": False,
            "gold_path": str(gold_path) if gold_path is not None else None,
            "gold_row_count": 0,
            "evaluated_value_count": 0,
            "correct_value_count": 0,
            "accuracy": None,
            "rows": [],
        }
    fused = {
        (str(row["entity_id"]), str(row["mediated_attribute_name"])): str(row["selected_value"])
        for row in fused_rows
    }
    predicted_by_truth = {
        str(row["primary_ground_truth_entity_id"]): str(row["entity_id"])
        for row in clusters
        if row.get("primary_ground_truth_entity_id") not in (None, "")
    }
    total = correct = 0
    gold_row_count = 0
    evaluated_rows: list[dict[str, Any]] = []
    with gold_path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            gold_row_count += 1
            entity_id = str(row["entity_id"])
            predicted_entity_id = predicted_by_truth.get(entity_id, entity_id)
            key = (predicted_entity_id, str(row["mediated_attribute"]))
            expected = str(row["selected_truth_value"])
            if key not in fused:
                continue
            total += 1
            predicted = fused[key]
            is_correct = predicted == expected
            correct += int(is_correct)
            evaluated_rows.append(
                {
                    "truth_entity_id": entity_id,
                    "predicted_entity_id": predicted_entity_id,
                    "mediated_attribute": str(row["mediated_attribute"]),
                    "expected_value": expected,
                    "predicted_value": predicted,
                    "correct": is_correct,
                }
            )
    return {
        "gold_available": total > 0,
        "gold_path": repo_relative(gold_path, gold_path.parents[2])
        if len(gold_path.parents) > 2
        else str(gold_path),
        "gold_row_count": gold_row_count,
        "evaluated_value_count": total,
        "correct_value_count": correct,
        "accuracy": correct / total if total else None,
        "rows": evaluated_rows,
    }


def _fusion_gold_errors(
    fused_rows: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    fusion_metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    del fused_rows, clusters
    curated = fusion_metrics.get("curated_fusion_metrics", {})
    rows = curated.get("rows", []) if isinstance(curated, dict) else []
    return [
        {**row, "error_type": "curated_fusion_mismatch"}
        for row in rows
        if isinstance(row, dict) and not bool(row.get("correct"))
    ]


def _unsupported_fused_values(fused_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unsupported_tokens = {"no info", "unknown", "n/a", "none", ""}
    rows: list[dict[str, Any]] = []
    for row in fused_rows:
        selected = str(row["selected_value"]).strip().lower()
        if selected in unsupported_tokens:
            rows.append(
                {
                    "entity_id": row["entity_id"],
                    "mediated_attribute_name": row["mediated_attribute_name"],
                    "selected_value": row["selected_value"],
                    "error_type": "unsupported_or_empty_value",
                }
            )
    return rows


def _high_conflict_fused_values(fused_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in fused_rows:
        alternatives = json.loads(str(row["alternative_values"]))
        if len(alternatives) >= 4:
            rows.append(
                {
                    "entity_id": row["entity_id"],
                    "mediated_attribute_name": row["mediated_attribute_name"],
                    "selected_value": row["selected_value"],
                    "confidence": row["confidence"],
                    "alternative_count": len(alternatives),
                    "error_type": "high_conflict_attribute",
                }
            )
    return rows


def _baseline_error_candidates(fused_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in fused_rows:
        alternatives = json.loads(str(row["alternative_values"]))
        if len(alternatives) > 1 or float(row["confidence"]) < 0.67:
            rows.append(
                {
                    "entity_id": row["entity_id"],
                    "mediated_attribute_name": row["mediated_attribute_name"],
                    "selected_value": row["selected_value"],
                    "confidence": row["confidence"],
                    "alternative_count": len(alternatives),
                    "error_reason": "low_support_or_conflict",
                }
            )
    return rows


def _finish_result(
    run_id: str,
    run_dir: Path,
    completed_stage: str,
    artifacts: dict[str, str],
    metrics: dict[str, str],
    config: BaselinePipelineConfig,
    repo_root: Path,
    checkpoint: RunCheckpoint | None = None,
) -> PipelineRunResult:
    manifest_path = run_dir / "run_manifest.json"
    if completed_stage in {"fuse", "evaluate", "export"}:
        summary_path = _write_m2_baseline_summary(
            run_id=run_id,
            run_dir=run_dir,
            metrics=metrics,
            config=config,
            repo_root=repo_root,
        )
        artifacts["m2_baseline_summary"] = str(summary_path)
    payload = {
        "run_id": run_id,
        "pipeline_id": config.pipeline_id,
        "completed_stage": completed_stage,
        "llm_decisions": config.llm_decisions,
        "configuration_hash": f"cfg_{sha256_text(config.model_dump_json())[:12]}",
        "code_commit": _code_commit(repo_root),
        "generated_at": datetime.now(UTC).isoformat(),
        "artifacts": {
            key: repo_relative(Path(value), repo_root) for key, value in artifacts.items()
        },
        "metrics": {key: repo_relative(Path(value), repo_root) for key, value in metrics.items()},
    }
    _write_json(manifest_path, payload)
    artifacts["run_manifest"] = str(manifest_path)
    if checkpoint is not None:
        checkpoint.finish(artifacts=artifacts, metrics=metrics)
    return PipelineRunResult(
        run_id=run_id,
        run_dir=str(run_dir),
        completed_stage=completed_stage,
        artifacts=artifacts,
        metrics=metrics,
    )


def _write_m2_baseline_summary(
    *,
    run_id: str,
    run_dir: Path,
    metrics: dict[str, str],
    config: BaselinePipelineConfig,
    repo_root: Path,
) -> Path:
    if "fixture" in config.pipeline_id:
        summary_path = run_dir / "m2_fixture_baseline_summary.md"
    else:
        reports_dir = repo_root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        summary_path = reports_dir / "m2_baseline_summary.md"
    loaded_metrics = {
        name: json.loads(Path(path).read_text(encoding="utf-8"))
        for name, path in metrics.items()
        if Path(path).exists()
    }
    schema = loaded_metrics.get("schema_metrics", {})
    blocking = loaded_metrics.get("blocking_metrics", {})
    linkage = loaded_metrics.get("linkage_metrics", {})
    cluster = loaded_metrics.get("cluster_metrics", {})
    fusion = loaded_metrics.get("fusion_metrics", {})
    curated_fusion_accuracy = _format_optional_metric(
        fusion.get("curated_fusion_metrics", {}).get("accuracy")
    )
    bootstrap_fusion_accuracy = _format_optional_metric(
        fusion.get("bootstrap_fusion_metrics", {}).get("accuracy")
    )
    text = f"""# M2 Baseline Summary

## Run

- Run ID: `{run_id}`
- Pipeline: `{config.pipeline_id}`
- Run artifacts: `{repo_relative(run_dir, repo_root)}`
- LLM decisions: `{config.llm_decisions}`

## Metrics

- Schema F1: `{schema.get("f1", 0):.4f}`
- Core schema F1: `{schema.get("core_schema_metrics", {}).get("f1", 0):.4f}`
- Monitor detail schema F1: `{schema.get("monitor_detail_schema_metrics", {}).get("f1", 0):.4f}`
- Candidate pairs: `{blocking.get("candidate_pair_count", 0)}`
- Blocking pair completeness: `{blocking.get("pair_completeness", 0):.4f}`
- Linkage test F1: `{linkage.get("metrics_by_split", {}).get("test", {}).get("f1", 0):.4f}`
- Agglomerative cluster F1: `{cluster.get("agglomerative", {}).get("f1", 0):.4f}`
- Connected-components cluster F1: `{cluster.get("connected_components", {}).get("f1", 0):.4f}`
- Curated fusion accuracy: `{curated_fusion_accuracy}`
- Bootstrap fusion accuracy: `{bootstrap_fusion_accuracy}`

## Known Weaknesses

- Schema alignment should be interpreted separately for core fields and detailed monitor attributes.
- Clustering is intentionally stricter than pair matching and still requires error review.
- Bootstrap fusion labels are majority-derived diagnostics; curated labels are the
  primary fusion check.

## Recommended M3 Routing Targets

- Ambiguous schema candidates and unmapped gold fields.
- Weak bridge merges, over-merged clusters, and under-merged truth entities.
- Low-support, high-conflict, and curated-mismatch fusion values.
"""
    summary_path.write_text(text, encoding="utf-8")
    return summary_path


def _format_optional_metric(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "NA"


def _is_specification_candidate(row: dict[str, Any]) -> bool:
    roles = str(row.get("semantic_role_suggestions", ""))
    return "specification" in roles or "measurement" in roles


def _type_score(inferred_type: str, target: str, schema: MediatedSchema) -> float:
    attribute_type = next(
        (attribute.type for attribute in schema.attributes if attribute.name == target), "string"
    )
    if target in {"price"}:
        return 1.0 if inferred_type in {"currency_or_price", "number"} else 0.2
    if target == "currency":
        return 1.0 if inferred_type == "currency_or_price" else 0.3
    if attribute_type in {"decimal", "number"}:
        return 1.0 if inferred_type in {"number", "measurement", "currency_or_price"} else 0.2
    if attribute_type == "boolean":
        return 0.9 if inferred_type in {"string", "number"} else 0.4
    if target == "specifications":
        return 0.8
    if inferred_type == "free_text" and target in {"title", "description"}:
        return 0.8
    if inferred_type == "measurement" and target not in {"title", "description"}:
        return 0.75
    return 0.6


def _value_score(row: dict[str, Any], target: str) -> float:
    roles = set(_json_list(str(row.get("semantic_role_suggestions", "[]"))))
    unit_patterns = _json_list(str(row.get("unit_patterns", "[]")))
    inferred_type = str(row.get("inferred_type", ""))
    if target == "title" and "title" in roles:
        return 1.0
    if target == "brand" and "brand" in roles:
        return 1.0
    if target == "model_number" and "model identifier" in roles:
        return 0.95
    if target == "price" and ("price" in roles or inferred_type == "currency_or_price"):
        return 0.95
    if target == "currency" and "currency" in roles:
        return 0.95
    if target == "description" and "description" in roles:
        return 0.9
    if target == "category" and "category" in roles:
        return 0.9
    if target == "specifications" and ("specification" in roles or unit_patterns):
        return 0.75
    if unit_patterns and _measurement_like_attribute(target):
        return 0.8
    return 0.35


def _context_score(row: dict[str, Any], target: str) -> float:
    non_null_rate = float(row.get("non_null_rate", 0.0) or 0.0)
    uniqueness_rate = float(row.get("uniqueness_rate", 0.0) or 0.0)
    if target in {"title", "model_number"}:
        return min(1.0, (uniqueness_rate * 0.7) + (non_null_rate * 0.3))
    if target in {"brand", "category", "currency"}:
        return min(1.0, ((1 - uniqueness_rate) * 0.5) + (non_null_rate * 0.5))
    return non_null_rate


def _json_list(value: str) -> list[str]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(decoded, list):
        return [str(item) for item in decoded]
    return []


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(value.replace("_", " "))}


def _informative_tokens(value: str) -> list[str]:
    tokens = [token for token in _tokens(value) if token not in STOPWORDS and len(token) > 2]
    return sorted(tokens)


def _model_tokens(value: str) -> set[str]:
    compact = normalize_model_number(value)
    found = {normalize_model_number(match.group(0)) for match in MODEL_PATTERN.finditer(value)}
    if compact and any(character.isdigit() for character in compact):
        found.add(compact)
    return {token for token in found if len(token) >= 3}


def _model_family_set(values: Iterable[str]) -> set[str]:
    families: set[str] = set()
    for value in values:
        normalized = normalize_model_number(value)
        if not normalized:
            continue
        digits = "".join(character for character in normalized if character.isdigit())
        letters = "".join(character for character in normalized if character.isalpha())[:4]
        families.add(f"{letters}{digits}" if digits else normalized)
        if digits:
            families.add(digits)
    return families


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _name_similarity(left: str, right: str) -> float:
    left_key = normalize_specification_key(left)
    right_key = normalize_specification_key(right)
    if left_key == right_key:
        return 1.0
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    token_score = _jaccard(left_tokens, right_tokens)
    char_score = _char_similarity(left_key, right_key)
    return max(token_score, char_score * 0.85)


def _char_similarity(left: str, right: str) -> float:
    left_qgrams = set(_qgrams(left.lower(), 3))
    right_qgrams = set(_qgrams(right.lower(), 3))
    return _jaccard(left_qgrams, right_qgrams)


def _qgrams(value: str, size: int) -> list[str]:
    if len(value) <= size:
        return [value] if value else []
    return [value[index : index + size] for index in range(0, len(value) - size + 1)]


def _looks_boolean_attribute(target: str, source_attribute_name: str) -> bool:
    combined = f"{target} {source_attribute_name}".lower()
    return target.startswith("has_") or target.startswith("is_") or combined in {
        "dvi",
        "vga",
        "hdmi",
        "displayport",
    }


def _normalize_boolean(raw_value: str) -> str:
    value = raw_value.strip().lower()
    if value in {"yes", "true", "1", "y"}:
        return "true"
    if value in {"no", "false", "0", "n"}:
        return "false"
    return value


def _measurement_like_attribute(attribute_name: str) -> bool:
    name = attribute_name.lower()
    return any(
        token in name
        for token in [
            "size",
            "resolution",
            "brightness",
            "response",
            "refresh",
            "weight",
            "height",
            "width",
            "depth",
            "dimension",
            "megapixel",
            "mp",
            "hz",
        ]
    )


def _canonical_unit(unit: str | None, attribute_name: str) -> str | None:
    if unit is None or unit == "":
        if "resolution" in attribute_name.lower():
            return "px"
        return None
    normalized = unit.lower()
    if normalized in {'"', "inch", "inches", "in"}:
        return "inch"
    if normalized in {"mp", "megapixels"}:
        return "MP"
    if normalized == "tb":
        return "GB"
    if normalized == "gb":
        return "GB"
    if normalized in {"cd/m²", "cd/m2", "nits"}:
        return "cd/m2"
    return normalized


def _normalization_result(
    canonical_value: str | None,
    canonical_unit: str | None,
    method: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "canonical_value": "" if canonical_value is None else str(canonical_value),
        "canonical_unit": canonical_unit,
        "normalization_method": method,
        "confidence": confidence,
    }


def _collapse_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _title_case_brand(value: str) -> str:
    aliases = {"hewlett packard": "HP", "hp": "HP", "lg": "LG", "aoc": "AOC"}
    cleaned = _collapse_space(value).strip()
    return aliases.get(cleaned.lower(), cleaned.title())


def _normalize_category(value: str) -> str:
    cleaned = _collapse_space(value).lower()
    if "mirrorless" in cleaned:
        return "mirrorless camera"
    if "dslr" in cleaned or "slr" in cleaned:
        return "dslr camera"
    if "monitor" in cleaned or "display" in cleaned:
        return "monitor"
    if "camera" in cleaned:
        return "camera"
    return cleaned


def _as_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _price_similarity(left: float | None, right: float | None) -> float:
    if left is None or right is None:
        return 0.0
    if left == right:
        return 1.0
    denominator = max(abs(left), abs(right), 1.0)
    relative = abs(left - right) / denominator
    return max(0.0, 1 - relative)


def _safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(true_positive: int, false_positive: int, false_negative: int) -> float:
    precision = _safe_div(true_positive, true_positive + false_positive)
    recall = _safe_div(true_positive, true_positive + false_negative)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def _pair_label(left_entity: str | None, right_entity: str | None) -> int | None:
    if left_entity is None or right_entity is None:
        return None
    return int(left_entity == right_entity)


def _pair_split(left: str, right: str, split_by_record: dict[str, str]) -> str:
    left_split = split_by_record[left]
    right_split = split_by_record[right]
    return left_split if left_split == right_split else "heldout_cross_split"


def _total_positive_pairs(entity_to_records: dict[str, set[str]]) -> int:
    return sum(len(records) * (len(records) - 1) // 2 for records in entity_to_records.values())


def _find(parent: dict[str, str], item: str) -> str:
    while parent[item] != item:
        parent[item] = parent[parent[item]]
        item = parent[item]
    return item


def _component_members(parent: dict[str, str], root: str) -> set[str]:
    return {item for item in parent if _find(parent, item) == root}


def _clusters_from_parent(parent: dict[str, str]) -> dict[str, set[str]]:
    clusters: dict[str, set[str]] = defaultdict(set)
    for item in parent:
        clusters[_find(parent, item)].add(item)
    return clusters


def _nonempty(values: set[str]) -> set[str]:
    return {value for value in values if value}


def _all_numbers(values: list[str]) -> bool:
    if not values:
        return False
    return all(_as_float(value) is not None for value in values)


def _select_numeric_value(values: list[str]) -> str:
    numeric_pairs = [
        (float_value, value)
        for value in values
        if (float_value := _as_float(value)) is not None
    ]
    numeric_values = sorted(float_value for float_value, _ in numeric_pairs)
    middle = median(numeric_values)
    return min(numeric_pairs, key=lambda item: abs(item[0] - middle))[1]


def _text_medoid(values: list[str]) -> str:
    if not values:
        return ""
    counts = Counter(values)
    unique_values = sorted(counts, key=lambda value: (-counts[value], -len(value), value))
    if len(unique_values) == 1:
        return unique_values[0]
    if len(unique_values) > 50:
        return unique_values[0]
    best_value = unique_values[0]
    best_score = -1.0
    for value in unique_values:
        score = mean(
            _char_similarity(value, other) for other in unique_values if other != value
        )
        if score > best_score or (math.isclose(score, best_score) and len(value) > len(best_value)):
            best_score = score
            best_value = value
    return best_value


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        pl.DataFrame(rows, infer_schema_length=None).write_parquet(path)
    else:
        pl.DataFrame().write_parquet(path)


def _write_validated_parquet(
    path: Path, rows: list[dict[str, Any]], model: type[BaseModel]
) -> None:
    validated_rows = [model.model_validate(row).model_dump() for row in rows]
    _write_parquet(path, validated_rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _stage_dir(run_dir: Path, stage: str) -> Path:
    path = run_dir / stage
    path.mkdir(parents=True, exist_ok=True)
    return path


def _new_run_id(slug: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    short = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")[:24]
    unique_suffix = sha256_text(f"{slug}|{time.perf_counter_ns()}")[:8]
    return f"run_{timestamp}_{short}_{unique_suffix}"


def _code_commit(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    return completed.stdout.strip()
