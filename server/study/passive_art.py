"""Read the exact enabled icon layer from PoB's own versioned DDS texture array."""

from functools import lru_cache
from io import BytesIO
import re
import struct

from PIL import Image
import zstandard
from server import paths
from .storage import fingerprint


@lru_cache(maxsize=4)
def _array(file_name, expected_hash):
    from pathlib import Path

    data = Path(file_name).read_bytes()
    if fingerprint(data) != expected_hash:
        raise ValueError("passive_texture_changed")
    return zstandard.ZstdDecompressor().decompress(data, max_output_size=128 * 1024 * 1024)


def read_icon(binding):
    version, file_name = binding["treeVersion"], binding["file"]
    if not re.fullmatch(r"[0-9_]+", version) or not re.fullmatch(
        r"skills_[0-9]+_[0-9]+_BC1\.dds\.zst", file_name
    ):
        raise ValueError("invalid_passive_texture")
    file = paths.pob_src_dir() / "TreeData" / version / file_name
    data = _array(str(file), binding["sha256"])
    if data[:4] != b"DDS " or data[84:88] != b"DX10":
        raise ValueError("unsupported_passive_texture")
    height, width = struct.unpack_from("<II", data, 12)
    levels = max(1, struct.unpack_from("<I", data, 28)[0])
    format_id, _, _, count, _ = struct.unpack_from("<5I", data, 128)
    if format_id not in {71, 72} or not 1 <= binding["layer"] <= count:
        raise ValueError("invalid_passive_texture_layer")
    stride = sum(
        max(1, (max(1, width >> level) + 3) // 4) * max(1, (max(1, height >> level) + 3) // 4) * 8
        for level in range(levels)
    )
    offset = 148 + (binding["layer"] - 1) * stride
    if offset + stride > len(data):
        raise ValueError("truncated_passive_texture")
    header = bytearray(data[:148])
    struct.pack_into("<I", header, 140, 1)
    with Image.open(BytesIO(bytes(header) + data[offset : offset + stride])) as image:
        output = BytesIO()
        image.convert("RGBA").save(output, format="PNG")
    return output.getvalue()
