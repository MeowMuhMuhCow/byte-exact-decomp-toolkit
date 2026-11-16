#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""sched106.py QUELLE.CPP --fkt FKT [--alle] - Instruktions-Scheduler des echten Watcom 10.6 mitlesen (worker, 29.10.2026).
ScheduleIns (OW bld/cg/c/inssched.c) liegt im 10.6-Abbild bei 0xA0152. Je Block wird von unten nach oben aus der
Bereitliste der Befehl mit minimalen Stall-Kosten gewaehlt; bei Gleichstand: groessere Hoehe, INDEX_ADJUST, groesseres
'stallable', FP-Sequenz, zuletzt die groessere Befehls-id (= spaeter erzeugt = spaeter im Quelltext).
Hooks: 0xA01AC Rundenanfang (Bereitliste in [ebp-8], Kette +0xC), 0xA02AC Wahl (ecx = gewaehlter data_dag),
Entscheidungsstellen 0xA01F9/0xA01FE (Kosten), 0xA0216 (Hoehe/Indexanpassung), 0xA0255 (stallable), 0xA0271 (FP-Sequenz),
0xA0281 (id). data_dag: +4 ins, +0xC ready, +0x10 stallable, +0x11 Flags (1 visited), +0x14 height, +0x18 anc_count.
Befehl: +0x22 Opcode, +0x34 id, +0x3A sequence, +0x40 Flags (0x80 INDEX_ADJUST).
Ausgabe je Block (von unten nach oben): gewaehlter Befehl, Bereitliste (ids), Grund der Wahl. Gruende 'id' sind die
Gleichstaende, die sich ueber die Quelltextreihenfolge kippen lassen."""
import sys,os,struct,argparse; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import w106cfg as C
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp
from irlist import ins as instxt
from latepick106 import fname
A_ENTRY,A_ROUND,A_PICK=0xA0152,0xA01AC,0xA02AC
REASON={0xA01F9:'kosten(erster)',0xA01FE:'kosten',0xA0216:'hoehe',0xA0240:'indexanp.',0xA0255:'stallable',0xA0271:'fpseq',0xA027F:'id'}
def lauf(src,fkt,alle=False):
    out=[]; st={'blk':0,'reason':None,'cur':None}
    def hook(e):
        def dag(p):
            ins=e.u32(p+4)
            return dict(dag=p,ins=ins,id=e.u32(ins+0x34),op=e.rd(ins+0x22,1)[0],h=e.u32(p+0x14),st=e.rd(p+0x10,1)[0],vis=e.rd(p+0x11,1)[0]&1)
        def h_entry(uc,a,s,_):
            try: f=fname(e)
            except Exception: f='?'
            st['cur']=f if (alle or fkt in f) else None
            if st['cur']: st['blk']+=1; out.append(('BLOCK',st['cur'],st['blk']))
        def h_round(uc,a,s,_):
            if not st['cur']: return
            p=e.u32(e.r(X.UC_X86_REG_EBP)-8); L=[]
            while p:
                d=dag(p)
                if not d['vis']: L.append(d)
                p=e.u32(p+0xC)
            st['ready']=L; st['reason']=None
        def h_reason(addr):
            def h(uc,a,s,_):
                if st['cur']: st['reason']=REASON[addr]
            return h
        def h_pick(uc,a,s,_):
            if not st['cur']: return
            p=e.r(X.UC_X86_REG_ECX)
            if not p: return
            d=dag(p)
            out.append(('WAHL',d['id'],instxt(e,d['ins']),st.get('reason'),[(x['id'],x['h'],x['st']) for x in st.get('ready',[])]))
        e.uc.hook_add(U.UC_HOOK_CODE,h_entry,begin=BASE+A_ENTRY,end=BASE+A_ENTRY)
        e.uc.hook_add(U.UC_HOOK_CODE,h_round,begin=BASE+A_ROUND,end=BASE+A_ROUND)
        e.uc.hook_add(U.UC_HOOK_CODE,h_pick,begin=BASE+A_PICK,end=BASE+A_PICK)
        for ad in REASON: e.uc.hook_add(U.UC_HOOK_CODE,h_reason(ad),begin=BASE+ad,end=BASE+ad)
    ok,o,e=comp(src,os.path.join(C.TMP,'sched_%d.obj'%os.getpid()),hook=hook)
    return ok,out
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('--fkt',default=''); ap.add_argument('--alle',action='store_true'); ap.add_argument('--nur-id',action='store_true')
    A=ap.parse_args(); ok,out=lauf(A.src,A.fkt,A.alle or not A.fkt)
    for z in out:
        if z[0]=='BLOCK': print('== %s Block %d (Wahl von unten nach oben)'%(z[1],z[2]))
        else:
            _,i,txt,r,ready=z
            if A.nur_id and r!='id': continue
            print('   id %3d  %-40s  %-14s bereit: %s'%(i,txt[:40],r or '?',' '.join('%d(h%d,s%d)'%x for x in ready)))
