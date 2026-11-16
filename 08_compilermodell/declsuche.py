#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""declsuche.py QUELLE EINHEIT FKT [--procs N] [--max-perm 720] - Deklarationsreihenfolge der Locals durchprobieren (worker).
Natuerlicher Hebel fuer Stapelplaetze und Gleichstaende (NHL95 declsearch): Locals stehen in umgekehrter Deklarationsreihenfolge
in der Namensliste. Der Deklarationsblock am Funktionsanfang wird in Einzeldeklarationen zerlegt und permutiert
(alle Reihenfolgen bis max-perm, sonst jede Variable an jede Position), jede Fassung im echten 10.6 gemessen."""
import sys,os,re,itertools,argparse; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import w106cfg as C
from editsuche import run
from variante import stand
DECL=re.compile(r'^(\s*)((?:static |register |volatile |const |signed |unsigned )*(?:char|short|int|long|unsigned|signed|[A-Z]\w*|\w+_t)\b[\s\*]*)(.+);\s*$')
def zerlege(body):
    L=body.split('\n'); i=next(k for k,l in enumerate(L) if l.strip()=='{')+1; ds=[]; j=i
    while j<len(L):
        m=DECL.match(L[j])
        if not m or '(' in m.group(3) and '=' not in m.group(3): break
        ind,typ,rest=m.groups()
        teile=[x.strip() for x in re.split(r',(?![^()]*\))',rest)]
        for t in teile:
            st=re.match(r'(\**)\s*(.*)',t); ds.append('%s%s%s%s;'%(ind,typ.strip(),' ' if not typ.strip().endswith('*') else '',st.group(1)+st.group(2)))
        j+=1
    return L,i,j,ds
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('einheit'); ap.add_argument('fkt'); ap.add_argument('--procs',type=int,default=max(1,(os.cpu_count() or 2)-1)); ap.add_argument('--max-perm',type=int,default=720)
    A=ap.parse_args(); s=open(A.src,errors='replace').read(); f=A.fkt.replace('f_','').lower()
    a=s.find('//@ f_'+f); b=s.find('\n//@',a+5); body=s[a:b if b>0 else len(s)]
    L,i,j,ds=zerlege(body)
    if len(ds)<2: print('weniger als 2 Deklarationen'); sys.exit()
    alt='\n'.join(L[i:j])+'\n'
    perms=list(itertools.permutations(ds)) if len(ds)<=6 and 720<=A.max_perm else None
    if perms is None:
        perms=[]
        for x in range(len(ds)):
            for y in range(len(ds)):
                if x!=y: d=list(ds); v=d.pop(x); d.insert(y,v); perms.append(tuple(d))
    perms=[p for p in dict.fromkeys(perms) if list(p)!=ds][:A.max_perm]
    E=[(alt,'\n'.join(p)+'\n') for p in perms]
    fs=os.path.join(C.LIVE,A.einheit+'.fstand'); g0,off0=stand(A.einheit,A.src,fs)
    print('%s %s: %d Deklarationen, %d Reihenfolgen, Ausgangsrest %s'%(A.einheit,A.fkt,len(ds),len(E),off0.get(f,0)),flush=True)
    R_=run(A.src,A.einheit,fs,f,E,A.procs); best=[]
    for k,g,rf,off in R_:
        if not isinstance(off,dict): continue
        rfn=0 if rf=='GLEICH' else rf
        schlechter=[x for x in off if x!=f and off[x]>off0.get(x,0)]
        if not schlechter: best.append((rfn,-g,k))
    best.sort()
    for rfn,g,k in best[:5]: print('  Rest %s, Einheit %d GLEICH:  %s'%(rfn,-g,' | '.join(x.strip() for x in perms[k])))
