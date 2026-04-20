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


def test_version_flag_prints_version_and_exits():
    """--version should print the installed version and exit 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    from importlib.metadata import version
    assert version("tracksplit") in result.stdout


def test_cli_invalid_format_rejected():
    """Invalid --format value should fail with a clean message."""
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".mkv")
    os.close(fd)
    try:
        result = runner.invoke(app, [path, "--format", "mp3"])
        assert result.exit_code != 0
    finally:
        os.unlink(path)


def test_cli_format_flag_in_help():
    """Help output should document the format option.

    Rich may wrap the flag name across lines in narrow terminals,
    so assert on the description text (values) rather than the
    literal '--format' substring.
    """
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "flac" in result.output
    assert "opus" in result.output
