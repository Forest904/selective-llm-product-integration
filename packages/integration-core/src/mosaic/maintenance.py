from __future__ import annotations

import shutil
from pathlib import Path

from mosaic.m1_utils import repo_relative

GENERATED_CLEAN_PATHS = (
    Path("artifacts/runs"),
    Path("artifacts/llm_calls"),
    Path("artifacts/llm_cache"),
    Path("artifacts/reports"),
    Path("data/interim"),
    Path("data/manifests"),
)


def generated_cleanup_targets(repo_root: Path) -> list[Path]:
    targets: list[Path] = []
    for relative in GENERATED_CLEAN_PATHS:
        target = repo_root / relative
        if target.is_dir() and any(child.name != ".gitkeep" for child in target.iterdir()):
            targets.append(target)
        elif target.is_file():
            targets.append(target)
    return targets


def clean_generated(repo_root: Path, *, yes: bool) -> list[str]:
    targets = generated_cleanup_targets(repo_root)
    relative_targets = [repo_relative(target, repo_root) for target in targets]
    if not yes:
        return relative_targets
    for target in targets:
        relative = repo_relative(target, repo_root)
        if relative.startswith("data/raw"):
            raise RuntimeError(f"refusing to delete raw data path: {relative}")
        if target.is_dir():
            for child in target.iterdir():
                if child.name == ".gitkeep":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            (target / ".gitkeep").touch(exist_ok=True)
        else:
            target.unlink()
    return relative_targets
