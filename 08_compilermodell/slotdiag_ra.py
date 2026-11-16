#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""slotdiag_ra.py QUELLE EINHEIT FKT [--procs N] - Stapelplatz-Diagnose wie
Werkzeuge/emu106/slotdiag.py, zusÃ¤tzlich USED_AS_FD (0x200) und die GrÃ¶Ãe je Name.

10.6-Abbild: AssignOtherLocals 0x90C42, Namensliste Names[N_TEMP] = [0xC6870],
Groessen-Sortierung -> Hook 0x90C6D. TempAllocBefore: Flag 0x200 zuerst, dann
GrÃ¶Ãe aufsteigend. 0 Befehle = Quelle stimmt bis auf die Stapelreihenfolge.
--alle schreibt hier nichts. Vorgabe --procs 2.
"""
import sys, os, struct, argparse, multiprocessing as mp

def _emu_dir():
    p = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        cand = os.path.join(p, 'Werkzeuge', 'emu106')
        if os.path.isdir(cand):
            return cand
        p = os.path.dirname(p)
    raise SystemExit('Werkzeuge/emu106 nicht gefunden')

sys.path.insert(0, _emu_dir())
import w106cfg as C
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp
import regdump106 as R
from latepick106 import fname
from fdiff2 import diff
A_SLOT = 0x90C6D
FD = 0x200

def lauf(src, fkt, unit, k=None, info=None):
    st = {'n': -1}
    def hook(e):
        rd = R.RegDump.__new__(R.RegDump)
        rd.e = e
        def h(uc, a, s, _):
            if fname(e) != fkt:
                return
            st['n'] += 1
            if st['n'] != 0:
                return
            p = e.r(X.UC_X86_REG_EAX)
            L = []
            while p:
                cls = e.rd(p + 4, 1)[0]
                size = e.u32(p + 8)
                nid = struct.unpack('<H', e.rd(p + 0x24, 2))[0]
                fl = struct.unpack('<H', e.rd(p + 0x2A, 2))[0]
                sym = e.u32(p + 0x14)
                txt = 't%d' % nid
                if sym:
                    try:
                        txt = e.cstr(e.u32(e.u32(sym + 0xC) + 0xC), 40) or txt
                    except Exception:
                        pass
                L.append(dict(p=p, size=size, id=nid, fl=fl, fd=1 if fl & FD else 0, cls=cls, txt=txt))
                p = e.u32(p)
            if info is not None:
                info.extend(L)
            if k is not None and 0 < k < len(L):
                key = lambda d: (d['fl'] & FD != 0, d['size'])
                first = min(i for i, d in enumerate(L) if key(d) == key(L[k]))
                x = L.pop(k)
                L.insert(first, x)
                for i, d in enumerate(L):
                    uc.mem_write(d['p'], struct.pack('<I', L[i + 1]['p'] if i + 1 < len(L) else 0))
                e.w(X.UC_X86_REG_EAX, L[0]['p'])
        e.uc.hook_add(U.UC_HOOK_CODE, h, begin=BASE + A_SLOT, end=BASE + A_SLOT)
    obj = os.path.join(C.TMP, 'slot_%d.obj' % os.getpid())
    ok, out, e = comp(src, obj, hook=hook)
    if not ok:
        return 9999
    try:
        return diff(unit, fkt, obj, 0)[0]
    except Exception:
        return 9999

def job(a):
    src, fkt, unit, k = a
    return k, lauf(src, fkt, unit, k)

def diag(src, unit, fkt, pool):
    info = []
    n0 = lauf(src, fkt, unit, None, info)
    if n0 in (0, 9999) or not info:
        return n0, info, []
    ks = [k for k in range(1, len(info))
          if (info[k]['fl'] & FD != 0, info[k]['size']) == (info[k - 1]['fl'] & FD != 0, info[k - 1]['size'])]
    R_ = pool.map(job, [(src, fkt, unit, k) for k in ks])
    R_.sort(key=lambda x: x[1])
    return n0, info, R_

def drucke_liste(info):
    print('   nr name             groesse  USED_AS_FD  flags')
    for i, d in enumerate(info):
        print('   %3d %-16s %7d  %10d  0x%04x' % (i, d['txt'][:16], d['size'], d['fd'], d['fl']))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('src', nargs='?')
    ap.add_argument('einheit', nargs='?')
    ap.add_argument('fkt', nargs='?')
    ap.add_argument('--alle', action='store_true')
    ap.add_argument('--procs', type=int, default=2)
    A = ap.parse_args()
    if A.alle:
        sys.exit('slotdiag_ra: --alle gibt es hier nicht (wÃ¼rde auÃerhalb dieses Ordners schreiben)')
    if not A.src or not A.einheit or not A.fkt:
        ap.error('QUELLE EINHEIT FKT')
    pool = mp.get_context('fork').Pool(A.procs, maxtasksperchild=40)
    n0, info, R_ = diag(A.src, A.einheit, A.fkt, pool)
    nfd = sum(d['fd'] for d in info)
    print('%s %s: %d abweichende Befehle; Stapel-Namensliste nach Groessensortierung (%d, davon USED_AS_FD %d):' % (
        A.einheit, A.fkt, n0, len(info), nfd))
    drucke_liste(info)
    for k, n in R_[:8]:
        d = info[k]
        first = min(i for i, x in enumerate(info)
                    if (x['fl'] & FD != 0, x['size']) == (d['fl'] & FD != 0, d['size']))
        print('  %4d Befehle: %s (groesse %d, USED_AS_FD %d) vor %s' % (
            n, d['txt'], d['size'], d['fd'], ', '.join(x['txt'] for x in info[first:k][:6])))
    pool.close()
    pool.join()
