#!/usr/bin/env python3
"""Inspect the 24-byte media header of reassembled port-5002 messages."""
import struct, sys, collections
sys.argv += []
exec(open("/mnt/d/Tools/Tuya/cam/build/parse5002.py").read().split("print(f\"{len(msgs)}")[0])

def nal_types(m):
    out, i = [], 0
    while True:
        i = m.find(b"\x00\x00\x01", i)
        if i < 0 or i + 3 >= len(m):
            return out
        out.append((m[i + 3] >> 1) & 0x3F)
        i += 3

groups = collections.defaultdict(list)
for seq, total, m in msgs:
    f = struct.unpack_from("<IHHIIII", m, 0)
    groups[f[1]].append((f, len(m), m))

for k, lst in groups.items():
    print(f"\n== field[4..5]={k:#06x}: {len(lst)} msgs")
    c = collections.Counter()
    for f, ln, m in lst[:12]:
        print(f"  u32_0={f[0]} u16_6={f[2]} seq={f[3]} ts={f[4]} u32_16={f[5]} u32_20={f[6]:#x} msglen={ln} nal={nal_types(m[24:])[:6]} b24={m[24:30].hex(' ')}")
    for f, ln, m in lst:
        c[(f[0], f[5], f[6] & 0xff)] += 1
    print("  (u32_0, u32_16, low byte u32_20) counts:", c.most_common(8))
    tss = [f[4] for f, _, _ in lst]
    print(f"  ts range {min(tss)}..{max(tss)}  approx fps {len(lst)/max(1,(max(tss)-min(tss))/1000):.1f}")
