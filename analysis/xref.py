#!/usr/bin/env python3
"""
Cross-reference string literals to referencing functions in tunnet.exe.

Usage:
    python xref.py <pattern> [<pattern> ...]

Each pattern is a regex matched against raw bytes (decoded latin1). All matching
string VAs are collected, then .text is scanned for RIP-relative LEA references
to those VAs, grouped by the enclosing .pdata function.
"""
import re, struct, sys, bisect
from pathlib import Path
from collections import defaultdict, Counter

EXE = Path(r"G:\SteamLibrary\steamapps\common\Tunnet\tunnet.exe")
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
fns.sort(); starts = [a for a,_ in fns]
def func_of(va):
    k = bisect.bisect_right(starts, va) - 1
    if k >= 0 and fns[k][0] <= va < fns[k][1]:
        return fns[k][0]
    return fns[k][0] if k >= 0 else None  # nearest preceding (leaf fns lack .pdata)

patterns = [p.encode("latin1") for p in sys.argv[1:]]
target_va = {}   # va -> text
for pat in patterns:
    try:
        rx = re.compile(pat)
    except re.error:
        rx = re.compile(re.escape(pat))
    for m in rx.finditer(d):
        va = off_to_va(m.start())
        if va is not None:
            target_va[va] = d[m.start():m.end()].decode("latin1", "replace")

print(f"target string VAs: {len(target_va)}")

tb = text["rawptr"]; tend = tb + text["vsize"]; tva = text["va"]
by_func = defaultdict(list)
i = tb
while i + 7 <= tend:
    b0 = d[i]
    if (b0 == 0x48 or b0 == 0x4C) and d[i+1] == 0x8D and (d[i+2] & 0xC7) == 0x05:
        disp = struct.unpack_from("<i", d, i+3)[0]
        iv = tva + (i - tb); target = iv + 7 + disp
        if target in target_va:
            by_func[func_of(iv)].append((iv, target_va[target]))
        i += 7; continue
    i += 1

print(f"functions referencing them: {len(by_func)}")
ranked = sorted(by_func.items(), key=lambda kv: -len(kv[1]))
for f, refs in ranked[:15]:
    names = Counter(t for _, t in refs)
    print(f"\n  func 0x{f:x}  ({len(refs)} refs)")
    for t, cnt in names.most_common(12):
        print(f"      {cnt:3d}  {t}")

# --- absolute pointer references (static tables) in .rdata/.data ---
print("\n=== absolute pointer references (static tables) ===")
for name in (".rdata", ".data"):
    sec = secs[name]
    blob = d[sec["rawptr"]:sec["rawptr"] + sec["rawsize"]]
    hits = defaultdict(list)
    for va, txt in target_va.items():
        needle = struct.pack("<Q", va)
        start = 0
        while True:
            k = blob.find(needle, start)
            if k < 0:
                break
            hits[txt].append(sec["va"] + k)
            start = k + 1
    if hits:
        print(f"\n section {name}:")
        for txt, offs in sorted(hits.items(), key=lambda kv: -len(kv[1])):
            print(f"   {len(offs):3d}x  {txt}   e.g. VA {', '.join(hex(x) for x in offs[:3])}")
