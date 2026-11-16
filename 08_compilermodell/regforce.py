#!/usr/bin/env python3
"""regforce.py SOURCE.CPP UNIT FUNC [--zwing K REG] [--alle] [--weit] [--procs N]

Force a specific register choice inside Watcom 10.6's GiveBestReg allocator in the
Unicorn emulator (supports both WPP386.EXE and WCC386.EXE via adr106.py) and measure
the resulting .OBJ with the exact judge (03_richter/fstand.py).

How it works:
  GiveBestReg (0x93BC8 in WPP386 / 0x61488 in WCC386) evaluates each candidate register
  for a conflict node using CountRegMoves (0x93744 / 0x61004). The highest move-savings
  score wins; ties prefer a register already in RegsInUse (0xC6840 / 0x858E0), or the
  first entry in the register table.
  By hooking CountRegMovesNach (0x93CE5 / 0x615A5), we overwrite EAX with 0x7FFFFFF for
  the desired target register at the K-th GiveBestReg call of the function (e.g., forcing
  a table index from EDX into ECX) and immediately measure whether the instruction diff
  drops to 0 (GLEICH).

Modes:
  1. Trace only (no flags): lists all GiveBestReg calls, candidate scores, chosen register, and ties.
  2. Single forced register (`--zwing K REG`, e.g. `--zwing 3 ECX`): forces call #K to pick REG
     and prints the new judge distance (`Rest`).
  3. Sweep all alternatives (`--alle` for tie candidates, `--alle --weit` for all valid candidate
     registers across all calls): runs in parallel and ranks which single register swap lowers `Rest`.
"""
import argparse
import multiprocessing as mp
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLKIT_ROOT = os.path.normpath(os.path.join(HERE, '..'))
for _p in (HERE, os.path.join(TOOLKIT_ROOT, '01_werkzeugkette'), TOOLKIT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import unicorn as U
from unicorn import x86_const as X
import project_config as PC
import w106cfg as C
from emu106 import BASE
from comp import comp
import adr106
from regdump106 import regname

_CFG = PC.load_config()
FSTAND = os.path.join(TOOLKIT_ROOT, '03_richter', 'fstand.py')
_LO = {}

REG_MAP = {
    'EAX': 0x01000003, 'EBX': 0x0200000C, 'ECX': 0x04000030, 'EDX': 0x080000C0,
    'ESI': 0x10000100, 'EDI': 0x20000200, 'EBP': 0x400,
    'AX': 0x03, 'BX': 0x0C, 'CX': 0x30, 'DX': 0xC0, 'SI': 0x100, 'DI': 0x200,
    'AL': 0x02, 'AH': 0x01, 'BL': 0x08, 'BH': 0x04, 'CL': 0x20, 'CH': 0x10, 'DL': 0x80, 'DH': 0x40,
}


def lo_von(unit):
    if not _LO:
        utsv = PC.resolve_path('units_tsv', _CFG)
        if utsv and os.path.isfile(utsv):
            for l in open(utsv, encoding='utf-8', errors='replace'):
                c = l.rstrip('\n').split('\t')
                if len(c) >= 3:
                    _LO[c[1]] = c[2]
    return _LO.get(unit, '010000')


def judge_rest(obj, unit, fkt):
    lo = lo_von(unit)
    f_hex = fkt.lower().replace('f_', '').upper()
    try:
        r = subprocess.run([sys.executable, FSTAND, obj, lo], capture_output=True, text=True, timeout=120)
        m = re.search(r'^' + re.escape(f_hex) + r'\s+\d+/\d+\s+(GLEICH|MATCH|(\d+) (?:Befehle|insns))', r.stdout, re.M)
        if not m:
            return 9999
        return 0 if m.group(1) in ('GLEICH', 'MATCH') else int(m.group(2))
    except Exception:
        return 9999


def lauf(src, unit, fkt, force=None, mit=None, keep=None):
    """force=(k, reg_mask): in the k-th GiveBestReg call of `fkt`, force `reg_mask` to win."""
    cc = adr106.compiler_aus_quelle(src)
    A = adr106.fuer(cc)
    O = adr106.OFF
    st = {'k': -1, 'in': False}
    namen = adr106.quellfunktionen(src)

    def hook(e):
        track = adr106.ProcTrack(e, cc, namen)

        def loop(uc, a, s, _):
            st['in'] = (fkt in track.name())
            if not st['in']:
                return
            st['k'] += 1
            if mit is not None:
                conf = e.r(X.UC_X86_REG_EDI)
                nm = e.u32(conf + O['conf_name'])
                nid = struct.unpack('<H', e.rd(nm + O['name_id'], 2))[0]
                sym = e.u32(nm + O['name_sym'])
                txt = 't%d' % nid
                if sym >= BASE:
                    try:
                        txt = e.cstr(e.u32(e.u32(sym + O['sym_inner']) + O['sym_inner']), 40) or txt
                    except Exception:
                        pass
                mit.append(dict(
                    k=st['k'], conf=conf, txt=txt, id=nid,
                    sav=e.u32(conf + O['conf_savings']), kand=[], best=None,
                    with_=e.u32(conf + O['conf_with']),
                    inuse=e.u32(BASE + A['RegsInUse']),
                ))

        def save(uc, a, s, _):
            if not st['in']:
                return
            reg = e.r(X.UC_X86_REG_ESI)
            sv = e.r(X.UC_X86_REG_EAX)
            if sv >= 0x80000000:
                sv -= 1 << 32
            if mit is not None and mit:
                mit[-1]['kand'].append((reg, sv))
            if force and st['k'] == force[0]:
                e.w(X.UC_X86_REG_EAX, 0x7FFFFFF if reg == force[1] else 0)

        def best(uc, a, s, _):
            if st['in'] and mit:
                mit[-1]['best'] = e.r(X.UC_X86_REG_EBP)

        def ping(uc, a, s, _):
            track.name()

        e.uc.hook_add(U.UC_HOOK_CODE, ping, begin=BASE + A['SortConflictsNach'], end=BASE + A['SortConflictsNach'])
        e.uc.hook_add(U.UC_HOOK_CODE, loop, begin=BASE + A['GiveBestRegSchleife'], end=BASE + A['GiveBestRegSchleife'])
        e.uc.hook_add(U.UC_HOOK_CODE, save, begin=BASE + A['CountRegMovesNach'], end=BASE + A['CountRegMovesNach'])
        e.uc.hook_add(U.UC_HOOK_CODE, best, begin=BASE + A['GiveBestRegGewaehlt'], end=BASE + A['GiveBestRegGewaehlt'])

    obj = keep or os.path.join(C.TMP, 'rf_%d_%s.obj' % (os.getpid(), force[0] if force else 'base'))
    ok, out, e = comp(src, obj, hook=hook)
    if not ok:
        return 9999, obj
    rest = judge_rest(obj, unit, fkt)
    if not keep and os.path.exists(obj):
        try:
            os.remove(obj)
        except OSError:
            pass
    return rest, obj


def _job(args):
    src, unit, fkt, k, reg = args
    try:
        r, _ = lauf(src, unit, fkt, (k, reg))
        return k, reg, r
    except Exception:
        return k, reg, 9999


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src', help='Path to C/C++ source file')
    ap.add_argument('einheit', help='Unit name')
    ap.add_argument('fkt', help='Function name (e.g. f_400010)')
    ap.add_argument('--zwing', nargs=2, metavar=('K', 'REG'), help='Force call #K to pick register REG (e.g. ECX or hex mask)')
    ap.add_argument('--alle', action='store_true', help='Sweep all equal-score tie candidates in parallel')
    ap.add_argument('--weit', action='store_true', help='With --alle: sweep all candidate registers, not only ties')
    ap.add_argument('--procs', type=int, default=4, help='Worker processes for --alle (default: 4)')
    ap.add_argument('--keep', default=None, help='Keep compiled .OBJ at this path')
    A = ap.parse_args()

    fkt = A.fkt.lower() if A.fkt.lower().startswith('f_') else 'f_' + A.fkt.lower()

    if A.zwing:
        rname = A.zwing[1].upper()
        reg = REG_MAP[rname] if rname in REG_MAP else int(A.zwing[1], 16)
        force = (int(A.zwing[0]), reg)
        mit = []
        n_forced, obj_path = lauf(A.src, A.einheit, fkt, force=force, mit=mit, keep=A.keep)
        print(f'{A.einheit} {fkt}: forced #{force[0]} -> {regname(reg)} => Rest {n_forced} Befehle')
        return

    mit = []
    n0, _ = lauf(A.src, A.einheit, fkt, force=None, mit=mit, keep=A.keep)
    print(f'{A.einheit} {fkt}: baseline Rest {n0} instructions, {len(mit)} GiveBestReg calls')
    ties = []
    for m in mit:
        if not m['kand']:
            continue
        bs = max(s for r, s in m['kand'])
        gl = [r for r, s in m['kand'] if s == bs]
        tie = 'TIE' if len(gl) > 1 else ''
        print('  #%-3d %-12s sav %6d  chosen %-5s  %s  %s  [with %s | inuse %s]' % (
            m['k'], m['txt'][:12], m['sav'], regname(m['best']),
            ' '.join('%s:%d' % (regname(r), s) for r, s in m['kand']), tie,
            regname(m['with_']) if m['with_'] else '-',
            regname(m['inuse']) if m['inuse'] else '-',
        ))
        if A.weit:
            ties += [(m['k'], r) for r, s in m['kand'] if r != m['best']]
        elif len(gl) > 1:
            ties += [(m['k'], r) for r in gl if r != m['best']]

    if not A.alle or n0 in (0, 9999):
        return
    print(f'Testing {len(ties)} forced register assignments across {A.procs} processes ...', flush=True)
    with mp.get_context('fork').Pool(A.procs, maxtasksperchild=40) as p:
        R = p.map(_job, [(A.src, A.einheit, fkt, k, r) for k, r in ties])
    R.sort(key=lambda x: x[2])
    for k, r, n in R[:15]:
        m = mit[k]
        print('  %4d insns: #%d %s -> %s (instead of %s)' % (n, k, m['txt'], regname(r), regname(m['best'])))


if __name__ == '__main__':
    main()
