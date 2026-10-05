#!/usr/bin/env python3
"""Cross-reference a numeric VA: find code LEAs and static pointer references."""
import struct, sys, bisect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

args = common.common_parser(
    "Find references to one or more VAs (code LEA + static pointers).",
    positional={"name": "addresses", "nargs": "*", "help": "VAs, e.g. 0x145265970"},
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
text = secs[".text"]
pdata = secs[".pdata"]
fns = []
for i in range(pdata["rawsize"] // 12):
    b, en, _ = struct.unpack_from("<III", d, pdata["rawptr"] + i*12)
    if b:
        fns.append((ib+b, ib+en))
fns.sort(); starts = [a for a, _ in fns]
def func_of(va):
    k = bisect.bisect_right(starts, va) - 1
    return fns[k][0] if k >= 0 else None

tb = text["rawptr"]; tend = tb + text["vsize"]; tva = text["va"]

for a in args.addresses:
    va = int(a, 16)
    print(f"\n=== refs to 0x{va:x} ===")
    # code LEAs
    refs = []
    i = tb
    while i + 7 <= tend:
        b0 = d[i]
        if (b0 == 0x48 or b0 == 0x4C) and d[i+1] == 0x8D and (d[i+2] & 0xC7) == 0x05:
            disp = struct.unpack_from("<i", d, i+3)[0]
            iv = tva + (i - tb); t = iv + 7 + disp
            if t == va:
                refs.append((iv, func_of(iv)))
            i += 7; continue
        i += 1
    print(f"  code LEA refs: {len(refs)}")
    for iv, f in refs[:20]:
        print(f"    0x{iv:x} in func 0x{f:x}" if f else f"    0x{iv:x} (no func)")
    # static pointers
    for name in (".rdata", ".data"):
        sec = secs[name]
        blob = d[sec["rawptr"]:sec["rawptr"] + sec["rawsize"]]
        needle = struct.pack("<Q", va)
        offs = []
        start = 0
        while True:
            k = blob.find(needle, start)
            if k < 0:
                break
            offs.append(sec["va"] + k)
            start = k + 1
        if offs:
            print(f"  {name} pointers: {len(offs)}  e.g. {', '.join(hex(x) for x in offs[:6])}")
