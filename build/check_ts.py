#!/usr/bin/env python3
"""Offline test: replay cap5002.bin from a fake 'camera' on 127.0.0.1:15002, run tuya_bridge.py
against it, then sanity-check the resulting MPEG-TS (sync, PIDs, continuity, PES/PTS)."""
import socket, struct, subprocess, sys, threading, collections

CAP = "/mnt/d/Tools/Tuya/cam/analysis/cap5002.bin"
OUT = "/mnt/d/Tools/Tuya/cam/analysis/live_test.ts"
BRIDGE = "/mnt/d/Tools/Tuya/cam/bridge/tuya_bridge.py"



ts = open(OUT, "rb").read()
print("TS bytes", len(ts), "packets", len(ts) / 188)
bad_sync = sum(1 for i in range(0, len(ts), 188) if ts[i] != 0x47)
pids = collections.Counter(); cc_err = 0; last_cc = {}; pes = collections.Counter(); pts_list = collections.defaultdict(list)
for i in range(0, len(ts) - 187, 188):
    p = ts[i:i + 188]
    pid = ((p[1] & 0x1F) << 8) | p[2]; pusi = p[1] & 0x40; afc = (p[3] >> 4) & 3; cc = p[3] & 0xF
    pids[pid] += 1
    if pid in last_cc and cc != (last_cc[pid] + 1) & 0xF:
        cc_err += 1
    last_cc[pid] = cc
    off = 4 + (1 + p[4] if afc == 3 else 0)
    if pusi and pid in (0x100, 0x101):
        assert p[off:off + 3] == b"\x00\x00\x01", "bad PES start"
        b = p[off + 9:off + 14]
        pts = ((b[0] >> 1) & 7) << 30 | b[1] << 22 | (b[2] >> 1) << 15 | b[3] << 7 | b[4] >> 1
        pes[pid] += 1; pts_list[pid].append(pts)
print("bad sync", bad_sync, "cc errors", cc_err)
print("packets per PID", {hex(k): v for k, v in pids.items()})
for pid, l in pts_list.items():
    d = [b - a for a, b in zip(l, l[1:])]
    print(f"PID {pid:#x}: {pes[pid]} frames, PTS {l[0]}..{l[-1]} ({(l[-1]-l[0])/90000:.1f}s), "
          f"fps {len(l)/((l[-1]-l[0])/90000):.1f}, non-increasing steps {sum(1 for x in d if x <= 0)}")
