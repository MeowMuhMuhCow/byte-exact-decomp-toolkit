# fsmod.py - Module interface for fstand per-function status and diff hunks.
# Rechenweg identisch mit gw/fstand.py (Symbolzuordnung, Fixup-Maskierung, Kern-/Pad-Regel I8). Der Richter bleibt fstand.py:
# suche.py prueft jeden Gewinn am Ende noch einmal mit fstand.py und legt dessen Ausgabe ab.
import sys,os,re,subprocess,difflib,struct,bisect,tempfile
_HERE=os.path.dirname(os.path.abspath(__file__))
_ROOT=os.path.normpath(os.path.join(_HERE,'..'))
for _p in (_HERE, os.path.join(_ROOT,'02_basis'), _ROOT):
    if _p not in sys.path: sys.path.insert(0,_p)
import project_config as PC, omf, le
_CFG=PC.load_config()
Q=PC.resolve_path('project_root',_CFG); B=int(_CFG.get('binary',{}).get('code_base_offset',0x10000) or 0x10000)
img=open(PC.resolve_path('flat_bin',_CFG),'rb').read()
_fset=set()
for _k,_rx in (('functions_tsv',r'[0-9a-fA-F]{6}\t'),('units_tsv',None)):
    _p=PC.resolve_path(_k,_CFG)
    if _p and os.path.isfile(_p):
        if _rx: _fset|={int(l.split('\t')[0],16) for l in open(_p) if re.match(_rx,l)}
        else: _fset|={int(x,16) for l in open(_p) for x in l.rstrip('\n').split('\t')[2:4] if re.match(r'[0-9a-fA-F]{6}$',x)}
_cp=PC.resolve_path('clobber_tsv',_CFG)
if _cp and os.path.isfile(_cp):
    _fset|={int(l[2:8],16) for l in open(_cp) if l.startswith('f_')}
FUN0=sorted(_fset - PC.load_excluded_table_addresses(_CFG))
SZ={7:4,5:2,6:6}; ORG=bytearray(img)
for s,t,g in le.fixups:
    for k in range(SZ.get(t,4)):
        if 0<=s-B+k<len(ORG): ORG[s-B+k]=0
PAD=os.environ.get('FSTAND_PAD','1')=='1'
PADX=re.compile(r'^(nop|xchg\s+ax,ax|int3|mov\s+(e?[a-d]x|e?[sd]i),\2|lea\s+(e?[a-d]x|e?[sd]i|esp|ebp),\[\3(\+eiz\*1)?\+0x0\]|lea\s+(e?[a-d]x|e?[sd]i),\[\5\]|add\s+BYTE PTR \[eax\],al|data16.*|nop\s+.*|xchg\s+eax,eax)$')
ENDX=re.compile(r'^(ret|jmp|iret|retf)'); RX=re.compile(r'^(call|j\w+)\s+0x([0-9a-f]+)$')
FILL_O=('nop','lea    eax,[eax+0x0]','lea    edx,[edx+0x0]','mov    eax,eax','mov    edx,edx','lea    ecx,[ecx+0x0]','mov    ecx,ecx','lea    ebx,[ebx+0x0]','mov    ebx,ebx')
def kern(L,A,ganz):
    k=len(L)
    while k>0 and PADX.match(L[k-1].strip()): k-=1
    if k>0 and ENDX.match(L[k-1]): return L[:k],(A[k]-A[0]) if k<len(A) else ganz
    return L,ganz
def dis(buf,base,res,ist_obj=False):
    p=os.path.join(PC.resolve_path('tmp_dir',_CFG,'/tmp'),'fm_%d.bin'%os.getpid()); open(p,'wb').write(bytes(buf))
    out=subprocess.run(['objdump','-D','-z','-b','binary','-mi386','-Mintel','--no-show-raw-insn',p],capture_output=True,text=True).stdout
    r=[]; ADR=[]
    for l in out.splitlines():
        if l[:1]!=' ' or ':' not in l: continue
        x=l.split('\t',1)[-1].strip(); adr=int(l.split(':')[0],16)
        q=RX.match(x)
        if q:
            tg=int(q.group(2),16)
            if ist_obj and ((q.group(1) in ('call','jmp') and tg==adr+5) or (q.group(1) not in ('call','jmp') and tg==adr+6)): x=q.group(1)+' EXT'   # Paritaet mit fstand.py: auch jcc rel32
            elif tg<len(buf): x=q.group(1)+' +%x'%tg
            else: x=q.group(1)+' '+res((base+tg)&0xffffffff)
        r.append(x); ADR.append(adr)
    ALL=ADR[:]
    while r and r[-1] in ('add    BYTE PTR [eax],al','(bad)'): r.pop(); ADR.pop()
    return r,ALL
