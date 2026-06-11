from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from mosaic.m1_utils import canonical_json, sha256_text
from mosaic.m3_models import LLMCallResult, LLMModelConfig


@dataclass(frozen=True)
class LLMRequestEstimate:
    input_tokens: int
    max_output_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class ProviderResponse:
    raw_response: str
    retry_count: int


class LLMProviderError(Exception):
    def __init__(
        self,
        *,
        failure_type: str,
        validation_status: str,
        retry_count: int,
        raw_response: str = "",
        message: str,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.validation_status = validation_status
        self.retry_count = retry_count
        self.raw_response = raw_response


def render_prompt(template: str, payload: Mapping[str, Any]) -> str:
    rendered = template
    for key, value in payload.items():
        replacement = canonical_json(value) if isinstance(value, (dict, list)) else str(value)
        rendered = rendered.replace("{{" + key + "}}", replacement)
    return rendered


def canonical_input_hash(
    *,
    stage: str,
    prompt_version: str,
    model_config: LLMModelConfig,
    payload: Mapping[str, Any],
) -> str:
    identity = {
        "stage": stage,
        "prompt_version": prompt_version,
        "provider": model_config.provider,
        "model": model_config.model,
        "temperature": model_config.temperature,
        "max_output_tokens": model_config.max_output_tokens,
        "structured_output": model_config.structured_output.model_dump(),
        "payload": payload,
    }
    return sha256_text(canonical_json(identity))


class LLMGateway:
    def __init__(self, model_config: LLMModelConfig, repo_root: Path, run_id: str) -> None:
        self.model_config = model_config
        self.repo_root = repo_root
        self.run_id = run_id
        self.cache_root = repo_root / model_config.cache_root
        self.call_log_root = repo_root / model_config.call_log_root / run_id
        self.call_log_root.mkdir(parents=True, exist_ok=True)

    def estimate_request(
        self,
        *,
        template_path: Path,
        payload: Mapping[str, Any],
    ) -> LLMRequestEstimate:
        template = template_path.read_text(encoding="utf-8")
        prompt = render_prompt(template, {"payload_json": payload})
        input_tokens = estimate_tokens(prompt)
        max_output_tokens = self.model_config.max_output_tokens
        return LLMRequestEstimate(
            input_tokens=input_tokens,
            max_output_tokens=max_output_tokens,
            estimated_cost_usd=estimated_cost(input_tokens, max_output_tokens, self.model_config),
        )

    def call_structured(
        self,
        *,
        stage: str,
        prompt_version: str,
        template_path: Path,
        payload: Mapping[str, Any],
        output_model: type[BaseModel],
        schema_name: str,
    ) -> LLMCallResult:
        template = template_path.read_text(encoding="utf-8")
        prompt = render_prompt(template, {"payload_json": payload})
        input_hash = canonical_input_hash(
            stage=stage,
            prompt_version=prompt_version,
            model_config=self.model_config,
            payload=payload,
        )
        request_id = f"llm_{sha256_text(self.run_id + stage + input_hash)[:20]}"
        cache_path = self.cache_root / stage / f"{input_hash}.json"
        cache_enabled = self.model_config.cache_mode in {"read", "write", "read_write"}
        start = time.perf_counter()
        cache_status = "disabled"
        raw_response = ""
        retry_count = 0
        failure_type: str | None = None
        validation_status = "valid"

        try:
            if cache_enabled and self.model_config.cache_mode in {"read", "read_write"}:
                cached = self._read_cache(cache_path)
                if cached is not None:
                    raw_response = cached
                    cache_status = "hit"
                else:
                    provider_response = self._invoke_provider(
                        stage=stage,
                        prompt=prompt,
                        payload=payload,
                        output_schema=output_model.model_json_schema(),
                        schema_name=schema_name,
                    )
                    raw_response = provider_response.raw_response
                    retry_count = provider_response.retry_count
                    cache_status = "miss"
            else:
                provider_response = self._invoke_provider(
                    stage=stage,
                    prompt=prompt,
                    payload=payload,
                    output_schema=output_model.model_json_schema(),
                    schema_name=schema_name,
                )
                raw_response = provider_response.raw_response
                retry_count = provider_response.retry_count
        except LLMProviderError as exc:
            raw_response = exc.raw_response
            retry_count = exc.retry_count
            failure_type = exc.failure_type
            validation_status = exc.validation_status

        parsed_response: dict[str, Any] | None = None
        if validation_status == "valid":
            try:
                decoded = json.loads(raw_response)
                validated = output_model.model_validate(decoded)
                parsed_response = validated.model_dump()
            except json.JSONDecodeError:
                validation_status = "invalid"
                failure_type = "invalid_json"
            except ValidationError:
                validation_status = "invalid"
                failure_type = "missing_or_invalid_fields"

        if (
            cache_enabled
            and cache_status == "miss"
            and self.model_config.cache_mode in {"write", "read_write"}
            and raw_response
            and validation_status in {"valid", "invalid"}
        ):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(raw_response, encoding="utf-8")
            cache_status = "write"

        latency_ms = int((time.perf_counter() - start) * 1000)
        input_tokens = estimate_tokens(prompt)
        output_tokens = estimate_tokens(raw_response)
        result = LLMCallResult(
            request_id=request_id,
            stage=stage,
            prompt_version=prompt_version,
            input_hash=input_hash,
            raw_response=raw_response,
            parsed_response=parsed_response,
            validation_status=validation_status,  # type: ignore[arg-type]
            failure_type=failure_type,
            retry_count=retry_count,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost(input_tokens, output_tokens, self.model_config),
            cache_status=cache_status,  # type: ignore[arg-type]
        )
        self._append_call_log(result, prompt, payload)
        return result

    def _read_cache(self, path: Path) -> str | None:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _invoke_provider(
        self,
        *,
        stage: str,
        prompt: str,
        payload: Mapping[str, Any],
        output_schema: dict[str, Any],
        schema_name: str,
    ) -> ProviderResponse:
        if self.model_config.execution_mode == "fake" or self.model_config.provider == "fake":
            return ProviderResponse(
                raw_response=canonical_json(_fake_response(stage, payload)),
                retry_count=0,
            )
        if self.model_config.provider == "openai":
            return self._call_openai(prompt, output_schema, schema_name)
        raise ValueError(f"unsupported provider: {self.model_config.provider}")

    def _call_openai(
        self, prompt: str, output_schema: dict[str, Any], schema_name: str
    ) -> ProviderResponse:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise LLMProviderError(
                failure_type="missing_api_key",
                validation_status="error",
                retry_count=0,
                message="OPENAI_API_KEY is required for live OpenAI execution",
            )
        if not self.model_config.model:
            raise LLMProviderError(
                failure_type="missing_model",
                validation_status="error",
                retry_count=0,
                message="model must be configured for live OpenAI execution",
            )
        body = {
            "model": self.model_config.model,
            "input": prompt,
            "temperature": self.model_config.temperature,
            "max_output_tokens": self.model_config.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": _openai_strict_schema(output_schema),
                    "strict": self.model_config.structured_output.strict,
                }
            },
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        last_error: Exception | None = None
        attempts = self.model_config.max_retries + 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(
                    request, timeout=self.model_config.timeout_seconds
                ) as response:
                    decoded = json.loads(response.read().decode("utf-8"))
                text = _extract_openai_text(decoded)
                if text:
                    return ProviderResponse(raw_response=text, retry_count=attempt)
                raise LLMProviderError(
                    failure_type="empty_response",
                    validation_status="error",
                    retry_count=attempt,
                    raw_response=json.dumps(decoded),
                    message="empty OpenAI response text",
                )
            except LLMProviderError as exc:
                last_error = exc
            except urllib.error.HTTPError as exc:
                raw_error = exc.read().decode("utf-8", errors="replace")
                last_error = LLMProviderError(
                    failure_type=f"http_{exc.code}",
                    validation_status="error",
                    retry_count=attempt,
                    raw_response=raw_error,
                    message=f"OpenAI HTTP error {exc.code}: {raw_error}",
                )
            except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
                last_error = exc
        retry_count = max(0, attempts - 1)
        failure_type = "timeout" if _is_timeout_error(last_error) else "provider_error"
        validation_status = "timeout" if failure_type == "timeout" else "error"
        raise LLMProviderError(
            failure_type=failure_type,
            validation_status=validation_status,
            retry_count=retry_count,
            raw_response=last_error.raw_response
            if isinstance(last_error, LLMProviderError)
            else "",
            message=f"OpenAI request failed: {last_error}",
        )

    def _append_call_log(
        self, result: LLMCallResult, prompt: str, payload: Mapping[str, Any]
    ) -> None:
        log_path = self.call_log_root / f"{result.stage}_calls.jsonl"
        row = {
            **result.model_dump(),
            "run_id": self.run_id,
            "provider": self.model_config.provider,
            "model": self.model_config.model,
            "settings": self.model_config.model_dump(),
            "request_payload": payload,
            "prompt": prompt,
            "created_at": datetime.now(UTC).isoformat(),
        }
        with log_path.open("a", encoding="utf-8") as file:
            file.write(canonical_json(row) + "\n")


