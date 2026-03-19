"""Length-prefixed wire framing for ezchat TCP connections.

Each frame on the wire:
    [4 bytes big-endian uint32 length] [length bytes payload]

During handshake: payload is UTF-8 JSON.
Post-handshake:   payload is encrypted bytes (nonce || ciphertext).
"""
from __future__ import annotations

import asyncio
import struct

_HEADER = struct.Struct("!I")   # big-endian uint32
_MAX_FRAME = 16 * 1024 * 1024  # 16 MiB safety limit


async def read_frame(reader: asyncio.StreamReader) -> bytes:
    """Read exactly one frame from the stream; raises EOFError on disconnect."""
    header = await reader.readexactly(_HEADER.size)
    (length,) = _HEADER.unpack(header)
    if length > _MAX_FRAME:
        raise ValueError(f"Frame too large: {length} bytes")
    return await reader.readexactly(length)


async def write_frame(writer: asyncio.StreamWriter, data: bytes) -> None:
    """Write one frame to the stream."""
    writer.write(_HEADER.pack(len(data)) + data)
    await writer.drain()
