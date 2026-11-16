# demo_zuordnung.py - Funktionen der target-Demo (unoptimiert uebersetzte Demo-/Debug-Fassung, falls vorhanden) den Funktionen unserer target.EXE zuordnen
# (worker, 24.10.2026). Die Demo zeigt Anweisungsreihenfolge, Lokale und Typen im Klartext. Merkmale je Funktion: Strings, auf die sie
# zeigt, und auffaellige Konstanten (keine Adressen); Gewichtung idf, Zuordnung ueber gewichtetes Jaccard mit Abstand zum Zweitbesten,
# danach Ausbreitung ueber Aufrufziele (gleiche Aufruffolge -> Aufgerufene paaren). 0 Tokens.
# Aufruf: python3 demo_zuordnung.py [--target DUMP FLAT] [--demo DUMP FLAT] -> meta/demo_mapping.tsv
import os,re,sys,glob,math,bisect,collections,struct,subprocess
Q6=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..')); P2=PC.resolve_path('logs_dir', _CFG)
H=os.path.expanduser('~'); H=H+'/target' if os.path.isdir(H+'/target/gw') else H
def arg(n,d):
    return sys.argv[sys.argv.index(n)+1:sys.argv.index(n)+3] if n in sys.argv else d
def flat(exe,ziel):   # LE-Abbild mit 32-Bit-Fixups, Code ab 0x10000 (wie target_flat.bin)
    if os.path.exists(ziel): return
    os.environ['TARGET_EXE']=exe; sys.path.insert(0,Q6+'/Werkzeuge/phase4')
    import importlib, le; importlib.reload(le)
    top=max(o['base']+o['vsize'] for o in le.objs[:2]); f=bytearray(top-0x10000)
    f[le.CB-0x10000:le.CB-0x10000+len(le.CODE)]=le.CODE; f[le.DB-0x10000:le.DB-0x10000+len(le.DATA)]=le.DATA
    for a,t,g in le.fixups:
        if t==7 and a-0x10000+4<=len(f): struct.pack_into('<I',f,a-0x10000,g)
    open(ziel,'wb').write(f)
def dump(fl,ziel):
    if not os.path.exists(ziel): open(ziel,'w').write(subprocess.run(['objdump','-D','-b','binary','-mi386','-Mintel','--no-show-raw-insn','--adjust-vma=0x10000',fl],capture_output=True,text=True).stdout)
RD,RF=arg('--target',[H+'/tmp/target_objdump.txt',H+'/gw/target_flat.bin'])
DD,DF=arg('--demo',[H+'/tmp/demo_objdump.txt',H+'/tmp/demo_flat.bin'])
os.makedirs(H+'/tmp',exist_ok=True)
flat(os.environ.get('DEMO_EXE', Q6+'/Original/Demo/DEMO.EXE'),DF); dump(DF,DD); dump(RF,RD)
def lade(d):
    ins=[]
    for l in open(d,errors='replace'):
        m=re.match(r'\s*([0-9a-f]+):\s+(\S+)\s*(.*)',l)
        if m: ins.append((int(m.group(1),16),m.group(2),m.group(3)))
    return ins
def bereiche(fl):
    b=open(fl,'rb').read(); return b
RI=lade(RD); DI=lade(DD); RB=open(RF,'rb').read(); DB=open(DF,'rb').read()
# Code-/Datengrenzen aus den LE-Objekten: Code 0x10000..CODE_END, Daten danach
def grenzen(fl_bytes,datenbasis): return (0x10000,datenbasis,datenbasis,0x10000+len(fl_bytes))
RG=grenzen(RB,0x1a0000); DG=grenzen(DB,0x1b0000)
def text_an(b,a):
    o=a-0x10000
    if o<0 or o>=len(b): return None
    e=b.find(b'\0',o,o+200)
    if e<0 or e-o<4: return None
    s=b[o:e]
    if all(32<=c<127 or c in (0xe4,0xf6,0xfc,0xc4,0xd6,0xdc,0xdf,0x84,0x94,0x81,0x8e,0x99,0x9a,0xe1) for c in s): return s.decode('latin1')
    return None
ALIAS={}
KLEIN={0xff,0xffff,0xffffffff,0xfffffffe,0x80000000,0x7fffffff,0x100,0x8000,0x7fff}
def merkmale(ins,von,bis,b,G):
    f=collections.Counter(); calls=[]
    i=bisect.bisect_left([x[0] for x in ins],von) if False else None
    return f,calls
# Index der Befehle je Adresse
def schnitte(ins,starts):
    adr=[x[0] for x in ins]; out={}
    for k,s in enumerate(starts):
        e=starts[k+1] if k+1<len(starts) else s+1
        i=bisect.bisect_left(adr,s); j=bisect.bisect_left(adr,e); out[s]=(i,j)
    return out
