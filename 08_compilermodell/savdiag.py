#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""savdiag.py - Nutzwert-Diagnose im echten 10.6 (worker, 29.10.2026), nach NHL95 countsolve.
Fuer EINE Funktion wird vor der Sortierung (Hook 0x9408F, Durchgang 0) der Nutzwert (savings, +0x14) eines Konflikts um d
verstellt und gemessen. 0 Befehle = im Original hatte diese Variable/dieses Temporaere einen anderen Nutzwert
(eine Benutzung mehr/weniger, in/ausserhalb einer Schleife), der Rest der Quelle stimmt.
  savdiag.py QUELLE EINHEIT FKT                 eine Funktion
  savdiag.py --alle [--procs N]                 alle Ziele aus OUT/tie_alle.tsv mit 'kein' (Ergebnis OUT/sav_alle.tsv, Log OUT/savall.log)"""
import sys,os,struct,time,argparse,multiprocessing as mp; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import w106cfg as C
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp
import regdump106 as R
from latepick106 import fname
from fdiff2 import diff
import irlist
DS=(-2,-1,1,2)
def lauf(src,fkt,unit,k=None,d=0,info=None):
    st={'n':-1}
    def hook(e):
        rd=R.RegDump.__new__(R.RegDump); rd.e=e
        def h(uc,a,s,_):
            if fname(e)!=fkt: return
            st['n']+=1
            if st['n']!=0: return
            p=e.r(X.UC_X86_REG_EAX); i=0
            while p:
                if info is not None:
                    dd=rd.name_info(p); dd['savings']=e.u32(p+0x14); dd['first']=irlist.ins(e,e.u32(p+0x38)); info.append(dd)
                if i==k:
                    v=e.u32(p+0x14); uc.mem_write(p+0x14,struct.pack('<I',max(0,v+d)))
                p=e.u32(p); i+=1
        e.uc.hook_add(U.UC_HOOK_CODE,h,begin=BASE+0x9408F,end=BASE+0x9408F)
    obj=os.path.join(C.TMP,'sav_%d.obj'%os.getpid())
    ok,out,e=comp(src,obj,hook=hook)
    if not ok: return 9999
    try: return diff(unit,fkt,obj,0)[0]
    except Exception: return 9999
def job(a):
    src,fkt,unit,k,d=a; return k,d,lauf(src,fkt,unit,k,d)
def diag(src,unit,fkt,pool):
    info=[]; n0=lauf(src,fkt,unit,None,0,info)
    if n0 in (0,9999) or not info: return n0,info,[]
    R_=pool.map(job,[(src,fkt,unit,k,d) for k in range(len(info)) for d in DS if info[k]['savings']+d>=0])
    R_.sort(key=lambda x:x[2]); return n0,info,R_
def zeile(info,k,d):
    x=info[k]; return '%s (sav %d%+d) aus: %s'%(x['txt'],x['savings'],d,x['first'][:50])
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('src',nargs='?'); ap.add_argument('einheit',nargs='?'); ap.add_argument('fkt',nargs='?')
    ap.add_argument('--alle',action='store_true'); ap.add_argument('--procs',type=int,default=max(1,(os.cpu_count() or 2)-1))
    A=ap.parse_args(); pool=mp.get_context('fork').Pool(A.procs,maxtasksperchild=40)
    if not A.alle:
        n0,info,R_=diag(A.src,A.einheit,A.fkt,pool)
        print('%s %s: %d abweichende Befehle, %d Konflikte'%(A.einheit,A.fkt,n0,len(info)))
        for k,d,n in R_[:10]: print('  %4d Befehle: %s'%(n,zeile(info,k,d)))
        sys.exit()
    lg=os.path.join(C.OUT,'savall.log'); out=os.path.join(C.OUT,'sav_alle.tsv')
    def log(x):
        z=time.strftime('%H:%M:%S ')+x; print(z,flush=True); open(lg,'a').write(z+'\n')
    from tieall import ziele
    Z={(u,f):(b,r,s) for u,f,b,r,s in ziele(15)}
    kein=[l.split('\t') for l in open(os.path.join(C.OUT,'tie_alle.tsv')) if l.split('\t')[5]=='kein']
    fertig=set()
    if os.path.exists(out): fertig={tuple(l.split('\t')[:2]) for l in open(out)}
    log('START %d Ziele ohne Gleichstand, %d schon fertig, %d Prozesse'%(len(kein),len(fertig),A.procs))
    for nr,p in enumerate(kein,1):
        u,f=p[0],p[1]
        if (u,f) in fertig or (u,f) not in Z: continue
        b,r,src=Z[(u,f)]; t=time.time()
        log('[%d/%d] %s f_%s (Rest %s) ...'%(nr,len(kein),u,f,r))
        n0,info,R_=diag(src,u,'f_'+f,pool)
        if R_ and R_[0][2]<n0:
            k,d,n=R_[0]; erg=('NUTZWERT -> exakt Original! ' if n==0 else 'besser (Rest %d): '%n)+zeile(info,k,d)
            weitere=[zeile(info,k2,d2) for k2,d2,n2 in R_[1:6] if n2==n]
        else: erg='keine Nutzwert-Aenderung hilft'; n=n0; weitere=[]
        open(out,'a').write('%s\t%s\t%s\t%d\t%d\t%s\t%s\t%.0fs\n'%(u,f,r,n0,n,erg,' | '.join(weitere),time.time()-t))
        log('      => %s  (%.0f s)'%(erg,time.time()-t))
    log('ENDE')
