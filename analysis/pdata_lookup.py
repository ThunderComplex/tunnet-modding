#!/usr/bin/env python3
"""List .pdata functions around a range and resolve containing functions."""
import struct, sys
from pathlib import Path
from bisect import bisect_right

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

args = common.common_parser(
    "List .pdata functions around a range and resolve containing functions.",
    positional={
        "name": "addresses",
        "nargs": "*",
        "help": "VAs to resolve, e.g. 0x1404e0ce0",
    },
).parse_args()
EXE = common.resolve_exe(args.exe)
d = EXE.read_bytes()
e = struct.unpack_from("<I", d, 0x3C)[0]; c = e + 4
n = struct.unpack_from("<H", d, c + 2)[0]; osz = struct.unpack_from("<H", d, c + 16)[0]
o = c + 20; ib = struct.unpack_from("<Q", d, o + 24)[0]; s = o + osz
secs = {}
for i in range(n):
    nm = d[s+i*40:s+i*40+8].rstrip(b"\0").decode("latin1")
    vs, va, rs, rp = struct.unpack_from("<IIII", d, s+i*40+8)
    secs[nm] = dict(va=ib+va, vsize=vs, rawptr=rp, rawsize=rs)
pdata = secs[".pdata"]
fns = []
for i in range(pdata["rawsize"] // 12):
    b, en, u = struct.unpack_from("<III", d, pdata["rawptr"] + i*12)
    if b:
        fns.append((ib+b, ib+en, ib+u))
fns.sort()
starts = [a for a,_,_ in fns]
print(f"total pdata fns: {len(fns)}")

def containing(va):
    k = bisect_right(starts, va) - 1
    # walk back until a range contains va
    while k >= 0:
        if fns[k][0] <= va < fns[k][1]:
            return fns[k]
        k -= 1
    return None

for a in args.addresses:
    va = int(a, 16)
    f = containing(va)
    if f:
        print(f"0x{va:x} -> func 0x{f[0]:x}..0x{f[1]:x} ({f[1]-f[0]:#x} bytes)")
    else:
        print(f"0x{va:x} -> <not in any pdata function>")

lo, hi = 0x1404dff00, 0x1404e7c00
print(f"\npdata functions with start in [{lo:#x},{hi:#x}]:")
for a, b, u in fns:
    if lo <= a <= hi:
        print(f"  0x{a:x} .. 0x{b:x}  ({b-a:#x} bytes)")
