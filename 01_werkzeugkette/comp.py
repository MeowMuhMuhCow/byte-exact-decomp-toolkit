#!/usr/bin/env python3
"""comp.py SOURCE.CPP OUTPUT.OBJ - Compile a single unit in-process via emu106 (respecting // OPT and // CC lines)."""
import gc
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import w106cfg as C
from emu106 import Emu106

DEF = ['-4r', '-oneatx', '-zp1', '-s']
WCC_STUB, WCC_EXIT = 0x33BC4, 0x33BC2   # Watcom 10.6 WCC386.EXE in the same Unicorn harness


def kopf(src):
    """Return (compiler, options) parsed from // OPT and // CC header lines."""
    opt = None
    cc = 'wpp386'
    for l in open(src, errors='replace'):
        s = l.strip()
        m = re.match(r'^// OPT (-.*)$', s)
        if m and opt is None:
            opt = re.split(r'\s+\(', m.group(1), maxsplit=1)[0].split()
        if re.match(r'^// CC wcc386\b', s):
            cc = 'wcc386'
    return cc, (opt or DEF)


def opts(src):
    return kopf(src)[1]


def comp(src, obj, extra=None, hook=None):
    gc.collect()   # Free Unicorn instances in reference cycles
    cc, opt = kopf(src)
    if cc == 'wcc386':
        exe = C.C_EXE
        name = 'S.C'
        kw = dict(exe=exe, stub=WCC_STUB, exit=WCC_EXIT)
    else:
        name = 'S.CPP'
        kw = {}
    d = tempfile.mkdtemp(dir=C.TMP)
    if os.path.exists(C.H):
        os.symlink(C.H, d + '/H')
    if os.path.exists(C.INC):
        os.symlink(C.INC, d + '/INC')
    shutil.copy(src, d + '/' + name)
    e = Emu106(d, [name] + (extra or opt) + ['-zq'], **kw)
    if hook:
        hook(e)   # Note: allocator hook addresses apply to WPP386.EXE
    code, dt = e.run()
    ok = os.path.exists(d + '/S.OBJ')
    if ok:
        shutil.copy(d + '/S.OBJ', obj)
    out = e.out.decode('latin-1')
    shutil.rmtree(d, ignore_errors=True)
    return ok, out, e


if __name__ == '__main__':
    ok, out, e = comp(sys.argv[1], sys.argv[2])
    print(ok, out[-300:])
