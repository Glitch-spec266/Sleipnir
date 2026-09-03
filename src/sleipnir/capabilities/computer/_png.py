"""A PNG encoder in stdlib ``zlib`` + ``struct``, for the Windows backend.

The Linux backend never needs this: ``spectacle``/``grim``/``import`` write
the file themselves. GDI hands back raw pixels instead, so something has to
turn them into a file the agent can read -- and adding Pillow for that would
break the project's "deps stay pydantic + httpx" rule for thirty lines of
work that the standard library already has the hard parts of (``zlib``
deflate, ``zlib.crc32``).

Deliberately minimal: 8-bit RGB, no interlace, no palette, every scanline
filtered with type 0 (None). Filtering exists to make the deflate stream
smaller, not to make the file valid; a screenshot is mostly flat UI colour
that deflate already handles well, and per-scanline filter selection in pure
Python would cost more time per capture than the bytes are worth.
"""

from __future__ import annotations

import struct
import zlib


def _chunk(tag: bytes, payload: bytes) -> bytes:
    """One PNG chunk: length, tag, payload, CRC over tag+payload."""
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_rgb(pixels: bytes, width: int, height: int) -> bytes:
    """Encode top-down, packed 8-bit RGB rows as a PNG file.

    ``pixels`` must be exactly ``width * height * 3`` bytes, row-major from
    the top-left -- the caller is responsible for having flipped a
    bottom-up DIB and dropped any alpha channel.
    """
    stride = width * 3
    expected = stride * height
    if len(pixels) != expected:
        raise ValueError(f"expected {expected} bytes of RGB, got {len(pixels)}")

    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter type 0 (None) for this scanline
        raw += pixels[row * stride : (row + 1) * stride]

    header = struct.pack(
        ">IIBBBBB",
        width,
        height,
        8,  # bit depth
        2,  # colour type 2 = truecolour RGB
        0,  # deflate
        0,  # adaptive filtering
        0,  # no interlace
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


__all__ = ["encode_rgb"]
