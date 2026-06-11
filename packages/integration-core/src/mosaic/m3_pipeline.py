from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from mosaic.checkpoints import RunCheckpoint, append_progress, checkpoint_hash, load_progress
from mosaic.llm_gateway import LLMGateway
from mosaic.m1_models import load_dataset_config, load_mediated_schema
from mosaic.m1_utils import canonical_json, repo_relative, sha256_text
from mosaic.m2_models import (
    AcceptedSchemaMapping,
    FusedValue,
    IntegratedEntity,
    PairPrediction,
    PipelineRunResult,
    load_baseline_pipeline_config,
)
from mosaic.m2_pipeline import (
    StageName,
    _classification_metrics,
    _code_commit,
    _fusion_metrics,
    _integrated_entities,
    _new_run_id,
    _record_lookup,
    _schema_metrics,
    _stage_dir,
    _write_json,
    _write_parquet,
    _write_validated_parquet,
    cluster_records,
    extract_claims,
    fuse_claims,
    generate_candidate_pairs,
    match_candidate_pairs,
    normalize_records,
    run_baseline_pipeline,
)
from mosaic.m3_models import (
    FusionLLMBatchDecision,
    FusionLLMDecision,
    LinkageLLMBatchDecision,
    LinkageLLMDecision,
    LLMCallResult,
    M3ExperimentConfig,
    SchemaLLMBatchDecision,
    SchemaLLMDecision,
    load_llm_model_config,
)


