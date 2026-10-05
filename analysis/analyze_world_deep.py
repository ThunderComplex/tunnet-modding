#!/usr/bin/env python3
"""Parse the tagged two-level World dump and locate type-name strings."""
import struct, sys, re
from pathlib import Path

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"H:\dev\Rust\tunnet-modding\deploy-test\world_deep.bin")
d = p.read_bytes()
world = struct.unpack_from("<Q", d, 0)[0]
print(f"world=0x{world:x} file={len(d)}")
pos = 8 + 0x800
l1 = {}
l2 = []
strre = re.compile(rb"[\x20-\x7e]{4,}")
while pos + 8 <= len(d):
    tag = struct.unpack_from("<Q", d, pos)[0]
    if tag == 1:
        o, ptr = struct.unpack_from("<QQ", d, pos + 8)
        buf = d[pos+24:pos+24+0x200]
        l1[o] = (ptr, buf)
        pos += 24 + 0x200
    elif tag == 2:
        o, o2, q = struct.unpack_from("<QQQ", d, pos + 8)
        buf = d[pos+32:pos+32+0x40]
        l2.append((o, o2, q, buf))
        pos += 32 + 0x40
    else:
        print(f"bad tag {tag} at {pos}")
        break
print(f"l1={len(l1)} l2={len(l2)}")

# names found in l2 buffers
named = []
for o, o2, q, buf in l2:
    names = [m.group(0).decode("latin1") for m in strre.finditer(buf)
             if b"::" in m.group(0)]
    for nm in names:
        named.append((o, o2, q, nm))
print(f"l2 type-name strings: {len(named)}")
for o, o2, q, nm in named[:40]:
    print(f"  world+{o:#05x} -> buf+{o2:#04x} @0x{q:x}: {nm}")

# which level-1 buffer (by world offset o) has the most named l2 pointers?
from collections import Counter
c = Counter(o for o, _, _, _ in named)
print("\nl1 offsets ranked by named children:")
for o, cnt in c.most_common(10):
    ptr, _ = l1.get(o, (0, b""))
    print(f"  world+{o:#05x} ptr=0x{ptr:x}: {cnt} names")
# for the top one, show offsets o2
if c:
    top = c.most_common(1)[0][0]
    o2s = sorted(o2 for o, o2, _, _ in named if o == top)
    print(f"\ntop l1 world+{top:#x}: name ptr offsets o2 = {[hex(x) for x in o2s[:20]]}")
    diffs = [o2s[i+1]-o2s[i] for i in range(len(o2s)-1)]
    print(f"  o2 diffs: {[hex(x) for x in diffs[:20]]}")
