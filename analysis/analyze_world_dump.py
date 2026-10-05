#!/usr/bin/env python3
"""Annotate a raw World memory dump (8-byte words) to reverse field offsets."""
import struct, sys
from pathlib import Path

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"H:\dev\Rust\tunnet-modding\deploy-test\world.bin")
base = int(sys.argv[2], 16) if len(sys.argv) > 2 else None  # module base
world = int(sys.argv[3], 16) if len(sys.argv) > 3 else None
d = p.read_bytes()

def classify(v):
    if v == 0:
        return "0"
    if base is not None and base <= v < base + 0x6000000:
        return f"mod+{v-base:#x}"
    if 0x7ff000000000 <= v < 0x800000000000:
        return "modptr"
    if 0x200000000000 <= v < 0x400000000000:
        return "heap"
    if v < 0x100000:
        return f"int:{v}"
    return f"0x{v:x}"

for off in range(0, len(d), 8):
    v = struct.unpack_from("<Q", d, off)[0]
    print(f"{off:#06x}: {v:#018x}  {classify(v)}")