def sym(nm):
    mm=re.search(r'\bW?\??f_([0-9a-f]{6})\b',nm); return 'f_%06x'%int(mm.group(1),16) if mm else nm
class Einheit:
    """OBJ einer Einheit laden: Code, Symbole, Funktionsgrenzen."""
    def __init__(self,obj,lo):
        self.obj=obj; self.lo=lo
        m=omf.modules(obj)[0]; cs=[s for s in m['segs'].values() if s['cls']=='CODE']+m['comdats']
        sg=max(cs,key=lambda s:len(s['data'])); d,mk=sg['data'],sg['mask']; self.n=n=len(d)
        dd=open(obj,'rb').read(); i=0; pubs=[]
        while i<len(dd):
            t=dd[i]; L=struct.unpack_from('<H',dd,i+1)[0]; b=dd[i+3:i+2+L]
            if t in (0x90,0x91,0xB6,0xB7):
                j=1 if b[0]<0x80 else 2; j+=1 if b[j]<0x80 else 2
                while j<len(b):
                    l=b[j]; nm=b[j+1:j+1+l].decode('latin1'); j+=1+l
                    off=struct.unpack_from('<I' if t&1 else '<H',b,j)[0]; j+=4 if t&1 else 2; j+=1 if b[j]<0x80 else 2
                    if off<n: pubs.append((off,nm))
            i+=3+L
        self.pubs=pubs=sorted(set(pubs)); self.offs=sorted(set(o for o,_ in pubs))
        self.FUN=sorted(set(FUN0)|{int(sym(nm)[2:],16) for _,nm in pubs if re.match(r'f_[0-9a-f]{6}$',sym(nm))})
        self.byoff={}
        for o,nm in pubs: self.byoff.setdefault(o,sym(nm))
        a=bytearray(d)
        for k in range(n):
            if mk[k]: a[k]=0
        self.a=a; self.extra=[]; self.fkt={}   # fkt[ad]=(of,on,an)
        for k,(of,nm) in enumerate(pubs):
            if k+1<len(pubs) and pubs[k+1][0]==of: continue
            on=self.offs[self.offs.index(of)+1] if self.offs.index(of)+1<len(self.offs) else n
            s=sym(nm)
            if not re.match(r'f_[0-9a-f]{6}$',s): self.extra.append((of,s,on-of)); continue
            ad=int(s[2:],16); ko=bisect.bisect_right(self.FUN,ad); an=self.FUN[ko] if ko<len(self.FUN) else ad+(on-of)
            self.fkt[ad]=(of,on,an)
    def res_o(self,ad):
        k=bisect.bisect_right(self.FUN,ad)-1
        return ('f_%06x'%self.FUN[k]+('' if self.FUN[k]==ad else '+%x'%(ad-self.FUN[k]))) if k>=0 else '?%06x'%ad
    def res_a(self,of):
        k=bisect.bisect_right(self.offs,of)-1
        return (self.byoff[self.offs[k]]+('' if self.offs[k]==of else '+%x'%(of-self.offs[k]))) if k>=0 else '?%x'%of
    def funktion(self,ad):
        """-> dict(ad,so,sn,nd,gl,status,O,A): Vergleich einer Funktion wie fstand.py (O = Original normiert, A = unsere)."""
        of,on,an=self.fkt[ad]
        if ad<B or an-B>len(ORG): return dict(ad=ad,so=0,sn=on-of,nd=None,gl=False,status='AUSSERHALB',O=[],A=[])
        A,AA=dis(self.a[of:on],of,self.res_a,True); O,OA=dis(ORG[ad-B:an-B],ad,self.res_o)
        O2=[re.sub(r'^(call|j\w+) \S+$',r'\1 EXT',x) if y.endswith(' EXT') and x.split()[0]==y.split()[0] else x for x,y in zip(O,A)]+O[len(A):]
        W=lambda L:[re.sub(r'^(call|jmp) (?!\+)\S+$',r'\1 *',x) for x in L]
        sm=difflib.SequenceMatcher(None,W(O2),W(A),autojunk=False); nd=sum(max(i2-i1,j2-j1) for tg,i1,i2,j1,j2 in sm.get_opcodes() if tg!='equal')
        if on==self.n and on-of<an-ad and A==O2[:len(A)] and all(x in FILL_O for x in O2[len(A):]): O2=O2[:len(A)]; an=ad+(on-of)
        gl=(an-ad==on-of) and A==O2
        if not gl and PAD:
            Ak,ga=kern(A,AA,on-of); Ok,go=kern(O2[:len(OA)],OA,an-ad); gl=(Ak==Ok and ga==go)
        return dict(ad=ad,so=an-ad,sn=on-of,nd=nd,gl=gl,status='GLEICH' if gl else f'{nd} Befehle',O=O2,A=A)
    def stand(self,nur=None):
        """Alle Funktionen (oder nur die Adressen in nur) -> {ad: dict}; dazu FEHLT-Zeilen (nd None)."""
        rows={}
        for ad in sorted(self.fkt):
            if nur is None or ad in nur: rows[ad]=self.funktion(ad)
        if nur is None:
            seen=set(self.fkt); hi=max(list(self.fkt)+[self.lo]); lo=min([a for a in self.fkt if a>=self.lo]+[hi]); ko=bisect.bisect_left(self.FUN,lo)
            for ad in self.FUN[ko:]:
                if ad>hi: break
                if ad not in seen:
                    k2=bisect.bisect_right(self.FUN,ad); an=self.FUN[k2] if k2<len(self.FUN) else ad
                    rows[ad]=dict(ad=ad,so=an-ad,sn=0,nd=None,gl=False,status='FEHLT',O=[],A=[])
        return rows
