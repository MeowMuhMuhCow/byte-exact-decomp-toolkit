#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""vorsort_c.py QUELLE EINHEIT FKT NAME[,NAME] - (08.11. worker) Namensliste VOR der Stapel-Sortierung (AssignOtherLocals 0x90C42,
Kopf [0xC6870]) umstellen: jeden genannten Namen an jede Position verschieben, echte Sortierung laufen lassen, messen.
Zeigt, welcher Name im Quelltext frueher/spaeter angelegt werden muss."""
import sys,os,struct,multiprocessing as mp; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp
from latepick106 import fname
import w106cfg as C
from slotdiag_c import mymess
A_AOL=0x90C42; HEAD=BASE+0xC6870
def lauf(src,fkt,unit,mv=None,info=None):
    st={'n':-1}
    def hook(e):
        def h(uc,a,s,_):
            try:
                if fname(e)!=fkt: return
            except Exception: return
            st['n']+=1
            if st['n']!=0: return
            p=e.u32(HEAD); L=[]
            while p:
                nid=struct.unpack('<H',e.rd(p+0x24,2))[0]; sym=e.u32(p+0x14); txt='t%d'%nid
                if sym:
                    try: txt=e.cstr(e.u32(e.u32(sym+0xc)+0xc),40) or txt
                    except Exception: pass
                L.append(dict(p=p,size=e.u32(p+8),txt=txt)); p=e.u32(p)
            if info is not None: info.extend(L)
            if mv is not None:
                i,j=mv; x=L.pop(i); L.insert(j,x)
                for q,d in enumerate(L): uc.mem_write(d['p'],struct.pack('<I',L[q+1]['p'] if q+1<len(L) else 0))
                uc.mem_write(HEAD,struct.pack('<I',L[0]['p']))
        e.uc.hook_add(U.UC_HOOK_CODE,h,begin=BASE+A_AOL,end=BASE+A_AOL)
    obj=os.path.join(C.TMP,'vs_%d.obj'%os.getpid())
    ok,out,e=comp(src,obj,hook=hook)
    if not ok: return 9999
    return mymess(unit,fkt,obj)
def job(a):
    src,fkt,unit,mv=a; return mv,lauf(src,fkt,unit,mv)
if __name__=='__main__':
    src,unit,fkt,names=sys.argv[1:5]; names=names.split(',')
    info=[]; n0=lauf(src,fkt,unit,None,info)
    print('start',n0,len(info),' '.join('%d:%s(%d)'%(i,d['txt'],d['size']) for i,d in enumerate(info)),flush=True)
    jobs=[(src,fkt,unit,(i,j)) for i,d in enumerate(info) if d['txt'] in names for j in range(len(info)) if j!=i]
    with mp.Pool(int(os.environ.get('PROCS','2'))) as P:
        for mv,n in P.imap_unordered(job,jobs):
            if n<n0: print(n,info[mv[0]]['txt'],mv,flush=True)
    print('ENDE',flush=True)
