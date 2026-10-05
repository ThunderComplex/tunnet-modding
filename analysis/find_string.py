#!/usr/bin/env python3
"""Find exact (delimited) occurrences of a string and xref them."""
import re, struct, sys
from pathlib import Path

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
text = secs[".text"]
needle = sys.argv[1].encode("latin1")
tva = text["va"]; tb = text["rawptr"]; tend = tb + text["vsize"]
# exact-delimited occurrences (not part of a longer identifier/path)
occ = []
start = 0
while True:
    k = d.find(needle, start)
    if k < 0: break
    before = d[k-1:k] if k > 0 else b"\x00"
    after = d[k+len(needle):k+len(needle)+1]
    if (not (before.isalnum() or before in b"_/\\.")) and (not (after.isalnum() or after in b"_/\\.")):
        va = off_to_va(k)
        if va: occ.append(va)
    start = k + 1
print(f"exact occurrences of {needle!r}: {len(occ)}")
for va in occ:
    print(f"  VA 0x{va:x}")
# xref
tvset = set(occ)
refs = []
i = tb
while i + 7 <= tend:
    b0 = d[i]
    if (b0 == 0x48 or b0 == 0x4C) and d[i+1] == 0x8D and (d[i+2] & 0xC7) == 0x05:
        disp = struct.unpack_from("<i", d, i+3)[0]
        iv = tva + (i - tb); t = iv + 7 + disp
        if t in tvset:
            refs.append(iv)
        i += 7; continue
    i += 1
print(f"LEA refs: {len(refs)}")
for iv in sorted(refs):
    print(f"  ref instr 0x{iv:x}")
