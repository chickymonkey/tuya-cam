#!/usr/bin/env python3
"""
tuya_bridge.py - pull video from a hacked Moes/Tuya Anyka camera (app_media, TCP 5002)
and write it to stdout as MPEG-TS for go2rtc's `exec:` source.

Camera protocol (see README.md):
  chunks:  "hh" | u32 seq | u32 total_len | u16 idx(1-based) | u16 cnt | u16 len | data
  message: off 4 u16 type (0x1000 video, 0x1001 audio), off 6 u16 stream (0 main H.265, 1 sub H.264),
           off 12 u32 timestamp (ms), video Annex-B data from the first 00 00 00 01.

Output: MPEG-TS with main as H.265 (PID 0x100) and/or sub as H.264 (PID 0x101).
go2rtc consumers can pick a track with ?video=h265 / ?video=h264.

Python 3.7+, standard library only.
usage: tuya_bridge.py [HOST] [--port 5002] [--streams main,sub] [--out FILE]
HOST defaults to the TUYA_CAM_HOST environment variable.
"""
import argparse
import os
import socket
import struct
import sys

STREAM_INFO = {
    # name: (camera stream id, PID, TS stream_type, PES stream_id)
    "main": (0, 0x100, 0x24, 0xE0),  # H.265 / HEVC
    "sub": (1, 0x101, 0x1B, 0xE1),   # H.264 / AVC
}
PMT_PID = 0x1000
TS = 188


