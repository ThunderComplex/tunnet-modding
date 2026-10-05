#!/usr/bin/env python3
"""Find callers of a target VA (direct rel32 call/jmp) and show .pdata range."""
import re, struct, sys, bisect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

args = common.common_parser(
    "Find callers of a target VA (direct rel32 call/jmp) and show .pdata range.",
    positional={"name": "address", "nargs": "?", "help": "target VA, e.g. 0x1404db3e0"},
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
text = secs[".text"]; pdata = secs[".pdata"]
fns = []
for i in range(pdata["rawsize"] // 12):
    b, en, _ = struct.unpack_from("<III", d, pdata["rawptr"] + i*12)
    if b:
        fns.append((ib+b, ib+en))
fns.sort(); starts = [a for a,_ in fns]
def func_of(va):
    k = bisect.bisect_right(starts, va) - 1
    return fns[k][0] if k >= 0 else None

target = int(args.address, 16)
# range
k = bisect.bisect_right(starts, target) - 1
print(f"target 0x{target:x}")
if k >= 0 and fns[k][0] <= target < fns[k][1]:
    print(f"  .pdata range: 0x{fns[k][0]:x} .. 0x{fns[k][1]:x}")

tb = text["rawptr"]; tend = tb + text["vsize"]; tva = text["va"]
callers = []
i = tb
while i + 5 <= tend:
    op = d[i]
    if op in (0xE8, 0xE9):
        rel = struct.unpack_from("<i", d, i+1)[0]
        iv = tva + (i - tb)
        dest = iv + 5 + rel
        if dest == target:
            callers.append((iv, func_of(iv), "call" if op == 0xE8 else "jmp"))
        i += 5; continue
    i += 1
print(f"  direct callers: {len(callers)}")
for iv, f, kind in callers:
    print(f"    {kind} from 0x{iv:x}  in func 0x{f:x}" if f else f"    {kind} from 0x{iv:x} (no func)")
