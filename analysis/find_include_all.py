#!/usr/bin/env python3
"""
Recover the exact asset table from tunnet.exe by locating the generated
`include_all_assets()` function.

Strategy:
  * Parse PE sections + .pdata (SEH function table) to get function ranges.
  * Scan .text for RIP-relative LEA instructions and resolve their targets.
  * Asset path string literals and include_bytes! data arrays live in .rdata;
    the function that references *all* of them is include_all_assets().
  * Within that function, pair each path reference with the following data
    reference to recover the path -> blob mapping exactly.
"""
import re
import struct
import json
from pathlib import Path
from collections import Counter, defaultdict

EXE = Path(r"G:\SteamLibrary\steamapps\common\Tunnet\tunnet.exe")
OUT = Path(r"H:\dev\Rust\tunnet-modding\data")
d = EXE.read_bytes()

# ------------------------------------------------------------- PE sections
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
    sections[name] = dict(va=image_base + vaddr, vsize=vsize,
                          rawptr=rawptr, rawsize=rawsize)

def off_to_va(off):
    for s in sections.values():
        if s["rawptr"] <= off < s["rawptr"] + s["rawsize"]:
            return s["va"] + (off - s["rawptr"])
    return None

def va_to_off(va):
    for s in sections.values():
        if s["va"] <= va < s["va"] + s["vsize"]:
            return s["rawptr"] + (va - s["va"])
    return None

text = sections[".text"]
rdata = sections[".rdata"]
pdata = sections[".pdata"]
print(f"image_base=0x{image_base:x}  .text VA=0x{text['va']:x} size=0x{text['vsize']:x}")

