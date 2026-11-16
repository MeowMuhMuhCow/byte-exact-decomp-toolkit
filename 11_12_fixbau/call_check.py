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
"""call_check.py (worker 16.11.): jeder direkte call/jmp rel32 (E8/E9) der Fix-EXE muss auf eine Stelle zielen, die im Original
Ziel eines call/jmp mit gleichem Inhalt ist (8 Bytes, Zeiger/rel32 maskiert). Lineare Disassemblierung per objdump."""
import sys, os, re, subprocess, collections, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import le
Q = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../..')); B=0x10000
def lade(p):
    b=open(p,'rb').read(); return le.lade(b[0x38d64:] if b[0x38d64:0x38d66]==b'MZ' else b)
def ziele(code, tag):
    fn=os.path.join(tempfile.gettempdir(), f'cc_{tag}_{os.getpid()}.bin'); open(fn,'wb').write(code)
    out=subprocess.run(['objdump','-D','-b','binary','-mi386','--adjust-vma=0x10000',fn],capture_output=True,text=True).stdout
    os.unlink(fn); r=[]
    for m in re.finditer(r'^\s*([0-9a-f]+):\s+(e8|e9) (?:[0-9a-f]{2} ){4}\s*(call|jmp)\s+0x([0-9a-f]+)', out, re.M):
        r.append((int(m.group(1),16)-B, int(m.group(4),16)-B, m.group(3)))
    return r
def maske(L, code):
    m=bytearray(len(code))
    for s,so,t,to,ty in L['fx']:
        if s==1:
            for i in range(so,min(so+4,len(m))): m[i]=1
    return m
def sig(code,m,t,W=8):
    out=bytearray(); i=t; skip=0
    while len(out)<W and 0<=i<len(code):
        if skip: out.append(0); skip-=1
        elif m[i]: out.append(0)
        else:
            out.append(code[i])
            if code[i] in (0xe8,0xe9): skip=4
        i+=1
    return bytes(out)
o=lade(ORIG_EXE); oc=le.objdaten(o,1); om=maske(o,oc)
oz=ziele(oc,'o'); osig=set(sig(oc,om,t) for a,t,k in oz if 0<=t<len(oc))
print('Original: direkte Aufrufe/Spruenge',len(oz))
for p in sys.argv[1:]:
    f=lade(p); fc=le.objdaten(f,1); fm=maske(f,fc); fz=ziele(fc,'f')
    schlecht=collections.defaultdict(list)
    for a,t,k in fz:
        if 0<=t<len(fc) and sig(fc,fm,t) not in osig: schlecht[t].append((a,k))
    calls=sum(1 for t,v in schlecht.items() if any(k=='call' for a,k in v))
    print(f'{p}: rel32-Ziele ohne Gegenstueck: {len(schlecht)} (davon mit call: {calls})')
    for t,v in sorted(schlecht.items(), key=lambda x:-len(x[1]))[:15]:
        print(f'    Ziel {t+B:06x} {fc[t:t+8].hex()}  von {len(v)}x, z.B. {v[0][1]} bei {v[0][0]+B:06x}')
