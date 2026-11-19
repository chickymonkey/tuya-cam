#!/bin/bash
# usage: dis.sh BINARY START END OUTFILE   (addresses in hex, e.g. 0x11000)
arm-linux-gnueabi-objdump -d --no-show-raw-insn --start-address="$2" --stop-address="$3" "$1" \
  | grep -vE '^\s*$|^Disassembly|file format' > "$4"
wc -l "$4"