# --------------------------------------------------------- function ranges
fns = []
poff = pdata["rawptr"]
for i in range(pdata["rawsize"] // 12):
    begin, end, unwind = struct.unpack_from("<III", d, poff + i * 12)
    if begin == 0:
        continue
    fns.append((image_base + begin, image_base + end))
fns.sort()
starts = [a for a, _ in fns]
import bisect
def func_of(va):
    idx = bisect.bisect_right(starts, va) - 1
    if idx >= 0 and fns[idx][0] <= va < fns[idx][1]:
        return fns[idx][0]
    return None
print(f".pdata functions: {len(fns)}")

# --------------------------------------------------------- path strings
PATH_RE = re.compile(
    rb"((?:textures|snd|models|shaders|fonts)/[A-Za-z0-9_./ -]*?\.(?:png|ogg|glb|wgsl|ttf))"
)
path_va = {}          # va -> path
path_occurrence = []  # (off, path)
for m in PATH_RE.finditer(d):
    p = m.group(1).decode("latin1")
    if re.search(r"(textures|snd|models|shaders|fonts)/", p[1:]):
        continue
    va = off_to_va(m.start())
    if va is None:
        continue
    if va not in path_va:
        path_va[va] = p
    path_occurrence.append((m.start(), p))
print(f"path literals: {len(path_occurrence)} occurrences, {len(path_va)} unique VAs")

# --------------------------------------------------------- blob starts
def carve_png(dd):
    sig = b"\x89PNG\r\n\x1a\n"
    out = []
    i = 0
    while True:
        i = dd.find(sig, i)
        if i < 0:
            break
        p = i + 8
        end = None
        while p + 8 <= len(dd):
            ln = struct.unpack_from(">I", dd, p)[0]
            typ = dd[p + 4:p + 8]
            if typ == b"IEND":
                end = p + 12
                break
            if ln > 0x10000000:
                break
            p += 12 + ln
            if p > len(dd):
                break
        if end is not None:
            out.append((i, end - i)); i = end
        else:
            i += 1
    return out

def carve_ogg(dd):
    out = []
    i = 0
    while True:
        i = dd.find(b"OggS", i)
        if i < 0:
            break
        p = i; end = i
        while p + 27 <= len(dd) and dd[p:p + 4] == b"OggS":
            nseg = dd[p + 26]
            if p + 27 + nseg > len(dd):
                break
            seglen = sum(dd[p + 27:p + 27 + nseg])
            page = p + 27 + nseg + seglen
            if page <= p:
                break
            end = page; p = page
        if end > i:
            out.append((i, end - i)); i = end
        else:
            i += 1
    return out

def carve_glb(dd):
    out = []
    i = 0
    while True:
        i = dd.find(b"glTF", i)
        if i < 0:
            break
        if i + 12 <= len(dd):
            ver, total = struct.unpack_from("<II", dd, i + 4)
            if ver == 2 and 12 <= total < 0x20000000 and i + total <= len(dd):
                clen, ctype = struct.unpack_from("<I4s", dd, i + 12)
                if ctype in (b"JSON", b"BIN\0") and i + 12 + 8 + clen <= i + total:
                    out.append((i, total)); i += total; continue
        i += 4
    return out

blob_by_va = {}  # va -> (kind, size)
glb_ranges = []
for o, s in carve_glb(d):
    va = off_to_va(o)
    if va:
        blob_by_va[va] = ("glb", s)
    glb_ranges.append((o, o + s))
def in_glb(off):
    return any(a <= off < b for a, b in glb_ranges)
for o, s in carve_png(d):
    if in_glb(o):
        continue
    va = off_to_va(o)
    if va:
        blob_by_va[va] = ("png", s)
for o, s in carve_ogg(d):
    va = off_to_va(o)
    if va:
        blob_by_va[va] = ("ogg", s)
print(f"blob starts: {len(blob_by_va)}")

# --------------------------------------------------------- scan .text for LEAs
tb = text["rawptr"]
tend = tb + text["vsize"]
text_va = text["va"]
refs = []  # (func_va, instr_va, target_va)
i = tb
while i + 7 <= tend:
    b0 = d[i]
    if (b0 == 0x48 or b0 == 0x4C) and d[i + 1] == 0x8D:
        modrm = d[i + 2]
        if (modrm & 0xC7) == 0x05:
            disp = struct.unpack_from("<i", d, i + 3)[0]
            instr_va = text_va + (i - tb)
            target = instr_va + 7 + disp
            if target in path_va or target in blob_by_va:
                refs.append((func_of(instr_va), instr_va, target))
            i += 7
            continue
    i += 1
print(f"resolved asset refs: {len(refs)}")

# group by function
by_func = defaultdict(list)
for f, iv, tv in refs:
    by_func[f].append((iv, tv))
ranked = sorted(by_func.items(), key=lambda kv: -len(kv[1]))
print("top functions by asset refs:")
for f, r in ranked[:8]:
    print(f"  func 0x{f:x}: {len(r)} refs")

if not ranked:
    raise SystemExit("no function found")

target_func, trefs = ranked[0]
trefs.sort()
print(f"\n>>> include_all_assets() candidate @ 0x{target_func:x} with {len(trefs)} refs")

# pair: each blob binds to the nearest preceding path ref
mapping = []
pending = None
for iv, tv in trefs:
    if tv in path_va:
        pending = (iv, tv)
    elif tv in blob_by_va:
        if pending is not None:
            kind, size = blob_by_va[tv]
            mapping.append(dict(path=path_va[pending[1]], kind=kind, va=tv, size=size,
                                off=va_to_off(tv), path_va=pending[1]))
            pending = None

# consistency: extension vs blob kind
ext_kind = {".png": "png", ".ogg": "ogg", ".glb": "glb"}
mismatch = [m for m in mapping if ext_kind.get(Path(m["path"]).suffix) not in (None, m["kind"])]
print(f"recovered mappings: {len(mapping)}")
print("by kind:", Counter(m["kind"] for m in mapping))
print(f"extension/kind mismatches: {len(mismatch)}")
for m in mismatch[:10]:
    print("   mismatch:", m["path"], m["kind"])
dup = [p for p, c in Counter(m["path"] for m in mapping).items() if c > 1]
print(f"paths mapped more than once: {len(dup)}")
used_blobs = {m["va"] for m in mapping}
print(f"blobs covered: {len(used_blobs)}/{len(blob_by_va)}")
missing_blobs = [v for v in blob_by_va if v not in used_blobs]
print("uncovered blob kinds:", Counter(blob_by_va[v][0] for v in missing_blobs))
# uncovered paths
used_paths = {m["path_va"] for m in mapping}
uncovered = [p for v, p in path_va.items() if v not in used_paths]
print(f"uncovered path literals in this function: {len(uncovered)}",
      Counter(Path(p).suffix for p in uncovered))

import csv
with (OUT / "asset_mapping_exact.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["path", "kind", "off", "size", "va", "path_va"])
    w.writeheader(); w.writerows(mapping)
(OUT / "include_all_assets.json").write_text(json.dumps(
    dict(func_va=target_func, refs=len(trefs), mappings=mapping), indent=2))
print(f"[+] wrote {OUT/'asset_mapping_exact.csv'}")
for m in mapping[:10]:
    print(f"  {m['path']} -> {m['kind']} @ off 0x{m['off']:x} size {m['size']}")