def _fake_response(stage: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if stage == "schema_batch":
        return {
            "decisions": [
                {
                    "case_id": str(case.get("case_id", "")),
                    "source_attribute": str(case.get("attribute_name", "")),
                    "target_attribute": str(
                        (list(case.get("deterministic_candidates", [])) or [{}])[0].get(
                            "target_attribute_name", "UNMAPPED"
                        )
                    ),
                    "decision": "unmapped"
                    if str(
                        (list(case.get("deterministic_candidates", [])) or [{}])[0].get(
                            "target_attribute_name", "UNMAPPED"
                        )
                    )
                    == "UNMAPPED"
                    else "match",
                    "confidence": 0.8,
                    "supporting_evidence": ["fake batch provider selected available evidence"],
                    "abstain": False,
                }
                for case in payload.get("cases", [])
            ]
        }
    if stage == "linkage_batch":
        return {
            "decisions": [
                {
                    "case_id": str(case.get("case_id", "")),
                    "decision": "match"
                    if float(case.get("match_probability", 0.0)) >= 0.5
                    else "non_match",
                    "confidence": 0.8,
                    "supporting_evidence": ["fake batch provider mirrored pair evidence"],
                    "contradicting_evidence": [],
                    "abstain": False,
                }
                for case in payload.get("cases", [])
            ]
        }
    if stage == "fusion_batch":
        decisions = []
        for case in payload.get("cases", []):
            allowed = [str(value) for value in case.get("allowed_outputs", [])]
            selected = allowed[0] if allowed else "ABSTAIN"
            claims = list(case.get("candidate_claims", []))
            supporting = [
                str(claim.get("claim_id"))
                for claim in claims
                if str(claim.get("normalized_value")) == selected
            ]
            decisions.append(
                {
                    "case_id": str(case.get("case_id", "")),
                    "selected_value": selected,
                    "confidence": 0.8 if selected != "ABSTAIN" else 0.0,
                    "supporting_claim_ids": supporting,
                    "contradicting_claim_ids": [],
                    "reason": "fake batch provider selected a claim-supported value",
                    "abstain": selected == "ABSTAIN",
                }
            )
        return {"decisions": decisions}
    if stage == "schema":
        candidates = list(payload.get("deterministic_candidates", []))
        best = candidates[0] if candidates else {}
        target = str(best.get("target_attribute_name", "UNMAPPED"))
        confidence = max(0.55, min(0.9, float(best.get("score_total", 0.55))))
        if target == "UNMAPPED":
            return {
                "source_attribute": str(payload.get("attribute_name", "")),
                "target_attribute": "UNMAPPED",
                "decision": "unmapped",
                "confidence": confidence,
                "supporting_evidence": ["deterministic candidates did not support a target"],
                "abstain": False,
            }
        return {
            "source_attribute": str(payload.get("attribute_name", "")),
            "target_attribute": target,
            "decision": "match",
            "confidence": confidence,
            "supporting_evidence": ["fake provider selected the top deterministic candidate"],
            "abstain": False,
        }
    if stage == "linkage":
        probability = float(payload.get("match_probability", 0.0))
        return {
            "decision": "match" if probability >= 0.5 else "non_match",
            "confidence": max(0.55, min(0.9, abs(probability - 0.5) + 0.5)),
            "supporting_evidence": ["fake provider mirrored deterministic borderline evidence"],
            "contradicting_evidence": [],
            "abstain": False,
        }
    if stage == "fusion":
        allowed = [str(value) for value in payload.get("allowed_outputs", [])]
        selected = allowed[0] if allowed else "ABSTAIN"
        return {
            "selected_value": selected,
            "confidence": 0.75 if selected != "ABSTAIN" else 0.0,
            "supporting_claim_ids": [
                str(value) for value in payload.get("default_supporting_claim_ids", [])
            ],
            "contradicting_claim_ids": [
                str(value) for value in payload.get("default_contradicting_claim_ids", [])
            ],
            "reason": "fake provider selected the deterministic default allowed value",
            "abstain": selected == "ABSTAIN",
        }
    return {}


def _extract_openai_text(decoded: Mapping[str, Any]) -> str:
    if isinstance(decoded.get("output_text"), str):
        return str(decoded["output_text"])
    for item in decoded.get("output", []):
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content", []):
            if isinstance(content, Mapping) and isinstance(content.get("text"), str):
                return str(content["text"])
    return ""


def _openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(schema)
    _require_all_object_properties(normalized)
    return normalized


def _require_all_object_properties(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            node["required"] = sorted(str(key) for key in node["properties"])
            node["additionalProperties"] = False
        for value in node.values():
            _require_all_object_properties(value)
    elif isinstance(node, list):
        for value in node:
            _require_all_object_properties(value)


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def estimated_cost(input_tokens: int, output_tokens: int, config: LLMModelConfig) -> float:
    return (
        input_tokens * config.pricing.input_usd_per_1m_tokens
        + output_tokens * config.pricing.output_usd_per_1m_tokens
    ) / 1_000_000


def _is_timeout_error(error: Exception | None) -> bool:
    if error is None:
        return False
    if isinstance(error, TimeoutError):
        return True
    if isinstance(error, urllib.error.URLError):
        return isinstance(error.reason, TimeoutError)
    return False
