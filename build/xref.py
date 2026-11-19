#!/usr/bin/env python3
"""Tiny ARM32 static-binary helper: find string -> vaddr -> literal-pool refs -> containing code.
usage: xref.py BINARY "string fragment" [more fragments...]
"""
import struct, sys

def load(path):
    d = open(path, "rb").read()
    assert d[:4] == b"\x7fELF"
    phoff, = struct.unpack_from("<I", d, 0x1C)
    phentsize, phnum = struct.unpack_from("<HH", d, 0x2A)
    segs = []
    for i in range(phnum):
        p_type, off, vaddr, paddr, filesz, memsz, flags, align = struct.unpack_from("<8I", d, phoff + i * phentsize)
        if p_type == 1:
            segs.append((off, vaddr, filesz, flags))
    return d, segs

def off2va(segs, o):
    for off, va, sz, _ in segs:
        if off <= o < off + sz:
            return va + (o - off)

def va2off(segs, v):
    for off, va, sz, _ in segs:
        if va <= v < va + sz:
            return off + (v - va)

def main():
    path = sys.argv[1]
    d, segs = load(path)
    for frag in sys.argv[2:]:
        b = frag.encode()
        start = 0
        while True:
            o = d.find(b, start)
            if o < 0:
                break
            start = o + 1
            # back up to string start
            s = o
            while s > 0 and d[s - 1] != 0:
                s -= 1
            va = off2va(segs, s)
            text = d[s:d.index(b"\0", s)].decode("latin1")
            refs = []
            needle = struct.pack("<I", va)
            r = 0
            while True:
                r = d.find(needle, r)
                if r < 0:
                    break
                if r % 4 == 0:
                    refs.append(off2va(segs, r))
                r += 1
            print(f"{va:#x} {text!r}")
            for rv in refs:
                print(f"    literal @ {rv:#x}")
            break

if __name__ == "__main__":
    main()
