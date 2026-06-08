from pathlib import Path

from mosaic.cli import REQUIRED_SCAFFOLD_PATHS


def test_required_scaffold_paths_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    missing = [
        relative for relative in REQUIRED_SCAFFOLD_PATHS if not (repo_root / relative).exists()
    ]

    assert missing == []
