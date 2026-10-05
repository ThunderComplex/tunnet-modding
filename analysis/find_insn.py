#!/usr/bin/env python3
"""Search tunnet.exe for the byte patterns the user found via Cheat Engine."""
import struct, sys, bisect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

args = common.common_parser("Find instruction byte patterns in tunnet.exe.",
                            positional={"name": "patterns", "nargs": "*"}).parse_args()
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
def off_to_va(off):
    for x in secs.values():
        if x["rawptr"] <= off < x["rawptr"] + x["rawsize"]:
            return x["va"] + (off - x["rawptr"])
text = secs[".text"]; pdata = secs[".pdata"]
fns = []
for i in range(pdata["rawsize"] // 12):
    b, en, _ = struct.unpack_from("<III", d, pdata["rawptr"] + i*12)
    if b:
        fns.append((ib+b, ib+en))
fns.sort(); starts = [a for a, _ in fns]
def func_of(va):
    k = bisect.bisect_right(starts, va) - 1
    return fns[k][0] if k >= 0 else None

patterns = {
    "movsd xmm14,[rax+40]": "F2440F107040",
    "movups xmm1,[rcx+44]": "0F104944",
    "movsd xmm3,[rbx+48]": "F20F105B48",
    "movups xmm1,[r9+10]": "410F104910",
    "movsd xmm0,[r9+10]": "F2410F104110",
    "movups [rsi+48],xmm1": "0F114E48",
    "movups [rbp+44],xmm1": "0F114D44",
    "movups [rcx+3C],xmm1": "0F11493C",
}
if args.patterns:
    patterns = {p: p.replace(" ", "") for p in args.patterns}
for name, hexs in patterns.items():
    pat = bytes.fromhex(hexs)
    hits = []
    i = 0
    while True:
        k = d.find(pat, i)
        if k < 0:
            break
        va = off_to_va(k)
        if va and text["va"] <= va < text["va"] + text["vsize"]:
            hits.append((va, func_of(va)))
        i = k + 1
    print(f"\n{name}  ({hexs})  hits={len(hits)}")
    for va, f in hits[:8]:
        print(f"   instr 0x{va:x}  func 0x{f:x}")
