import json
from pathlib import Path

from mosaic.cli import REQUIRED_SCAFFOLD_PATHS


def test_required_scaffold_paths_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    missing = [
        relative for relative in REQUIRED_SCAFFOLD_PATHS if not (repo_root / relative).exists()
    ]

    assert missing == []


def test_m3_example_configs_are_parseable() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    model_config = json.loads(
        (repo_root / "configs" / "models" / "openai_m3_example.json").read_text(
            encoding="utf-8"
        )
    )
    experiment_config = json.loads(
        (
            repo_root / "configs" / "experiments" / "m3_llm_assisted_example.json"
        ).read_text(encoding="utf-8")
    )

    assert model_config["provider"] == "openai"
    assert "model" in model_config
    assert model_config["structured_output"]["enabled"] is True
    assert (
        experiment_config["model_config"]
        == "configs/models/openai_m3_example.json"
    )
    assert experiment_config["llm_assistance"] == {
        "schema": True,
        "linkage": True,
        "fusion": True,
        "normalization": False,
    }
