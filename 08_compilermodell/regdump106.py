#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""regdump106.py DATEI.CPP [OPTIONEN] - Registerverteiler des echten Watcom 10.6 mitlesen (worker, 29.10.2026).
Hooks im CF-Abbild von BINW/WPP386.EXE (Bildoffsets, gefunden ueber Ghidra/capstone gegen OW-Quelle 2002):
  0x94020 AssignConflicts   0x94094 nach SortConflicts (eax = sortierte Liste)   0x94148 ConfBefore (savings +0x14, unsigned >)
  0x93F40 GiveRegister      0x93F7D nach GiveBestReg (eax = vergebener Registersatz, 0 = keiner, esi = Konflikt)
  0x93EF8 InMemory (eax = Konflikt)
Konfliktknoten: +0 next, +8 name, +0C start_block, +10 tree, +14 savings, +54 state.
Name: +4 Klasse (1 Speicher, 2 temp), +8 Groesse, +14 Front-End-Symbol, +24 id."""
import os, sys, shutil, tempfile, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unicorn as U
from unicorn import x86_const as X
from emu106 import Emu106, BASE

A_SORTED, A_GIVEN, A_INMEM, A_ASSIGN = 0x94094, 0x93F7D, 0x93EF8, 0x94020
# Registersaetze (empirisch an t1.cpp bestimmt, Bytes aus ByteRegs-Tabelle 0xC1100): AL=2 AH=1 BL=8 BH=4 CL=20 CH=10 DL=80 DH=40, SI=100 DI=200 BP=400,
# 32-Bit-Kennbits 0x01000000 EAX, 0x02000000 EBX, 0x04000000 ECX, 0x08000000 EDX, 0x10000000 ESI, 0x20000000 EDI
E32 = {0x01000000: 'EAX', 0x02000000: 'EBX', 0x04000000: 'ECX', 0x08000000: 'EDX', 0x10000000: 'ESI', 0x20000000: 'EDI'}
B8 = {2: 'AL', 1: 'AH', 8: 'BL', 4: 'BH', 0x20: 'CL', 0x10: 'CH', 0x80: 'DL', 0x40: 'DH', 0x100: 'SI', 0x200: 'DI', 0x400: 'BP', 0x800: 'SP'}
X16 = {3: 'AX', 0xc: 'BX', 0x30: 'CX', 0xc0: 'DX'}


def regname(v):
    if v is None: return '-'
    if isinstance(v, str): return v
    if v == 0: return 'keins'
    out = [n for b, n in E32.items() if v & b]
    if out: return '+'.join(out)
    if v == 0x400: return 'EBP'
    for m, n in X16.items():
        if v == m: return n
    return '+'.join(n for b, n in B8.items() if v & b) or '%08x' % v


class RegDump:
    def __init__(self, emu):
        self.e = emu; self.passes = []; self.fnames = []; self.cur = None
        uc = emu.uc
        uc.hook_add(U.UC_HOOK_CODE, self._sorted, begin=BASE + A_SORTED, end=BASE + A_SORTED)
        uc.hook_add(U.UC_HOOK_CODE, self._given, begin=BASE + A_GIVEN, end=BASE + A_GIVEN)
        uc.hook_add(U.UC_HOOK_CODE, self._inmem, begin=BASE + A_INMEM, end=BASE + A_INMEM)

    def name_info(self, conf):
        e = self.e; nm = e.u32(conf + 8)
        cls = e.rd(nm + 4, 1)[0]; size = e.u32(nm + 8); sym = e.u32(nm + 0x14); nid = struct.unpack('<H', e.rd(nm + 0x24, 2))[0]
        txt = ''
        if sym:
            try:
                sn = e.u32(sym + 0xc); p = e.u32(sn + 0xc) if sn else 0
                txt = e.cstr(p, 64) if p else ''
            except Exception: txt = '?'
        return dict(conf=conf, name=nm, cls=cls, size=size, sym=sym, id=nid, txt=txt or ('t%d' % nid))

    def _sorted(self, uc, addr, size, _):
        e = self.e; p = e.r(X.UC_X86_REG_EAX); lst = []
        while p:
            d = self.name_info(p); d['savings'] = e.u32(p + 0x14); d['reg'] = None; lst.append(d); p = e.u32(p)
        fn = '?'
        try:
            cp = e.u32(BASE + 0xC6894); fs = e.u32(e.u32(cp + 0x84) + 8)
            fn = e.cstr(e.u32(e.u32(fs + 0xc) + 0xc), 80)
        except Exception: pass
        self.cur = {c['conf']: c for c in lst}; self.passes.append(lst); self.fnames.append(fn)

    def _given(self, uc, addr, size, _):
        if self.cur is None: return
        c = self.cur.get(self.e.r(X.UC_X86_REG_ESI))
        if c is not None: c['reg'] = self.e.r(X.UC_X86_REG_EAX)

    def _inmem(self, uc, addr, size, _):
        if self.cur is None: return
        c = self.cur.get(self.e.r(X.UC_X86_REG_EAX))
        if c is not None and c['reg'] is None: c['reg'] = 'mem'


def run(src, opts, keep=None):
    import w106cfg as C
    d = tempfile.mkdtemp(dir=C.TMP)
    os.symlink(C.H, d + '/H'); os.symlink(C.INC, d + '/INC')
    shutil.copy(src, d + '/S.CPP')
    e = Emu106(d, ['S.CPP'] + opts + ['-zq']); rd = RegDump(e)
    code, dt = e.run()
    if keep: shutil.copy(d + '/S.OBJ', keep)
    shutil.rmtree(d, ignore_errors=True)
    return rd, code, e


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('--fkt', default=None); ap.add_argument('opts', nargs='*')
    a = ap.parse_args()
    rd, code, e = run(a.src, a.opts or ['-4r', '-oneatx', '-zp1', '-s'])
    for i, p in enumerate(rd.passes):
        if a.fkt and a.fkt not in rd.fnames[i]: continue
        print('%s â Durchgang %d: %d Konflikte' % (rd.fnames[i], i, len(p)))
        for c in p:
            print('  %-16s %s gr %2d  savings %6d -> %s' % (c['txt'][:16], 'glob' if c['cls'] == 1 else '    ', c['size'], c['savings'], regname(c['reg'])))
