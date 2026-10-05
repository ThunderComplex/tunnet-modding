#!/usr/bin/env python3
"""Decode Cheat Engine .PTR pointer-scan results.

Format (from CE's PointerscanresultReader.pas):
  .PTR: $ce, version:u8, modulelistlength:u32,
        [name_len:u32][name][base:u64] * modulelistlength,
        maxlevel:u32, compressed:u8
        if compressed: aligned:u8, bitModuleIndex:u8, bitModuleOffset:u8,
                       bitLevel:u8, bitOffset:u8, endsCount:u8, endsCount*4
        if version>=2: baseRangeScan:u8 (+ QWord if set)
  .PTR.results.N: fixed sizeofentry bytes/path, bit-packed LSB-first:
        moduleoffset(bitModuleOffset), modulenr(bitModuleIndex, signed),
        offsetcount(bitLevel), offsetcount * offset(bitOffset, <<2 if aligned)
  address = module_base[modulenr] + moduleoffset
  for j = offsetcount-1 .. 0: address = *(address) + offsets[j]
"""
import struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

args = common.common_parser(
    "Decode Cheat Engine .PTR pointer-scan results.",
    positional={"name": "ptr", "nargs": "?",
                "help": ".PTR file (default: first *.PTR in <repo>/pointermap)"},
).parse_args()
if args.ptr:
    base = Path(args.ptr)
else:
    pm = common.REPO / "pointermap"
    cands = sorted(pm.glob("*.PTR")) if pm.is_dir() else []
    if not cands:
        sys.exit("error: no .PTR file given and none found in <repo>/pointermap")
    base = cands[0]
d = base.parent
p = base.read_bytes()
i = 0
assert p[i] == 0xCE, "bad signature"
i += 1
ver = p[i]; i += 1
mlen = struct.unpack_from("<i", p, i)[0]; i += 4
mods = []
for _ in range(mlen):
    x = struct.unpack_from("<i", p, i)[0]; i += 4
    name = p[i:i+x].decode("latin1"); i += x
    addr = struct.unpack_from("<Q", p, i)[0]; i += 8
    mods.append((name, addr))
maxlevel = struct.unpack_from("<i", p, i)[0]; i += 4
compressed = p[i]; i += 1
aligned = bit_mi = bit_mo = bit_lvl = bit_off = endsc = 0
ends = []
if compressed:
    aligned = p[i]; i += 1
    bit_mi = p[i]; i += 1
    bit_mo = p[i]; i += 1
    bit_lvl = p[i]; i += 1
    bit_off = p[i]; i += 1
    endsc = p[i]; i += 1
    ends = [struct.unpack_from("<I", p, i+4*k)[0] for k in range(endsc)]
    i += 4*endsc
if ver >= 2:
    i += 1  # baseRangeScan flag
sizeofentry = (bit_mo + bit_mi + bit_lvl + bit_off*maxlevel + 7)//8
print(f"ver={ver} modules={mlen} maxlevel={maxlevel} compressed={compressed} "
      f"aligned={aligned} bits mo/mi/lvl/off={bit_mo}/{bit_mi}/{bit_lvl}/{bit_off} "
      f"ends={endsc} sizeofentry={sizeofentry}")
print("tunnet.exe:", [hex(a) for n, a in mods if "tunnet" in n.lower()])

def bits(buf, start, n):
    v = 0
    for k in range(n):
        v |= ((buf[(start+k) >> 3] >> ((start+k) & 7)) & 1) << k
    return v

files = sorted(d.glob(base.name + ".results.*"),
               key=lambda f: int(f.name.rsplit(".", 1)[1]))
entries = []
for f in files:
    b = f.read_bytes()
    o = 0
    while o + sizeofentry <= len(b):
        e = b[o:o+sizeofentry]
        mo = struct.unpack_from("<I", e, 0)[0]
        mi = bits(e, bit_mo, bit_mi)
        if mi >= 128:
            mi -= 256
        lvl = bits(e, bit_mo+bit_mi, bit_lvl)
        offs = []
        bit = bit_mo+bit_mi+bit_lvl
        for _ in range(lvl):
            v = bits(e, bit, bit_off); bit += bit_off
            if aligned:
                v <<= 2
            offs.append(v)
        entries.append((mi, mo, lvl, offs, f.name))
        o += sizeofentry
print(f"entries={len(entries)}")
for mi, mo, lvl, offs, fn in entries:
    name = mods[mi][0] if 0 <= mi < len(mods) else f"?{mi}"
    mbase = mods[mi][1] if 0 <= mi < len(mods) else 0
    print(f"{fn}: mod={mi}({name}) static={mbase+mo:#x} lvl={lvl} offs={[hex(x) for x in offs]}")
