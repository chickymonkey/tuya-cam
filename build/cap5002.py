#!/usr/bin/env python3
"""Connect to app_media's port 5002 and save whatever it sends (read-only probe).
Retries the connection until the camera is awake; keeps the socket open for the whole window.
usage: cap5002.py [host] [port] [seconds] [outfile]   (host defaults to $TUYA_CAM_HOST)
"""
import os, socket, sys, time

host = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TUYA_CAM_HOST")
if not host:
    sys.exit("usage: cap5002.py HOST ... (or set TUYA_CAM_HOST)")
port = int(sys.argv[2]) if len(sys.argv) > 2 else 5002
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 300
out = sys.argv[4] if len(sys.argv) > 4 else "/mnt/d/Tools/Tuya/cam/analysis/cap5002.bin"

data = bytearray()
t0 = time.time()
s = None
while time.time() - t0 < secs:
    if s is None:
        try:
            s = socket.create_connection((host, port), timeout=3)
            s.settimeout(1)
            print(f"[{time.time()-t0:5.1f}s] connected", flush=True)
        except OSError as e:
            time.sleep(2)
            continue
    try:
        chunk = s.recv(65536)
        if not chunk:
            print(f"[{time.time()-t0:5.1f}s] server closed, reconnecting", flush=True)
            s.close(); s = None
            continue
        if not data:
            print(f"[{time.time()-t0:5.1f}s] first data", flush=True)
        data += chunk
        if len(data) > 8 * 1024 * 1024:
            print("8 MB captured, stopping", flush=True)
            break
    except socket.timeout:
        pass
    except OSError as e:
        print(f"[{time.time()-t0:5.1f}s] socket error {e}, reconnecting", flush=True)
        s.close(); s = None
if s:
    s.close()
open(out, "wb").write(data)
print(f"received {len(data)} bytes in {time.time()-t0:.1f}s -> {out}")
print(data[:256].hex(" "))
