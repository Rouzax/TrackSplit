"""In-place patcher for the OpusHead pre_skip field in Ogg Opus files."""
from __future__ import annotations

from pathlib import Path


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
    """Compute the Ogg page CRC over `data`.

    CRC-32 with polynomial 0x04C11DB7, init 0, no reflection, no xorout
    (RFC 3533).
    """
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ b) & 0xFF]
    return crc


_OGG_PAGE_HEADER_LEN = 27
_CRC_FIELD_OFFSET = 22


def _first_page_length(data: bytes) -> int:
    if data[:4] != b"OggS":
        raise ValueError("Not an Ogg file (missing 'OggS' capture pattern)")
    nsegs = data[26]
    seg_table_end = _OGG_PAGE_HEADER_LEN + nsegs
    return seg_table_end + sum(data[_OGG_PAGE_HEADER_LEN:seg_table_end])


def _opus_head_offset(data: bytes, page_len: int) -> int:
    i = data.find(b"OpusHead", 0, page_len)
    if i < 0:
        raise ValueError("OpusHead not found in first Ogg page")
    return i


def _check_mapping_family(data: bytes, opus_head: int) -> None:
    family = data[opus_head + 18]
    if family != 0:
        raise ValueError(
            f"Unsupported OpusHead channel mapping family {family} "
            "(only family 0, mono/stereo, is supported)",
        )


def read_opus_pre_skip(path: Path) -> int:
    """Return the pre_skip value from the OpusHead in `path`."""
    data = path.read_bytes()
    page_len = _first_page_length(data)
    head = _opus_head_offset(data, page_len)
    _check_mapping_family(data, head)
    return int.from_bytes(data[head + 10:head + 12], "little")


def patch_opus_pre_skip(path: Path, new_pre_skip: int) -> None:
    """Rewrite pre_skip in the OpusHead of `path` and recompute the page CRC.

    Only family-0 OpusHead layouts are supported. Raises ValueError otherwise.
    """
    if not 0 <= new_pre_skip <= 0xFFFF:
        raise ValueError(f"pre_skip must fit in uint16, got {new_pre_skip}")
    data = bytearray(path.read_bytes())
    page_len = _first_page_length(bytes(data))
    head = _opus_head_offset(bytes(data), page_len)
    _check_mapping_family(bytes(data), head)

    data[head + 10:head + 12] = new_pre_skip.to_bytes(2, "little")
    data[_CRC_FIELD_OFFSET:_CRC_FIELD_OFFSET + 4] = b"\x00\x00\x00\x00"
    new_crc = ogg_crc(bytes(data[:page_len]))
    data[_CRC_FIELD_OFFSET:_CRC_FIELD_OFFSET + 4] = new_crc.to_bytes(4, "little")

    path.write_bytes(bytes(data))
