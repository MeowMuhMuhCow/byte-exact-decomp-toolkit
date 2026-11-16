#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_TK = _os.path.normpath(_os.path.join(_HERE, '..'))
if _TK not in _sys.path: _sys.path.insert(0, _TK)
import project_config as _PC
_CFG = _PC.load_config()
ORIG_EXE = _os.environ.get('ORIG_EXE') or _PC.resolve_path('orig_exe', _CFG)
UNITS_TSV = _PC.resolve_path('units_tsv', _CFG)
if '--orig' in _sys.argv:
    _i = _sys.argv.index('--orig'); ORIG_EXE = _sys.argv[_i + 1]; del _sys.argv[_i:_i + 2]
"""zeiger_check.py (worker, 16.11.2026): prueft eine Fix-EXE gegen Original/target.EXE.
Jeder Zeiger (LE-Fixup) der Fix-EXE, der in den Code zeigt, muss auf eine Stelle zeigen, die es im Original
als Zeigerziel mit gleichem Inhalt gibt (Bytes maskiert: Fixup-Stellen und rel32 nach E8/E9).
Zusaetzlich: Daten->Code-Zeiger paarweise (Daten sind gleich gross) - gleiches Ziel wie im Original?
Aufruf: python3 zeiger_check.py PFAD/TARGET_FIX_xxx_LE.EXE   (oder die gebundene EXE)"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import le
Q = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../..'))
STUB = 0x38d64
def lade(p):
    b = open(p, 'rb').read()
    if b[STUB:STUB+2] == b'MZ' and len(b) > STUB + 0x1000 and b[:2] == b'MZ': 
        try: return le.lade(b[STUB:])
        except Exception: pass
    return le.lade(b)
o = lade(ORIG_EXE); f = lade(sys.argv[1])
B = 0x10000; W = 8
def maske(L, code):
    m = bytearray(len(code))
    for s, so, t, to, ty in L['fx']:
        if s == 1:
            n = 2 if ty in (2, 5) else (6 if ty == 6 else 4)
            for i in range(so, min(so + n, len(m))): m[i] = 1
    return m
def sig(code, m, t):
    out = bytearray(); i = t; skip = 0
    while len(out) < W and i < len(code):
        if skip: out.append(0); skip -= 1
        elif m[i]: out.append(0)
        else:
            out.append(code[i])
            if code[i] in (0xe8, 0xe9): skip = 4
        i += 1
    return bytes(out)
oc, fc = le.objdaten(o, 1), le.objdaten(f, 1); om, fm = maske(o, oc), maske(f, fc)
osig = collections.Counter(sig(oc, om, to) for s, so, t, to, ty in o['fx'] if t == 1 and to is not None and to < len(oc))
schlecht = collections.defaultdict(list)
for s, so, t, to, ty in f['fx']:
    if t == 1 and to is not None and to < len(fc):
        if sig(fc, fm, to) not in osig: schlecht[to].append((s, so))
od = {so: (t, to) for s, so, t, to, ty in o['fx'] if s == 2}; fd = {so: (t, to) for s, so, t, to, ty in f['fx'] if s == 2}
paar = []
for k in sorted(od):
    if k in fd and od[k][0] == 1 and fd[k][0] == 1:
        if sig(oc, om, od[k][1]) != sig(fc, fm, fd[k][1]):
            # Ziel muss eine Funktionsgrenze sein: davor ret/jmp/Fuellung, d. h. kein Sprung mitten in eine Funktion
            t1 = fd[k][1]; vor = fc[max(0, t1-9):t1]
            grenze = t1 % 16 == 0 and (vor.endswith(b'\xc3') or vor[-3:-2] == b'\xc2' or vor.endswith(b'\x00') or vor.endswith(b'\x8d\x40\x00') or vor.endswith(b'\x8b\xc9') or vor.endswith(b'\x8b\xd2') or vor.endswith(b'\x90'))
            paar.append((k, od[k][1], t1, 'Grenze-ok' if grenze else 'MITTEN'))
print(f'Fixups Original {len(o["fx"])}, Fix {len(f["fx"])}')
print(f'A) Zeigerziele ohne Gegenstueck im Original: {len(schlecht)} Ziele ({sum(len(v) for v in schlecht.values())} Zeiger)')
for t in sorted(schlecht)[:60]:
    q = schlecht[t]; print(f'   Ziel {t+B:06x}  von {len(q)}x z.B. Obj{q[0][0]}+{q[0][1]:06x}   Bytes {fc[t:t+10].hex()}')
falsch = [x for x in paar if x[3] == 'MITTEN']
print(f'B) Daten->Code-Zeiger mit anderem Inhalt: {len(paar)}, davon mitten in eine Funktion: {len(falsch)}')
for k, a, b, g in paar[:40]: print(f'   Daten+{k:05x}: Original {a+B:06x} [{oc[a:a+8].hex()}]  Fix {b+B:06x} [{fc[b:b+8].hex()}] {g}')
print('ERGEBNIS:', 'DATENZEIGER SAUBER' if not falsch else 'FEHLER: Datenzeiger mitten in Funktion')
