"""Tests for tracksplit.tools config loading."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tracksplit import tools


@pytest.fixture(autouse=True)
def reset_tools_state():
    tools._tool_paths.clear()
    tools._config_loaded = False
    yield
    tools._tool_paths.clear()
    tools._config_loaded = False


class TestToolLoading:
    def test_defaults_when_no_config(self, tmp_path: Path):
        with patch("tracksplit.tools.paths") as mock_paths:
            mock_paths.config_file.return_value = tmp_path / "does_not_exist.toml"
            assert tools.get_tool("ffmpeg") == "ffmpeg"
            assert tools.get_tool("mkvmerge") == "mkvmerge"

    def test_reads_custom_paths_from_toml(self, tmp_path: Path):
        config = tmp_path / "config.toml"
        config.write_text(
            '[tools]\n'
            'ffmpeg = "/opt/ffmpeg/bin/ffmpeg"\n'
            'mkvmerge = "/usr/local/bin/mkvmerge"\n'
        )
        with patch("tracksplit.tools.paths") as mock_paths:
            mock_paths.config_file.return_value = config
            assert tools.get_tool("ffmpeg") == "/opt/ffmpeg/bin/ffmpeg"
            assert tools.get_tool("mkvmerge") == "/usr/local/bin/mkvmerge"
            # Unspecified defaults still apply
            assert tools.get_tool("ffprobe") == "ffprobe"

    def test_malformed_toml_logs_warning_and_uses_defaults(self, tmp_path: Path, caplog):
        config = tmp_path / "config.toml"
        config.write_text("this is not [valid toml")
        with patch("tracksplit.tools.paths") as mock_paths:
            mock_paths.config_file.return_value = config
            assert tools.get_tool("ffmpeg") == "ffmpeg"
        assert any("config" in r.message.lower() for r in caplog.records)
