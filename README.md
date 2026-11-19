# Moes/Tuya battery camera (model SC03W7T) – hacking notes

Local (cloud-free) streaming of the Moes/Tuya SC03W7T battery camera into Frigate / Home Assistant,
without flashing anything. The camera runs a script from the SD card at every wake. The script keeps it
awake and lets a small Python bridge pull the raw H.265/H.264 frames from `app_media` (TCP 5002) and turn
them into MPEG-TS for go2rtc.

```
camera app_media :5002 ──TCP──> tuya_bridge.py (in Frigate's go2rtc, exec:) ──MPEG-TS──> go2rtc RTSP :8554 ──> Frigate
```

## Repository layout
| path | what |
|---|---|
| `sdcard/bin/busybox` | static busybox 1.36.1 (provides `nc`, `netstat`, `sh`) – built by `build/build_busybox.sh` |
| `sdcard/bin/sntp` | small NTP client (source `src/sntp/sntp.c`) – keeps the clock right while `app_boot` is frozen |
| `sdcard/bin/hello` | toolchain smoke test only (source `src/hello/hello.c`), not needed |
| `sdcard/test_shell/keepawake.sh` | the hook script: keeps the camera awake, opens a root shell on :2323, hands :5002 over to the bridge |
| `sdcard/backup_recon.sh.disabled` | phase-1 flash backup/recon script (optional, see step 1) |
| `bridge/tuya_bridge.py` | camera → MPEG-TS bridge (Python 3.7+, standard library only) |
| `bridge/frigate_snippet.yml` | go2rtc + camera config to merge into Frigate |
| `build/` | research and test tools (protocol capture/parse, bridge tests, remote-shell helper) |

## Setup: local streaming step by step

### What you need
- The camera with a microSD card (FAT32) and **permanent USB power**. Streaming keeps the SoC awake, which would drain the battery in hours.
- The camera already paired with the Tuya/Moes app and on your Wi-Fi. The script waits for the Tuya cloud time sync before it does anything.
- A DHCP reservation for the camera, so its IP never changes. No IP is hard-coded in the repo: the tools read the camera IP from the `TUYA_CAM_HOST` environment variable, and Frigate reads it from `FRIGATE_TUYA_CAM_HOST`.
- An NTP server on your LAN (e.g. the router or Home Assistant; example: `192.168.3.120`).
- Frigate 0.14+ (Home Assistant add-on or Docker) with `python3` available in the container. The official image has it.

### 1. (Recommended) back up the flash first
Do this once, before anything else: the FACTORY and PARAM partitions are unique to each camera.
1. Copy `sdcard/backup_recon.sh.disabled` to the SD card as `test_shell/backup_recon.sh`.
2. Insert the card and wake the camera (button or motion). Wait about 1 minute.
3. Take the card out and copy `dump/` to your PC (check `full_8MB.bin` is 8388608 bytes and save SHA-256 checksums).
4. Delete `test_shell/backup_recon.sh` from the card.

### 2. Adjust the settings for your network
- `sdcard/test_shell/keepawake.sh`: set `NTP_SERVER=` to your NTP server. `KEEP_MIN` only matters when `stream_mode` is absent.
- Camera IP for the PC tools (`tuya_bridge.py`, `build/camsh.py`, `build/cap5002.py`). Set it once per shell:
  - PowerShell: `$env:TUYA_CAM_HOST = "192.168.1.50"`
  - bash/WSL: `export TUYA_CAM_HOST=192.168.1.50`
  
  `tuya_bridge.py` and `cap5002.py` also accept the IP as their first argument.
- Camera IP for Frigate: set `FRIGATE_TUYA_CAM_HOST` (see step 6).

Edit with an editor that keeps **LF** line endings (VS Code: "LF" in the status bar). A CRLF script will not run on the camera.
`.gitattributes` makes git check scripts out with LF.

