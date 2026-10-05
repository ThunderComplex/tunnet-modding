#!/usr/bin/env python3
"""Extract all embedded assets using the recovered exact table, with validation."""
import json, struct, sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

parser = common.common_parser("Extract all embedded assets using the recovered table.")
parser.add_argument(
    "--dest",
    default=None,
    help="destination directory (default: <repo>/assets_extracted)",
)
args = parser.parse_args()
EXE = common.resolve_exe(args.exe)
DATA = common.resolve_data(args.data)
TABLE = json.loads((DATA / "asset_table.json").read_text())
d = EXE.read_bytes()
DEST = Path(args.dest) if args.dest else common.REPO / "assets_extracted"

def png_size(off):
    p = off + 8
    while p + 8 <= len(d):
        ln = struct.unpack_from(">I", d, p)[0]
        if d[p+4:p+8] == b"IEND":
            return p + 12 - off
        p += 12 + ln
        if ln > 0x10000000 or p > len(d):
            return None
    return None

def ogg_size(off):
    p = off; end = off
    while p + 27 <= len(d) and d[p:p+4] == b"OggS":
        nseg = d[p+26]
        if p + 27 + nseg > len(d):
            break
        seglen = sum(d[p+27:p+27+nseg])
        page = p + 27 + nseg + seglen
        if page <= p:
            break
        end = page; p = page
    return end - off if end > off else None

def glb_size(off):
    if off + 12 > len(d):
        return None
    ver, total = struct.unpack_from("<II", d, off+4)
    return total if ver == 2 else None

mismatch = []
total = 0
DEST.mkdir(parents=True, exist_ok=True)
for t in TABLE:
    off = t["data_off"]; ln = t["data_len"]; path = t["path"]
    if off is None:
        mismatch.append((path, "no offset")); continue
    actual = None
    if path.endswith(".png"):
        actual = png_size(off)
    elif path.endswith(".ogg"):
        actual = ogg_size(off)
    elif path.endswith(".glb"):
        actual = glb_size(off)
    if actual is not None and actual != ln:
        mismatch.append((path, f"len {ln} vs container {actual}"))
    blob = d[off:off+ln]
    dest = DEST / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    total += ln

print(f"extracted {len(TABLE)} assets, {total/1e6:.1f} MB -> {DEST}")
print(f"size mismatches: {len(mismatch)}")
for m in mismatch[:20]:
    print("   ", m)
print("by ext:", Counter(Path(t['path']).suffix for t in TABLE))
