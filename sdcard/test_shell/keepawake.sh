#!/bin/sh
# Phase 2 test: keep the Anyka SoC awake for KEEP_MIN minutes and open telnet.
# Uses the same sequence the vendor's OTA script uses (iot heart 0 + stop app_boot).
# After KEEP_MIN it resumes app_boot so the camera goes back to normal sleep.
# Run from /bin/check_test_shell.sh (every file in /tmp/sdcard/test_shell runs at each wake).
# Remove this file from the SD card to disable.

KEEP_MIN=30
LOG=/tmp/sdcard/keepawake.log

(
  exec >>$LOG 2>&1
  echo "==== $(date) keepawake start (KEEP_MIN=$KEEP_MIN)"

  # Network root shell on port 23 (no password - LAN only, for testing)
  # Our own full busybox (stock one lacks dd/sync/mknod and its telnetd has no devpts support)
  # Telnet on port 2323: port 23 appears to be answered by the Wi-Fi MCU, not Linux.
  BB=/tmp/sdcard/bin/busybox
  if [ -f $BB ]; then
    chmod +x $BB
    mkdir -p /tmp/bb && $BB --install -s /tmp/bb
    echo "busybox installed to /tmp/bb -> $?"
    # NOTE: do NOT put /tmp/bb first in PATH: its `date` returns garbage on kernel 4.4
    # (glibc 64-bit time), which skipped the time-sync wait and froze app_boot before
    # Wi-Fi connected (blinking blue LED). Call /tmp/bb/<tool> explicitly instead.
    # telnetd fails with "can't find free pty" on this kernel, so use a raw nc shell.
    # Connect with PuTTY "Raw" to port 2323. -ll keeps listening after disconnect.
    # (-e must be last; the trailing -i is passed to sh for an interactive prompt)
    /tmp/bb/nc -ll -p 2323 -e /tmp/bb/sh -i &
    echo "nc shell on port 2323 started"
  else
    echo "ERROR: $BB missing on SD card - telnet not started"
  fi

  # Let app_boot get the time from Tuya cloud first (clock starts at 1970).
  # Sleep countdown starts ~10 s after cloud online, so poll every 0.5 s.
  t=0
  # Time sync happens after Wi-Fi + Tuya cloud are up, so it also tells us app_boot has
  # finished connecting. Use the stock /bin/date (see note above).
  while [ "$(/bin/date +%Y)" = "1970" ] && [ $t -lt 60 ]; do
    usleep 500000
    t=$((t+1))
  done
  echo "time now: $(/bin/date) (waited $t x 0.5 s)"
  if [ "$(/bin/date +%Y)" = "1970" ]; then
    echo "no time sync after 30 s (Wi-Fi/cloud not up?) - NOT freezing app_boot, camera stays normal"
    exit 0
  fi

  # Same order as vendor check_sd_ota.sh
  iot heart 0
  echo "iot heart 0 -> $?"
  killall app_watchdog
  echo "killed app_watchdog -> $?"
  sleep 1
  ps | grep '/bin/app_boot' | grep -v grep | while read pid rest; do
    kill -STOP $pid && echo "app_boot $pid stopped"
  done

  # Handover watcher: app_media serves ONE client and blocks (holding a lock) while the
  # paused app_boot's socket is full. When a LAN client (the Frigate bridge) is waiting on
  # :5002 and app_boot's loopback connection still exists, un-pause app_boot for 1 s so
  # app_media can finish its send and switch to the bridge. Never kill app_boot (that
  # hangs the camera: blinking blue LED).
  # Streaming mode: if /tmp/sdcard/stream_mode exists, stay awake forever (USB power!).
  # Keep the clock right while app_boot (which syncs from Tuya cloud) is frozen.
  # Done AFTER the freeze on purpose: the Tuya time sync above is our signal that
  # app_boot finished connecting; setting the time earlier would break that gate.
  NTP_SERVER=192.168.3.120
  SNTP=/tmp/sdcard/bin/sntp
  [ -f $SNTP ] && chmod +x $SNTP && $SNTP $NTP_SERVER -s

  NS=/tmp/bb/netstat
  t=0
  while true; do
    sleep 5
    t=$((t+5))
    if [ -x $NS ]; then
      CONN=$($NS -tn 2>/dev/null)
      LAN=$(echo "$CONN" | grep ':5002 ' | grep ESTABLISHED | grep -v '127.0.0.1:[0-9]* *127.0.0.1')
      BOOT=$(echo "$CONN" | grep '127.0.0.1:[0-9]* *127.0.0.1:5002 *ESTABLISHED')
      if [ -n "$LAN" ] && [ -n "$BOOT" ]; then
        echo "$(date) bridge waiting on :5002 -> draining app_boot for 1 s"
        ps | grep '/bin/app_boo[t]' | while read pid rest; do
          kill -CONT $pid; sleep 1; kill -STOP $pid
        done
      fi
    fi
    if [ $((t % 1800)) -eq 0 ] && [ -x $SNTP ]; then
      $SNTP $NTP_SERVER -s
    fi
    if [ $((t % 60)) -eq 0 ]; then
      echo "$(date) awake $((t/60)) min"
      if [ ! -f /tmp/sdcard/stream_mode ] && [ $((t/60)) -ge $KEEP_MIN ]; then
        break
      fi
    fi
  done

  echo "$(date) resuming app_boot"
  ps | grep '/bin/app_boot' | grep -v grep | while read pid rest; do
    kill -CONT $pid && echo "app_boot $pid resumed"
  done
  iot heart 1
  echo "iot heart 1 -> $?"
) &
