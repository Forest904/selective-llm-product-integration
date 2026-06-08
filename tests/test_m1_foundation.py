from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from mosaic.cli import app
from mosaic.ingestion import ingest_dataset, iter_source_records, summarize_ground_truth
from mosaic.m1_models import DatasetConfig, SourceInput, load_dataset_config
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
    assert "Manually place Alaska" in result.output
    assert "data/raw/alaska/<vertical>/extracted/" in result.output
