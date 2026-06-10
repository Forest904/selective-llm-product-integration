from __future__ import annotations

import json
from pathlib import Path

import mosaic.cli as cli_module
import polars as pl
import pytest
from mosaic.alaska import local_alaska_dataset_configs, select_best_candidate
from mosaic.cli import app
from mosaic.ingestion import ingest_dataset, iter_source_records, summarize_ground_truth
from mosaic.m1_models import CandidateMetrics, DatasetConfig, SourceInput, load_dataset_config
from mosaic.m1_utils import positive_pairs_from_cluster_sizes, sha256_text, stable_record_uid
from mosaic.profiling import profile_dataset
from mosaic.schema_validation import validate_mediated_schema
from typer.testing import CliRunner

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_stable_record_uid_rejects_row_position() -> None:
    assert stable_record_uid("source_a", "record_001") == "source_a:record_001"

    with pytest.raises(ValueError, match="row position"):
        stable_record_uid("source_a", "row_number")


def test_checksum_is_deterministic() -> None:
    assert sha256_text("same payload") == sha256_text("same payload")
    assert sha256_text("same payload") != sha256_text("different payload")


def test_positive_pair_count_from_clusters() -> None:
    assert positive_pairs_from_cluster_sizes([1, 2, 3, 4]) == 10


def test_format_readers_normalize_to_source_records(tmp_path: Path) -> None:
    csv_path = tmp_path / "records.csv"
    json_path = tmp_path / "records.json"
    jsonl_path = tmp_path / "records.jsonl"
    parquet_path = tmp_path / "records.parquet"

    csv_path.write_text("id,title\nr1,Camera\n", encoding="utf-8")
    json_path.write_text('[{"id": "r1", "title": "Camera"}]', encoding="utf-8")
    jsonl_path.write_text('{"id": "r1", "title": "Camera"}\n', encoding="utf-8")
    pl.DataFrame([{"id": "r1", "title": "Camera"}]).write_parquet(parquet_path)

    sources = [
        SourceInput(
            source_id="s",
            origin="fixture",
            path="records.csv",
            format="csv",
            id_field="id",
        ),
        SourceInput(
            source_id="s",
            origin="fixture",
            path="records.json",
            format="json",
            id_field="id",
        ),
        SourceInput(
            source_id="s",
            origin="fixture",
            path="records.jsonl",
            format="jsonl",
            id_field="id",
        ),
        SourceInput(
            source_id="s",
            origin="fixture",
            path="records.parquet",
            format="parquet",
            id_field="id",
        ),
    ]

    rows = [list(iter_source_records(source, tmp_path)) for source in sources]

    assert [row[0][0] for row in rows] == ["r1", "r1", "r1", "r1"]
    assert len({row[0][1] for row in rows}) == 1


def test_malformed_jsonl_row_becomes_ingestion_error(tmp_path: Path) -> None:
    input_path = tmp_path / "records.jsonl"
    input_path.write_text('{"id": "r1", "title": "Camera"}\n{"id":\n', encoding="utf-8")
    config = DatasetConfig(
        dataset_id="tmp_fixture",
        benchmark="fixture",
        vertical="camera",
        sources=[
            SourceInput(
                source_id="s",
                origin="fixture",
                path="records.jsonl",
                format="jsonl",
                id_field="id",
            )
        ],
    )

    manifest = ingest_dataset(config, tmp_path, output_root=tmp_path / "out")
    errors = pl.read_parquet(tmp_path / "out" / "ingestion_errors.parquet")

    assert manifest.total_record_count == 1
    assert errors.height == 1
    assert errors.row(0, named=True)["error_type"] == "malformed_row"


def test_fixture_ground_truth_summary() -> None:
    summary = summarize_ground_truth("data/ground_truth/fixture_m1_entity_clusters.csv", REPO_ROOT)

    assert summary.entity_count == 2
    assert summary.labeled_record_count == 6
    assert summary.positive_pair_count == 6


def test_ground_truth_summary_deduplicates_repeated_pairs(tmp_path: Path) -> None:
    ground_truth_path = tmp_path / "entity_resolution_gt.csv"
    ground_truth_path.write_text(
        "entity_id,spec_id\n"
        "ENTITY#001,www.ebay.com//14633\n"
        "ENTITY#001,www.ebay.com//14633\n"
        "ENTITY#001,www.ebay.com//20380\n"
        "ENTITY#002,ca.pcpartpicker.com//1\n",
        encoding="utf-8",
    )

    summary = summarize_ground_truth("entity_resolution_gt.csv", tmp_path)

    assert summary.entity_count == 2
    assert summary.labeled_record_count == 3
    assert summary.positive_pair_count == 1


