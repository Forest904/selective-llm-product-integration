from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from mosaic.checkpoints import append_progress, load_progress
from mosaic.m2_models import load_baseline_pipeline_config
from mosaic.m2_pipeline import run_baseline_pipeline
from mosaic.maintenance import clean_generated
from mosaic.subsets import materialize_subset

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_subset_materialization_is_deterministic_and_filters_labels(tmp_path: Path) -> None:
    repo = tmp_path
    raw_root = repo / "data/raw/alaska/monitor/extracted/monitor_specs"
    truth_root = repo / "data/raw/alaska/monitor/extracted/monitor_ground_truths"
    truth_root.mkdir(parents=True)
    sources = ["source_a", "source_b", "source_c"]
    for source in sources:
        (raw_root / source).mkdir(parents=True)

    er_path = truth_root / "monitor_entity_resolution_gt.csv"
    with er_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["entity_id", "spec_id"])
        writer.writeheader()
        for index in range(65):
            entity_id = f"ENTITY#{index:03d}"
            for source in sources[: 2 + (index % 2)]:
                record_id = f"{index}_{source}"
                (raw_root / source / f"{record_id}.json").write_text(
                    json.dumps({"title": f"Monitor {index}", "brand": source}),
                    encoding="utf-8",
                )
                writer.writerow({"entity_id": entity_id, "spec_id": f"{source}//{record_id}"})

    sm_path = truth_root / "monitor_schema_matching_gt.csv"
    sm_path.write_text(
        "source_attribute_id,target_attribute_name\n"
        "source_a//brand,brand\n"
        "source_b//title,title\n"
        "not_selected//price,price\n",
        encoding="utf-8",
    )
    dataset_path = repo / "configs/datasets/selected_dataset.json"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text(
        json.dumps(
            {
                "dataset_id": "alaska_monitor_m1",
                "benchmark": "alaska",
                "vertical": "monitor",
                "version": "test",
                "sources": [
                    {
                        "source_id": source,
                        "name": source,
                        "origin": "test",
                        "path": f"data/raw/alaska/monitor/extracted/monitor_specs/{source}",
                        "format": "alaska_json_dir",
                    }
                    for source in sources
                ],
                "ground_truth_path": er_path.relative_to(repo).as_posix(),
                "mapping_gold_path": sm_path.relative_to(repo).as_posix(),
            }
        ),
        encoding="utf-8",
    )
    spec_path = repo / "configs/subsets/m4_monitor_subset_60.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(
        json.dumps(
            {
                "subset_id": "alaska_monitor_live_subset_60",
                "base_dataset_config": dataset_path.relative_to(repo).as_posix(),
                "entity_count": 60,
                "random_seed": 13,
                "strategy": "entity_balanced",
                "output_root": "data/processed/subsets/alaska_monitor_live_subset_60",
            }
        ),
        encoding="utf-8",
    )

    first = materialize_subset(spec_path, repo)
    second = materialize_subset(spec_path, repo)

    assert first.selected_entity_count == 60
    assert first.subset_hash == second.subset_hash
    subset_er = repo / first.output_root / "ground_truth/entity_resolution_gt.csv"
    assert sum(1 for _ in csv.DictReader(subset_er.open(encoding="utf-8"))) > 60
    subset_sm = (repo / first.output_root / "ground_truth/schema_matching_gt.csv").read_text(
        encoding="utf-8"
    )
    assert "not_selected" not in subset_sm


def test_cleanup_dry_run_preserves_raw_data(tmp_path: Path) -> None:
    for relative in ["artifacts/runs/run_x", "data/interim/m1", "data/raw/alaska/monitor"]:
        path = tmp_path / relative
        path.mkdir(parents=True)
        (path / "file.txt").write_text("x", encoding="utf-8")

    targets = clean_generated(tmp_path, yes=False)
    assert "artifacts/runs" in targets
    assert "data/interim" in targets
    assert all(not target.startswith("data/raw") for target in targets)

    clean_generated(tmp_path, yes=True)
    assert (tmp_path / "data/raw/alaska/monitor/file.txt").exists()
    assert (tmp_path / "artifacts/runs/.gitkeep").exists()


def test_baseline_resume_reuses_completed_schema_stage() -> None:
    config = load_baseline_pipeline_config(REPO_ROOT / "configs/pipelines/fixture_m2.json")
    partial = run_baseline_pipeline(config, REPO_ROOT, stop_after="schema")
    resumed = run_baseline_pipeline(config, REPO_ROOT, resume_run_id=partial.run_id)

    assert resumed.run_id == partial.run_id
    checkpoint = json.loads(
        (Path(resumed.run_dir) / "run_checkpoint.json").read_text(encoding="utf-8")
    )
    assert "schema" in checkpoint["completed_stages"]
    assert checkpoint["status"] == "complete"


def test_progress_validation_rejects_unknown_and_duplicate_case_ids(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.jsonl"
    append_progress(progress_path, [{"case_id": "known", "output": {}, "route": {}}])
    assert set(load_progress(progress_path, {"known"})) == {"known"}

    append_progress(progress_path, [{"case_id": "known", "output": {}, "route": {}}])
    with pytest.raises(RuntimeError, match="duplicate checkpoint case_id"):
        load_progress(progress_path, {"known"})

    unknown_path = tmp_path / "unknown.jsonl"
    append_progress(unknown_path, [{"case_id": "unknown", "output": {}, "route": {}}])
    with pytest.raises(RuntimeError, match="unknown checkpoint case_id"):
        load_progress(unknown_path, {"known"})
