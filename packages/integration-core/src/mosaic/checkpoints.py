from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mosaic.m1_utils import canonical_json, repo_relative, sha256_text

CHECKPOINT_FILE = "run_checkpoint.json"


def checkpoint_hash(payload: Any) -> str:
    return f"chk_{sha256_text(canonical_json(payload))[:16]}"


class RunCheckpoint:
    def __init__(
        self,
        *,
        repo_root: Path,
        run_dir: Path,
        run_id: str,
        config_hash: str,
        dataset_hash: str | None,
        prompt_hash: str | None = None,
        model_hash: str | None = None,
        resume: bool = False,
    ) -> None:
        self.repo_root = repo_root
        self.run_dir = run_dir
        self.path = run_dir / CHECKPOINT_FILE
        self.run_id = run_id
        self.expected = {
            "config_hash": config_hash,
            "dataset_hash": dataset_hash,
            "prompt_hash": prompt_hash,
            "model_hash": model_hash,
        }
        if resume:
            self.payload = self._load_and_validate()
        else:
            self.payload = {
                "run_id": run_id,
                "status": "running",
                "current_stage": None,
                "completed_stages": [],
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                **self.expected,
                "artifacts": {},
                "metrics": {},
            }
            self.write()

    @property
    def artifacts(self) -> dict[str, str]:
        return dict(self.payload.get("artifacts", {}))

    @property
    def metrics(self) -> dict[str, str]:
        return dict(self.payload.get("metrics", {}))

    def is_stage_complete(self, stage: str, *, required: list[str] | None = None) -> bool:
        if stage not in set(self.payload.get("completed_stages", [])):
            return False
        paths = self.artifacts | self.metrics
        for key in required or []:
            value = paths.get(key)
            if value is None or not (self.repo_root / value).exists():
                return False
        return True

    def start_stage(self, stage: str) -> None:
        self.payload["status"] = "running"
        self.payload["current_stage"] = stage
        self.payload["updated_at"] = datetime.now(UTC).isoformat()
        self.write()

    def complete_stage(
        self,
        stage: str,
        *,
        artifacts: dict[str, str],
        metrics: dict[str, str],
    ) -> None:
        completed = list(self.payload.get("completed_stages", []))
        if stage not in completed:
            completed.append(stage)
        self.payload["completed_stages"] = completed
        self.payload["current_stage"] = None
        self.payload["status"] = "running"
        self.payload["updated_at"] = datetime.now(UTC).isoformat()
        self.payload["artifacts"] = {
            key: repo_relative(Path(value), self.repo_root) for key, value in artifacts.items()
        }
        self.payload["metrics"] = {
            key: repo_relative(Path(value), self.repo_root) for key, value in metrics.items()
        }
        self.write()

    def finish(self, *, artifacts: dict[str, str], metrics: dict[str, str]) -> None:
        self.payload["status"] = "complete"
        self.payload["current_stage"] = None
        self.payload["updated_at"] = datetime.now(UTC).isoformat()
        self.payload["artifacts"] = {
            key: repo_relative(Path(value), self.repo_root) for key, value in artifacts.items()
        }
        self.payload["metrics"] = {
            key: repo_relative(Path(value), self.repo_root) for key, value in metrics.items()
        }
        self.write()

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.payload, indent=2, sort_keys=True), encoding="utf-8")

    def _load_and_validate(self) -> dict[str, Any]:
        if not self.path.exists():
            raise RuntimeError(f"checkpoint not found for resume: {self.path}")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("run_id") != self.run_id:
            raise RuntimeError("checkpoint run_id mismatch")
        for key, expected in self.expected.items():
            if expected is not None and payload.get(key) != expected:
                raise RuntimeError(f"checkpoint {key} mismatch; refusing unsafe resume")
        if payload.get("status") == "complete":
            return dict(payload)
        payload["status"] = "running"
        payload["updated_at"] = datetime.now(UTC).isoformat()
        return dict(payload)


def latest_run_id(artifact_root: Path, slug: str) -> str | None:
    normalized_slug = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")[:24]
    candidates = [
        path
        for path in artifact_root.glob(f"run_*{normalized_slug}*")
        if path.is_dir() and (path / CHECKPOINT_FILE).exists()
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0].name


def load_progress(path: Path, expected_case_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        case_id = str(row.get("case_id", ""))
        if case_id not in expected_case_ids:
            raise RuntimeError(f"unknown checkpoint case_id {case_id} in {path}:{line_number}")
        if case_id in rows:
            raise RuntimeError(f"duplicate checkpoint case_id {case_id} in {path}:{line_number}")
        rows[case_id] = row
    return rows


def append_progress(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(canonical_json(row) + "\n")
