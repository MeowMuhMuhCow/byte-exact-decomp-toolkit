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
"""kreuz_check.py (worker 16.11.): Versatzkarte Original->Fix und falsche direkte Aufrufe (E8/E9) mit Quell-/Zieleinheit."""
import sys, os, re, struct, subprocess, tempfile, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import le
Q=os.path.abspath(os.path.join(os.path.dirname(__file__),'../../../../..')); B=0x10000
def lade(p):
    b=open(p,'rb').read(); return le.lade(b[0x38d64:] if b[0x38d64:0x38d66]==b'MZ' else b)
oc=le.objdaten(lade(ORIG_EXE),1)
units=[]
for l in open(UNITS_TSV,encoding='utf-8',errors='replace'):
    p=l.rstrip('\n').split('\t')
    try: units.append((int(p[2],16)-B,int(p[3],16)-B,p[1]))
    except: pass
units.sort(); ulo=[u[0] for u in units]
def unit(a):
    k=bisect.bisect_right(ulo,a)-1
    return units[k][2] if k>=0 and a<units[k][1] else '?'
def calls(code):
    fn=os.path.join(tempfile.gettempdir(),f'kc_{os.getpid()}.bin'); open(fn,'wb').write(code)
    out=subprocess.run(['objdump','-D','-b','binary','-mi386',fn],capture_output=True,text=True).stdout; os.unlink(fn)
    return [(int(m.group(1),16),int(m.group(3),16)) for m in re.finditer(r'^\s*([0-9a-f]+):\s+(e8|e9) (?:[0-9a-f]{2} ){4}\s*(?:call|jmp)\s+0x([0-9a-f]+)',out,re.M)]
oz=set(calls(oc))
for p in sys.argv[1:]:
    fc=le.objdaten(lade(p),1)
    # Versatzkarte orig->fix
    karte=[]; last=None
    for a in range(0,len(oc)-24,0x20):
        pat=oc[a:a+24]
        if len(set(pat))<8: continue
        k=fc.find(pat,max(0,a-0x8000),a+0x8000)
        if k<0 or fc.find(pat,k+1,a+0x8000)>=0: continue
        karte.append((a,k-a))
    ka=[x[0] for x in karte]
    def zuorig(fa):  # fix->orig ueber Karte (naechster Stuetzpunkt)
        best=None
        for a,d in karte[max(0,bisect.bisect_left(ka,fa-0x9000)):bisect.bisect_left(ka,fa+0x1000)]:
            if a+d<=fa: best=fa-d
        return best
    fz=calls(fc); paare={}
    for s,t in fz:
        so=zuorig(s); to=zuorig(t)
        if so is None: continue
        # Original-Aufruf an derselben Stelle?
        if so<len(oc)-5 and oc[so] in (0xe8,0xe9):
            tor=so+5+struct.unpack('<i',oc[so+1:so+5])[0]
            if to is not None and tor!=to and oc[tor:tor+6]!=fc[t:t+6]:
                key=(unit(so),unit(tor)); paare.setdefault(key,[]).append((s,t,so,tor))
    print(f'== {p}: falsche direkte Aufrufe {sum(len(v) for v in paare.values())}')
    for (us,ut),v in sorted(paare.items(),key=lambda x:-len(x[1]))[:25]:
        s,t,so,tor=v[0]; print(f'   {us:22s} -> {ut:22s} {len(v):4d}x  z.B. orig {so+B:06x}->{tor+B:06x}')