### 3. Prepare the SD card
Copy these to the **root** of the SD card:
```
bin/busybox                 (from sdcard/bin)
bin/sntp                    (from sdcard/bin)
test_shell/keepawake.sh     (from sdcard/test_shell)
stream_mode                 (new EMPTY file, no extension - keeps the camera awake forever)
```
> ⚠️ **Never create an `upgrade/` folder** on the card. The firmware flashes any file in it whose name starts with `BC7`.
> Without `stream_mode` the camera stays awake for `KEEP_MIN` (30) minutes and then goes back to normal battery sleep.

### 4. Boot the camera
1. Plug in USB power, insert the SD card and power-cycle or wake the camera.
2. Within about 20 s, `keepawake.sh` waits for Wi-Fi plus the Tuya time sync. It then stops the sleep heartbeat (`iot heart 0`), kills `app_watchdog`, freezes `app_boot` (SIGSTOP, **never kill it**), sets the clock from NTP and starts a root shell on port 2323.
3. Check it worked:
   - `python build/camsh.py "ps; tail /tmp/sdcard/keepawake.log"`, or PuTTY → connection type **Raw**, port **2323**.
   - The log should show `app_boot NNN stopped` and then `awake N min` every minute.
   - If it says `no time sync after 30 s`, Wi-Fi or the cloud was not up. The camera is left untouched; wake it again.

The Tuya app shows the camera offline while it streams locally. That is expected, because `app_boot` is frozen.

### 5. Test the bridge from your PC (optional)
```
python bridge/tuya_bridge.py --out test.ts --seconds 10      # uses $TUYA_CAM_HOST
```
Open `test.ts` in VLC. It should hold the 2560x1440 H.265 and 640x360 H.264 tracks. Only **one** client can be connected to :5002 at a time, so stop this before starting Frigate.
On first connect the script un-freezes `app_boot` for 1 s so `app_media` switches to the new client. Allow up to about 5 s.

### 6. Add the camera to Frigate
1. Copy `bridge/tuya_bridge.py` into Frigate's config folder, which is `/config` inside the container:
   - HA add-on 0.14+: `/addon_configs/ccab4aaf_frigate/` (or `ccab4aaf_frigate-fa` for the full-access variant).
   - Docker: the folder mounted as `/config`.
2. Merge `bridge/frigate_snippet.yml` into your Frigate config. Don't replace the file.
   Set the camera IP once as `FRIGATE_TUYA_CAM_HOST`:
   - HA add-on: in the snippet's `environment_vars:` section.
   - Docker: as a container environment variable (`-e FRIGATE_TUYA_CAM_HOST=...` or `environment:` in compose).
   
   Frigate fills it into the go2rtc stream as `{FRIGATE_TUYA_CAM_HOST}`. Restart Frigate.
3. go2rtc runs the bridge and restarts it if the stream drops (10 s timeout). Detection uses the H.264 sub stream and recording uses the H.265 main stream.
   Frigate's web UI may not play the H.265 recordings in every browser.

### Stopping / going back to stock
- Delete `stream_mode` → the camera sleeps normally 30 min after its next wake.
- Delete `test_shell/keepawake.sh` → fully stock behaviour on the next wake. Nothing on the flash was changed.
- If the camera hangs with a blinking blue LED, disconnect the battery and USB to reset it.

### Rebuilding the binaries (optional – prebuilt ones are in `sdcard/bin`)
In WSL Ubuntu 24.04 (`sudo apt install gcc-arm-linux-gnueabi make wget`):
```
bash build/build_busybox.sh          # edit OUT= to point at this repo's sdcard/bin first
arm-linux-gnueabi-gcc -march=armv5te -mfloat-abi=soft -static -O2 -s -o sdcard/bin/sntp src/sntp/sntp.c
```
The tools in `build/` still have hard-coded paths under `/mnt/d/Tools/Tuya/cam/`. Edit them before use.

---

# Research notes

## Hardware
- Main SoC: Anyka AK3918AV100, 64 MB RAM, 8 MB SPI NOR. Not supported by OpenIPC (as of Nov 2026).
- Wi-Fi/power MCU: AICSemi (RTOS, own UART @ 921600, `aic>` prompt). Controls power to the Anyka SoC (PIR / button / Wi-Fi wake). **Do not flash.**
- Anyka UART: 115200 8N1, root shell with no password (`[root@anyka ~]$`).
- Sensor: 2560x1440 main stream + 640x360 sub stream, 15 fps.

