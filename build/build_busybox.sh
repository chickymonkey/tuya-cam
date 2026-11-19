#!/bin/bash
# Build a static busybox for the Anyka AK3918AV100 (ARM926EJ-S, ARMv5TE, soft-float).
# Run inside WSL Ubuntu: bash /mnt/d/Tools/Tuya/cam/build/build_busybox.sh
set -e
VER=1.36.1
WORK=~/cam-build
OUT=/mnt/d/Tools/Tuya/cam/sdcard/bin

mkdir -p "$WORK" "$OUT"
cd "$WORK"
[ -f busybox-$VER.tar.bz2 ] || wget -q https://busybox.net/downloads/busybox-$VER.tar.bz2
rm -rf busybox-$VER
# (bzip2 may not be installed; python's tarfile handles .bz2)
python3 -c "import tarfile,sys; tarfile.open(sys.argv[1]).extractall('.')" busybox-$VER.tar.bz2
cd busybox-$VER

make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- defconfig >/dev/null
# static, ARMv5TE soft-float; drop tc (does not build with new kernel headers)
sed -i \
  -e 's/^CONFIG_TC=y/# CONFIG_TC is not set/' \
  -e 's/^# CONFIG_STATIC is not set/CONFIG_STATIC=y/' \
  -e 's/^CONFIG_EXTRA_CFLAGS=.*/CONFIG_EXTRA_CFLAGS="-march=armv5te -mfloat-abi=soft"/' \
  .config
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- oldconfig </dev/null >/dev/null
grep -E '^CONFIG_(STATIC|FEATURE_DEVPTS|TELNETD|EXTRA_CFLAGS)=' .config

make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- -j"$(nproc)" >build.log 2>&1 || { tail -30 build.log; exit 1; }
arm-linux-gnueabi-strip busybox
file busybox
arm-linux-gnueabi-readelf -A busybox | grep CPU_arch
cp busybox "$OUT/busybox"
ls -l "$OUT/busybox"
