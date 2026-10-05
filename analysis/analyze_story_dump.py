#!/usr/bin/env python3
"""Analyze live Story/Credits resource dumps vs the loaded save."""
import struct, sys
from pathlib import Path

tmp = Path(r"C:\Users\THUNDE~1\AppData\Local\Temp\opencode")
c = (tmp / "credits.bin").read_bytes()
s = (tmp / "story.bin").read_bytes()

print("=== Credits (u32 words) ===")
for o in range(0, len(c), 4):
    v = struct.unpack_from("<I", c, o)[0]
    print(f"  +0x{o:02x}: {v:>12}  ({v:#x})")

print("\n=== Credits (u64 words) ===")
for o in range(0, len(c), 8):
    v = struct.unpack_from("<Q", c, o)[0]
    print(f"  +0x{o:02x}: {v:#018x}")

print("\n=== Story (u64 words) ===")
for o in range(0, len(s), 8):
    v = struct.unpack_from("<Q", s, o)[0]
    print(f"  +0x{o:03x}: {v:#018x}")

# Search for known save values in Story.
print("\n=== search Story for save values ===")
import re
def find_u32(val):
    pat = struct.pack("<I", val)
    return [i for i in range(len(s)-3) if s[i:i+4] == pat]
def find_f32(val):
    pat = struct.pack("<f", val)
    return [i for i in range(len(s)-3) if s[i:i+4] == pat]
for name, val in [("shop_level", 4), ("page_no", 5), ("pages", 12),
                  ("disinfected", 0), ("state? ConnectToShelters", 0)]:
    print(f"  u32 {name}={val}: {[hex(x) for x in find_u32(val)][:12]}")
for f in (90.565056, 6.3651347, 97.53335):
    print(f"  f32 {f}: {[hex(x) for x in find_f32(f)][:8]}")

# Flag run: digging=1,relay=1,hub=1,filter=0,scan_short=1,scan_long=0,
# jetpack=0,antivirus=0,sprint=0,optical_fiber=0,antenna=0,surface=0,companion=0
flag = bytes([1,1,1,0,1,0,0,0,0,0,0,0,0])
print("\n=== flag run 01 01 01 00 01 00*8 ===")
for i in range(len(s)-len(flag)):
    if s[i:i+len(flag)] == flag:
        print(f"  at +0x{i:x}")
