#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""slotdiag.py QUELLE EINHEIT FKT [--procs N] - Stapelplatz-Diagnose im echten 10.6 (worker, 29.10.2026), nach NHL95 slotdump.
10.6-Abbild: AssignOtherLocals 0x90C42, Namensliste Names[N_TEMP] = [0xC6870], LastTemp = [0xC6860],
Groessen-Sortierung SortList(..., TempAllocBefore 0x90CDC) -> Hook 0x90C6D (eax = sortierte Liste, Groesse +8, id +0x24).
Die Liste wird danach von oben nach unten auf den Stapel verteilt. Hier wird jeder Name einmal an den Anfang seines Laufs
gleicher Groesse gestellt (= was die instabile Sortierung auch liefern kann; erreichbar meist ueber Deklarationsreihenfolge
oder Benutzungszahl) und gemessen. 0 Befehle = Quelle stimmt bis auf die Stapelreihenfolge."""
import sys,os,struct,argparse,multiprocessing as mp; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import w106cfg as C
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp
import regdump106 as R
from latepick106 import fname
from fdiff2 import diff
A_SLOT=0x90C6D
def lauf(src,fkt,unit,k=None,info=None):
    st={'n':-1}
    def hook(e):
        rd=R.RegDump.__new__(R.RegDump); rd.e=e
        def h(uc,a,s,_):
            if fname(e)!=fkt: return
            st['n']+=1
            if st['n']!=0: return
            p=e.r(X.UC_X86_REG_EAX); L=[]
            while p:
                cls=e.rd(p+4,1)[0]; size=e.u32(p+8); nid=struct.unpack('<H',e.rd(p+0x24,2))[0]
                fl=struct.unpack('<H',e.rd(p+0x2a,2))[0]; sym=e.u32(p+0x14); txt='t%d'%nid
                if sym:
                    try: txt=e.cstr(e.u32(e.u32(sym+0xc)+0xc),40) or txt
                    except Exception: pass
                L.append(dict(p=p,size=size,id=nid,fl=fl,txt=txt)); p=e.u32(p)
            if info is not None: info.extend(L)
            if k is not None and 0<k<len(L):
                key=lambda d:(d['fl']&0x200!=0,d['size'])
                first=min(i for i,d in enumerate(L) if key(d)==key(L[k]))
                x=L.pop(k); L.insert(first,x)
                for i,d in enumerate(L): uc.mem_write(d['p'],struct.pack('<I',L[i+1]['p'] if i+1<len(L) else 0))
                e.w(X.UC_X86_REG_EAX,L[0]['p'])
        e.uc.hook_add(U.UC_HOOK_CODE,h,begin=BASE+A_SLOT,end=BASE+A_SLOT)
    obj=os.path.join(C.TMP,'slot_%d.obj'%os.getpid())
    ok,out,e=comp(src,obj,hook=hook)
    if not ok: return 9999
    try: return diff(unit,fkt,obj,0)[0]
    except Exception: return 9999
def job(a):
    src,fkt,unit,k=a; return k,lauf(src,fkt,unit,k)
def diag(src,unit,fkt,pool):
    info=[]; n0=lauf(src,fkt,unit,None,info)
    if n0 in (0,9999) or not info: return n0,info,[]
    ks=[k for k in range(1,len(info)) if (info[k]['fl']&0x200!=0,info[k]['size'])==(info[k-1]['fl']&0x200!=0,info[k-1]['size'])]
    R_=pool.map(job,[(src,fkt,unit,k) for k in ks]); R_.sort(key=lambda x:x[1]); return n0,info,R_
def alle(procs):
    import time
    from tieall import ziele
    lg=os.path.join(C.OUT,'slotall.log'); out=os.path.join(C.OUT,'slot_alle.tsv')
    def log(x):
        z=time.strftime('%H:%M:%S ')+x; print(z,flush=True); open(lg,'a').write(z+'\n')
    Z={(u,f):(b,r,s) for u,f,b,r,s in ziele(15)}
    kein=[l.split('\t') for l in open(os.path.join(C.OUT,'tie_alle.tsv')) if l.split('\t')[5]!='' and not (l.split('\t')[6]=='0' and l.split('\t')[5] not in ('-','kein'))]
    fertig=set()
    if os.path.exists(out): fertig={tuple(l.split('\t')[:2]) for l in open(out)}
    log('START %d Ziele ohne Gleichstand-Treffer, %d schon fertig, %d Prozesse'%(len(kein),len(fertig),procs))
    pool=mp.get_context('fork').Pool(procs,maxtasksperchild=40)
    for nr,p in enumerate(kein,1):
        u,f=p[0],p[1]
        if (u,f) in fertig or (u,f) not in Z: continue
        b,r,src=Z[(u,f)]; t=time.time()
        log('[%d/%d] %s f_%s (Rest %s) ...'%(nr,len(kein),u,f,r))
        n0,info,R_=diag(src,u,'f_'+f,pool)
        if R_ and R_[0][1]<n0:
            k,n=R_[0]; d=info[k]; first=min(i for i,x in enumerate(info) if (x['fl']&0x200!=0,x['size'])==(d['fl']&0x200!=0,d['size']))
            erg=('STAPEL -> exakt Original! ' if n==0 else 'besser (Rest %d): '%n)+'%s (Groesse %d) vor %s'%(d['txt'],d['size'],', '.join(x['txt'] for x in info[first:k][:5]))
        else: erg='keine Stapelumstellung hilft' if n0 not in (0,9999) else 'uebersprungen (%s)'%n0; n=n0
        open(out,'a').write('%s\t%s\t%s\t%s\t%s\t%s\t%.0fs\n'%(u,f,r,n0,n,erg,time.time()-t))
        log('      => %s  (%.0f s)'%(erg,time.time()-t))
    log('ENDE')
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('src',nargs='?'); ap.add_argument('einheit',nargs='?'); ap.add_argument('fkt',nargs='?'); ap.add_argument('--alle',action='store_true'); ap.add_argument('--procs',type=int,default=max(1,(os.cpu_count() or 2)-1))
    A=ap.parse_args()
    if A.alle: alle(A.procs); sys.exit()
    pool=mp.get_context('fork').Pool(A.procs,maxtasksperchild=40)
    n0,info,R_=diag(A.src,A.einheit,A.fkt,pool)
    print('%s %s: %d abweichende Befehle; Stapel-Namensliste nach Groessensortierung (%d):'%(A.einheit,A.fkt,n0,len(info)))
    print('   '+', '.join('%s(%d)'%(d['txt'],d['size']) for d in info[:30]))
    for k,n in R_[:8]:
        d=info[k]; first=min(i for i,x in enumerate(info) if (x['fl']&0x200!=0,x['size'])==(d['fl']&0x200!=0,d['size']))
        print('  %4d Befehle: %s (Groesse %d) vor %s'%(n,d['txt'],d['size'],', '.join(x['txt'] for x in info[first:k][:6])))