def fmerk(ins,i,j,b,G):
    f=collections.Counter(); calls=[]
    for k in range(i,j):
        a,op,ar=ins[k]
        for h in re.findall(r'0x[0-9a-f]+',ar):
            v=int(h,16)
            if op=='call' and G[0]<=v<G[1]: calls.append(ALIAS.get(v,v) if G is DG else v); continue
            if G[0]<=v<G[1]: continue
            if G[2]<=v<G[3]:
                t=text_an(b,v)
                if t: f['S:'+t]+=1
                continue
            if v>16 and v not in KLEIN: f['K:%x'%v]+=1
    return f,calls
# Funktionsgrenzen: unsere aus fstand (alle Einheiten), Demo aus Aufrufzielen + Starts nach ret/Fuellbefehlen
RF_={}
for fs in glob.glob(P2+'/live_fstand/*.fstand')+glob.glob(P2+'/zaehlen_fstand/*.fstand'):
    u=os.path.basename(fs)[:-7]
    for l in open(fs,errors='replace'):
        m=re.match(r'([0-9A-F]{6})\s+(\d+)/(\d+)\s+(GLEICH|(\d+) Befehle)',l.strip())
        if m: RF_.setdefault(int(m.group(1),16),(u,int(m.group(2)),0 if m.group(4)=='GLEICH' else int(m.group(5))))
FUELL=re.compile(r'^(lea\s+e(ax|dx|cx|bx|si|di),\[e\2\+0x0\]|nop|mov\s+e(si|di),e\3|xchg\s+ax,ax)')
ds=set()
for a,op,ar in DI:
    if op=='call':
        m=re.match(r'0x([0-9a-f]+)$',ar.strip())
        if m and DG[0]<=int(m.group(1),16)<DG[1]: ds.add(int(m.group(1),16))
for k in range(len(DI)-1):
    if DI[k][1] in ('ret','jmp'):
        q=k+1
        while q<len(DI) and (FUELL.match(DI[q][1]+' '+DI[q][2]) or DI[q][1] in ('nop','int3','(bad)','add')): q+=1
        if q<len(DI) and q>k+1 and DI[q][0]<DG[1] and DI[q][1]=='push': ds.add(DI[q][0])
dstarts=sorted(x for x in ds if x<DG[1]); rstarts=sorted(RF_)
# Start mitten im Prolog (Aufrufziel hinter push ebx/push ecx): mit dem vorigen Start verschmelzen, wenn dazwischen nur push liegen
_da=[x[0] for x in DI]; _m=[]
for s in dstarts:
    if _m:
        i=bisect.bisect_left(_da,_m[-1]); j=bisect.bisect_left(_da,s)
        if j-i<=4 and all(DI[k][1]=='push' for k in range(i,j)): ALIAS[s]=_m[-1]; continue   # j==i: Fuellbytes verschlucken den Prolog-Anfang
    _m.append(s)
dstarts=_m
RS=schnitte(RI,rstarts); DS=schnitte(DI,dstarts)
RM={s:fmerk(RI,*RS[s],RB,RG) for s in rstarts}; DM={s:fmerk(DI,*DS[s],DB,DG) for s in dstarts}
df=collections.Counter()
for f,_ in list(RM.values())+list(DM.values()):
    for k in f: df[k]+=1
N=len(RM)+len(DM); idf={k:math.log(N/v) for k,v in df.items()}
inv=collections.defaultdict(list)
for s,(f,_) in DM.items():
    for k in f:
        if df[k]<=60: inv[k].append(s)
def score(a,b):
    ka=set(a); kb=set(b); g=sum(idf[k]*min(a[k],b[k]) for k in ka&kb); u=sum(idf[k]*max(a.get(k,0),b.get(k,0)) for k in ka|kb)
    return g/u if u else 0
paar={}; meth={}; sc={}
for s,(f,_) in RM.items():
    if sum(idf.get(k,0) for k in f)<6: continue
    kand=collections.Counter()
    for k in f:
        for d in inv.get(k,[]): kand[d]+=idf[k]
    best=sorted(((score(f,DM[d][0]),d) for d,_ in kand.most_common(12)),reverse=True)
    if not best: continue
    b0=best[0]; b1=best[1][0] if len(best)>1 else 0
    if b0[0]>=0.35 and b0[0]-b1>=0.1: paar[s]=b0[1]; meth[s]='merkmal'; sc[s]=b0[0]
