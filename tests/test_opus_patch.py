"""Tests for the Ogg Opus in-place patcher."""
from tracksplit.opus_patch import ogg_crc


class TestOggCrc:
    def test_empty_bytes(self):
        assert ogg_crc(b"") == 0

    def test_single_byte_vector(self):
        # CRC-32/MPEG-2 variant: polynomial 0x04C11DB7, init 0, no reflect, no xorout.
        # For a single 0x00 byte, CRC is 0 (init-state feed of zero keeps CRC 0).
        assert ogg_crc(b"\x00") == 0

    def test_ascii_vector(self):
        # Ogg uses CRC-32 with polynomial 0x04C11DB7, init 0, no reflection,
        # no xorout (not the canonical CRC-32/MPEG-2 variant, which uses
        # init 0xFFFFFFFF). For init=0, CRC("123456789") == 0x89A1897F.
        assert ogg_crc(b"123456789") == 0x89A1897F
