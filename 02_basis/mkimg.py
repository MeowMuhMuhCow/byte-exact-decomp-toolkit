#!/usr/bin/env python3
"""mkimg.py OUTPUT_FLAT.BIN - Build a flat memory image from an LE executable with all fixups applied."""
import struct
import sys
from le import CODE, DATA, CB, DB, objs, fixups

END = DB + objs[1]['vsize']
m = bytearray(END - CB)
m[0:len(CODE)] = CODE
m[DB - CB:DB - CB + len(DATA)] = DATA
for s, t, v in fixups:
    o = s - CB
    if t == 7:
        m[o:o + 4] = struct.pack('<I', v)
    elif t == 5:
        m[o:o + 2] = struct.pack('<H', v & 0xFFFF)
    elif t == 6:
        m[o:o + 6] = struct.pack('<IH', v, 0)
open(sys.argv[1], 'wb').write(m)
print(hex(CB), hex(END), len(m))