def hunks(f):
    """Diff-Hunks einer Funktion: [(tag, O-Zeilen, A-Zeilen, pos)] mit pos = Anteil (0..1) der Stelle in der Funktion."""
    O,A=f['O'],f['A']; W=lambda L:[re.sub(r'^(call|jmp) (?!\+)\S+$',r'\1 *',x) for x in L]
    sm=difflib.SequenceMatcher(None,W(O),W(A),autojunk=False); out=[]
    for tg,i1,i2,j1,j2 in sm.get_opcodes():
        if tg!='equal': out.append((tg,[norm(x) for x in O[i1:i2]],[norm(x) for x in A[j1:j2]],(i1/max(1,len(O)))))
    return out
def norm(s): return re.sub(r'\s+',' ',s.strip())
def kurz(rows): 
    g=sum(1 for r in rows.values() if r['gl']); return g,len(rows),sum(r['so'] for r in rows.values() if r['gl']),sum(r['so'] for r in rows.values())
def text(rows,extra=()):
    L=[f"{r['ad']:06X} {r['so']:4d}/{r['sn']:<4d} {r['status']}" for r in sorted(rows.values(),key=lambda r:r['ad'])]
    for of,s,sz in extra: L.append(f'EXTRA  {s} {sz} B @+{of:x}')
    g,n,bg,bt=kurz(rows); nah=sum(1 for r in rows.values() if r['nd'] is not None and 0<r['nd']<=10 or (r['nd']==0 and not r['gl']))
    L.append(f'{g}/{n} GLEICH, Bytes {bg}/{bt}, Fast-Treffer(<=10 Bef) {nah}, EXTRA {len(extra)}'); return '\n'.join(L)
if __name__=='__main__':
    e=Einheit(sys.argv[1],int(sys.argv[2],16)); rows=e.stand()
    if len(sys.argv)>3:
        f=rows[int(sys.argv[3],16)]
        for l in difflib.unified_diff(f['O'],f['A'],'original','neu',n=2,lineterm=''): print(l)
    else: print(text(rows,e.extra))
