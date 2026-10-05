#!/usr/bin/env python3
"""Annotate a raw World memory dump (8-byte words) to reverse field offsets."""
import struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

parser = common.common_parser(
    "Annotate a raw World memory dump (8-byte words) to reverse field offsets.",
    positional={"name": "dump", "nargs": "?",
                "help": "world.bin (default <repo>/data/world.bin)"},
)
parser.add_argument("--base", default=None, help="module base address (hex), for annotations")
parser.add_argument("--world", default=None, help="world pointer (hex)")
args = parser.parse_args()
p = Path(args.dump) if args.dump else common.resolve_data(args.data) / "world.bin"
base = int(args.base, 16) if args.base else None  # module base
world = int(args.world, 16) if args.world else None
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
