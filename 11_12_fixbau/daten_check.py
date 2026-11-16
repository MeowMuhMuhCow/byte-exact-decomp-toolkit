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
"""daten_check.py (worker 16.11.): vergleicht das Datenobjekt einer Fix-EXE mit dem Original, ausser an Fixup-Stellen."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import le
Q = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../..'))
o = le.lade(open(ORIG_EXE,'rb').read()[0x38d64:])
for p in sys.argv[1:]:
    b = open(p,'rb').read(); f = le.lade(b[0x38d64:] if b[0x38d64:0x38d66]==b'MZ' else b)
    od, fd = le.objdaten(o,2), le.objdaten(f,2)
    fx = set()
    for L in (o,f):
        for s,so,t,to,ty in L['fx']:
            if s==2: fx.update(range(so, so+4))
    diff=[i for i in range(min(len(od),len(fd))) if od[i]!=fd[i] and i not in fx]
    # zusammenhaengende Bereiche
    ber=[]; 
    for i in diff:
        if ber and i<=ber[-1][1]+8: ber[-1][1]=i
        else: ber.append([i,i])
    print(f'{os.path.basename(os.path.dirname(p)) or p}: Datenbytes anders (ohne Zeiger): {len(diff)} in {len(ber)} Bereichen')
    for a,e in ber[:12]: print(f'    d_{0x1a0000+a:06x}..{0x1a0000+e:06x}  orig {od[a:e+1][:16].hex()}  fix {fd[a:e+1][:16].hex()}')
