#!/usr/bin/env python3
"""Find literal-pool words equal to given addresses (who uses this global/function?).
usage: litref.py BINARY 0xADDR [0xADDR...]
"""
import struct, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from xref import load, off2va

d, segs = load(sys.argv[1])
for a in sys.argv[2:]:
    v = int(a, 16)
    needle = struct.pack("<I", v)
    hits, r = [], 0
    while True:
        r = d.find(needle, r)
        if r < 0:
            break
        if r % 4 == 0:
            hits.append(off2va(segs, r))
        r += 1
    print(f"{v:#x}: " + " ".join(f"{h:#x}" for h in hits))
