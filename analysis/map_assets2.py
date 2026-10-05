#!/usr/bin/env python3
"""
Refined asset mapping for tunnet.exe.

Distinguishes *standalone* embedded assets (textures/, snd/, models/, shaders/,
fonts/ from bevy_embedded_assets) from PNG textures that live *inside* .glb
model containers, then tests whether the emission order of path string
literals matches the file-offset order of the data blobs (the "Nth path <-> Nth
blob" hypothesis).
"""
import re
import struct
import json
import csv
from pathlib import Path
from collections import Counter

EXE = Path(r"G:\SteamLibrary\steamapps\common\Tunnet\tunnet.exe")
OUT = Path(r"H:\dev\Rust\tunnet-modding\data")
data = EXE.read_bytes()

# ------------------------------------------------------------------ carving
def carve_png(d):
    sig = b"\x89PNG\r\n\x1a\n"
    out = []
    i = 0
    while True:
        i = d.find(sig, i)
        if i < 0:
            break
        p = i + 8
        end = None
        while p + 8 <= len(d):
            ln = struct.unpack_from(">I", d, p)[0]
            typ = d[p + 4:p + 8]
            if typ == b"IEND":
                end = p + 12
                break
            if ln > 0x10000000:
                break
            p += 12 + ln
            if p > len(d):
                break
        if end is not None:
            out.append((i, end - i))
            i = end
        else:
            i += 1
    return out

def carve_ogg(d):
    out = []
    i = 0
    while True:
        i = d.find(b"OggS", i)
        if i < 0:
            break
        p = i
        end = i
        while p + 27 <= len(d) and d[p:p + 4] == b"OggS":
            nseg = d[p + 26]
            if p + 27 + nseg > len(d):
                break
            seglen = sum(d[p + 27:p + 27 + nseg])
            page = p + 27 + nseg + seglen
            if page <= p:
                break
            end = page
            p = page
        if end > i:
            out.append((i, end - i))
            i = end
        else:
            i += 1
    return out

def carve_glb(d):
    out = []
    i = 0
    while True:
        i = d.find(b"glTF", i)
        if i < 0:
            break
        if i + 12 <= len(d):
            ver, total = struct.unpack_from("<II", d, i + 4)
            if ver == 2 and 12 <= total < 0x20000000 and i + total <= len(d):
                clen, ctype = struct.unpack_from("<I4s", d, i + 12)
                if ctype in (b"JSON", b"BIN\0") and i + 12 + 8 + clen <= i + total:
                    out.append((i, total))
                    i += total
                    continue
        i += 4
    return out

pngs = carve_png(data)
oggs = carve_ogg(data)
glbs = carve_glb(data)
print(f"raw signatures: png={len(pngs)} ogg={len(oggs)} glb={len(glbs)}")

glb_ranges = [(o, o + s) for o, s in glbs]
def in_glb(off):
    for a, b in glb_ranges:
        if a <= off < b:
            return True
    return False

standalone_png = [(o, s) for o, s in pngs if not in_glb(o)]
in_model_png = [(o, s) for o, s in pngs if in_glb(o)]
print(f"standalone png={len(standalone_png)}  in-model png={len(in_model_png)}")

blobs = []
for o, s in standalone_png:
    blobs.append(dict(off=o, size=s, kind="png"))
for o, s in oggs:
    blobs.append(dict(off=o, size=s, kind="ogg"))
for o, s in glbs:
    blobs.append(dict(off=o, size=s, kind="glb"))
blobs.sort(key=lambda b: b["off"])
print("standalone blob kinds:", Counter(b["kind"] for b in blobs))

# ------------------------------------------------------------------ paths
PATH_RE = re.compile(
    rb"((?:textures|snd|models|shaders|fonts)/[A-Za-z0-9_./ -]*?\.(?:png|ogg|glb|wgsl|ttf))"
)
occ = []
for m in PATH_RE.finditer(data):
    p = m.group(1).decode("latin1")
    # drop obvious run-ons: must not contain a second known dir marker mid-path
    if re.search(r"(textures|snd|models|shaders|fonts)/", p[1:]):
        continue
    occ.append((m.start(), p))

first = {}
for off, p in sorted(occ):
    first.setdefault(p, off)
print(f"asset path occurrences={len(occ)} unique={len(first)}")
print("unique by ext:", Counter(Path(p).suffix for p in first))

paths_by_ext = {}
for p, off in first.items():
    paths_by_ext.setdefault(Path(p).suffix, []).append((off, p))
for k in paths_by_ext:
    paths_by_ext[k].sort()

# --------------------------------------------------- order alignment test
ext_to_kind = {".png": "png", ".ogg": "ogg", ".glb": "glb"}
result = {}
for ext, kind in ext_to_kind.items():
    plist = paths_by_ext.get(ext, [])
    blist = [b for b in blobs if b["kind"] == kind]
    print(f"\n{ext}: paths={len(plist)} blobs={len(blist)}")
    if len(plist) == len(blist):
        result[ext] = list(zip(plist, blist))
        print("  -> 1:1 counts, assuming offset order maps")
    else:
        print("  -> counts differ")

# global kind-sequence comparison
pseq = []
seen = set()
for off, p in sorted(occ):
    if p in seen:
        continue
    seen.add(p)
    e = Path(p).suffix
    if e in ext_to_kind:
        pseq.append(e)
bseq = [{"png": ".png", "ogg": ".ogg", "glb": ".glb"}[b["kind"]] for b in blobs]
print(f"\nglobal seq: paths={len(pseq)} blobs={len(bseq)}")
if len(pseq) == len(bseq):
    mism = sum(1 for a, b in zip(pseq, bseq) if a != b)
    print(f"global order mismatches: {mism}/{len(pseq)}")
    if mism < len(pseq) * 0.1:
        print("ORDER HYPOTHESIS STRONGLY SUPPORTED")

# ------------------------------------------------------------------ output
rows = []
for ext, pairs in result.items():
    for (poff, p), b in pairs:
        rows.append(dict(path=p, kind=b["kind"], off=b["off"],
                         size=b["size"], va=0x142404000 + (b["off"] - 0x02403000)
                         if 0x02403000 <= b["off"] < 0x02403000 + 0x02ed82c0 else None,
                         path_off=poff))
with (OUT / "asset_mapping.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["path", "kind", "off", "size", "va", "path_off"])
    w.writeheader()
    w.writerows(rows)
print(f"\n[+] wrote {len(rows)} tentative mappings -> {OUT/'asset_mapping.csv'}")

summary = dict(
    standalone=dict(png=len(standalone_png), ogg=len(oggs), glb=len(glbs)),
    in_model_png=len(in_model_png),
    unique_paths=len(first),
    counts_by_ext={k: len(v) for k, v in paths_by_ext.items()},
)
(OUT / "asset_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
