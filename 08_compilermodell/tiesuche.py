import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""tiesuche.py - Gleichstaende im echten 10.6 erzwingen (worker). Fuer EINE Funktion wird nach SortConflicts die Liste
umgeordnet (nur innerhalb gleicher savings = was die instabile Sortierung auch liefern koennte), dann gemessen."""
import sys,struct,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import w106cfg as C
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp
import regdump106 as R
from fdiff2 import diff
def lauf(src,fkt,unit,ordne,passnr=0):
    """ordne(liste_von_dicts) -> neue Reihenfolge (Liste derselben dicts)"""
    st={'n':-1}
    def hook(e):
        rd=R.RegDump.__new__(R.RegDump); rd.e=e
        def h(uc,a,s,_):
            if R.RegDump.__dict__ and fkt not in fname(e): return
            st['n']+=1
            if st['n']!=passnr: return
            p=e.r(X.UC_X86_REG_EAX); L=[]
            while p:
                d=rd.name_info(p); d['savings']=e.u32(p+0x14); L.append(d); p=e.u32(p)
            N=ordne(L)
            assert sorted(x['conf'] for x in N)==sorted(x['conf'] for x in L)
            for i,d in enumerate(N):
                uc.mem_write(d['conf'],struct.pack('<I',N[i+1]['conf'] if i+1<len(N) else 0))
            e.w(X.UC_X86_REG_EAX,N[0]['conf'] if N else 0)
        e.uc.hook_add(U.UC_HOOK_CODE,h,begin=BASE+R.A_SORTED,end=BASE+R.A_SORTED)
    import os; obj=os.path.join(C.TMP,'tie_%d.obj'%os.getpid())
    ok,out,e=comp(src,obj,hook=hook)
    if not ok: return 9999,None
    return diff(unit,fkt,obj,0)[0],obj
from latepick106 import fname
