#!/usr/bin/env python3
"""Run a command on the camera through the nc shell on port 2323 and print the output.
usage: camsh.py "command; command" [wait_seconds]
Camera address comes from the TUYA_CAM_HOST environment variable."""
import os, socket, sys, time

host = os.environ.get("TUYA_CAM_HOST")
if not host:
    sys.exit("set TUYA_CAM_HOST to the camera's IP address first")

cmd = sys.argv[1]
wait = float(sys.argv[2]) if len(sys.argv) > 2 else 4
s = socket.create_connection((host, 2323), timeout=5)
s.settimeout(0.5)
s.sendall((cmd + "\necho __END__\n").encode())
buf, t0 = b"", time.time()
while time.time() - t0 < wait and b"__END__\n" not in buf.replace(b"\r", b""):
    try:
        c = s.recv(65536)
        if not c:
            break
        buf += c
    except socket.timeout:
        pass
s.close()
print(buf.decode("latin1").replace("__END__", "").rstrip())
