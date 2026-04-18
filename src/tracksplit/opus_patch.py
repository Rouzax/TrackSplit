"""In-place patcher for the OpusHead pre_skip field in Ogg Opus files."""
from __future__ import annotations


def _build_table() -> list[int]:
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            if r & 0x80000000:
                r = ((r << 1) & 0xFFFFFFFF) ^ 0x04C11DB7
            else:
                r = (r << 1) & 0xFFFFFFFF
        table.append(r)
    return table


_CRC_TABLE: list[int] = _build_table()


def ogg_crc(data: bytes) -> int:
    """Compute the Ogg page CRC (CRC-32/MPEG-2) over `data`."""
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ b) & 0xFF]
    return crc
