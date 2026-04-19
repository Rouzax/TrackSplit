"""Tests for the Ogg Opus in-place patcher."""
import subprocess
from pathlib import Path

import pytest

from tracksplit.opus_patch import (
    ogg_crc,
    patch_opus_pre_skip,
    read_opus_pre_skip,
)


class TestOggCrc:
    def test_empty_bytes(self):
        assert ogg_crc(b"") == 0

    def test_single_byte_vector(self):
        assert ogg_crc(b"\x00") == 0

    def test_ascii_vector(self):
        # Ogg uses init 0, not the canonical CRC-32/MPEG-2 init 0xFFFFFFFF.
        assert ogg_crc(b"123456789") == 0x89A1897F


def _make_tiny_opus(tmp_path: Path) -> Path:
    out = tmp_path / "tiny.opus"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-t", "0.1", "-c:a", "libopus", "-b:a", "64k",
            str(out),
        ],
        check=True,
    )
    return out


class TestReadAndPatchPreSkip:
    def test_read_default_pre_skip(self, tmp_path):
        f = _make_tiny_opus(tmp_path)
        assert read_opus_pre_skip(f) == 312

    def test_roundtrip_zero(self, tmp_path):
        f = _make_tiny_opus(tmp_path)
        patch_opus_pre_skip(f, 0)
        assert read_opus_pre_skip(f) == 0

    def test_roundtrip_960(self, tmp_path):
        f = _make_tiny_opus(tmp_path)
        patch_opus_pre_skip(f, 960)
        assert read_opus_pre_skip(f) == 960

    def test_patch_only_touches_six_bytes(self, tmp_path):
        f = _make_tiny_opus(tmp_path)
        before = f.read_bytes()
        patch_opus_pre_skip(f, 960)
        after = f.read_bytes()
        assert len(before) == len(after)
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        # 2 bytes for pre_skip, 4 bytes for the Ogg page CRC.
        assert len(diffs) == 6

    def test_patched_file_still_decodable_by_ffprobe(self, tmp_path):
        f = _make_tiny_opus(tmp_path)
        patch_opus_pre_skip(f, 960)
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "stream=codec_name,sample_rate,channels",
                "-of", "default=noprint_wrappers=1",
                str(f),
            ],
            capture_output=True, text=True, check=True,
        )
        assert "codec_name=opus" in result.stdout

    def test_rejects_non_zero_channel_mapping_family(self, tmp_path):
        f = tmp_path / "surround.opus"
        opus_head = (
            b"OpusHead"
            + b"\x01"
            + b"\x06"
            + (312).to_bytes(2, "little")
            + (48000).to_bytes(4, "little")
            + (0).to_bytes(2, "little")
            + b"\x01"
            + b"\x06\x04\x01\x02\x03\x04\x05\x00"
        )
        page = bytearray()
        page += b"OggS\x00\x02"
        page += (0).to_bytes(8, "little")
        page += (1).to_bytes(4, "little")
        page += (0).to_bytes(4, "little")
        page += (0).to_bytes(4, "little")
        page += bytes([1])
        page += bytes([len(opus_head)])
        page += opus_head
        crc = ogg_crc(bytes(page))
        page[22:26] = crc.to_bytes(4, "little")
        f.write_bytes(bytes(page))

        with pytest.raises(ValueError, match="channel mapping family"):
            patch_opus_pre_skip(f, 960)
