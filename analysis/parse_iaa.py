#!/usr/bin/env python3
"""
Parse the disassembly of include_all_assets() (0x1408202c0) and recover the
exact asset table by tracking argument registers for each call to add_asset
(0x14081fa10).

Windows x64 method call `add_asset(&mut self, path: &Path, data: &[u8])`:
    rcx = self
    rdx = path.ptr     r8  = path.len
    r9  = data.ptr     [rsp+0x20] = data.len
"""
import re, struct, json, csv, subprocess
from pathlib import Path
from collections import Counter

EXE = Path(r"G:\SteamLibrary\steamapps\common\Tunnet\tunnet.exe")
OUT = Path(r"H:\dev\Rust\tunnet-modding\data")
ASM = Path(r"C:\Users\THUNDE~1\AppData\Local\Temp\opencode\iaa.asm")
d = EXE.read_bytes()

# sections for va<->off
e = struct.unpack_from("<I", d, 0x3C)[0]; c = e + 4
n = struct.unpack_from("<H", d, c + 2)[0]; osz = struct.unpack_from("<H", d, c + 16)[0]
o = c + 20; ib = struct.unpack_from("<Q", d, o + 24)[0]; s = o + osz
secs = {}
for i in range(n):
    nm = d[s+i*40:s+i*40+8].rstrip(b"\0").decode("latin1")
    vs, va, rs, rp = struct.unpack_from("<IIII", d, s+i*40+8)
    secs[nm] = dict(va=ib+va, vsize=vs, rawptr=rp, rawsize=rs)
def va_to_off(va):
    for x in secs.values():
        if x["va"] <= va < x["va"] + x["vsize"]:
            return x["rawptr"] + (va - x["va"])
def read_str(va, ln):
    off = va_to_off(va)
    return d[off:off+ln].decode("latin1") if off is not None else None

ADD = 0x14081fa10
line_re = re.compile(r"^\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} )+\s*(.*)$")
lea_re = re.compile(r"lea\s+0x[0-9a-f]+\(%rip\),%(\w+)\s+#\s*(0x[0-9a-f]+)")
movq_re = re.compile(r"movq?\s+\$(0x[0-9a-f]+),0x20\(%rsp\)")
movimm_re = re.compile(r"mov\s+\$(0x[0-9a-f]+),%(\w+)")
movreg_re = re.compile(r"mov\s+%(\w+),%(\w+)")
call_re = re.compile(r"call\s+(0x[0-9a-f]+)")

reg = {}
stack_dlen = None
mappings = []
for line in ASM.read_text(encoding="utf-8", errors="replace").splitlines():
    m = line_re.match(line)
    if not m:
        continue
    body = m.group(2)
    ml = lea_re.search(body)
    if ml:
        reg[ml.group(1)] = int(ml.group(2), 16)
        continue
    mq = movq_re.search(body)
    if mq:
        stack_dlen = int(mq.group(1), 16)
        continue
    mi = movimm_re.search(body)
    if mi:
        reg[mi.group(2)] = int(mi.group(1), 16)
        continue
    mr = movreg_re.search(body)
    if mr:
        src, dst = mr.group(1), mr.group(2)
        if src in reg:
            reg[dst] = reg[src]
        continue
    mc = call_re.search(body)
    if mc and int(mc.group(1), 16) == ADD:
        path_ptr = reg.get("rdx")
        path_len = reg.get("r8d", reg.get("r8"))
        data_ptr = reg.get("r9")
        mappings.append(dict(path_ptr=path_ptr, path_len=path_len,
                             data_ptr=data_ptr, data_len=stack_dlen))

print(f"add_asset calls parsed: {len(mappings)}")
# validate & build table
table = []
bad = 0
for m in mappings:
    if None in (m["path_ptr"], m["path_len"], m["data_ptr"], m["data_len"]):
        bad += 1; continue
    p = read_str(m["path_ptr"], m["path_len"])
    if not p:
        bad += 1; continue
    table.append(dict(path=p, data_va=m["data_ptr"], data_len=m["data_len"],
                      data_off=va_to_off(m["data_ptr"])))
print(f"valid entries: {len(table)}  bad: {bad}")
print("by ext:", Counter(Path(t['path']).suffix for t in table))
print("top dirs:", Counter(t['path'].split('/')[0] for t in table))

# check data pointer points at a real container for known kinds
kinds = Counter()
for t in table:
    off = t["data_off"]
    if off is None:
        kinds["<no off>"] += 1; continue
    head = d[off:off+4]
    if head[:4] == b"\x89PNG": kinds["png"] += 1
    elif head == b"OggS": kinds["ogg"] += 1
    elif head == b"glTF": kinds["glb"] += 1
    else: kinds["other:" + t["path"].rsplit(".",1)[-1]] += 1
print("data head kinds:", kinds)

# verify carved sizes roughly match data_len for containers
with (OUT / "asset_table.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["path", "data_off", "data_len", "data_va"])
    w.writeheader()
    for t in table:
        w.writerow(dict(path=t["path"], data_off=t["data_off"],
                        data_len=t["data_len"], data_va=t["data_va"]))
(OUT / "asset_table.json").write_text(json.dumps(table, indent=2))
print(f"[+] wrote {OUT/'asset_table.csv'} ({len(table)} assets)")