class LLMBudgetTracker:
    def __init__(self, config: M3ExperimentConfig, gateway: LLMGateway, repo_root: Path) -> None:
        self.config = config
        self.gateway = gateway
        self.repo_root = repo_root
        self.run_call_count = 0
        self.run_cost_usd = 0.0
        self.stage_call_counts: dict[str, int] = defaultdict(int)
        self.daily_call_count, self.daily_cost_usd = self._daily_usage()

    def skip_reason(self, stage: str, estimated_cost_usd: float) -> str | None:
        routing = self.config.routing
        if (
            routing.max_cases_per_stage is not None
            and self.stage_call_counts[stage] >= routing.max_cases_per_stage
        ):
            return "stage_case_limit"
        if (
            routing.per_run_call_budget is not None
            and self.run_call_count >= routing.per_run_call_budget
        ):
            return "per_run_call_budget"
        if routing.daily_call_budget is not None and (
            self.daily_call_count + self.run_call_count >= routing.daily_call_budget
        ):
            return "daily_call_budget"
        if estimated_cost_usd > 0 and routing.per_run_cost_budget_usd is not None:
            if self.run_cost_usd + estimated_cost_usd > routing.per_run_cost_budget_usd:
                return "per_run_cost_budget"
        if estimated_cost_usd > 0 and routing.daily_cost_budget_usd is not None:
            if (
                self.daily_cost_usd + self.run_cost_usd + estimated_cost_usd
                > routing.daily_cost_budget_usd
            ):
                return "daily_cost_budget"
        return None

    def record(self, stage: str, result: LLMCallResult) -> None:
        self.stage_call_counts[stage] += 1
        self.run_call_count += 1
        self.run_cost_usd += result.estimated_cost_usd

    def _daily_usage(self) -> tuple[int, float]:
        root = self.repo_root / self.gateway.model_config.call_log_root
        today = datetime.now(UTC).date()
        call_count = 0
        cost = 0.0
        if not root.exists():
            return call_count, cost
        for path in root.glob("*/*_calls.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    created_at = datetime.fromisoformat(str(row["created_at"])).date()
                except (KeyError, json.JSONDecodeError, ValueError):
                    continue
                if created_at == today:
                    call_count += 1
                    cost += float(row.get("estimated_cost_usd", 0.0) or 0.0)
        return call_count, cost


def run_assisted_pipeline(
    config: M3ExperimentConfig,
    repo_root: Path,
    *,
    stop_after: StageName = "export",
    baseline_result: PipelineRunResult | None = None,
    resume_run_id: str | None = None,
) -> PipelineRunResult:
    baseline_config = load_baseline_pipeline_config(repo_root / config.baseline_pipeline_config)
    if baseline_result is None:
        baseline_result = run_baseline_pipeline(baseline_config, repo_root)
    dataset_config = load_dataset_config(repo_root / baseline_config.dataset_config)
    schema = load_mediated_schema(repo_root / baseline_config.schema_path)
    model_config = load_llm_model_config(repo_root / config.model_config_path)

    run_id = resume_run_id or _new_run_id(config.experiment_id)
    run_dir = repo_root / config.artifact_root / run_id
    _stage_dir(run_dir, "logs")
    _stage_dir(run_dir, "metrics")
    gateway = LLMGateway(model_config, repo_root, run_id)
    budget = LLMBudgetTracker(config, gateway, repo_root)
    checkpoint = RunCheckpoint(
        repo_root=repo_root,
        run_dir=run_dir,
        run_id=run_id,
        config_hash=f"cfg_{sha256_text(config.model_dump_json())[:12]}",
        dataset_hash=checkpoint_hash(dataset_config.model_dump()),
        prompt_hash=checkpoint_hash(config.prompt_versions.model_dump(by_alias=True)),
        model_hash=checkpoint_hash(model_config.model_dump()),
        resume=resume_run_id is not None,
    )

    artifacts: dict[str, str] = {
        f"baseline_{key}": value for key, value in baseline_result.artifacts.items()
    }
    metrics: dict[str, str] = {
        f"baseline_{key}": value for key, value in baseline_result.metrics.items()
    }
    if resume_run_id is not None:
        artifacts.update(
            {key: str(repo_root / value) for key, value in checkpoint.artifacts.items()}
        )
        metrics.update({key: str(repo_root / value) for key, value in checkpoint.metrics.items()})
    model_settings = model_config.model_dump()

    if not checkpoint.is_stage_complete("schema", required=["assisted_schema_mappings"]):
        checkpoint.start_stage("schema")
        schema_outputs = assist_schema_alignment(
            config=config,
            gateway=gateway,
            budget=budget,
            repo_root=repo_root,
            run_dir=run_dir,
            baseline_artifacts=baseline_result.artifacts,
            target_attributes=[attribute.name for attribute in schema.attributes],
            mapping_gold_path=dataset_config.mapping_gold_path,
        )
        artifacts.update(schema_outputs["artifacts"])
        metrics.update(schema_outputs["metrics"])
        checkpoint.complete_stage("schema", artifacts=artifacts, metrics=metrics)
    if stop_after == "schema":
        return _finish_assisted_result(
            config,
            model_settings,
            run_id,
            run_dir,
            stop_after,
            artifacts,
            metrics,
            repo_root,
            checkpoint,
        )

    records_path = (
        repo_root
        / "data"
        / "interim"
        / "m1"
        / dataset_config.dataset_id
        / "source_records.parquet"
    )
    if not checkpoint.is_stage_complete("normalize", required=["normalized_records"]):
        checkpoint.start_stage("normalize")
        normalize_outputs = normalize_records(
            config=baseline_config,
            dataset_config=dataset_config,
            schema=schema,
            repo_root=repo_root,
            records_path=records_path,
            accepted_mappings_path=Path(artifacts["assisted_schema_mappings"]),
            run_dir=run_dir,
        )
        artifacts.update(normalize_outputs["artifacts"])
        metrics.update(normalize_outputs["metrics"])
        checkpoint.complete_stage("normalize", artifacts=artifacts, metrics=metrics)
    if stop_after == "normalize":
        return _finish_assisted_result(
            config,
            model_settings,
            run_id,
            run_dir,
            stop_after,
            artifacts,
            metrics,
            repo_root,
            checkpoint,
        )

    if not checkpoint.is_stage_complete("block", required=["candidate_pairs"]):
        checkpoint.start_stage("block")
        blocking_outputs = generate_candidate_pairs(
            config=baseline_config,
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
        return _finish_assisted_result(
            config,
            model_settings,
            run_id,
            run_dir,
            stop_after,
            artifacts,
            metrics,
            repo_root,
            checkpoint,
        )

    if not checkpoint.is_stage_complete("deterministic_match", required=["pair_predictions"]):
        checkpoint.start_stage("deterministic_match")
        match_outputs = match_candidate_pairs(
            config=baseline_config,
            repo_root=repo_root,
            normalized_records_path=Path(artifacts["normalized_records"]),
            candidate_pairs_path=Path(artifacts["candidate_pairs"]),
            run_dir=run_dir,
        )
        artifacts.update(match_outputs["artifacts"])
        metrics.update(match_outputs["metrics"])
        checkpoint.complete_stage("deterministic_match", artifacts=artifacts, metrics=metrics)

    if not checkpoint.is_stage_complete("match", required=["assisted_pair_predictions"]):
        checkpoint.start_stage("match")
        linkage_outputs = assist_record_linkage(
            config=config,
            gateway=gateway,
            budget=budget,
            repo_root=repo_root,
            run_dir=run_dir,
            normalized_records_path=Path(artifacts["normalized_records"]),
            pair_features_path=Path(artifacts["pair_features"]),
            pair_predictions_path=Path(artifacts["pair_predictions"]),
        )
        artifacts.update(linkage_outputs["artifacts"])
        metrics.update(linkage_outputs["metrics"])
        checkpoint.complete_stage("match", artifacts=artifacts, metrics=metrics)
    if stop_after == "match":
        return _finish_assisted_result(
            config,
            model_settings,
            run_id,
            run_dir,
            stop_after,
            artifacts,
            metrics,
            repo_root,
            checkpoint,
        )

    if not checkpoint.is_stage_complete("cluster", required=["cluster_memberships"]):
        checkpoint.start_stage("cluster")
        cluster_outputs = cluster_records(
            config=baseline_config,
            dataset_config=dataset_config,
            repo_root=repo_root,
            normalized_records_path=Path(artifacts["normalized_records"]),
            pair_predictions_path=Path(artifacts["assisted_pair_predictions"]),
            run_dir=run_dir,
        )
        artifacts.update(cluster_outputs["artifacts"])
        metrics.update(cluster_outputs["metrics"])
        checkpoint.complete_stage("cluster", artifacts=artifacts, metrics=metrics)
    if stop_after == "cluster":
        return _finish_assisted_result(
            config,
            model_settings,
            run_id,
            run_dir,
            stop_after,
            artifacts,
            metrics,
            repo_root,
            checkpoint,
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
        return _finish_assisted_result(
            config,
            model_settings,
            run_id,
            run_dir,
            stop_after,
            artifacts,
            metrics,
            repo_root,
            checkpoint,
        )

    if not checkpoint.is_stage_complete("deterministic_fuse", required=["fused_values"]):
        checkpoint.start_stage("deterministic_fuse")
        fusion_outputs = fuse_claims(
            config=baseline_config,
            repo_root=repo_root,
            claims_path=Path(artifacts["attribute_claims"]),
            clusters_path=Path(artifacts["clusters"]),
            run_dir=run_dir,
        )
        artifacts.update(fusion_outputs["artifacts"])
        metrics.update(fusion_outputs["metrics"])
        checkpoint.complete_stage("deterministic_fuse", artifacts=artifacts, metrics=metrics)

    if not checkpoint.is_stage_complete("fusion", required=["assisted_integrated_entities_jsonl"]):
        checkpoint.start_stage("fusion")
        assisted_fusion = assist_fusion(
            config=config,
            gateway=gateway,
            budget=budget,
            repo_root=repo_root,
            run_dir=run_dir,
            baseline_config=baseline_config,
            claims_path=Path(artifacts["attribute_claims"]),
            clusters_path=Path(artifacts["clusters"]),
            fused_values_path=Path(artifacts["fused_values"]),
            fusion_artifacts={
                key: value
                for key, value in artifacts.items()
                if key
                in {
                    "baseline_error_candidates",
                    "fusion_curated_errors",
                    "fusion_unsupported_values",
                    "fusion_high_conflict_attributes",
                }
            },
        )
        artifacts.update(assisted_fusion["artifacts"])
        metrics.update(assisted_fusion["metrics"])
        checkpoint.complete_stage("fusion", artifacts=artifacts, metrics=metrics)
    return _finish_assisted_result(
        config,
        model_settings,
        run_id,
        run_dir,
        stop_after,
        artifacts,
        metrics,
        repo_root,
        checkpoint,
    )


def assist_schema_alignment(
    *,
    config: M3ExperimentConfig,
    gateway: LLMGateway,
    budget: LLMBudgetTracker,
    repo_root: Path,
    run_dir: Path,
    baseline_artifacts: dict[str, str],
    target_attributes: list[str],
    mapping_gold_path: str | None,
) -> dict[str, dict[str, str]]:
    accepted_rows = pl.read_parquet(baseline_artifacts["accepted_schema_mappings"]).to_dicts()
    candidate_rows = pl.read_parquet(baseline_artifacts["mapping_candidates"]).to_dicts()
    stage_dir = _stage_dir(run_dir, "schema")
    if config.decision_mode == "primary":
        return _primary_schema_alignment(
            config=config,
            gateway=gateway,
            budget=budget,
            repo_root=repo_root,
            stage_dir=stage_dir,
            accepted_rows=accepted_rows,
            candidate_rows=candidate_rows,
            target_attributes=target_attributes,
            mapping_gold_path=mapping_gold_path,
        )
    route_ids = _schema_route_ids(config, accepted_rows, baseline_artifacts)
    candidates_by_source = _rows_by_key(candidate_rows, "source_attribute_id")
    assisted_rows: list[dict[str, Any]] = [dict(row) for row in accepted_rows]
    rows_by_source = {str(row["source_attribute_id"]): row for row in assisted_rows}
    route_rows: list[dict[str, Any]] = []

    for source_attribute_id in sorted(route_ids):
        if not config.llm_assistance.schema_enabled:
            route_rows.append(_skipped_route_row("schema", source_attribute_id, "not_selected"))
            continue
        deterministic = rows_by_source[source_attribute_id]
        candidates = candidates_by_source.get(source_attribute_id, [])
        payload = {
            "source_attribute_id": source_attribute_id,
            "attribute_name": deterministic["attribute_name"],
            "source_id": deterministic["source_id"],
            "deterministic_decision": _without_ground_truth(deterministic),
            "deterministic_candidates": [_without_ground_truth(row) for row in candidates[:8]],
            "allowed_targets": target_attributes + ["UNMAPPED", "ABSTAIN"],
        }
        template_path = repo_root / config.prompt_versions.schema_prompt / "template.md"
        estimate = gateway.estimate_request(template_path=template_path, payload=payload)
        skip_reason = budget.skip_reason("schema", estimate.estimated_cost_usd)
        if skip_reason is not None:
            route_rows.append(
                _skipped_route_row(
                    "schema",
                    source_attribute_id,
                    skip_reason,
                    estimate.input_tokens,
                    estimate.max_output_tokens,
                    estimate.estimated_cost_usd,
                )
            )
            continue
        result = gateway.call_structured(
            stage="schema",
            prompt_version=config.prompt_versions.schema_prompt,
            template_path=template_path,
            payload=payload,
            output_model=SchemaLLMDecision,
            schema_name="mosaic_schema_decision",
        )
        budget.record("schema", result)
        accepted, fallback_reason = _apply_schema_decision(
            deterministic,
            result,
            set(target_attributes),
            config.routing.schema_confidence_threshold,
        )
        rows_by_source[source_attribute_id].update(accepted)
        route_rows.append(
            _route_row(
                stage="schema",
                case_id=source_attribute_id,
                result=result,
                accepted=fallback_reason is None,
                fallback_reason=fallback_reason,
            )
        )

    assisted_rows = [rows_by_source[str(row["source_attribute_id"])] for row in accepted_rows]
    mappings_path = stage_dir / "assisted_schema_mappings.parquet"
    route_path = stage_dir / "schema_routing_manifest.parquet"
    metrics_path = stage_dir / "assisted_schema_metrics.json"
    quality_path = stage_dir / "schema_quality_cost.json"
    _write_validated_parquet(mappings_path, assisted_rows, AcceptedSchemaMapping)
    _write_parquet(route_path, route_rows)
    _write_json(metrics_path, _schema_metrics(assisted_rows, mapping_gold_path, repo_root))
    _write_json(quality_path, _quality_cost_table(route_rows, config))
    return {
        "artifacts": {
            "assisted_schema_mappings": str(mappings_path),
            "schema_routing_manifest": str(route_path),
            "schema_quality_cost": str(quality_path),
        },
        "metrics": {"assisted_schema_metrics": str(metrics_path)},
    }


def assist_record_linkage(
    *,
    config: M3ExperimentConfig,
    gateway: LLMGateway,
    budget: LLMBudgetTracker,
    repo_root: Path,
    run_dir: Path,
    normalized_records_path: Path,
    pair_features_path: Path,
    pair_predictions_path: Path,
) -> dict[str, dict[str, str]]:
    predictions = pl.read_parquet(pair_predictions_path).to_dicts()
    stage_dir = _stage_dir(run_dir, "matching")
    predictions_path = stage_dir / "assisted_pair_predictions.parquet"
    decisions_path = stage_dir / "assisted_pair_decisions.parquet"
    route_path = stage_dir / "linkage_routing_manifest.parquet"
    metrics_path = stage_dir / "assisted_linkage_metrics.json"
    quality_path = stage_dir / "linkage_quality_cost.json"

    if config.decision_mode == "primary":
        return _primary_record_linkage(
            config=config,
            gateway=gateway,
            budget=budget,
            repo_root=repo_root,
            normalized_records_path=normalized_records_path,
            pair_features_path=pair_features_path,
            predictions=predictions,
            predictions_path=predictions_path,
            decisions_path=decisions_path,
            route_path=route_path,
            metrics_path=metrics_path,
            quality_path=quality_path,
        )

    if not config.llm_assistance.linkage:
        _write_validated_parquet(predictions_path, predictions, PairPrediction)
        _write_parquet(decisions_path, [])
        _write_parquet(route_path, [])
        _write_json(metrics_path, {"metrics_by_split": _classification_metrics(predictions)})
        _write_json(quality_path, _quality_cost_table([], config))
        return {
            "artifacts": {
                "assisted_pair_predictions": str(predictions_path),
                "assisted_pair_decisions": str(decisions_path),
                "linkage_routing_manifest": str(route_path),
                "linkage_quality_cost": str(quality_path),
            },
            "metrics": {"assisted_linkage_metrics": str(metrics_path)},
        }

    features = {
        str(row["candidate_pair_id"]): row
        for row in pl.read_parquet(pair_features_path).to_dicts()
    }
    records = _record_lookup(pl.read_parquet(normalized_records_path).to_dicts())
    route_ids = {
        str(row["candidate_pair_id"])
        for row in predictions
        if config.routing.linkage_min_probability
        <= float(row["match_probability"])
        <= config.routing.linkage_max_probability
    }
    assisted_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []

    for row in predictions:
        candidate_pair_id = str(row["candidate_pair_id"])
        output_row = dict(row)
        if candidate_pair_id not in route_ids:
            assisted_rows.append(output_row)
            continue
        feature_row = features[candidate_pair_id]
        payload = {
            "candidate_pair_id": candidate_pair_id,
            "left_record": records[str(row["left_record_uid"])],
            "right_record": records[str(row["right_record_uid"])],
            "pair_features": _without_ground_truth(feature_row),
            "match_probability": row["match_probability"],
            "deterministic_prediction": row["match_prediction"],
            "threshold": row["threshold"],
        }
        template_path = repo_root / config.prompt_versions.linkage / "template.md"
        estimate = gateway.estimate_request(template_path=template_path, payload=payload)
        skip_reason = budget.skip_reason("linkage", estimate.estimated_cost_usd)
        if skip_reason is not None:
            assisted_rows.append(output_row)
            route_rows.append(
                _skipped_route_row(
                    "linkage",
                    candidate_pair_id,
                    skip_reason,
                    estimate.input_tokens,
                    estimate.max_output_tokens,
                    estimate.estimated_cost_usd,
                )
            )
            continue
        result = gateway.call_structured(
            stage="linkage",
            prompt_version=config.prompt_versions.linkage,
            template_path=template_path,
            payload=payload,
            output_model=LinkageLLMDecision,
            schema_name="mosaic_linkage_decision",
        )
        budget.record("linkage", result)
        output_row, decision_payload, fallback_reason = _apply_linkage_decision(
            output_row,
            result,
            config.routing.linkage_confidence_threshold,
        )
        assisted_rows.append(output_row)
        decision_rows.append(decision_payload)
        route_rows.append(
            _route_row(
                stage="linkage",
                case_id=candidate_pair_id,
                result=result,
                accepted=fallback_reason is None,
                fallback_reason=fallback_reason,
                ground_truth_label=row.get("ground_truth_label"),
                deterministic_prediction=row["match_prediction"],
                assisted_prediction=output_row["match_prediction"],
            )
        )

    _write_validated_parquet(predictions_path, assisted_rows, PairPrediction)
    _write_parquet(decisions_path, decision_rows)
    _write_parquet(route_path, route_rows)
    _write_json(metrics_path, {"metrics_by_split": _classification_metrics(assisted_rows)})
    _write_json(quality_path, _quality_cost_table(route_rows, config))
    return {
        "artifacts": {
            "assisted_pair_predictions": str(predictions_path),
            "assisted_pair_decisions": str(decisions_path),
            "linkage_routing_manifest": str(route_path),
            "linkage_quality_cost": str(quality_path),
        },
        "metrics": {"assisted_linkage_metrics": str(metrics_path)},
    }


def assist_fusion(
    *,
    config: M3ExperimentConfig,
    gateway: LLMGateway,
    budget: LLMBudgetTracker,
    repo_root: Path,
    run_dir: Path,
    baseline_config: Any,
    claims_path: Path,
    clusters_path: Path,
    fused_values_path: Path,
    fusion_artifacts: dict[str, str],
) -> dict[str, dict[str, str]]:
    claims = pl.read_parquet(claims_path).to_dicts()
    clusters = pl.read_parquet(clusters_path).to_dicts()
    fused_rows = pl.read_parquet(fused_values_path).to_dicts()
    stage_dir = _stage_dir(run_dir, "fusion")
    if config.decision_mode == "primary":
        return _primary_fusion(
            config=config,
            gateway=gateway,
            budget=budget,
            repo_root=repo_root,
            stage_dir=stage_dir,
            baseline_config=baseline_config,
            claims=claims,
            clusters=clusters,
            fused_rows=fused_rows,
            fusion_artifacts=fusion_artifacts,
        )
    route_keys = _fusion_route_keys(fusion_artifacts)
    claims_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        claims_by_key[(str(claim["entity_id"]), str(claim["mediated_attribute_name"]))].append(
            claim
        )

    assisted_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    for row in fused_rows:
        key = (str(row["entity_id"]), str(row["mediated_attribute_name"]))
        output_row = dict(row)
        case_id = "|".join(key)
        if key not in route_keys or not config.llm_assistance.fusion:
            assisted_rows.append(output_row)
            if key in route_keys:
                route_rows.append(_skipped_route_row("fusion", case_id, "not_selected"))
            continue
        group = claims_by_key.get(key, [])
        allowed_outputs = _allowed_fusion_outputs(row, group)
        payload = {
            "entity_id": key[0],
            "attribute": key[1],
            "candidate_claims": [_claim_prompt_payload(claim) for claim in group],
            "allowed_outputs": allowed_outputs,
            "deterministic_selected_value": row["selected_value"],
            "deterministic_confidence": row["confidence"],
            "default_supporting_claim_ids": json.loads(str(row["supporting_claim_ids"])),
            "default_contradicting_claim_ids": json.loads(str(row["contradicting_claim_ids"])),
        }
        template_path = repo_root / config.prompt_versions.fusion / "template.md"
        estimate = gateway.estimate_request(template_path=template_path, payload=payload)
        skip_reason = budget.skip_reason("fusion", estimate.estimated_cost_usd)
        if skip_reason is not None:
            assisted_rows.append(output_row)
            route_rows.append(
                _skipped_route_row(
                    "fusion",
                    case_id,
                    skip_reason,
                    estimate.input_tokens,
                    estimate.max_output_tokens,
                    estimate.estimated_cost_usd,
                )
            )
            continue
        result = gateway.call_structured(
            stage="fusion",
            prompt_version=config.prompt_versions.fusion,
            template_path=template_path,
            payload=payload,
            output_model=FusionLLMDecision,
            schema_name="mosaic_fusion_decision",
        )
        budget.record("fusion", result)
        output_row, fallback_reason = _apply_fusion_decision(
            output_row,
            result,
            allowed_outputs,
            group,
            config.routing.fusion_confidence_threshold,
        )
        assisted_rows.append(output_row)
        route_rows.append(
            _route_row(
                stage="fusion",
                case_id=case_id,
                result=result,
                accepted=fallback_reason is None,
                fallback_reason=fallback_reason,
            )
        )

    fused_path = stage_dir / "assisted_fused_values.parquet"
    entities_path = stage_dir / "assisted_integrated_entities.parquet"
    export_path = stage_dir / "assisted_integrated_entities.jsonl"
    route_path = stage_dir / "fusion_routing_manifest.parquet"
    metrics_path = stage_dir / "assisted_fusion_metrics.json"
    quality_path = stage_dir / "fusion_quality_cost.json"
    integrated_rows = _integrated_entities(clusters, assisted_rows)
    _write_validated_parquet(fused_path, assisted_rows, FusedValue)
    _write_validated_parquet(entities_path, integrated_rows, IntegratedEntity)
    export_path.write_text(
        "\n".join(canonical_json(row) for row in integrated_rows)
        + ("\n" if integrated_rows else ""),
        encoding="utf-8",
    )
    fusion_metrics = _fusion_metrics(
        assisted_rows,
        repo_root / baseline_config.fusion.bootstrap_fusion_gold_path
        if baseline_config.fusion.bootstrap_fusion_gold_path is not None
        else None,
        repo_root / baseline_config.fusion.curated_fusion_gold_path
        if baseline_config.fusion.curated_fusion_gold_path is not None
        else None,
        clusters,
    )
    _write_parquet(route_path, route_rows)
    _write_json(metrics_path, fusion_metrics)
    _write_json(quality_path, _quality_cost_table(route_rows, config))
    return {
        "artifacts": {
            "assisted_fused_values": str(fused_path),
            "assisted_integrated_entities": str(entities_path),
            "assisted_integrated_entities_jsonl": str(export_path),
            "fusion_routing_manifest": str(route_path),
            "fusion_quality_cost": str(quality_path),
        },
        "metrics": {"assisted_fusion_metrics": str(metrics_path)},
    }


def _primary_schema_alignment(
    *,
    config: M3ExperimentConfig,
    gateway: LLMGateway,
    budget: LLMBudgetTracker,
    repo_root: Path,
    stage_dir: Path,
    accepted_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    target_attributes: list[str],
    mapping_gold_path: str | None,
) -> dict[str, dict[str, str]]:
    candidates_by_source = _rows_by_key(candidate_rows, "source_attribute_id")
    rows_by_source = {str(row["source_attribute_id"]): dict(row) for row in accepted_rows}
    route_rows: list[dict[str, Any]] = []
    target_set = set(target_attributes)
    template_path = repo_root / config.prompt_versions.schema_prompt / "template.md"

    case_payloads = []
    for source_attribute_id in sorted(rows_by_source):
        deterministic = rows_by_source[source_attribute_id]
        case_payloads.append(
            {
                "case_id": source_attribute_id,
                "source_attribute_id": source_attribute_id,
                "attribute_name": deterministic["attribute_name"],
                "source_id": deterministic["source_id"],
                "deterministic_candidates": [
                    _without_ground_truth(row)
                    for row in candidates_by_source.get(source_attribute_id, [])[:8]
                ],
                "allowed_targets": target_attributes + ["UNMAPPED", "ABSTAIN"],
            }
        )

    progress_path = stage_dir / "schema_batch_progress.jsonl"
    progress_rows = load_progress(progress_path, {str(case["case_id"]) for case in case_payloads})
    for row in progress_rows.values():
        rows_by_source[str(row["case_id"])] = dict(row["output"])
        route_rows.append(dict(row["route"]))
    _restore_budget_from_routes(
        budget,
        "schema",
        [dict(row["route"]) for row in progress_rows.values()],
    )
    remaining_cases = [
        case for case in case_payloads if str(case["case_id"]) not in progress_rows
    ]

    for batch in _chunks(remaining_cases, config.routing.schema_batch_size):
        payload = {"cases": batch}
        estimate = gateway.estimate_request(template_path=template_path, payload=payload)
        skip_reason = budget.skip_reason("schema", estimate.estimated_cost_usd)
        progress_batch: list[dict[str, Any]] = []
        if skip_reason is not None or not config.llm_assistance.schema_enabled:
            for case in batch:
                case_id = str(case["case_id"])
                output_row = _schema_primary_default(
                    rows_by_source[case_id], "unselected_primary_default"
                )
                rows_by_source[case_id] = output_row
                route_row = _primary_default_route_row(
                    "schema",
                    case_id,
                    skip_reason or "not_selected",
                    estimate.input_tokens,
                    estimate.max_output_tokens,
                    estimate.estimated_cost_usd,
                )
                route_rows.append(route_row)
                progress_batch.append(
                    {"case_id": case_id, "output": output_row, "route": route_row}
                )
            append_progress(progress_path, progress_batch)
            continue
        result = gateway.call_structured(
            stage="schema_batch",
            prompt_version=config.prompt_versions.schema_prompt,
            template_path=template_path,
            payload=payload,
            output_model=SchemaLLMBatchDecision,
            schema_name="mosaic_schema_batch_decision",
        )
        budget.record("schema", result)
        try:
            decisions = batch_decisions_by_case(
                result.parsed_response,
                [str(case["case_id"]) for case in batch],
            )
            batch_error = None
        except ValueError as exc:
            decisions = {}
            batch_error = str(exc)
        for index, case in enumerate(batch):
            case_id = str(case["case_id"])
            deterministic = rows_by_source[case_id]
            if batch_error is not None:
                output_row = _schema_primary_default(deterministic, batch_error)
                rows_by_source[case_id] = output_row
                route_row = _batch_route_row(
                    "schema",
                    case_id,
                    result,
                    index,
                    accepted=False,
                    fallback_reason="batch_validation_error",
                    defaulted=True,
                )
                route_rows.append(route_row)
                progress_batch.append(
                    {"case_id": case_id, "output": output_row, "route": route_row}
                )
                continue
            output, fallback_reason = _apply_primary_schema_decision(
                deterministic,
                decisions[case_id],
                target_set,
                config.routing.schema_confidence_threshold,
            )
            rows_by_source[case_id] = output
            route_row = _batch_route_row(
                "schema",
                case_id,
                result,
                index,
                accepted=fallback_reason is None,
                fallback_reason=fallback_reason,
                defaulted=fallback_reason is not None,
            )
            route_rows.append(route_row)
            progress_batch.append({"case_id": case_id, "output": output, "route": route_row})
        append_progress(progress_path, progress_batch)

    assisted_rows = [rows_by_source[str(row["source_attribute_id"])] for row in accepted_rows]
    mappings_path = stage_dir / "assisted_schema_mappings.parquet"
    route_path = stage_dir / "schema_routing_manifest.parquet"
    metrics_path = stage_dir / "assisted_schema_metrics.json"
    quality_path = stage_dir / "schema_quality_cost.json"
    _write_validated_parquet(mappings_path, assisted_rows, AcceptedSchemaMapping)
    _write_parquet(route_path, route_rows)
    _write_json(metrics_path, _schema_metrics(assisted_rows, mapping_gold_path, repo_root))
    _write_json(quality_path, _quality_cost_table(route_rows, config))
    return {
        "artifacts": {
            "assisted_schema_mappings": str(mappings_path),
            "schema_routing_manifest": str(route_path),
            "schema_quality_cost": str(quality_path),
        },
        "metrics": {"assisted_schema_metrics": str(metrics_path)},
    }


def _primary_record_linkage(
    *,
    config: M3ExperimentConfig,
    gateway: LLMGateway,
    budget: LLMBudgetTracker,
    repo_root: Path,
    normalized_records_path: Path,
    pair_features_path: Path,
    predictions: list[dict[str, Any]],
    predictions_path: Path,
    decisions_path: Path,
    route_path: Path,
    metrics_path: Path,
    quality_path: Path,
) -> dict[str, dict[str, str]]:
    features = {
        str(row["candidate_pair_id"]): row
        for row in pl.read_parquet(pair_features_path).to_dicts()
    }
    records = _record_lookup(pl.read_parquet(normalized_records_path).to_dicts())
    selected_ids = {
        str(row["candidate_pair_id"])
        for row in sorted(
            predictions,
            key=lambda item: float(item.get("match_probability", 0.0) or 0.0),
            reverse=True,
        )[: config.routing.primary_linkage_case_cap]
    }
    rows_by_pair: dict[str, dict[str, Any]] = {}
    case_payloads: list[dict[str, Any]] = []
    for row in predictions:
        candidate_pair_id = str(row["candidate_pair_id"])
        output_row = _linkage_primary_default(row, "unselected_primary_default")
        rows_by_pair[candidate_pair_id] = output_row
        if candidate_pair_id not in selected_ids or not config.llm_assistance.linkage:
            continue
        feature_row = features[candidate_pair_id]
        case_payloads.append(
            {
                "case_id": candidate_pair_id,
                "candidate_pair_id": candidate_pair_id,
                "left_record": records[str(row["left_record_uid"])],
                "right_record": records[str(row["right_record_uid"])],
                "pair_features": _without_ground_truth(feature_row),
                "match_probability": row["match_probability"],
                "deterministic_prediction": row["match_prediction"],
                "threshold": row["threshold"],
            }
        )

    route_rows: list[dict[str, Any]] = [
        _primary_summary_route_row(
            "linkage",
            eligible_count=len(predictions),
            unselected_default_count=len(predictions) - len(case_payloads),
        )
    ]
    decision_rows: list[dict[str, Any]] = []
    template_path = repo_root / config.prompt_versions.linkage / "template.md"
    progress_path = predictions_path.parent / "linkage_batch_progress.jsonl"
    progress_rows = load_progress(progress_path, {str(case["case_id"]) for case in case_payloads})
    for row in progress_rows.values():
        rows_by_pair[str(row["case_id"])] = dict(row["output"])
        route_rows.append(dict(row["route"]))
        if row.get("decision") is not None:
            decision_rows.append(dict(row["decision"]))
    _restore_budget_from_routes(
        budget,
        "linkage",
        [dict(row["route"]) for row in progress_rows.values()],
    )
    remaining_cases = [
        case for case in case_payloads if str(case["case_id"]) not in progress_rows
    ]
    for batch in _chunks(remaining_cases, config.routing.linkage_batch_size):
        payload = {"cases": batch}
        estimate = gateway.estimate_request(template_path=template_path, payload=payload)
        skip_reason = budget.skip_reason("linkage", estimate.estimated_cost_usd)
        progress_batch: list[dict[str, Any]] = []
        if skip_reason is not None:
            for case in batch:
                case_id = str(case["case_id"])
                route_row = _primary_default_route_row(
                    "linkage",
                    case_id,
                    skip_reason,
                    estimate.input_tokens,
                    estimate.max_output_tokens,
                    estimate.estimated_cost_usd,
                )
                route_rows.append(route_row)
                progress_batch.append(
                    {
                        "case_id": case_id,
                        "output": rows_by_pair[case_id],
                        "route": route_row,
                        "decision": None,
                    }
                )
            append_progress(progress_path, progress_batch)
            continue
        result = gateway.call_structured(
            stage="linkage_batch",
            prompt_version=config.prompt_versions.linkage,
            template_path=template_path,
            payload=payload,
            output_model=LinkageLLMBatchDecision,
            schema_name="mosaic_linkage_batch_decision",
        )
        budget.record("linkage", result)
        try:
            decisions = batch_decisions_by_case(
                result.parsed_response,
                [str(case["case_id"]) for case in batch],
            )
            batch_error = None
        except ValueError as exc:
            decisions = {}
            batch_error = str(exc)
        for index, case in enumerate(batch):
            case_id = str(case["case_id"])
            deterministic = rows_by_pair[case_id]
            fallback_reason: str | None
            decision_row = {
                "candidate_pair_id": case_id,
                "request_id": result.request_id,
                "validation_status": result.validation_status,
                "failure_type": result.failure_type or batch_error,
                "raw_response": result.raw_response,
                "parsed_response": canonical_json(decisions.get(case_id, {})),
            }
            decision_rows.append(decision_row)
            if batch_error is not None:
                fallback_reason = "batch_validation_error"
                output_row = _linkage_primary_default(deterministic, fallback_reason)
            else:
                output_row, fallback_reason = _apply_primary_linkage_decision(
                    deterministic,
                    decisions[case_id],
                    config.routing.linkage_confidence_threshold,
                )
            rows_by_pair[case_id] = output_row
            route_row = _batch_route_row(
                "linkage",
                case_id,
                result,
                index,
                accepted=fallback_reason is None,
                fallback_reason=fallback_reason,
                defaulted=fallback_reason is not None,
                ground_truth_label=deterministic.get("ground_truth_label"),
                deterministic_prediction=deterministic["match_prediction"],
                assisted_prediction=output_row["match_prediction"],
            )
            route_rows.append(route_row)
            progress_batch.append(
                {
                    "case_id": case_id,
                    "output": output_row,
                    "route": route_row,
                    "decision": decision_row,
                }
            )
        append_progress(progress_path, progress_batch)

    assisted_rows = [rows_by_pair[str(row["candidate_pair_id"])] for row in predictions]
    _write_validated_parquet(predictions_path, assisted_rows, PairPrediction)
    _write_parquet(decisions_path, decision_rows)
    _write_parquet(route_path, route_rows)
    _write_json(metrics_path, {"metrics_by_split": _classification_metrics(assisted_rows)})
    _write_json(quality_path, _quality_cost_table(route_rows, config))
    return {
        "artifacts": {
            "assisted_pair_predictions": str(predictions_path),
            "assisted_pair_decisions": str(decisions_path),
            "linkage_routing_manifest": str(route_path),
            "linkage_quality_cost": str(quality_path),
        },
        "metrics": {"assisted_linkage_metrics": str(metrics_path)},
    }


def _primary_fusion(
    *,
    config: M3ExperimentConfig,
    gateway: LLMGateway,
    budget: LLMBudgetTracker,
    repo_root: Path,
    stage_dir: Path,
    baseline_config: Any,
    claims: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    fused_rows: list[dict[str, Any]],
    fusion_artifacts: dict[str, str],
) -> dict[str, dict[str, str]]:
    route_keys = _fusion_route_keys(fusion_artifacts)
    claims_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        claims_by_key[(str(claim["entity_id"]), str(claim["mediated_attribute_name"]))].append(
            claim
        )
    eligible_rows = [
        row
        for row in fused_rows
        if (str(row["entity_id"]), str(row["mediated_attribute_name"])) in route_keys
    ]
    selected_keys = {
        (str(row["entity_id"]), str(row["mediated_attribute_name"]))
        for row in sorted(
            eligible_rows,
            key=lambda item: (
                float(item.get("confidence", 1.0) or 1.0),
                -len(json.loads(str(item.get("alternative_values", "[]")))),
            ),
        )[: config.routing.primary_fusion_case_cap]
    }
    assisted_rows: list[dict[str, Any]] = []
    case_payloads: list[dict[str, Any]] = []
    row_by_case: dict[str, dict[str, Any]] = {}
    for row in fused_rows:
        key = (str(row["entity_id"]), str(row["mediated_attribute_name"]))
        case_id = "|".join(key)
        if key in route_keys and key not in selected_keys:
            assisted_rows.append(_fusion_primary_default(row, "unselected_primary_default"))
            continue
        if key not in selected_keys or not config.llm_assistance.fusion:
            assisted_rows.append(dict(row))
            continue
        group = claims_by_key.get(key, [])
        row_by_case[case_id] = dict(row)
        case_payloads.append(
            {
                "case_id": case_id,
                "entity_id": key[0],
                "attribute": key[1],
                "candidate_claims": [_claim_prompt_payload(claim) for claim in group],
                "allowed_outputs": _allowed_fusion_outputs(row, group),
                "deterministic_selected_value": row["selected_value"],
                "deterministic_confidence": row["confidence"],
            }
        )

    route_rows: list[dict[str, Any]] = [
        _primary_summary_route_row(
            "fusion",
            eligible_count=len(eligible_rows),
            unselected_default_count=max(0, len(eligible_rows) - len(case_payloads)),
        )
    ]
    template_path = repo_root / config.prompt_versions.fusion / "template.md"
    progress_path = stage_dir / "fusion_batch_progress.jsonl"
    progress_rows = load_progress(progress_path, {str(case["case_id"]) for case in case_payloads})
    for row in progress_rows.values():
        assisted_rows.append(dict(row["output"]))
        route_rows.append(dict(row["route"]))
    _restore_budget_from_routes(
        budget,
        "fusion",
        [dict(row["route"]) for row in progress_rows.values()],
    )
    remaining_cases = [
        case for case in case_payloads if str(case["case_id"]) not in progress_rows
    ]
    for batch in _chunks(remaining_cases, config.routing.fusion_batch_size):
        payload = {"cases": batch}
        estimate = gateway.estimate_request(template_path=template_path, payload=payload)
        skip_reason = budget.skip_reason("fusion", estimate.estimated_cost_usd)
        progress_batch: list[dict[str, Any]] = []
        if skip_reason is not None:
            for case in batch:
                case_id = str(case["case_id"])
                output_row = _fusion_primary_default(row_by_case[case_id], skip_reason)
                assisted_rows.append(output_row)
                route_row = _primary_default_route_row(
                    "fusion",
                    case_id,
                    skip_reason,
                    estimate.input_tokens,
                    estimate.max_output_tokens,
                    estimate.estimated_cost_usd,
                )
                route_rows.append(route_row)
                progress_batch.append(
                    {"case_id": case_id, "output": output_row, "route": route_row}
                )
            append_progress(progress_path, progress_batch)
            continue
        result = gateway.call_structured(
            stage="fusion_batch",
            prompt_version=config.prompt_versions.fusion,
            template_path=template_path,
            payload=payload,
            output_model=FusionLLMBatchDecision,
            schema_name="mosaic_fusion_batch_decision",
        )
        budget.record("fusion", result)
        try:
            decisions = batch_decisions_by_case(
                result.parsed_response,
                [str(case["case_id"]) for case in batch],
            )
            batch_error = None
        except ValueError as exc:
            decisions = {}
            batch_error = str(exc)
        for index, case in enumerate(batch):
            case_id = str(case["case_id"])
            deterministic = row_by_case[case_id]
            fallback_reason: str | None
            group = claims_by_key.get(
                (str(deterministic["entity_id"]), str(deterministic["mediated_attribute_name"])),
                [],
            )
            if batch_error is not None:
                fallback_reason = "batch_validation_error"
                output_row = _fusion_primary_default(deterministic, fallback_reason)
            else:
                output_row, fallback_reason = _apply_primary_fusion_decision(
                    deterministic,
                    decisions[case_id],
                    _allowed_fusion_outputs(deterministic, group),
                    group,
                    config.routing.fusion_confidence_threshold,
                )
            assisted_rows.append(output_row)
            route_row = _batch_route_row(
                "fusion",
                case_id,
                result,
                index,
                accepted=fallback_reason is None,
                fallback_reason=fallback_reason,
                defaulted=fallback_reason is not None,
            )
            route_rows.append(route_row)
            progress_batch.append({"case_id": case_id, "output": output_row, "route": route_row})
        append_progress(progress_path, progress_batch)

    fused_path = stage_dir / "assisted_fused_values.parquet"
    entities_path = stage_dir / "assisted_integrated_entities.parquet"
    export_path = stage_dir / "assisted_integrated_entities.jsonl"
    route_path = stage_dir / "fusion_routing_manifest.parquet"
    metrics_path = stage_dir / "assisted_fusion_metrics.json"
    quality_path = stage_dir / "fusion_quality_cost.json"
    integrated_rows = _integrated_entities(clusters, assisted_rows)
    _write_validated_parquet(fused_path, assisted_rows, FusedValue)
    _write_validated_parquet(entities_path, integrated_rows, IntegratedEntity)
    export_path.write_text(
        "\n".join(canonical_json(row) for row in integrated_rows)
        + ("\n" if integrated_rows else ""),
        encoding="utf-8",
    )
    fusion_metrics = _fusion_metrics(
        assisted_rows,
        repo_root / baseline_config.fusion.bootstrap_fusion_gold_path
        if baseline_config.fusion.bootstrap_fusion_gold_path is not None
        else None,
        repo_root / baseline_config.fusion.curated_fusion_gold_path
        if baseline_config.fusion.curated_fusion_gold_path is not None
        else None,
        clusters,
    )
    _write_parquet(route_path, route_rows)
    _write_json(metrics_path, fusion_metrics)
    _write_json(quality_path, _quality_cost_table(route_rows, config))
    return {
        "artifacts": {
            "assisted_fused_values": str(fused_path),
            "assisted_integrated_entities": str(entities_path),
            "assisted_integrated_entities_jsonl": str(export_path),
            "fusion_routing_manifest": str(route_path),
            "fusion_quality_cost": str(quality_path),
        },
        "metrics": {"assisted_fusion_metrics": str(metrics_path)},
    }


def batch_decisions_by_case(
    parsed_response: dict[str, Any] | None,
    expected_case_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if parsed_response is None or not isinstance(parsed_response.get("decisions"), list):
        raise ValueError("batch response missing decisions")
    expected = set(expected_case_ids)
    seen: set[str] = set()
    decisions: dict[str, dict[str, Any]] = {}
    for item in parsed_response["decisions"]:
        if not isinstance(item, dict):
            raise ValueError("batch decision is not an object")
        case_id = str(item.get("case_id", ""))
        if case_id not in expected:
            raise ValueError(f"unknown case_id: {case_id}")
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        decisions[case_id] = item
    missing = sorted(expected - seen)
    if missing:
        raise ValueError(f"missing case_id: {missing[0]}")
    return decisions


def _restore_budget_from_routes(
    budget: LLMBudgetTracker,
    stage: str,
    route_rows: Iterable[dict[str, Any]],
) -> None:
    for row in route_rows:
        if not row.get("call_count_charge"):
            continue
        budget.run_call_count += 1
        budget.stage_call_counts[stage] += 1
        budget.run_cost_usd += float(row.get("estimated_cost_usd", 0.0) or 0.0)


def _apply_primary_schema_decision(
    deterministic: dict[str, Any],
    parsed: dict[str, Any],
    target_attributes: set[str],
    confidence_threshold: float,
) -> tuple[dict[str, Any], str | None]:
    target = str(parsed["target_attribute"])
    if bool(parsed.get("abstain")) or target == "ABSTAIN":
        return _schema_primary_default(deterministic, "abstention"), "abstention"
    if target != "UNMAPPED" and target not in target_attributes:
        return _schema_primary_default(deterministic, "unsupported_target"), "unsupported_target"
    if float(parsed["confidence"]) < confidence_threshold:
        return _schema_primary_default(deterministic, "low_confidence"), "low_confidence"
    decision = "unmapped" if target == "UNMAPPED" else "accepted"
    return {
        **deterministic,
        "target_attribute_name": target,
        "decision": decision,
        "method": "llm_primary_schema_v1",
    }, None


def _schema_primary_default(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **row,
        "target_attribute_name": "UNMAPPED",
        "decision": "unmapped",
        "method": f"llm_primary_default_schema_v1:{reason}",
    }


def _apply_primary_linkage_decision(
    deterministic: dict[str, Any],
    parsed: dict[str, Any],
    confidence_threshold: float,
) -> tuple[dict[str, Any], str | None]:
    if bool(parsed.get("abstain")) or parsed["decision"] == "abstain":
        return _linkage_primary_default(deterministic, "abstention"), "abstention"
    if float(parsed["confidence"]) < confidence_threshold:
        return _linkage_primary_default(deterministic, "low_confidence"), "low_confidence"
    output = dict(deterministic)
    output["match_prediction"] = 1 if parsed["decision"] == "match" else 0
    output["model_status"] = "llm_primary_linkage_v1"
    return output, None


def _linkage_primary_default(row: dict[str, Any], reason: str) -> dict[str, Any]:
    output = dict(row)
    output["match_prediction"] = 0
    output["model_status"] = f"llm_primary_default_non_match_v1:{reason}"
    return output


def _apply_primary_fusion_decision(
    deterministic: dict[str, Any],
    parsed: dict[str, Any],
    allowed_outputs: list[str],
    known_claims: list[dict[str, Any]],
    confidence_threshold: float,
) -> tuple[dict[str, Any], str | None]:
    selected_value = str(parsed["selected_value"])
    supporting = {str(value) for value in parsed["supporting_claim_ids"]}
    contradicting = {str(value) for value in parsed["contradicting_claim_ids"]}
    known_claim_ids = {str(claim["claim_id"]) for claim in known_claims}
    if bool(parsed.get("abstain")) or selected_value == "ABSTAIN":
        return _fusion_primary_default(deterministic, "abstention"), "abstention"
    if selected_value not in allowed_outputs:
        return _fusion_primary_default(deterministic, "unsupported_value"), "unsupported_value"
    if not supporting or not supporting <= known_claim_ids or not contradicting <= known_claim_ids:
        return _fusion_primary_default(deterministic, "unknown_claim_id"), "unknown_claim_id"
    if not _fusion_value_supported_by_claims(selected_value, supporting, known_claims):
        return _fusion_primary_default(deterministic, "unsupported_value"), "unsupported_value"
    if not _fusion_units_compatible(selected_value, supporting, known_claims, deterministic):
        return _fusion_primary_default(deterministic, "incompatible_unit"), "incompatible_unit"
    if float(parsed["confidence"]) < confidence_threshold:
        return _fusion_primary_default(deterministic, "low_confidence"), "low_confidence"
    output = dict(deterministic)
    output.update(
        {
            "selected_value": selected_value,
            "fusion_method": "llm_primary_fusion_v1",
            "confidence": float(parsed["confidence"]),
            "supporting_claim_ids": json.dumps(sorted(supporting)),
            "contradicting_claim_ids": json.dumps(sorted(contradicting)),
            "llm_used": True,
            "abstained": False,
        }
    )
    return output, None


def _fusion_primary_default(row: dict[str, Any], reason: str) -> dict[str, Any]:
    output = dict(row)
    output.update(
        {
            "selected_value": "",
            "selected_unit": None,
            "fusion_method": f"llm_primary_default_abstain_v1:{reason}",
            "confidence": 0.0,
            "supporting_claim_ids": "[]",
            "contradicting_claim_ids": "[]",
            "llm_used": False,
            "abstained": True,
        }
    )
    return output


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    chunk_size = max(1, size)
    for index in range(0, len(rows), chunk_size):
        yield rows[index : index + chunk_size]


def _schema_route_ids(
    config: M3ExperimentConfig,
    accepted_rows: list[dict[str, Any]],
    baseline_artifacts: dict[str, str],
) -> set[str]:
    route_ids: set[str] = set()
    for row in accepted_rows:
        margin = float(row.get("score_margin", 0.0))
        score = float(row.get("score_total", 0.0))
        if margin <= config.routing.schema_low_margin_threshold:
            route_ids.add(str(row["source_attribute_id"]))
        if (
            str(row["target_attribute_name"]) == "UNMAPPED"
            and score >= config.routing.schema_unmapped_min_score
        ):
            route_ids.add(str(row["source_attribute_id"]))
    for name in ("schema_ambiguous_candidates", "schema_unmapped_gold"):
        path = baseline_artifacts.get(name)
        if path is None or not Path(path).exists():
            continue
        frame = pl.read_parquet(path)
        if "source_attribute_id" in frame.columns:
            route_ids.update(str(value) for value in frame["source_attribute_id"].to_list())
    return route_ids


def _apply_schema_decision(
    deterministic: dict[str, Any],
    result: LLMCallResult,
    target_attributes: set[str],
    confidence_threshold: float,
) -> tuple[dict[str, Any], str | None]:
    if result.validation_status != "valid" or result.parsed_response is None:
        return dict(deterministic), result.failure_type or "invalid_output"
    parsed = result.parsed_response
    target = str(parsed["target_attribute"])
    if bool(parsed.get("abstain")) or target == "ABSTAIN":
        return dict(deterministic), "abstention"
    if target != "UNMAPPED" and target not in target_attributes:
        return dict(deterministic), "unsupported_target"
    if float(parsed["confidence"]) < confidence_threshold:
        return dict(deterministic), "low_confidence"
    decision = "unmapped" if target == "UNMAPPED" else "accepted"
    return {
        **deterministic,
        "target_attribute_name": target,
        "decision": decision,
        "method": "llm_assisted_schema_v1",
    }, None


def _apply_linkage_decision(
    deterministic: dict[str, Any],
    result: LLMCallResult,
    confidence_threshold: float,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    decision_payload = {
        "candidate_pair_id": deterministic["candidate_pair_id"],
        "request_id": result.request_id,
        "validation_status": result.validation_status,
        "failure_type": result.failure_type,
        "raw_response": result.raw_response,
        "parsed_response": canonical_json(result.parsed_response or {}),
    }
    if result.validation_status != "valid" or result.parsed_response is None:
        return deterministic, decision_payload, result.failure_type or "invalid_output"
    parsed = result.parsed_response
    if bool(parsed.get("abstain")) or parsed["decision"] == "abstain":
        return deterministic, decision_payload, "abstention"
    if float(parsed["confidence"]) < confidence_threshold:
        return deterministic, decision_payload, "low_confidence"
    output = dict(deterministic)
    output["match_prediction"] = 1 if parsed["decision"] == "match" else 0
    output["model_status"] = "llm_assisted_linkage_v1"
    return output, decision_payload, None


def _apply_fusion_decision(
    deterministic: dict[str, Any],
    result: LLMCallResult,
    allowed_outputs: list[str],
    known_claims: list[dict[str, Any]],
    confidence_threshold: float,
) -> tuple[dict[str, Any], str | None]:
    if result.validation_status != "valid" or result.parsed_response is None:
        return dict(deterministic), result.failure_type or "invalid_output"
    parsed = result.parsed_response
    selected_value = str(parsed["selected_value"])
    supporting = {str(value) for value in parsed["supporting_claim_ids"]}
    contradicting = {str(value) for value in parsed["contradicting_claim_ids"]}
    known_claim_ids = {str(claim["claim_id"]) for claim in known_claims}
    if bool(parsed.get("abstain")) or selected_value == "ABSTAIN":
        output = dict(deterministic)
        output["abstained"] = True
        return output, "abstention"
    if selected_value not in allowed_outputs:
        return dict(deterministic), "unsupported_value"
    if not supporting or not supporting <= known_claim_ids or not contradicting <= known_claim_ids:
        return dict(deterministic), "unknown_claim_id"
    if not _fusion_value_supported_by_claims(selected_value, supporting, known_claims):
        return dict(deterministic), "unsupported_value"
    if not _fusion_units_compatible(selected_value, supporting, known_claims, deterministic):
        return dict(deterministic), "incompatible_unit"
    if float(parsed["confidence"]) < confidence_threshold:
        return dict(deterministic), "low_confidence"
    output = dict(deterministic)
    output.update(
        {
            "selected_value": selected_value,
            "fusion_method": "llm_assisted_fusion_v1",
            "confidence": float(parsed["confidence"]),
            "supporting_claim_ids": json.dumps(sorted(supporting)),
            "contradicting_claim_ids": json.dumps(sorted(contradicting)),
            "llm_used": True,
            "abstained": False,
        }
    )
    return output, None


def _fusion_route_keys(fusion_artifacts: dict[str, str]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for name in (
        "baseline_error_candidates",
        "fusion_curated_errors",
        "fusion_unsupported_values",
        "fusion_high_conflict_attributes",
    ):
        path = fusion_artifacts.get(name)
        if path is None or not Path(path).exists():
            continue
        frame = pl.read_parquet(path)
        if {"entity_id", "mediated_attribute_name"} <= set(frame.columns):
            keys.update(
                (str(row["entity_id"]), str(row["mediated_attribute_name"]))
                for row in frame.to_dicts()
            )
    return keys


def _allowed_fusion_outputs(row: dict[str, Any], claims: list[dict[str, Any]]) -> list[str]:
    values = {str(row["selected_value"])}
    values.update(str(value) for value in json.loads(str(row["alternative_values"])))
    values.update(str(claim["normalized_value"]) for claim in claims)
    return sorted(value for value in values if value) + ["ABSTAIN"]


def _claim_prompt_payload(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": claim["claim_id"],
        "source_id": claim["source_id"],
        "raw_value": claim["raw_value"],
        "normalized_value": claim["normalized_value"],
        "unit": claim["unit"],
        "extraction_confidence": claim["extraction_confidence"],
    }


def _rows_by_key(rows: Iterable[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    return grouped


def _without_ground_truth(row: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in row.items()
        if "ground_truth" not in str(key).lower() and "gold" not in str(key).lower()
    }


def _fusion_value_supported_by_claims(
    selected_value: str, supporting: set[str], known_claims: list[dict[str, Any]]
) -> bool:
    return any(
        str(claim["claim_id"]) in supporting
        and str(claim["normalized_value"]) == selected_value
        for claim in known_claims
    )


def _fusion_units_compatible(
    selected_value: str,
    supporting: set[str],
    known_claims: list[dict[str, Any]],
    deterministic: dict[str, Any],
) -> bool:
    selected_units = {
        _normalized_unit(claim.get("unit"))
        for claim in known_claims
        if str(claim["normalized_value"]) == selected_value and str(claim["claim_id"]) in supporting
    }
    competing_units = {
        _normalized_unit(claim.get("unit"))
        for claim in known_claims
        if str(claim["normalized_value"]) == selected_value
    }
    selected_units.discard("")
    competing_units.discard("")
    deterministic_unit = _normalized_unit(deterministic.get("selected_unit"))
    if deterministic_unit and selected_units and deterministic_unit not in selected_units:
        return False
    if not selected_units or not competing_units:
        return True
    return not selected_units.isdisjoint(competing_units)


def _normalized_unit(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _skipped_route_row(
    stage: str,
    case_id: str,
    reason: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "case_id": case_id,
        "selected": False,
        "accepted": False,
        "fallback_applied": False,
        "fallback_reason": reason,
        "request_id": None,
        "input_hash": None,
        "validation_status": "not_called",
        "failure_type": None,
        "cache_status": None,
        "latency_ms": 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimated_cost_usd,
    }


def _primary_summary_route_row(
    stage: str,
    *,
    eligible_count: int,
    unselected_default_count: int,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "case_id": "__primary_summary__",
        "selected": False,
        "accepted": False,
        "fallback_applied": False,
        "fallback_reason": "summary",
        "request_id": None,
        "input_hash": None,
        "validation_status": "summary",
        "failure_type": None,
        "cache_status": None,
        "latency_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "summary": True,
        "eligible_count": eligible_count,
        "unselected_default_count": unselected_default_count,
        "defaulted": False,
        "call_count_charge": 0,
    }


def _primary_default_route_row(
    stage: str,
    case_id: str,
    reason: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
) -> dict[str, Any]:
    row = _skipped_route_row(
        stage,
        case_id,
        reason,
        input_tokens,
        output_tokens,
        estimated_cost_usd,
    )
    row["defaulted"] = True
    row["primary_default_reason"] = reason
    row["call_count_charge"] = 0
    return row


def _batch_route_row(
    stage: str,
    case_id: str,
    result: LLMCallResult,
    batch_index: int,
    *,
    accepted: bool,
    fallback_reason: str | None,
    defaulted: bool,
    ground_truth_label: Any | None = None,
    deterministic_prediction: Any | None = None,
    assisted_prediction: Any | None = None,
) -> dict[str, Any]:
    row = _route_row(
        stage=stage,
        case_id=case_id,
        result=result,
        accepted=accepted,
        fallback_reason=fallback_reason,
        ground_truth_label=ground_truth_label,
        deterministic_prediction=deterministic_prediction,
        assisted_prediction=assisted_prediction,
    )
    charged = batch_index == 0
    row["batch_index"] = batch_index
    row["call_count_charge"] = 1 if charged else 0
    row["defaulted"] = defaulted
    if not charged:
        row["latency_ms"] = 0
        row["input_tokens"] = 0
        row["output_tokens"] = 0
        row["estimated_cost_usd"] = 0.0
    return row


def _route_row(
    *,
    stage: str,
    case_id: str,
    result: LLMCallResult,
    accepted: bool,
    fallback_reason: str | None,
    ground_truth_label: Any | None = None,
    deterministic_prediction: Any | None = None,
    assisted_prediction: Any | None = None,
) -> dict[str, Any]:
    row = {
        "stage": stage,
        "case_id": case_id,
        "selected": True,
        "accepted": accepted,
        "fallback_applied": fallback_reason is not None,
        "fallback_reason": fallback_reason,
        "request_id": result.request_id,
        "input_hash": result.input_hash,
        "validation_status": result.validation_status,
        "failure_type": result.failure_type,
        "cache_status": result.cache_status,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "estimated_cost_usd": result.estimated_cost_usd,
        "call_count_charge": 1,
        "defaulted": fallback_reason is not None,
    }
    if ground_truth_label is not None:
        row["ground_truth_label"] = ground_truth_label
        row["deterministic_prediction"] = deterministic_prediction
        row["assisted_prediction"] = assisted_prediction
        row["assisted_correct"] = int(assisted_prediction == ground_truth_label)
    return row


def _quality_cost_table(
    route_rows: list[dict[str, Any]], config: M3ExperimentConfig
) -> dict[str, Any]:
    summary_rows = [row for row in route_rows if row.get("summary")]
    selected = [row for row in route_rows if row.get("selected")]
    charged_call_count = sum(int(row.get("call_count_charge", 1) or 0) for row in selected)
    total_cost = sum(float(row.get("estimated_cost_usd", 0.0) or 0.0) for row in selected)
    correct_rows = [row for row in selected if "assisted_correct" in row]
    unselected_default_count = sum(
        int(row.get("unselected_default_count", 0) or 0) for row in summary_rows
    )
    eligible_count = (
        sum(int(row.get("eligible_count", 0) or 0) for row in summary_rows)
        if summary_rows
        else len(route_rows)
    )
    return {
        "eligible_count": eligible_count,
        "selected_count": len(selected),
        "llm_call_count": charged_call_count,
        "accepted_count": sum(1 for row in selected if row.get("accepted")),
        "defaulted_count": sum(1 for row in selected if row.get("defaulted"))
        + unselected_default_count,
        "unselected_default_count": unselected_default_count,
        "cache_hit_count": sum(
            int(row.get("call_count_charge", 1) or 0)
            for row in selected
            if row.get("cache_status") == "hit"
        ),
        "invalid_output_count": sum(
            1 for row in selected if row.get("validation_status") != "valid"
        ),
        "abstention_count": sum(
            1 for row in selected if row.get("fallback_reason") == "abstention"
        ),
        "fallback_count": sum(1 for row in selected if row.get("fallback_applied")),
        "input_tokens": sum(int(row.get("input_tokens", 0) or 0) for row in selected),
        "output_tokens": sum(int(row.get("output_tokens", 0) or 0) for row in selected),
        "estimated_cost_usd": total_cost,
        "average_latency_ms": (
            sum(int(row.get("latency_ms", 0) or 0) for row in selected) / charged_call_count
            if charged_call_count
            else 0.0
        ),
        "labeled_decision_count": len(correct_rows),
        "assisted_correct_count": sum(int(row["assisted_correct"]) for row in correct_rows),
        "frontier": _quality_cost_frontier(route_rows, config),
    }


def _quality_cost_frontier(
    route_rows: list[dict[str, Any]], config: M3ExperimentConfig
) -> list[dict[str, Any]]:
    selected = [row for row in route_rows if row.get("selected")]
    budgets = {0, len(selected)}
    if config.routing.max_cases_per_stage is not None:
        budgets.add(min(config.routing.max_cases_per_stage, len(selected)))
    if config.routing.per_run_call_budget is not None:
        budgets.add(min(config.routing.per_run_call_budget, len(selected)))
    budgets.update(range(1, len(selected) + 1))
    points: list[dict[str, Any]] = []
    for budget in sorted(budgets):
        prefix = selected[:budget]
        labeled = [row for row in prefix if "assisted_correct" in row]
        points.append(
            {
                "call_budget": budget,
                "selected_count": len(prefix),
                "input_tokens": sum(int(row.get("input_tokens", 0) or 0) for row in prefix),
                "output_tokens": sum(int(row.get("output_tokens", 0) or 0) for row in prefix),
                "estimated_cost_usd": sum(
                    float(row.get("estimated_cost_usd", 0.0) or 0.0) for row in prefix
                ),
                "cache_hit_count": sum(1 for row in prefix if row.get("cache_status") == "hit"),
                "invalid_output_count": sum(
                    1 for row in prefix if row.get("validation_status") != "valid"
                ),
                "abstention_count": sum(
                    1 for row in prefix if row.get("fallback_reason") == "abstention"
                ),
                "fallback_count": sum(1 for row in prefix if row.get("fallback_applied")),
                "accepted_count": sum(1 for row in prefix if row.get("accepted")),
                "labeled_decision_count": len(labeled),
                "assisted_correct_count": sum(int(row["assisted_correct"]) for row in labeled),
                "assisted_accuracy": (
                    sum(int(row["assisted_correct"]) for row in labeled) / len(labeled)
                    if labeled
                    else None
                ),
            }
        )
    return points


def _finish_assisted_result(
    config: M3ExperimentConfig,
    model_config: dict[str, Any],
    run_id: str,
    run_dir: Path,
    completed_stage: str,
    artifacts: dict[str, str],
    metrics: dict[str, str],
    repo_root: Path,
    checkpoint: RunCheckpoint | None = None,
) -> PipelineRunResult:
    manifest_path = run_dir / "run_manifest.json"
    payload = {
        "run_id": run_id,
        "pipeline_id": config.experiment_id,
        "completed_stage": completed_stage,
        "llm_decisions": True,
        "configuration_hash": f"cfg_{sha256_text(config.model_dump_json())[:12]}",
        "code_commit": _code_commit(repo_root),
        "generated_at": datetime.now(UTC).isoformat(),
        "experiment_config": config.model_dump(by_alias=True),
        "decision_mode": config.decision_mode,
        "primary_defaults": _primary_defaults_manifest(config),
        "model_config": model_config,
        "prompt_versions": config.prompt_versions.model_dump(by_alias=True),
        "llm_call_logs": repo_relative(
            repo_root / str(model_config["call_log_root"]) / run_id,
            repo_root,
        ),
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


def _primary_defaults_manifest(config: M3ExperimentConfig) -> dict[str, str]:
    if config.decision_mode != "primary":
        return {}
    return {
        "schema": "UNMAPPED",
        "linkage": "non_match",
        "fusion": "abstain_missing_value",
    }
