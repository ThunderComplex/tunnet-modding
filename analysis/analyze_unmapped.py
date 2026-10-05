#!/usr/bin/env python3
"""Analyze blob references across all functions to classify unmapped blobs."""
import re, struct, json
from pathlib import Path
from collections import Counter, defaultdict
import bisect

EXE = Path(r"G:\SteamLibrary\steamapps\common\Tunnet\tunnet.exe")
OUT = Path(r"H:\dev\Rust\tunnet-modding\data")
d = EXE.read_bytes()

e_lfanew = struct.unpack_from("<I", d, 0x3C)[0]
coff = e_lfanew + 4
num_sections = struct.unpack_from("<H", d, coff + 2)[0]
opt_size = struct.unpack_from("<H", d, coff + 16)[0]
opt = coff + 20
image_base = struct.unpack_from("<Q", d, opt + 24)[0]
sec = opt + opt_size
sections = {}
for i in range(num_sections):
    o = sec + i * 40
    name = d[o:o + 8].rstrip(b"\0").decode("latin1")
    vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", d, o + 8)
    sections[name] = dict(va=image_base + vaddr, vsize=vsize, rawptr=rawptr, rawsize=rawsize)

def off_to_va(off):
    for s in sections.values():
        if s["rawptr"] <= off < s["rawptr"] + s["rawsize"]:
            return s["va"] + (off - s["rawptr"])
def va_to_off(va):
    for s in sections.values():
        if s["va"] <= va < s["va"] + s["vsize"]:
            return s["rawptr"] + (va - s["va"])

text = sections[".text"]; pdata = sections[".pdata"]

fns = []
for i in range(pdata["rawsize"] // 12):
    begin, end, _ = struct.unpack_from("<III", d, pdata["rawptr"] + i * 12)
    if begin:
        fns.append((image_base + begin, image_base + end))
fns.sort(); starts = [a for a, _ in fns]
def func_of(va):
    idx = bisect.bisect_right(starts, va) - 1
    if idx >= 0 and fns[idx][0] <= va < fns[idx][1]:
        return fns[idx][0]

def carve_png(dd):
    out = []; i = 0; sig = b"\x89PNG\r\n\x1a\n"
    while True:
        i = dd.find(sig, i)
        if i < 0: break
        p = i + 8; end = None
        while p + 8 <= len(dd):
            ln = struct.unpack_from(">I", dd, p)[0]; typ = dd[p+4:p+8]
            if typ == b"IEND": end = p + 12; break
            if ln > 0x10000000: break
            p += 12 + ln
            if p > len(dd): break
        if end is not None: out.append((i, end - i)); i = end
        else: i += 1
    return out
def carve_ogg(dd):
    out = []; i = 0
    while True:
        i = dd.find(b"OggS", i)
        if i < 0: break
        p = i; end = i
        while p + 27 <= len(dd) and dd[p:p+4] == b"OggS":
            nseg = dd[p+26]
            if p + 27 + nseg > len(dd): break
            seglen = sum(dd[p+27:p+27+nseg]); page = p + 27 + nseg + seglen
            if page <= p: break
            end = page; p = page
        if end > i: out.append((i, end-i)); i = end
        else: i += 1
    return out
def carve_glb(dd):
    out = []; i = 0
    while True:
        i = dd.find(b"glTF", i)
        if i < 0: break
        if i + 12 <= len(dd):
            ver, total = struct.unpack_from("<II", dd, i+4)
            if ver == 2 and 12 <= total < 0x20000000 and i + total <= len(dd):
                clen, ctype = struct.unpack_from("<I4s", dd, i+12)
                if ctype in (b"JSON", b"BIN\0") and i+12+8+clen <= i+total:
                    out.append((i,total)); i += total; continue
        i += 4
    return out

glbs = carve_glb(d); glb_ranges = [(o,o+s) for o,s in glbs]
def in_glb(o): return any(a<=o<b for a,b in glb_ranges)
blob_by_va = {}
for o,s in glbs:
    va=off_to_va(o); blob_by_va[va]=("glb",s,o)
for o,s in carve_png(d):
    if not in_glb(o):
        va=off_to_va(o); blob_by_va[va]=("png",s,o)
for o,s in carve_ogg(d):
    va=off_to_va(o); blob_by_va[va]=("ogg",s,o)

# exact mappings recovered earlier
exact = json.loads((OUT/"include_all_assets.json").read_text())
mapped_va = {m["va"] for m in exact["mappings"]}

# scan refs across all .text
ref_by_blob = defaultdict(list)
tb=text["rawptr"]; tend=tb+text["vsize"]; tva=text["va"]
i=tb
while i+7<=tend:
    b0=d[i]
    if (b0==0x48 or b0==0x4C) and d[i+1]==0x8D and (d[i+2]&0xC7)==0x05:
        disp=struct.unpack_from("<i", d, i+3)[0]
        iv=tva+(i-tb); target=iv+7+disp
        if target in blob_by_va:
            ref_by_blob[target].append(func_of(iv))
        i+=7; continue
    i+=1

unmapped = [va for va in blob_by_va if va not in mapped_va]
print(f"unmapped blobs: {len(unmapped)}")
print("kinds:", Counter(blob_by_va[v][0] for v in unmapped))
# cluster by referencing function
fn_counter = Counter()
for v in unmapped:
    fs = ref_by_blob.get(v)
    if not fs:
        fn_counter["<no lea ref>"] += 1
    else:
        for f in fs:
            fn_counter[f] += 1
print("referencing functions of unmapped blobs:")
for f, c in fn_counter.most_common(10):
    print(f"   0x{f:x}: {c}" if isinstance(f,int) else f"   {f}: {c}")

# offsets of unmapped blobs (are they clustered?)
offs = sorted(blob_by_va[v][2] for v in unmapped)
print("unmapped offset range: 0x%x .. 0x%x" % (offs[0], offs[-1]))
# print sample paths near unmapped? just list sizes
print("unmapped sizes:", sorted(blob_by_va[v][1] for v in unmapped)[:20], "...")
