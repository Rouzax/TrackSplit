"""Tests for the Ogg Opus in-place patcher."""
from tracksplit.opus_patch import ogg_crc


class TestOggCrc:
    def test_empty_bytes(self):
        assert ogg_crc(b"") == 0

    def test_single_byte_vector(self):
        assert ogg_crc(b"\x00") == 0

    def test_ascii_vector(self):
        # Ogg uses init 0, not the canonical CRC-32/MPEG-2 init 0xFFFFFFFF.
        assert ogg_crc(b"123456789") == 0x89A1897F