def log(*a):
    print("[tuya_bridge]", *a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- MPEG-TS muxer
def crc32_mpeg(data):
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


class TsMuxer:
    def __init__(self, out, streams):
        self.out = out
        self.streams = streams              # list of names
        self.cc = {}                        # continuity counters per PID
        self.pcr_pid = STREAM_INFO[streams[0]][1]
        self.pat = self._psi_packet(0, self._pat_section())
        self.pmt = self._psi_packet(PMT_PID, self._pmt_section())

    def _next_cc(self, pid):
        c = self.cc.get(pid, 0)
        self.cc[pid] = (c + 1) & 0x0F
        return c

    def _pat_section(self):
        body = struct.pack(">HBBB", 1, 0xC1, 0, 0) + struct.pack(">HH", 1, 0xE000 | PMT_PID)
        sec = struct.pack(">BH", 0x00, 0xB000 | (len(body) + 4)) + body
        return sec + struct.pack(">I", crc32_mpeg(sec))

    def _pmt_section(self):
        es = b""
        for name in self.streams:
            _, pid, stype, _ = STREAM_INFO[name]
            es += struct.pack(">BHH", stype, 0xE000 | pid, 0xF000)
        body = struct.pack(">HBBB", 1, 0xC1, 0, 0) + struct.pack(">HH", 0xE000 | self.pcr_pid, 0xF000) + es
        sec = struct.pack(">BH", 0x02, 0xB000 | (len(body) + 4)) + body
        return sec + struct.pack(">I", crc32_mpeg(sec))

    def _psi_packet(self, pid, section):
        payload = b"\x00" + section          # pointer_field
        return pid, payload

    def write_psi(self):
        for pid, payload in (self.pat, self.pmt):
            hdr = struct.pack(">BHB", 0x47, 0x4000 | pid, 0x10 | self._next_cc(pid))
            self.out.write(hdr + payload + b"\xFF" * (TS - 4 - len(payload)))

    def write_frame(self, name, pts90k, data, key):
        _, pid, _, sid = STREAM_INFO[name]
        pts = pts90k & 0x1FFFFFFFF
        pes_hdr = struct.pack(
            ">3sBHBBB5s", b"\x00\x00\x01", sid, 0, 0x80, 0x80, 5,
            bytes([0x21 | ((pts >> 29) & 0x0E), (pts >> 22) & 0xFF, 0x01 | ((pts >> 14) & 0xFE),
                   (pts >> 7) & 0xFF, 0x01 | ((pts << 1) & 0xFE)]))
        pes = pes_hdr + data
        first = True
        pos = 0
        chunks = []
        while pos < len(pes):
            af = b""
            if first and (pid == self.pcr_pid or key):
                flags = (0x40 if key else 0) | (0x10 if pid == self.pcr_pid else 0)
                af_body = bytes([flags])
                if pid == self.pcr_pid:
                    pcr = (pts - 9000) & 0x1FFFFFFFF   # PCR 100 ms ahead of PTS
                    af_body += bytes([(pcr >> 25) & 0xFF, (pcr >> 17) & 0xFF, (pcr >> 9) & 0xFF,
                                      (pcr >> 1) & 0xFF, ((pcr & 1) << 7) | 0x7E, 0x00])
                af = bytes([len(af_body)]) + af_body
            room = TS - 4 - len(af)
            part = pes[pos:pos + room]
            if len(part) < room:                 # last packet: stuff with adaptation field
                need = room - len(part)
                if af:
                    af = bytes([af[0] + need]) + af[1:] + b"\xFF" * need
                elif need == 1:
                    af = b"\x00"
                else:
                    af = bytes([need - 1, 0x00]) + b"\xFF" * (need - 2)
            afc = 0x30 if af else 0x10
            hdr = struct.pack(">BHB", 0x47, (0x4000 if first else 0) | pid, afc | self._next_cc(pid))
            chunks.append(hdr + af + part)
            pos += len(part)
            first = False
        self.out.write(b"".join(chunks))


# ---------------------------------------------------------------- camera side
def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("camera closed the connection")
        buf += chunk
    return bytes(buf)


def messages(sock):
    """Yield reassembled app_media messages."""
    cur_seq, parts = None, []
    while True:
        hdr = recv_exact(sock, 16)
        if hdr[:2] != b"hh":
            # resync: slide until we find "hh"
            buf = hdr
            while buf[:2] != b"hh":
                buf = buf[1:] + recv_exact(sock, 1)
            hdr = buf
        seq, total, idx, cnt, ln = struct.unpack_from("<IIHHH", hdr, 2)
        body = recv_exact(sock, ln)
        if idx == 1:
            cur_seq, parts = seq, [body]
        elif seq == cur_seq:
            parts.append(body)
        else:
            cur_seq, parts = None, []
            continue
        if idx == cnt and cur_seq == seq:
            yield b"".join(parts)
            cur_seq, parts = None, []


def is_keyframe(name, data):
    """Look for an IDR / parameter-set NAL in the first few NAL units."""
    i, seen = 0, 0
    while seen < 6:
        i = data.find(b"\x00\x00\x01", i)
        if i < 0 or i + 3 >= len(data):
            return False
        b = data[i + 3]
        if name == "main":
            if ((b >> 1) & 0x3F) in (19, 20, 32, 33, 34):  # IDR_W_RADL, IDR_N_LP, VPS, SPS, PPS
                return True
        elif (b & 0x1F) in (5, 7, 8):                     # IDR, SPS, PPS
            return True
        i += 3
        seen += 1
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", nargs="?", default=os.environ.get("TUYA_CAM_HOST"),
                    help="camera IP (default: $TUYA_CAM_HOST)")
    ap.add_argument("--port", type=int, default=5002)
    ap.add_argument("--streams", default="main,sub", help="comma list of main,sub")
    ap.add_argument("--out", help="write to file instead of stdout (for testing)")
    ap.add_argument("--seconds", type=float, default=0, help="stop after N seconds (testing)")
    args = ap.parse_args()
    if not args.host:
        ap.error("camera host missing: pass HOST or set TUYA_CAM_HOST")

    names = [s.strip() for s in args.streams.split(",") if s.strip()]
    for n in names:
        if n not in STREAM_INFO:
            ap.error("unknown stream %r" % n)
    by_id = {STREAM_INFO[n][0]: n for n in names}

    out = open(args.out, "wb") if args.out else sys.stdout.buffer
    mux = TsMuxer(out, names)

    sock = socket.create_connection((args.host, args.port), timeout=10)
    sock.settimeout(10)                      # no data for 10 s -> exit, go2rtc restarts us
    log("connected to %s:%d, streams=%s" % (args.host, args.port, ",".join(names)))

    started = {n: False for n in names}      # wait for a keyframe per stream
    base_ms = None
    last_ms = None
    wrap = 0
    frames = 0
    try:
        for m in messages(sock):
            if len(m) < 24:
                continue
            typ, sid = struct.unpack_from("<HH", m, 4)
            if typ != 0x1000 or sid not in by_id:
                continue
            name = by_id[sid]
            sc = m.find(b"\x00\x00\x00\x01", 16)
            if sc < 0:
                continue
            data = m[sc:]
            key = is_keyframe(name, data)
            if not started[name]:
                if not key:
                    continue
                started[name] = True
                log("%s: first keyframe" % name)

            ts_ms = struct.unpack_from("<I", m, 12)[0]
            if last_ms is not None and ts_ms + 0x80000000 < last_ms:
                wrap += 1 << 32
            last_ms = ts_ms
            ts_ms += wrap
            if base_ms is None:
                base_ms = ts_ms
            pts = (ts_ms - base_ms) * 90 + 90000   # start at 1 s

            if key:
                mux.write_psi()
            mux.write_frame(name, pts, data, key)
            out.flush()
            frames += 1
            if args.seconds and (ts_ms - base_ms) / 1000.0 >= args.seconds:
                break
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    except (ConnectionError, socket.timeout, OSError) as e:
        log("camera stream ended: %s" % e)
        sys.exit(1)
    finally:
        log("frames written: %d" % frames)
        sock.close()


if __name__ == "__main__":
    main()
