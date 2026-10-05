#!/usr/bin/env python3
"""Print raw LEA reference instruction addresses for given string patterns."""
import re, struct, sys, bisect
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

args = common.common_parser(
    "Print raw LEA reference instruction addresses for given string patterns.",
    positional={
        "name": "patterns",
        "nargs": "*",
        "help": "regex patterns matched against raw bytes (latin1)",
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
def off_to_va(off):
    for x in secs.values():
        if x["rawptr"] <= off < x["rawptr"] + x["rawsize"]:
            return x["va"] + (off - x["rawptr"])
text = secs[".text"]
target_va = {}
for pat in args.patterns:
    rx = re.compile(pat.encode("latin1"))
    for m in rx.finditer(d):
        va = off_to_va(m.start())
        if va is not None:
            target_va[va] = m.group(0).decode("latin1", "replace")
tb = text["rawptr"]; tend = tb + text["vsize"]; tva = text["va"]
refs = []
i = tb
while i + 7 <= tend:
    b0 = d[i]
    if (b0 == 0x48 or b0 == 0x4C) and d[i+1] == 0x8D and (d[i+2] & 0xC7) == 0x05:
        disp = struct.unpack_from("<i", d, i+3)[0]
        iv = tva + (i - tb); t = iv + 7 + disp
        if t in target_va:
            refs.append((iv, target_va[t]))
        i += 7; continue
    i += 1
refs.sort()
print(f"total refs: {len(refs)}")
prev = None
cluster_start = None
for iv, t in refs:
    if prev is None or iv - prev > 0x400:
        if cluster_start is not None:
            print(f"  cluster 0x{cluster_start:x} .. 0x{prev:x}  ({prev-cluster_start:#x} bytes)")
        cluster_start = iv
    prev = iv
print(f"  cluster 0x{cluster_start:x} .. 0x{prev:x}  ({prev-cluster_start:#x} bytes)")
print("\nraw refs (instr_va  target):")
for iv, t in refs:
    print(f"  0x{iv:x}  {t}")
