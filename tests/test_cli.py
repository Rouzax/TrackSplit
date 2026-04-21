"""Tests for the CLI entry point."""

from typer.testing import CliRunner

from tracksplit.cli import app
from tracksplit.tools import find_active_config  # type: ignore[reportAttributeAccessIssue]

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


def test_find_active_config_returns_none_when_no_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tracksplit.tools.paths.config_file",
        lambda: tmp_path / "missing.toml",
    )
    assert find_active_config() is None


def test_find_active_config_returns_existing_file(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text("[tools]\n")
    monkeypatch.setattr("tracksplit.tools.paths.config_file", lambda: p)
    assert find_active_config() == p


def test_check_flag_exits_zero_when_all_tools_present(monkeypatch):
    monkeypatch.setattr("tracksplit.tools.verify_tool", lambda name: (True, f"{name} version 1.0"))
    monkeypatch.setattr("tracksplit.tools.find_active_config", lambda: None)
    result = runner.invoke(app, ["--check"])
    assert result.exit_code == 0


def test_check_flag_exits_one_when_required_tool_missing(monkeypatch):
    def fake_verify(name):
        if name == "ffmpeg":
            return False, "not found on PATH"
        return True, f"{name} version 1.0"
    monkeypatch.setattr("tracksplit.tools.verify_tool", fake_verify)
    monkeypatch.setattr("tracksplit.tools.find_active_config", lambda: None)
    result = runner.invoke(app, ["--check"])
    assert result.exit_code == 1


def test_check_flag_exits_zero_when_only_optional_tool_missing(monkeypatch):
    def fake_verify(name):
        if name in ("mkvextract", "mkvmerge"):
            return False, "not found on PATH"
        return True, f"{name} version 1.0"
    monkeypatch.setattr("tracksplit.tools.verify_tool", fake_verify)
    monkeypatch.setattr("tracksplit.tools.find_active_config", lambda: None)
    result = runner.invoke(app, ["--check"])
    assert result.exit_code == 0


def test_check_flag_shows_section_headers(monkeypatch):
    monkeypatch.setattr("tracksplit.tools.verify_tool", lambda name: (True, f"{name} 1.0"))
    monkeypatch.setattr("tracksplit.tools.find_active_config", lambda: None)
    result = runner.invoke(app, ["--check"])
    assert "Tools" in result.output
    assert "Config" in result.output
    assert "Python packages" in result.output


def test_run_check_missing_config_shows_expected_path(tmp_path, monkeypatch, capsys):
    """--check must print the canonical config path when the file is absent."""
    from tracksplit import cli
    fake_config = tmp_path / "TrackSplit" / "config.toml"
    monkeypatch.setattr("tracksplit.tools.paths.config_file", lambda: fake_config)
    # Stub out tool/package probing so we only inspect the Config section.
    monkeypatch.setattr("tracksplit.tools.verify_tool", lambda name: (True, "stub 1.0"))
    cli._run_check()
    out = capsys.readouterr().out
    assert str(fake_config) in out
    assert "No config file found" in out
