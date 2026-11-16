import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""irlist.py QUELLE FKT - Konfliktliste VOR der Sortierung mit erstem/letztem Befehl je Konflikt (worker)."""
import sys,struct,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import w106cfg as C
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp
import regdump106 as R
from latepick106 import fname
OP={0:'nop',1:'add',3:'sub',5:'mul',7:'div',8:'mod',9:'and',0xa:'or',0xb:'xor',0xc:'shr',0xd:'shl',0x11:'neg',0x12:'not',0x24:'conv',0x26:'mov',0x28:'lea',0x2a:'push',0x2c:'parm',0x30:'==',0x31:'!=',0x32:'>',0x33:'<=',0x34:'<',0x35:'>=',0x36:'call'}
def nm(e,n):
    try:
        cls=e.rd(n+4,1)[0]
        if cls==0: return '#%d'%struct.unpack('<i',e.rd(n+0x10,4))[0]
        sym=e.u32(n+0x14); nid=struct.unpack('<H',e.rd(n+0x24,2))[0]
        if sym:
            s=e.cstr(e.u32(e.u32(sym+0xc)+0xc),40)
            return s if cls!=2 else s
        return {2:'t%d'%nid,3:'R',4:'[idx]'}.get(cls,'c%d'%cls)
    except Exception: return '?'
def ins(e,v):
    if not v: return '-'
    op=e.rd(v+0x22,1)[0]; n=e.rd(v+0x3f,1)[0]; ops=[nm(e,e.u32(v+0x44+4*k)) for k in range(min(n,3))]; r=e.u32(v+0x30)
    return '%s = %s %s'%(nm(e,r) if r else '_',OP.get(op,'op%x'%op),','.join(ops))
def liste(src,fkt):
    out=[]
    def hook(e):
        rd=R.RegDump.__new__(R.RegDump); rd.e=e
        def a(uc,ad,s,_):
            if fname(e)!=fkt or out: return
            p=e.r(X.UC_X86_REG_EAX)
            while p:
                d=rd.name_info(p); d['savings']=e.u32(p+0x14); d['first']=ins(e,e.u32(p+0x38)); d['last']=ins(e,e.u32(p+0x3c)); out.append(d); p=e.u32(p)
        e.uc.hook_add(U.UC_HOOK_CODE,a,begin=BASE+0x9408f,end=BASE+0x9408f)
    comp(src,os.path.join(C.TMP,'irl.obj'),hook=hook)
    return out
if __name__=='__main__':
    for i,d in enumerate(liste(sys.argv[1],sys.argv[2])):
        if len(sys.argv)>3 and not (int(sys.argv[3])<=i<=int(sys.argv[4])): continue
        print('%3d %-6s sav %3d  %-34s | %s'%(i,d['txt'][:6],d['savings'],d['first'][:34],d['last'][:40]))