## Flash layout (8 MB, contiguous)
| mtd | name | offset | size |
|---|---|---|---|
| 0 | SPL | 0x000000 | 64K |
| 1 | ENV | 0x010000 | 4K |
| 2 | ENVBK | 0x011000 | 4K |
| 3 | DTB | 0x012000 | 64K |
| 4 | KERNEL (+initrd rootfs) | 0x022000 | 3432K |
| 5 | ROOTFS | 0x37C000 | 16K |
| 6 | FACTORY (unique!) | 0x380000 | 16K |
| 7 | PARAM (unique!) | 0x384000 | 128K |
| 8 | CONFIG (jffs2, /tmp/usr_config) | 0x3A4000 | 368K |
| 9 | APP2 | 0x400000 | 4M |

Backup: `dump_original/` (checksums in SHA256SUMS.txt), taken 2026-11-16 with `cat /dev/mtdblockN`.

## Boot / hooks
- `/etc/init.d/rcS` -> `rc.local` -> `/bin/main.sh` starts `app_media`, `app_boot`, `app_watchdog` (same binary as app_boot; `iot`, `ota`, `fota`, `factory` are symlinks to it).
- `/bin/check_test_shell.sh`: 5 s after boot, runs **every file** in `/tmp/sdcard/test_shell/` (SD card `\test_shell\`). <- our hook.
- `/bin/check_sd_ota.sh`: 8 s after boot, flashes any file in `/tmp/sdcard/upgrade/` whose name starts with `BC7`. **Never create `upgrade/`.**
- Sleep: `app_boot` counts `active time` down ~10 s after idle, then tells the MCU to cut power. `iot heart 0` disables the MCU heartbeat (vendor OTA script uses it).
- Root fs is ramfs: changes to / are lost each wake. Persistent: SD card, `/tmp/usr_config` (mtd8).

## Busybox 1.30.1 applets
arp ash cat chmod cp date devmem df dmesg echo free grep hostid hostname httpd id ifconfig init insmod kill killall killall5 klogd ln ls lsmod md5sum mdev microcom mkdir mkfs.vfat mount mv nohup ping printf ps pwd reboot rm rmmod route sh sleep syslogd telnetd tftp top udhcpc umount uptime usleep vi wget
(no dd, sync, awk, uname, netstat)

## Security
- Console prints Wi-Fi SSID/password and Tuya keys in plain text. Keep logs private.

## Results log
- 2026-11-16: `keepawake.sh` works on USB power: app_boot frozen, no sleep countdown, app_media keeps encoding, telnet port 23 reachable at the camera's LAN IP (ICMP ping does not answer). Tuya cloud is offline while app_boot is frozen.
- Confirmed awake 7+ min (MCU has no independent power-off timeout). Issues: telnetd not in `ps` after start (to check); clock stays 1970 if app_boot is frozen before Tuya time sync -> script now waits for time sync first.
- Inbound TCP to Linux works: busybox `httpd -p 8080` reachable from LAN -> RTSP server on the camera is viable.
- telnetd failed with "can't find free pty" (devpts ptmxmode=000, /dev/ptmx missing) -> script chmods /dev/pts/ptmx and symlinks /dev/ptmx.

- Kernel 4.4.282 (Buildroot 2018.02, gcc 5.5). Cross toolchain: WSL Ubuntu 24.04 `arm-linux-gnueabi-gcc -march=armv5te -mfloat-abi=soft -static` works (`src/hello` ran OK).
- Stock busybox telnetd: "can't find free pty" (no FEATURE_DEVPTS). Built own static busybox 1.36.1 (`build/build_busybox.sh` -> `sdcard/bin/busybox`); needs real `/dev/ptmx` (mknod c 5 2).
- Port 23 seems answered/blocked by the Wi-Fi MCU; port 2323 reaches Linux -> telnet runs on 2323.
- Correction: ports are not filtered (httpd works on 2323 and 8080). Own telnetd still fails "can't find free pty" even with /dev/ptmx c 5 2 -> parked. Working remote shell: `/tmp/bb/nc -ll -p 2323 -e /tmp/bb/sh -i`, PuTTY connection type **Raw**, port 2323.
- Note: TCP connects to closed ports still "succeed" from the PC (MCU completes handshake) - only real data proves a port.
- Listening by default: 5002 (app_media frame server), 6668 (Tuya LAN), 8765 (unknown).
- With app_boot frozen, its 127.0.0.1 -> 5002 socket fills up (Recv-Q ~100 KB). Watch whether app_media stalls when one client stops reading.

## app_media port 5002 protocol (reverse engineered 2026-11-16)
- TCP server on 0.0.0.0:5002 (reachable from LAN). **One client at a time**: a new connection replaces (closes) the old one.
- Sending is blocking and holds a mutex (0x259d10) that the accept thread also needs. If the current client stops reading (e.g. app_boot SIGSTOPped), app_media blocks and a new client is not swapped in until the old socket drains (`kill -CONT app_boot; sleep 1; kill -STOP app_boot`).
- Framing (both directions, also used on the UDP command channel): 16-byte chunk header, little endian:
  `"hh"(0x6868) | u32 msg_seq | u32 msg_total_len | u16 chunk_idx (1-based) | u16 chunk_cnt | u16 chunk_len (<=16384)` + chunk data.
- Reassembled message = one media frame:
  - off 4: u16 type (0x1000 video, 0x1001 audio); off 6: u16 stream (0 main, 1 sub, 22 = small non-media/AI msg)
  - off 8: u32 per-stream seq; off 12: timestamp ms (u64?)
  - audio: 256 bytes G.711 A-law 8 kHz mono at off 24 (31.25 fps)
  - video: Annex-B data from first `00 00 00 01` (around off 25); main = **H.265** 2560x1440 15 fps, sub = **H.264** 640x360 15 fps; IDR every ~2 s (VPS/SPS/PPS repeated before each IDR)
- No request needed: app_media streams to whichever client is connected (app_boot sent VIDEO_START at boot).
- Own busybox `date` returns garbage (year 134291730, frozen) on kernel 4.4 - Ubuntu 24.04 armel glibc uses 64-bit time. Use stock `/bin/date`; never put /tmp/bb first in PATH in scripts. Freezing app_boot before Wi-Fi/cloud is up -> blinking blue LED.
- Clock: app_boot sets time from Tuya cloud ~10 s after boot (OSD shows 1970 if app_boot is frozen earlier). `src/sntp` -> `sdcard/bin/sntp` sets time from NTP 192.168.3.120 via raw 32-bit syscalls; keepawake runs it after the freeze and every 30 min.
- **Do not kill app_boot** (`kill -9`): camera hangs with blinking blue LED (needs battery disconnect). Keep it SIGSTOPped; keepawake.sh drains it for 1 s only when a LAN client waits on :5002.
- Streaming mode: create empty file `stream_mode` in SD root -> keepawake never ends (USB power required).
- Bridge for Frigate (HA add-on): `bridge/tuya_bridge.py` -> MPEG-TS (main H.265 PID 0x100, sub H.264 PID 0x101). Offline replay test OK (`build/test_bridge.py`).
- 2026-11-16 live test OK: watcher drained app_boot ("bridge waiting on :5002"), bridge got 1048 frames/30 s, app_media survived bridge disconnect, immediate reconnect works without drain. Valid TS (`build/check_ts.py`). Frigate config: `bridge/frigate_snippet.yml`.
- Remote helper: `build/camsh.py "cmd"` runs a command over the nc shell (2323).
- Tools: `build/cap5002.py` (capture), `build/parse5002.py`, `build/fields5002.py`, `build/extract5002.py`; sample in `analysis/`.

## SD card scripts
- `sdcard/test_shell/keepawake.sh` – phase 2 test: telnetd + keep awake 30 min.
- `sdcard/backup_recon.sh.disabled` – the phase 1 backup/recon script (done).
