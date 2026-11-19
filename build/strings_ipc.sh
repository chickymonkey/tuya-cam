#!/bin/bash
# Dump IPC-related strings (with file offsets) from the vendor binaries.
cd /mnt/d/Tools/Tuya/cam/dump_original/sys
mkdir -p /mnt/d/Tools/Tuya/cam/analysis
for b in app_media app_boot; do
  strings -t x -n 5 "$b" > /mnt/d/Tools/Tuya/cam/analysis/$b.strings.txt
  echo "== $b ($(wc -l < /mnt/d/Tools/Tuya/cam/analysis/$b.strings.txt) strings)"
  grep -iE 'ipc|subtype|tcp_server|tcp_client|ringbuf|5002|8765|MIPC|TCPS|TCPC|frame|venc|stream' \
    /mnt/d/Tools/Tuya/cam/analysis/$b.strings.txt | head -120
done
