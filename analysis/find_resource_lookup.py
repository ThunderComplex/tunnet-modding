#!/usr/bin/env python3
"""
Trace a panic format-string piece to the code that builds its fmt::Arguments.

For " does not exist in the `World`" (from `World::resource::<T>`):
  string VA S
    -> .rdata locations P holding a pointer to S (the &str ptr field)
    -> the pieces array base (P-16 if this piece is #1, else P)
    -> code that LEAs the pieces array base (the panic site)
"""
import struct, sys, bisect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

args = common.common_parser("Trace a panic piece to its panic site.").parse_args()
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
def va_to_off(va):
    for x in secs.values():
        if x["va"] <= va < x["va"] + x["vsize"]:
            return x["rawptr"] + (va - x["va"])
def read_u64(va):
    off = va_to_off(va)
    return struct.unpack_from("<Q", d, off)[0] if off is not None else None
def read_cstr(va, maxlen=80):
    off = va_to_off(va)
    if off is None:
        return None
    end = d.find(b"\0", off, off+maxlen)
    return d[off:end].decode("latin1", "replace")

def find_ptr_locations(target_va):
    res = []
    for name in (".rdata", ".data"):
        sec = secs[name]
        blob = d[sec["rawptr"]:sec["rawptr"] + sec["rawsize"]]
        needle = struct.pack("<Q", target_va)
        j = 0
        while True:
            k = blob.find(needle, j)
            if k < 0:
                break
            res.append(sec["va"] + k)
            j = k + 1
    return res

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
tb = text["rawptr"]; tend = tb + text["vsize"]; tva = text["va"]
def code_lea_refs(target_va):
    out = []
    i = tb
    while i + 7 <= tend:
        b0 = d[i]
        if (b0 == 0x48 or b0 == 0x4C) and d[i+1] == 0x8D and (d[i+2] & 0xC7) == 0x05:
            disp = struct.unpack_from("<i", d, i+3)[0]
            iv = tva + (i - tb); t = iv + 7 + disp
            if t == target_va:
                out.append((iv, func_of(iv)))
            i += 7; continue
        i += 1
    return out

needle = sys.argv[1].encode("latin1") if len(sys.argv) > 1 else b" does not exist in the `World`"
sv = []
i = 0
while True:
    k = d.find(needle, i)
    if k < 0:
        break
    va = off_to_va(k)
    if va:
        sv.append(va)
    i = k + 1
print(f"string VAs: {len(sv)}")

funcs = set()
for S in sv[:6]:
    for P in find_ptr_locations(S):
        # P is the address of the &str ptr field. Read the element.
        ptr = read_u64(P)
        ln = read_u64(P + 8)
        if ptr is None or ptr != S:
            continue
        text_s = read_cstr(S)
        # Determine pieces-array base: check P-16 as piece0
        for base in (P, P - 16):
            if base < 0:
                continue
            # sanity: base points into .rdata and base+16 is the other &str
            other_ptr = read_u64(base)
            if other_ptr is None:
                continue
            refs = code_lea_refs(base)
            if refs:
                funcs.update(f for _, f in refs)
                print(f"  S=0x{S:x} P=0x{P:x} base=0x{base:x} -> {len(refs)} code refs")
                for iv, f in refs[:6]:
                    print(f"     0x{iv:x} in func 0x{f:x}")
print(f"\ncandidate functions: {len(funcs)}")
for f in sorted(funcs):
    print(f"  0x{f:x}")