def test_canonical_alaska_layout_discovery(tmp_path: Path) -> None:
    _write_alaska_source(
        tmp_path,
        vertical="monitor",
        source_id="www.ebay.com",
        record_id="14633",
        payload={"<page title>": "Monitor", "manufacturer": "Dell", "model": "U2412M"},
    )
    _write_alaska_ground_truth(tmp_path, vertical="monitor", spec_ids=["www.ebay.com//14633"])

    configs = local_alaska_dataset_configs(tmp_path)

    assert len(configs) == 1
    config = configs[0]
    assert config.dataset_id == "alaska_monitor_m1"
    assert config.ground_truth_path == (
        "data/raw/alaska/monitor/extracted/monitor_ground_truths/"
        "monitor_entity_resolution_gt.csv"
    )
    assert config.mapping_gold_path == (
        "data/raw/alaska/monitor/extracted/monitor_ground_truths/"
        "monitor_schema_matching_gt.csv"
    )
    assert [source.source_id for source in config.sources] == ["www.ebay.com"]
    assert config.sources[0].path == (
        "data/raw/alaska/monitor/extracted/monitor_specs/www.ebay.com"
    )


def test_select_best_candidate_prefers_gated_metrics() -> None:
    camera = _candidate_metric("camera", score=95, gate=False)
    monitor = _candidate_metric("monitor", score=80, gate=True)
    notebook = _candidate_metric("notebook", score=75, gate=True)

    selected = select_best_candidate([camera, monitor, notebook])

    assert selected.vertical == "monitor"


def test_dataset_select_writes_local_selected_monitor_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_gated_monitor_benchmark(tmp_path)
    monkeypatch.setattr(cli_module, "_repo_root", lambda: tmp_path)

    result = runner.invoke(app, ["dataset", "select"])

    assert result.exit_code == 0
    assert "selected Alaska vertical: monitor" in result.output
    assert "gate=True" in result.output
    selected_config = load_dataset_config(
        tmp_path / "configs" / "datasets" / "selected_dataset.json"
    )
    assert selected_config.dataset_id == "alaska_monitor_m1"
    assert selected_config.vertical == "monitor"


def test_mediated_schema_validation_accepts_required_schema() -> None:
    schema = validate_mediated_schema(REPO_ROOT / "configs" / "schemas" / "mediated_schema.json")

    assert {attribute.name for attribute in schema.attributes} >= {
        "title",
        "brand",
        "model_number",
        "category",
        "description",
        "price",
        "currency",
        "specifications",
    }


