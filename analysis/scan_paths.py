#!/usr/bin/env python3
"""Broad scan of asset-like path strings in tunnet.exe."""
import sys
import re
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

args = common.common_parser(
    "Broad scan of asset-like path strings in tunnet.exe."
).parse_args()
EXE = common.resolve_exe(args.exe)
d = EXE.read_bytes()

rx = re.compile(
    rb"([A-Za-z0-9_][A-Za-z0-9_./ -]*?\."
    rb"(?:png|ogg|glb|gltf|wgsl|ttf|otf|mp3|wav|json|ron|bin|txt|hdr|ktx2|basis))"
)
hits = [m.group(1).decode("latin1") for m in rx.finditer(d)]
c = Counter(hits)
print("total occurrences:", len(hits), "unique:", len(c))

dirs = Counter()
for p in c:
    if "/" in p:
        dirs[p.rsplit("/", 1)[0].split("/")[0]] += 1
    else:
        dirs["<root>"] += 1
print("top-level dirs:", dirs.most_common(50))

for ext in (".png", ".ogg", ".glb", ".ttf", ".wgsl"):
    sub = [p for p in c if p.endswith(ext)]
    dd = Counter(p.rsplit("/", 1)[0] if "/" in p else "<root>" for p in sub)
    print(f"\nunique {ext}: {len(sub)}")
    print("  dirs:", dd.most_common(40))

ass = [p for p in c if "asset" in p.lower()]
print("\npaths containing 'asset':", len(ass))
for p in ass[:20]:
    print("   ", p)
