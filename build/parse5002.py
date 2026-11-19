#!/usr/bin/env python3
"""Reassemble 'hh' chunked messages from a port-5002 capture and summarise them.
usage: parse5002.py capture.bin [outdir]
"""
import struct, sys, os, collections

data = open(sys.argv[1], "rb").read()
outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(sys.argv[1])

# find first header
pos = data.find(b"hh")
msgs, cur, skipped = [], None, 0
while pos + 16 <= len(data):
    if data[pos:pos + 2] != b"hh":
        nxt = data.find(b"hh", pos + 1)
        if nxt < 0:
            break
        skipped += nxt - pos
        pos = nxt
        continue
    seq, total, idx, cnt, ln = struct.unpack_from("<IIHHH", data, pos + 2)
    body = data[pos + 16:pos + 16 + ln]
    if len(body) < ln:
        break
    if idx == 1:
        cur = [seq, total, cnt, bytearray()]
    if cur and cur[0] == seq:
        cur[3] += body
        if idx == cnt:
            msgs.append((seq, total, bytes(cur[3])))
            cur = None
    pos += 16 + ln

print(f"{len(msgs)} messages, {skipped} bytes skipped")
kinds = collections.Counter()
examples = {}
for seq, total, m in msgs:
    key = m[:4].hex()
    kinds[key] += 1
    examples.setdefault(key, []).append(m)
for key, n in kinds.most_common():
    ex = examples[key]
    sizes = [len(m) for m in ex]
    print(f"\nprefix {key}: {n} msgs, size min {min(sizes)} max {max(sizes)}")
    for m in ex[:3]:
        print("   ", m[:48].hex(" "))
        sc = m.find(b"\x00\x00\x00\x01")
        if sc >= 0:
            print(f"    start code at {sc}: next bytes {m[sc+4:sc+8].hex(' ')}")

# dump raw payloads by prefix for inspection
for key, ex in examples.items():
    with open(os.path.join(outdir, f"msg_{key}.bin"), "wb") as f:
        for m in ex:
            f.write(m)
