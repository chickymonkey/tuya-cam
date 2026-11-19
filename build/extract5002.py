#!/usr/bin/env python3
"""Extract elementary streams from a port-5002 capture: main/sub video + G.711 audio."""
import struct, sys, collections
exec(open("/mnt/d/Tools/Tuya/cam/build/parse5002.py").read().split("print(f\"{len(msgs)}")[0])
outdir = "/mnt/d/Tools/Tuya/cam/analysis/"

outs = {0: open(outdir + "stream0_main.bin", "wb"), 1: open(outdir + "stream1_sub.bin", "wb")}
aud = open(outdir + "audio_g711a_8k.raw", "wb")
first = {0: True, 1: True}
nal_h265 = collections.Counter(); nal_h264 = collections.Counter()
for seq, total, m in msgs:
    typ, stream = struct.unpack_from("<HH", m, 4)
    if typ == 0x1001:
        aud.write(m[24:])
        continue
    if typ != 0x1000 or stream not in outs:
        other = globals().setdefault("other", collections.Counter())
        other[(typ, stream)] += 1
        if other[(typ, stream)] <= 2:
            print(f"other msg typ={typ:#x} stream={stream} len={len(m)}: {m[:40].hex(' ')}")
        continue
    sc = m.find(b"\x00\x00\x00\x01")
    payload = m[sc:]
    # list NAL header bytes in this frame
    i = 0
    while True:
        i = payload.find(b"\x00\x00\x01", i)
        if i < 0 or i + 3 >= len(payload):
            break
        b = payload[i + 3]
        (nal_h265 if stream == 0 else nal_h264)[b] += 1
        i += 3
    outs[stream].write(payload)

print("stream0 NAL first bytes:", {f"{k:#04x}": v for k, v in nal_h265.most_common()})
print("  as H.265 types:", sorted({(k >> 1) & 0x3F for k in nal_h265}))
print("stream1 NAL first bytes:", {f"{k:#04x}": v for k, v in nal_h264.most_common()})
print("  as H.264 types:", sorted({k & 0x1F for k in nal_h264}))