def test_mediated_schema_validation_rejects_missing_required_attribute(tmp_path: Path) -> None:
    schema_path = tmp_path / "bad_schema.json"
    schema_path.write_text(
        """
        {
          "schema_version": "bad",
          "domain": "product",
          "attributes": [],
          "specifications_shape": {}
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mediated schema missing required attributes"):
        validate_mediated_schema(schema_path)


def test_fixture_ingest_and_profile_generate_m1_artifacts() -> None:
    config = load_dataset_config(REPO_ROOT / "configs" / "datasets" / "fixture_dataset.json")

    manifest = ingest_dataset(config, REPO_ROOT)
    result = profile_dataset(config, REPO_ROOT, evidence_level="fixture")

    assert manifest.total_record_count == 6
    assert Path(REPO_ROOT / manifest.raw_artifacts["source_records"]).exists()
    assert Path(REPO_ROOT / manifest.raw_artifacts["ingestion_errors"]).exists()
    assert result.source_attributes_path.exists()
    assert result.summary_path.exists()
    assert result.fusion_conflict_count >= 1


def test_m1_cli_commands() -> None:
    ingest_result = runner.invoke(app, ["dataset", "ingest", "--fixture"])
    profile_result = runner.invoke(app, ["dataset", "profile", "--fixture"])
    schema_result = runner.invoke(app, ["schema", "validate"])

    assert ingest_result.exit_code == 0
    assert "ingested 6 records" in ingest_result.output
    assert profile_result.exit_code == 0
    assert "wrote source profiles" in profile_result.output
    assert schema_result.exit_code == 0
    assert "validated mediated schema" in schema_result.output


def test_dataset_download_command_is_not_exposed() -> None:
    result = runner.invoke(app, ["dataset", "--help"])

    assert result.exit_code == 0
    assert "download" not in result.output


def test_missing_dataset_config_mentions_manual_placement() -> None:
    result = runner.invoke(
        app,
        ["dataset", "ingest", "--config", "configs/datasets/does_not_exist.json"],
    )

    assert result.exit_code != 0
    assert "Place Alaska" in result.output
    assert "data/raw/alaska/<vertical>/extracted/" in result.output


def _write_alaska_source(
    repo_root: Path,
    *,
    vertical: str,
    source_id: str,
    record_id: str,
    payload: dict[str, str],
) -> None:
    source_dir = (
        repo_root
        / "data"
        / "raw"
        / "alaska"
        / vertical
        / "extracted"
        / f"{vertical}_specs"
        / source_id
    )
    source_dir.mkdir(parents=True, exist_ok=True)
    source_file = source_dir / f"{record_id}.json"
    source_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_alaska_ground_truth(repo_root: Path, *, vertical: str, spec_ids: list[str]) -> None:
    ground_truth_dir = (
        repo_root
        / "data"
        / "raw"
        / "alaska"
        / vertical
        / "extracted"
        / f"{vertical}_ground_truths"
    )
    ground_truth_dir.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"ENTITY#001,{spec_id}" for spec_id in spec_ids)
    (ground_truth_dir / f"{vertical}_entity_resolution_gt.csv").write_text(
        f"entity_id,spec_id\n{rows}\n",
        encoding="utf-8",
    )
    (ground_truth_dir / f"{vertical}_schema_matching_gt.csv").write_text(
        "source_attribute_id,target_attribute_name\n"
        f"{spec_ids[0].split('//', 1)[0]}//model,model_number\n",
        encoding="utf-8",
    )


def _write_gated_monitor_benchmark(repo_root: Path) -> None:
    vertical = "monitor"
    sources = ("source-a.example", "source-b.example", "source-c.example")
    ground_truth_dir = (
        repo_root
        / "data"
        / "raw"
        / "alaska"
        / vertical
        / "extracted"
        / f"{vertical}_ground_truths"
    )
    ground_truth_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_rows = ["entity_id,spec_id"]
    for entity_index in range(200):
        entity_id = f"ENTITY#{entity_index:03}"
        for variant in range(5):
            source_id = sources[variant % len(sources)]
            record_id = f"{entity_index}_{variant}"
            _write_alaska_source(
                repo_root,
                vertical=vertical,
                source_id=source_id,
                record_id=record_id,
                payload={
                    "<page title>": f"Monitor {entity_index} listing {variant}",
                    "manufacturer": "Dell",
                    "model": f"M{entity_index:03}",
                    "category": "monitor",
                    "description": f"Display listing {variant}",
                    "price": str(100 + variant),
                    "currency": "USD",
                },
            )
            ground_truth_rows.append(f"{entity_id},{source_id}//{record_id}")
    (ground_truth_dir / f"{vertical}_entity_resolution_gt.csv").write_text(
        "\n".join(ground_truth_rows) + "\n",
        encoding="utf-8",
    )
    (ground_truth_dir / f"{vertical}_schema_matching_gt.csv").write_text(
        "source_attribute_id,target_attribute_name\n"
        "source-a.example//<page title>,title\n"
        "source-a.example//model,model_number\n"
        "source-a.example//manufacturer,brand\n"
        "source-a.example//category,category\n"
        "source-a.example//description,description\n"
        "source-a.example//price,price\n"
        "source-a.example//currency,currency\n",
        encoding="utf-8",
    )


def _candidate_metric(vertical: str, *, score: float, gate: bool) -> CandidateMetrics:
    return CandidateMetrics(
        vertical=vertical,
        source_count=3,
        record_count=1000,
        attribute_count=10,
        entity_count=200 if gate else 100,
        labeled_record_count=500,
        positive_pair_count=300,
        mediated_attribute_coverage=5,
        missingness_rate=0.1,
        schema_heterogeneity=0.5,
        overlap_score=0.4,
        model_number_coverage=0.6,
        title_signal_coverage=0.6,
        fusion_conflict_count=100 if gate else 50,
        satisfies_assignment_gate=gate,
        selection_score=score,
        evidence_level="local_profile",
    )
