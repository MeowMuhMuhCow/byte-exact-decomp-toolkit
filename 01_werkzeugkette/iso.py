#!/usr/bin/env python3
"""iso.py - Pure-Python ISO-9660 reader/extractor for historical compiler CD-ROM images.

Usage:
  python3 iso.py compiler.iso ls [filter]
  python3 iso.py compiler.iso x OUTPUT_DIR [filter ...]
"""
import os
import struct
import sys


def walk(f, lba, size, path, out):
    f.seek(lba * 2048)
    data = f.read(size)
    i = 0
    while i < len(data):
        l = data[i]
        if l == 0:
            i = (i // 2048 + 1) * 2048
            continue
        rec = data[i:i + l]
        elba = struct.unpack('<I', rec[2:6])[0]
        esz = struct.unpack('<I', rec[10:14])[0]
        fl = rec[25]
        nl = rec[32]
        name = rec[33:33 + nl]
        i += l
        if name in (b'\x00', b'\x01'):
            continue
        n = name.decode('latin1').split(';')[0]
        p = path + '/' + n
        if fl & 2:
            walk(f, elba, esz, p, out)
        else:
            out.append((p, elba, esz))


def listing(fn):
    f = open(fn, 'rb')
    f.seek(16 * 2048)
    pvd = f.read(2048)
    root = pvd[156:190]
    lba = struct.unpack('<I', root[2:6])[0]
    sz = struct.unpack('<I', root[10:14])[0]
    out = []
    walk(f, lba, sz, '', out)
    return f, out


if __name__ == '__main__':
    f, out = listing(sys.argv[1])
    print(len(out), 'files')
    if sys.argv[2] == 'ls':
        for p, l, s in out:
            if not len(sys.argv) > 3 or sys.argv[3].lower() in p.lower():
                print(s, p)
    elif sys.argv[2] == 'x':
        dst = sys.argv[3]
        pat = [x.lower() for x in sys.argv[4:]]
        for p, l, s in out:
            if any(x in p.lower() for x in pat):
                t = os.path.join(dst, p.lstrip('/'))
                os.makedirs(os.path.dirname(t), exist_ok=True)
                f.seek(l * 2048)
                open(t, 'wb').write(f.read(s))
                print('x', s, p)