# Doppelbelegung einer Demo-Funktion: nur die beste behalten
wer=collections.defaultdict(list)
for s,d in paar.items(): wer[d].append(s)
for d,l in wer.items():
    if len(l)>1:
        l.sort(key=lambda s:-sc[s])
        for s in l[1:]: del paar[s]
# Ausbreitung (mehrere Runden): (1) gleich lange Aufruffolgen positionsweise, (2) Luecken in der Adressfolge (Linker legt Module und ihre
# Funktionen in Quellreihenfolge ab: gleich viele Funktionen zwischen zwei Paaren -> positionsweise), (3) Merkmale + gepaarte Aufgerufene.
def frei(): return set(paar.values())
for runde in range(6):
    neu=0; belegt=frei()
    for s,d in list(paar.items()):
        cr=RM[s][1]; cd=DM[d][1]
        if len(cr)!=len(cd) or not cr: continue
        for x,y in zip(cr,cd):
            if x in RF_ and x not in paar and y in DM and y not in belegt:
                paar[x]=y; meth[x]=f'aufruf{runde+1}'; sc[x]=0; belegt.add(y); neu+=1
    ps=sorted(paar.items()); ri={s:k for k,s in enumerate(rstarts)}; di={d:k for k,d in enumerate(dstarts)}
    for (s1,d1),(s2,d2) in zip(ps,ps[1:]):
        if d2<=d1: continue
        a,b=ri[s1],ri[s2]; c,e=di[d1],di[d2]
        if 0<b-a-1==e-c-1<=8:
            for k in range(1,b-a):
                x=rstarts[a+k]; y=dstarts[c+k]
                if x not in paar and y not in belegt: paar[x]=y; meth[x]=f'luecke{runde+1}'; sc[x]=0; belegt.add(y); neu+=1
    # Merkmale um gepaarte Aufgerufene ergaenzen
    rueck={v:k for k,v in paar.items()}
    for s,(f,cl) in RM.items():
        for x in cl:
            if x in paar: f['C:%x'%paar[x]]=1
    for d,(f,cl) in DM.items():
        for y in cl:
            if y in rueck: f['C:%x'%y]=1
    for k in list(df):
        if k.startswith('C:'): del df[k]
    for f,_ in list(RM.values())+list(DM.values()):
        for k in f:
            if k.startswith('C:'): df[k]+=1
    idf.update({k:math.log(N/v) for k,v in df.items() if k.startswith('C:')})
    inv=collections.defaultdict(list)
    for d,(f,_) in DM.items():
        if d in belegt: continue
        for k in f:
            if df[k]<=60: inv[k].append(d)
    for s,(f,_) in RM.items():
        if s in paar or sum(idf.get(k,0) for k in f)<6: continue
        kand=collections.Counter()
        for k in f:
            for d in inv.get(k,[]): kand[d]+=idf[k]
        best=sorted(((score(f,DM[d][0]),d) for d,_ in kand.most_common(12)),reverse=True)
        if best and best[0][0]>=0.35 and best[0][0]-(best[1][0] if len(best)>1 else 0)>=0.1 and best[0][1] not in belegt:
            paar[s]=best[0][1]; meth[s]=f'merkmal{runde+2}'; sc[s]=best[0][0]; belegt.add(best[0][1]); neu+=1
    if not neu: break
dende={d:(dstarts[k+1] if k+1<len(dstarts) else d+1) for k,d in enumerate(dstarts)}
out=open(sys.argv[sys.argv.index('--aus')+1] if '--aus' in sys.argv else P2+'/demo_zuordnung.tsv','w'); out.write('einheit\tfkt\tbytes\trest\tdemo_adr\tdemo_befehle\tmethode\tscore\tdemo_ende\taufrufe_r_d\n')
for s in sorted(paar):
    u,by,re_=RF_[s]; d=paar[s]; out.write(f'{u}\tf_{s:06x}\t{by}\t{re_}\t{d:06x}\t{DS[d][1]-DS[d][0]}\t{meth[s]}\t{sc[s]:.2f}\t{dende[d]:06x}\t{len(RM[s][1])}/{len(DM[d][1])}\n')
out.close()
offen=[s for s in RF_ if RF_[s][2]>0]; offen_b=sum(RF_[s][1] for s in offen); ged=[s for s in offen if s in paar]
print(f'Demo-Funktionen {len(dstarts)}, unsere {len(RF_)}; zugeordnet {len(paar)} (Merkmal {sum(1 for m in meth.values() if m=="merkmal")}, Aufruf {sum(1 for m in meth.values() if m!="merkmal")})')
print(f'offen: {len(offen)} Fkt / {offen_b} B, davon mit Demo-Partner {len(ged)} Fkt / {sum(RF_[s][1] for s in ged)} B')
