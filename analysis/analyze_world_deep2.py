#!/usr/bin/env python3
"""Parse the tagged two-level World dump (0x800/0x40) and inspect key buffers."""
import struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

args = common.common_parser(
    "Parse the tagged two-level World dump (0x800/0x40) and inspect key buffers.",
    positional={"name": "dump", "nargs": "?",
                "help": "world_deep.bin (default <repo>/data/world_deep.bin)"},
).parse_args()
p = Path(args.dump) if args.dump else common.resolve_data(args.data) / "world_deep.bin"
d = p.read_bytes()
world = struct.unpack_from("<Q", d, 0)[0]
pos = 8 + 0x800
l1 = {}
while pos + 8 <= len(d):
    tag = struct.unpack_from("<Q", d, pos)[0]
    if tag == 1:
        o, ptr = struct.unpack_from("<QQ", d, pos + 8)
        l1[o] = (ptr, d[pos+24:pos+24+0x800])
        pos += 24 + 0x800
    elif tag == 2:
        pos += 32 + 0x40
    else:
        print("bad tag", tag, "at", pos); break
print(f"world=0x{world:x} l1={len(l1)}")
for o in (0x10, 0x180, 0x1e0, 0x1f8, 0x210):
    if o not in l1:
        print(f"\nworld+{o:#x}: <no pointer>"); continue
    ptr, buf = l1[o]
    print(f"\n=== world+{o:#x} -> 0x{ptr:x} (first 0x100) ===")
    for i in range(0, 0x100, 8):
        v = struct.unpack_from("<Q", buf, i)[0]
        print(f"  +0x{i:03x}: {v:#018x}")
