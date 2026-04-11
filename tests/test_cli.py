"""Tests for the CLI entry point."""

from typer.testing import CliRunner

from tracksplit.cli import app

runner = CliRunner()


def test_cli_no_args():
    """Invoking with no arguments should fail (no_args_is_help)."""
    result = runner.invoke(app, [])
    assert result.exit_code != 0


def test_cli_nonexistent_path():
    """Passing a path that does not exist should fail."""
    result = runner.invoke(app, ["/tmp/does_not_exist_tracksplit_xyz"])
    assert result.exit_code != 0


def test_cli_help():
    """--help should succeed and mention key options."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "output" in result.output.lower()


def test_cli_format_flag_in_help():
    """--format flag should appear in help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--format" in result.output
