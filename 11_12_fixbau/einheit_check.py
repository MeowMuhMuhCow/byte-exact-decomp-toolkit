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
"""einheit_check.py (worker, 16.11.): ordnet jede unveraenderte Einheit ihrer neuen Lage in der Fix-EXE zu (haeufigste
Verschiebung der Fixup-Quellen) und prueft jeden Zeiger der Einheit: gleiche Stelle, gleiches Ziel (Daten: gleicher
Offset; Code: gleicher Inhalt)."""
import sys, os, collections, bisect, pathlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import le
Q = pathlib.Path(__file__).resolve().parents[5]
o = le.lade(open(Path(ORIG_EXE),'rb').read()[0x38d64:]); f = le.lade(open(sys.argv[1],'rb').read())
oc, fc = le.objdaten(o,1), le.objdaten(f,1); B=0x10000
units=[]
for l in open(Path(UNITS_TSV),encoding='utf-8',errors='replace'):
    p=l.rstrip('\n').split('\t')
    try: units.append((int(p[2],16)-B,int(p[3],16)-B,p[1]))
    except: pass
units.sort()
geaendert=set(x.name[:-7] for x in (Path(PC.resolve_path('src_p3_dir', _CFG))).glob('*_P1.CPP'))|set()
of=sorted((so,t,to) for s,so,t,to,ty in o['fx'] if s==1)
ff={so:(t,to) for s,so,t,to,ty in f['fx'] if s==1}; fs=sorted(ff)
def sig(code,t,n=6): return code[t:t+n]
probleme=collections.defaultdict(list); keinlage=[]
for lo,hi,name in units:
    if name in geaendert: continue
    src=[x for x in of if lo<=x[0]<hi]
    if not src: continue
    h=collections.Counter()
    for so,_,_ in src[:200]:
        i=bisect.bisect_left(fs,so-0x200)
        while i<len(fs) and fs[i]<so+0x8000: h[fs[i]-so]+=1; i+=1
    d,n=h.most_common(1)[0]
    if n < min(len(src),200)*0.8: keinlage.append((name,len(src),n)); continue
    for so,t,to in src:
        g=ff.get(so+d)
        if g is None: probleme[name].append(('FIXUP FEHLT',so+B,so+d+B,t,to)); continue
        if t==2:
            if g!=(2,to): probleme[name].append(('DATENZIEL ANDERS',so+B,so+d+B,to,g))
        else:
            if g[0]!=1 or (oc[to:to+1] != fc[g[1]:g[1]+1]): probleme[name].append(('CODEZIEL ANDERS',so+B,so+d+B,hex(to+B),hex(g[1]+B) if g[0]==1 else g))
print('Einheiten ohne eindeutige Lage:',keinlage[:20])
print('Einheiten mit Problemen:',len(probleme))
for n,v in sorted(probleme.items(), key=lambda x:-len(x[1]))[:40]:
    print(n,len(v),v[:3])
