from mosaic.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Mosaic reproducible research pipeline CLI" in result.output


def test_doctor() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Mosaic M0 scaffold ready" in result.output


def test_fixture_reproduce() -> None:
    result = runner.invoke(app, ["reproduce", "--fixture"])

    assert result.exit_code == 0
    assert "Fixture reproduction scaffold completed" in result.output


def test_report_build() -> None:
    result = runner.invoke(app, ["report", "build"])

    assert result.exit_code == 0
    assert "Report generation scaffold completed" in result.output
