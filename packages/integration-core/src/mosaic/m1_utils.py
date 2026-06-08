from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROW_POSITION_FIELDS = {"row", "row_id", "row_number", "row_position", "index", "__index__"}


def stable_record_uid(source_id: str, source_record_id: str) -> str:
    if not source_id.strip():
        raise ValueError("source_id is required")
    if not source_record_id.strip():
        raise ValueError("source_record_id is required")
    if source_record_id.strip().lower() in ROW_POSITION_FIELDS:
        raise ValueError("row position cannot be used as a stable source_record_id")
    return f"{source_id}:{source_record_id}"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def positive_pairs_from_cluster_sizes(cluster_sizes: Iterable[int]) -> int:
    return sum(size * (size - 1) // 2 for size in cluster_sizes if size > 1)


def repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()
