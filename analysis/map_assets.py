#!/usr/bin/env python3
"""
Map assets embedded in tunnet.exe via bevy_embedded_assets 0.2.1.

Mechanism (from the crate's build.rs): a generated `include_all_assets()`
calls `embedded.add_asset(Path::new(<relpath>), include_bytes!(<abspath>))`
for every file under the build-time `assets/` directory. So the binary holds:
  * the relative path string literals (e.g. "textures/foo.png")
  * the raw file contents as &'static [u8] blobs

This script:
  1. Parses PE sections to map file offsets <-> virtual addresses.
  2. Finds candidate asset path strings.
  3. Carves embedded blobs by container format (PNG / Ogg / GLB / WGSL / TTF).
  4. Reports orderings so we can test the "Nth path <-> Nth blob" hypothesis.
"""
import re
import struct
import sys
import json
from pathlib import Path

EXE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"G:\SteamLibrary\steamapps\common\Tunnet\tunnet.exe")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
    r"H:\dev\Rust\tunnet-modding\data")

data = EXE.read_bytes()
N = len(data)

# ---------------------------------------------------------------- PE parsing
def parse_pe(d):
    e_lfanew = struct.unpack_from("<I", d, 0x3C)[0]
    assert d[e_lfanew:e_lfanew + 4] == b"PE\0\0", "not a PE"
    coff = e_lfanew + 4
    num_sections = struct.unpack_from("<H", d, coff + 2)[0]
    opt_size = struct.unpack_from("<H", d, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", d, opt)[0]
    if magic == 0x20B:  # PE32+
        image_base = struct.unpack_from("<Q", d, opt + 24)[0]
    else:
        image_base = struct.unpack_from("<I", d, opt + 28)[0]
    sec = opt + opt_size
    sections = []
    for i in range(num_sections):
        off = sec + i * 40
        name = d[off:off + 8].rstrip(b"\0").decode("latin1")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", d, off + 8)
        sections.append(dict(name=name, vaddr=vaddr, vsize=vsize,
                             rawptr=rawptr, rawsize=rawsize,
                             va=image_base + vaddr))
    return image_base, sections

image_base, sections = parse_pe(data)

def off_to_va(off):
    for s in sections:
        if s["rawptr"] <= off < s["rawptr"] + s["rawsize"]:
            return s["va"] + (off - s["rawptr"])
    return None

def va_to_off(va):
    for s in sections:
        if s["va"] <= va < s["va"] + s["vsize"]:
            return s["rawptr"] + (va - s["va"])
    return None

def section_of(off):
    for s in sections:
        if s["rawptr"] <= off < s["rawptr"] + s["rawsize"]:
            return s["name"]
    return None

# --------------------------------------------------- asset path string scan
PATH_RE = re.compile(
    rb"((?:textures|snd|models|shaders|fonts)/[A-Za-z0-9_./ -]*?\.(?:png|ogg|glb|gltf|wgsl|ttf|otf|mp3|wav|json|ron|bin|txt))"
)

path_hits = []
for m in PATH_RE.finditer(data):
    path_hits.append(dict(off=m.start(), path=m.group(1).decode("latin1")))
print(f"[+] asset path strings found: {len(path_hits)}")
uniq_paths = sorted({h["path"] for h in path_hits})
print(f"    unique paths: {len(uniq_paths)}")

# ------------------------------------------------------- blob carving
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
        # iterate pages until the stream's pages are exhausted; Ogg has no
        # global length, so bound by page chain using granule/continuation is
        # complex. Heuristic: pages are contiguous; stop at first gap.
        p = i
        end = i
        while p + 27 <= len(d) and d[p:p + 4] == b"OggS":
            nseg = d[p + 26]
            if p + 27 + nseg > len(d):
                break
            seglen = sum(d[p + 27:p + 27 + nseg])
            page = p + 27 + nseg + seglen
            end = page
            p = page
        out.append((i, end - i))
        i = end if end > i else i + 1
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
                # sanity: first chunk header
                clen, ctype = struct.unpack_from("<I4s", d, i + 12)
                if ctype in (b"JSON", b"BIN\0") and i + 12 + 8 + clen <= i + total:
                    out.append((i, total))
                    i += total
                    continue
        i += 4
    return out

def carve_simple(d, sig, minlen=16):
    out = []
    i = 0
    while True:
        i = d.find(sig, i)
        if i < 0:
            break
        out.append((i, None))
        i += len(sig)
    return out

print("[*] carving blobs ...")
blobs = []
for off, size in carve_png(data):
    blobs.append(dict(off=off, size=size, kind="png"))
for off, size in carve_ogg(data):
    blobs.append(dict(off=off, size=size, kind="ogg"))
for off, size in carve_glb(data):
    blobs.append(dict(off=off, size=size, kind="glb"))
blobs.sort(key=lambda b: b["off"])
from collections import Counter
print("    blob kinds:", Counter(b["kind"] for b in blobs))

# ------------------------------------------------------- ordering analysis
paths_sorted = sorted(path_hits, key=lambda h: h["off"])
by_ext = Counter(Path(h["path"]).suffix for h in path_hits)
print("    path extensions:", by_ext)

# try to align: for each kind, take paths with matching extension in order
ext_to_kind = {".png": "png", ".ogg": "ogg", ".glb": "glb"}
report = dict(
    exe=str(EXE),
    image_base=image_base,
    sections=sections,
    path_count=len(path_hits),
    unique_paths=uniq_paths,
    blob_count=len(blobs),
    blobs=blobs,
    paths=[dict(off=h["off"], va=off_to_va(h["off"]), section=section_of(h["off"]),
                path=h["path"]) for h in paths_sorted],
)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "asset_map.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(f"[+] wrote {OUT / 'asset_map.json'}")

# quick hypothesis test: same-order alignment per extension
for ext, kind in ext_to_kind.items():
    p = [h for h in paths_sorted if h["path"].endswith(ext)]
    b = [x for x in blobs if x["kind"] == kind]
    pu = sorted({h["path"] for h in p})
    print(f"    {ext}: {len(p)} occurrences, {len(pu)} unique vs {len(b)} blobs", end="")
    if len(pu) == len(b):
        print("  -> order match possible")
    else:
        print("")

# global order correlation: unique paths (first occurrence) vs blobs
def ext_seq(hits):
    seen = set()
    seq = []
    for h in sorted(hits, key=lambda x: x["off"]):
        if h["path"] in seen:
            continue
        seen.add(h["path"])
        seq.append((h["off"], Path(h["path"]).suffix))
    return seq

pseq = ext_seq(path_hits)
bseq = [(b["off"], "." + b["kind"] if b["kind"] != "glb" else ".glb") for b in blobs]
# normalize .glb for glb, png, ogg already fine
norm = {".png": ".png", ".ogg": ".ogg", ".glb": ".glb"}
bseq = [(o, norm.get(e, e)) for o, e in bseq]
# compare only the three blob kinds
bset = [e for _, e in bseq]
pset = [e for _, e in pseq if e in (".png", ".ogg", ".glb")]
print(f"    order seq lens: paths={len(pset)} blobs={len(bset)}")
if len(pset) == len(bset):
    mism = sum(1 for a, b in zip(pset, bset) if a != b)
    print(f"    global order mismatches: {mism}/{len(pset)}")
else:
    # print first divergence-ish summary
    print("    path seq head:", pset[:15])
    print("    blob seq head:", bset[:15])
