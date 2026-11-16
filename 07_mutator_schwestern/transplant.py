# transplant.py - Zwillinge mechanisch loesen, ohne Sprachmodell (worker, 24.10.2026). Zu jeder offenen Funktion mit einer
# geloesten Vorlage >= TP_SCHWELLE (aehnlich.tsv): Original-Assembler von Vorlage und Ziel ausrichten (difflib auf normierten Befehlen),
# aus gleichen Befehlspaaren eine Wertetabelle Vorlage->Ziel bauen (Adressen, Aufrufziele, Konstanten), den Vorlagen-Block damit
# umschreiben (d_/f_/Bxxxxxx-Namen; Variante Z auch Zahlen), fehlende Definitionen (#define, struct, typedef, extern, Prototyp,
# #pragma aux) aus der Vorlagen-Einheit mitnehmen, mit Vorlagen-Kopf (V) und mit Ziel-Kopf (K, Parameter umbenannt) uebersetzen.
# Uebernahme nur, wenn das Ziel besser wird und keine Funktion der Einheit schlechter. Schreibt ueber sperre.py nach p3
# (Konflikt -> logs/conflict/transplant/), kreislauf.sh poliert danach mit dem Mutator. 0 Tokens.
# Env: TP_SCHWELLE (0.8), TP_N (alle), TP_PAR (3), TP_VORLAGEN (2 je Ziel), TP_TROCKEN=1 (nur Varianten erzeugen, nicht uebersetzen),
#      TP_DUMP (objdump-Datei), TP_EINHEIT (nur diese Einheit). Log: logs/transplant.tsv
import os,re,sys,glob,subprocess,difflib,collections,bisect,time,threading,queue,shutil,hashlib
Q6=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..')); P2=PC.resolve_path('logs_dir', _CFG)
H=os.path.expanduser('~'); H=H+'/target' if os.path.isdir(H+'/target/gw') else H
E_=os.environ.get; SCHW=float(E_('TP_SCHWELLE','0.8')); NMAX=int(E_('TP_N','100000')); PAR=int(E_('TP_PAR','3'))
NV=int(E_('TP_VORLAGEN','2')); TROCKEN=bool(E_('TP_TROCKEN')); NUR=E_('TP_EINHEIT')
def lies(f):
    try: return open(f,encoding='latin1',errors='replace').read().replace('\r','')
    except Exception: return ''
def quelle(u):
    for d in ('p3','p2','p1'):
        f=os.path.join(PC.resolve_path('src_dir', _CFG), d, f'{u}_P1.CPP')
        if os.path.exists(f): return f
LOT={}
for l in lies(PC.resolve_path('units_tsv', _CFG)).splitlines():
    x=l.split('\t')
    if len(x)>2: LOT.setdefault(x[1],x[2])
# --- Stand und Original-Assembler
fsd=P2+'/live_fstand' if os.path.isdir(P2+'/live_fstand') else P2+'/zaehlen_fstand'
stand={}
for f in glob.glob(fsd+'/*.fstand'):
    u=os.path.basename(f)[:-7]
    for l in lies(f).splitlines():
        m=re.match(r'([0-9A-F]{6})\s+(\d+)/(\d+)\s+(GLEICH|(\d+) Befehle)',l.strip())
        if m: stand[(u,'f_'+m.group(1).lower())]=(int(m.group(2)),0 if m.group(4)=='GLEICH' else int(m.group(5)))
dump=E_('TP_DUMP',H+'/tmp/target_objdump.txt')
if not os.path.exists(dump):
    os.makedirs(os.path.dirname(dump),exist_ok=True)
    open(dump,'w').write(subprocess.run(['objdump','-D','-b','binary','-mi386','-Mintel','--no-show-raw-insn','--adjust-vma=0x10000',H+'/gw/target_flat.bin'],capture_output=True,text=True).stdout)
REG=r'\b(e?[abcd]x|[abcd][lh]|e?[sd]i|e?bp|e?sp)\b'
INS={}
for l in open(dump,errors='replace'):
    m=re.match(r'\s*([0-9a-f]+):\s+(\S+)\s*(.*)',l)
    if m: INS[int(m.group(1),16)]=(m.group(2),m.group(3))
ADR=sorted(INS)
def folge(a,n):
    i=bisect.bisect_left(ADR,a); out=[]
    while i<len(ADR) and ADR[i]<a+n: out.append(INS[ADR[i]]); i+=1
    return out
def normb(op,a): return op+' '+re.sub(r'0x[0-9a-f]+|\b\d+\b','K',re.sub(REG,'R',a))
def konst(a): return [int(x,16) if x.startswith('0x') else int(x) for x in re.findall(r'0x[0-9a-f]+|(?<![\w])\d+(?![\w])',re.sub(REG,'R',a))]
def wertetabelle(kv,kz):
    sv=folge(int(kv[1][2:],16),stand[kv][0]); sz=folge(int(kz[1][2:],16),stand[kz][0])
    M=collections.defaultdict(collections.Counter)
    sm=difflib.SequenceMatcher(None,[normb(*x) for x in sv],[normb(*x) for x in sz],autojunk=False)
    for tag,i1,i2,j1,j2 in sm.get_opcodes():
        if tag!='equal': continue
        for k in range(i2-i1):
            a=konst(sv[i1+k][1]); b=konst(sz[j1+k][1])
            if len(a)==len(b):
                for x,y in zip(a,b): M[x][y]+=1
    T={}
    for x,c in M.items():
        y,n=c.most_common(1)[0]
        if n/sum(c.values())>=0.75: T[x]=(y,n/sum(c.values()))
    return T
# --- Quelltext-Bloecke
def bloecke(t):
    L=t.split('\n'); st=[i for i,l in enumerate(L) if l.startswith('//@ ')]
    return L,st
def block(t,fk):   # bei doppelten //@-Marken (Kopfliste) den Block nehmen, der die Definition enthaelt
    L,st=bloecke(t); erst=None
    for k,i in enumerate(st):
        if L[i].split()[1]==fk:
            e=st[k+1] if k+1<len(st) else len(L)
            if zerlege(L[i:e],fk): return i,e,L
            erst=erst or (i,e,L)
    return erst
def zerlege(zeilen,fk):
    """Block -> (kopfzeile //@, vorspann, signatur, rumpf) oder None. Rumpf bis zur letzten '}' in Spalte 0."""
    s=None
    for i,l in enumerate(zeilen[1:],1):
        if re.match(r'[^\s#/].*\b'+fk+r'\s*\(',l): s=i; break
    if s is None: return None
    txt='\n'.join(zeilen[s:]); b=txt.find('{')
    if b<0: return None
    rumpf=txt[b:]; ende=[m.end() for m in re.finditer(r'(?m)^\}[ \t]*;?[ \t]*$',rumpf)]
    if not ende: return None
    return zeilen[0],zeilen[1:s],txt[:b],rumpf[:ende[-1]]
def params(sig):
    a=sig.find('('); z=sig.rfind(')')
    if a<0 or z<a: return None
    inn=sig[a+1:z].strip()
    if inn in ('','void'): return []
    teile=[]; tiefe=0; cur=''
    for ch in inn:
        if ch in '([': tiefe+=1
        if ch in ')]': tiefe-=1
        if ch==',' and tiefe==0: teile.append(cur); cur=''
        else: cur+=ch
    teile.append(cur); out=[]
    for p in teile:
        if '(' in p or '...' in p: return None
        m=re.search(r'(\w+)\s*(\[[^\]]*\])?\s*(=.*)?$',p.strip())
        if not m or re.fullmatch(r'(int|char|short|long|unsigned|signed|void|float|double)',m.group(1)): return None
        out.append(m.group(1))
    return out
NAMRE=re.compile(r'\b([A-Za-z]{1,3}_?)([0-9A-Fa-f]{6})\b')
def ersetzer(T,fv,fz):
    ak=sorted(x for x in T if 0x10000<=x<0x400000)
    def neu(v):
        if v in T: return T[v][0]
        i=bisect.bisect_right(ak,v)-1
        if i>=0 and v-ak[i]<=64: return T[ak[i]][0]+(v-ak[i])
        return None
    def S(text):
        def r(m):
            h=m.group(2); v=int(h,16)
            if m.group(0)==fv: return fz
            if not (0x10000<=v<0x400000): return m.group(0)
            n=neu(v)
            if n is None: return m.group(0)
            nh=f'{n:06x}'; nh=nh.upper() if h.isupper() else nh if h.islower() else nh
            return m.group(1)+nh
        return NAMRE.sub(r,text)
    def Z(text):   # Zahlen ausserhalb von Strings/Kommentaren
        def r(m):
            s=m.group(0)
            if s.startswith('"') or s.startswith("'") or s.startswith('//') or s.startswith('/*'): return s
            v=int(s,16) if s.lower().startswith('0x') else int(s)
            if v<2 or v not in T or T[v][0]==v: return s
            return hex(T[v][0]) if s.lower().startswith('0x') else str(T[v][0])
        return re.sub(r'"(\\.|[^"\\])*"|\'(\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/|(?<![\w.])(0[xX][0-9a-fA-F]+|\d+)(?![\w.])',r,text,flags=re.S)
    return S,Z
WORT=re.compile(r'\b[A-Za-z_]\w*\b')
def definitionen(tv,vblock_lo,vblock_hi,woerter,ziel_text):
    """Zeilen der Vorlagen-Einheit (ausserhalb des Vorlagen-Blocks), die die gesuchten Woerter definieren; rekursiv 3 Stufen."""
    L=tv.split('\n'); nimm=set(); offen=set(woerter); fertig=set()
    for _ in range(3):
        neu=set()
        for w in offen-fertig:
            fertig.add(w); adrname=bool(NAMRE.fullmatch(w))
            for i,l in enumerate(L):
                if vblock_lo<=i<vblock_hi or w not in l: continue
                if re.match(r'\s*#\s*(define|pragma\s+aux)\s+'+re.escape(w)+r'\b',l):
                    j=i; nimm.add(j)
                    while L[j].rstrip().endswith('\\') and j+1<len(L): j+=1; nimm.add(j)
                elif re.match(r'(struct|class|union|enum)\s+'+re.escape(w)+r'\b[^;]*$',l):
                    j=i; tiefe=0; gesehen=False
                    while j<len(L):
                        nimm.add(j); tiefe+=L[j].count('{')-L[j].count('}'); gesehen|=('{' in L[j])
                        if gesehen and tiefe<=0 and ';' in L[j]: break
                        j+=1
                elif re.search(r'\b(struct|class|union)\s+'+re.escape(w)+r'\b[^;]*\{.*\}\s*;',l) or re.match(r'typedef\b.*\b'+re.escape(w)+r'\b.*;',l):
                    nimm.add(i)
                elif adrname and re.match(r'[A-Za-z_].*\b'+re.escape(w)+r'\b.*;\s*(//.*)?$',l) and not re.match(r'\s*(return|if|for|while)\b',l):
                    nimm.add(i)
        for i in nimm:
            for w in WORT.findall(L[i]):
                if not re.search(r'\b'+re.escape(w)+r'\b',ziel_text): neu.add(w)
        offen=neu
        if not offen-fertig: break
    return [L[i] for i in sorted(nimm)]
KW={'int','char','short','long','unsigned','signed','void','float','double','const','volatile','struct','class','union','enum'}
def _split(inn):
    teile=[]; tiefe=0; cur=''
    for ch in inn:
        if ch in '([': tiefe+=1
        if ch in ')]': tiefe-=1
        if ch==',' and tiefe==0: teile.append(cur); cur=''
        else: cur+=ch
    teile.append(cur); return [x.strip() for x in teile if x.strip() and x.strip()!='void']
def _ptyp(p):   # 'V32 *p1' -> ('V32 *','p1'), 'int' -> ('int',None)
    m=re.match(r'^(.*?[\s\*&])(\w+)\s*(\[[^\]]*\])?$',p)
    if m and m.group(2) not in KW and m.group(1).strip(): return m.group(1).strip()+(m.group(3) or ''),m.group(2)
    return p,None
DEFRE=lambda n: re.compile(r'^([^\s#/][^;{}()]*?)\b'+n+r'\s*\(([^;{}]*)\)\s*\{?\s*$')
DECRE=lambda n: re.compile(r'^(extern\s+)?((?!return\b)[A-Za-z_][^;{}()=]*?)\b'+n+r'\s*\(([^;{}]*)\)\s*;')   # nur Deklarationen in Spalte 0, keine Aufrufe
def signatur(t,n):   # (rueckgabe, [param-strings]) aus Definition (bevorzugt) oder Deklaration
    d=None
    for l in t.split('\n'):
        m=DEFRE(n).match(l)
        if m and not re.match(r'\s*(return|if|for|while|else)\b',l): return m.group(1).strip(),_split(m.group(2))
        if d is None:
            m=DECRE(n).match(l)
            if m: d=(m.group(2).strip(),_split(m.group(3)))
    return d
REP={'E341','E473','E385','E056','E333','E003'}
def reparatur(j):   # worker (target/Claude 25.10.): Prototyp-Fehler -> Signatur der gerufenen Funktion minimal an die Vorlage anpassen
    L=j['text'].split('\n'); codes={}
    for e in j.get('fehler_alle',[]):
        m=re.match(r'(\d+): .*?\b(E\d{3})\b',e)
        if not m or m.group(2) not in REP: continue
        zl=L[int(m.group(1))-1] if 0<int(m.group(1))<=len(L) else ''
        for x in re.findall(r'\b(f_[0-9a-f]{6})\b',zl+' '+e):
            if x in j['sig'] and x!=j['fk']: codes.setdefault(x,set()).add(m.group(2))
    neu=0
    for X,cs in sorted(codes.items()):
        rt,pt=j['sig'][X]; tp=[_ptyp(x) for x in pt]
        anz='E341' in cs; typ=False; ret=bool(cs&{'E385','E003'})   # Typfehler (E473/E333) -> Cast am Aufruf, s. unten
        if not (anz or ret): continue
        def neue(zp,rz):   # zp: Ziel-Parameter [(typ,name)], rz: Ziel-Rueckgabe
            if anz and len(tp)<len(zp): return None
            n=[]
            for k in range(max(len(zp),len(tp) if (anz or typ) else len(zp))):
                ty=(tp[k][0] if (typ or k>=len(zp)) and k<len(tp) else zp[k][0]); nm=zp[k][1] if k<len(zp) else (tp[k][1] or f'tp{k}_')
                n.append((ty,nm,k>=len(zp)))   # 3. Feld: neu angehaengter Parameter
            return n,(rt if ret else rz)
        hat_decl=any(DECRE(X).match(l) for l in L)   # Default-Argument (= 0) fuer neue Parameter nur an einer Stelle (Deklaration, sonst Definition), damit andere Aufrufer weiter uebersetzen
        for i,l in enumerate(L):
            m=DEFRE(X).match(l)
            if m and not re.match(r'\s*(return|if|for|while|else)\b',l):
                r_=neue([_ptyp(x) for x in _split(m.group(2))],m.group(1).strip())
                if not r_: continue
                ps,rr=r_; L[i]=f"{rr} {X}({', '.join((f'{ty} {nm}' if nm else ty)+(' = 0' if nw and not hat_decl else '') for ty,nm,nw in ps) or 'void'})"+(' {' if l.rstrip().endswith('{') else ''); neu+=1; continue
            m=DECRE(X).match(l)
            if m:
                r_=neue([_ptyp(x) for x in _split(m.group(3))],m.group(2).strip())
                if not r_: continue
                ps,rr=r_; L[i]=(m.group(1) or '')+f"{rr} {X}({', '.join(ty+(' = 0' if nw else '') for ty,nm,nw in ps) or 'void'});"; neu+=1
    # E473/E333 im transplantierten Block: Argumente auf die Parametertypen des ZIEL-Prototyps casten (Zeiger-Casts erzeugen keinen Code)
    for e in j.get('fehler_alle',[]):
        m=re.match(r'(\d+): .*?\b(E473|E333)\b',e)
        if not m: continue
        i=int(m.group(1))-1
        if not 0<=i<len(L): continue
        for X in set(re.findall(r'\b(f_[0-9a-f]{6})\s*\(',L[i])):
            sg=signatur(j['text'],X)
            if not sg or X==j['fk']: continue
            zt=[_ptyp(x)[0] for x in sg[1]]
            q=L[i].find(X+'('); a0=q+len(X)+1; tiefe=1; k=a0
            while k<len(L[i]) and tiefe:
                tiefe+=(L[i][k]=='(')-(L[i][k]==')'); k+=1
            args=_split(L[i][a0:k-1])
            if len(args)!=len(zt) or not args: continue
            neu_args=', '.join(f'({t})({x})' for t,x in zip(zt,args))
            L[i]=L[i][:a0]+neu_args+L[i][k-1:]; neu+=1
    return '\n'.join(L) if neu else None
def varianten(u,fk,vu,vf):
    tz=lies(quelle(u)); tv=lies(quelle(vu))
    bz=block(tz,fk); bv=block(tv,vf)
    if not bz or not bv: return [],'Block fehlt',{}
    iz,ez,LZ=bz; iv,ev,LV=bv
    dz=zerlege(LZ[iz:ez],fk); dv=zerlege(LV[iv:ev],vf)
    if not dz or not dv: return [],'Block nicht zerlegbar',{}
    T=wertetabelle((vu,vf),(u,fk)); S,Z=ersetzer(T,vf,fk)
    rest_z='\n'.join(LZ[:iz]+LZ[ez:])
    woerter={S(w) for w in WORT.findall('\n'.join(dv[1])+dv[2]+dv[3])}
    fehlend={w for w in woerter if not re.search(r'\b'+re.escape(w)+r'\b',rest_z)}
    # Rueckabbildung neuer Name -> Vorlagenname fuer die Definitionssuche
    rueck={}
    for w in WORT.findall('\n'.join(dv[1])+dv[2]+dv[3]): rueck.setdefault(S(w),w)
    such={rueck.get(w,w) for w in fehlend}
    # #pragma aux der Vorlage fuer aufgerufene Funktionen, die im Ziel kein pragma haben
    for w in WORT.findall(dv[3]):
        if re.search(r'^\s*#\s*pragma\s+aux\s+'+re.escape(w)+r'\b',tv,re.M) and not re.search(r'^\s*#\s*pragma\s+aux\s+'+re.escape(S(w))+r'\b',tz,re.M): such.add(w)
    defs=definitionen(tv,iv,ev,such,rest_z)
    out=[]
    pz=params(dz[2]); pv=params(dv[2])
    for zn,F in (('A',S),('Z',lambda t:Z(S(t)))):
        dl=[F(l) for l in defs]; dl=[l for l in dl if l.strip() and l not in rest_z.split('\n')]
        vorsp=[l for l in (F(l) for l in dv[1]) if l.strip() and l not in rest_z.split('\n') and l not in dl]
        kern=[dz[0]]+dz[1]+dl+vorsp
        out.append(('V'+zn,kern+[F(dv[2])+F(dv[3])]))
        if pz is not None and pv is not None and len(pz)==len(pv):
            mp=dict(zip(pv,pz)); rb=F(dv[3])
            if mp: rb=re.sub(r'\b('+'|'.join(map(re.escape,mp))+r')\b',lambda m:mp[m.group(1)],rb)
            out.append(('K'+zn,kern+[dz[2]+rb]))
    # W: Deklarationen der Vorlage gewinnen (extern/Prototyp des Ziels durch die umbenannte Vorlagenzeile ersetzen)
    def decl(l,w): return re.match(r'[A-Za-z_].*\b'+re.escape(w)+r'\s*(\(|\[|;|=)',l) and re.search(r';\s*(//.*)?$',l) and not re.match(r'\s*(return|if|for|while|else|do|switch|#)\b',l)
    LVa=LV[:iv]+LV[ev:]; tausch={}
    for w0 in set(WORT.findall(dv[2]+dv[3])):
        if not NAMRE.fullmatch(w0): continue
        w1=S(w0); lv=[l for l in LVa if decl(l,w0)]
        if len(lv)!=1: continue
        for i,l in enumerate(LZ):
            if not (iz<=i<ez) and decl(l,w1) and S(lv[0])!=l: tausch[i]=S(lv[0])
    LZw=[tausch.get(i,l) for i,l in enumerate(LZ)]
    texte=[]; seen=set()
    for n,zeilen in out:
        for w,LL in (('',LZ),('W',LZw)):
            if w and not tausch: continue
            t='\n'.join(LL[:iz]+zeilen+['']+LL[ez:])
            if t in seen: continue
            seen.add(t); texte.append((n+w,t))
    sigs={}
    for w0 in set(re.findall(r'\bf_[0-9a-f]{6}\b',dv[3])):
        sg=signatur(tv,w0)
        if sg: sigs[S(w0)]=(S(sg[0]),[S(x) for x in sg[1]])
    return texte,f'{len(T)} Werte, {len(defs)} Def., {len(tausch)} Tausch',sigs
# --- Ziele
AE={}
for l in lies(P2+'/aehnlich.tsv').splitlines()[1:]:
    x=l.split('\t')
    if len(x)>=7 and x[6]: AE[(x[0],x[1])]=[(x[i],x[i+1],float(x[i+2])) for i in (4,7,10) if len(x)>i+2 and x[i]]
erledigt=set()
LOG=P2+'/transplant.tsv'
for l in lies(LOG).splitlines()[1:]:
    x=l.split('\t')
    if len(x)>8 and not x[8].startswith(('nicht uebersetzt','Basis fehlt')): erledigt.add((x[0],x[1],x[2],x[3]))   # worker: gescheiterte Uebersetzungen erneut versuchen (Prototyp-Reparatur)
ziele=[]
for (u,fk),v in sorted(AE.items(),key=lambda kv:-stand.get(kv[0],(0,0))[0]):
    if NUR and u!=NUR: continue
    if stand.get((u,fk),(0,0))[1]==0 or u not in LOT or not quelle(u): continue
    vl=[(vu,vf,r) for vu,vf,r in v if r>=SCHW and stand.get((vu,vf),(0,1))[1]==0 and quelle(vu) and (u,fk,vu,vf) not in erledigt][:NV]
    if vl: ziele.append((u,fk,vl))
    if len(ziele)>=NMAX: break
jobs=[]; info={}
for u,fk,vl in ziele:
    for vu,vf,r in vl:
        try: tx,inf,sg=varianten(u,fk,vu,vf)
        except Exception as ex: tx,inf,sg=[],f'Fehler {ex}',{}
        info[(u,fk,vu,vf)]=(r,inf)
        for n,t in tx: jobs.append(dict(u=u,fk=fk,vu=vu,vf=vf,r=r,var=n,text=t,sig=sg))
eh=sorted({j['u'] for j in jobs})
print(f'Transplantat: {len(ziele)} Ziele, {len(jobs)} Varianten in {len(eh)} Einheiten (Schwelle {SCHW})',flush=True)
if TROCKEN:
    d=E_('TP_TROCKEN_DIR',P2+'/transplant_trocken'); shutil.rmtree(d,ignore_errors=True); os.makedirs(d,exist_ok=True)
    for j in jobs: open(f"{d}/{j['u']}_{j['fk']}_{j['vu']}_{j['vf']}_{j['var']}.CPP",'w',encoding='latin1',errors='replace').write(j['text'])
    for k,(r,inf) in info.items(): print(*k,r,inf)
    sys.exit(0)
# --- uebersetzen und messen
sys.path.insert(0,H+'/gw'); import bau
sys.path.insert(0,Q6+'/Werkzeuge/phase4'); import sperre
basis={u:lies(quelle(u)) for u in eh}; basis_md5={u:sperre.lese_md5(os.path.join(PC.resolve_path('src_p3_dir', _CFG), f'{u}_P1.CPP')) for u in eh}
alle=[dict(u=u,var='BASIS',text=basis[u]) for u in eh]+jobs
def optcc(t):
    m=re.search(r'^// OPT (.*)$',t,re.M); return (m.group(1).strip() if m else '-4r -oneatx -zp1 -s','wcc386' if re.search(r'^// CC wcc386',t,re.M) else 'wpp386')
def messe(obj,lo):
    txt=subprocess.run(['python3',H+'/gw/fstand.py',obj,lo],capture_output=True,text=True,errors='replace').stdout; d={}
    for l in txt.splitlines():
        m=re.match(r'([0-9A-F]{6})\s+\d+/\d+\s+(GLEICH|(\d+) Befehle|FEHLT)',l.strip())
        if m: d['f_'+m.group(1).lower()]=0 if m.group(2)=='GLEICH' else int(m.group(3)) if m.group(3) else 99999
    return d,txt
def lauf(liste):
    gr=collections.defaultdict(list)
    for j in liste: gr[optcc(j['text'])].append(j)
    pakete=[(oc,v[i:i+30]) for oc,v in gr.items() for i in range(0,len(v),30)]
    q=queue.Queue(); [q.put(p) for p in pakete]
    ges=len(liste); fort=[0,time.time()]; lk=threading.Lock()   # worker: Fortschrittsanzeige
    def arbeiter(s):
        ctn=f'ct_tp{s}'; os.makedirs(f'{H}/target/{ctn}',exist_ok=True)
        for f in glob.glob(os.path.join(PC.resolve_path('src_dir', _CFG), '*.H')): shutil.copy(f,f'{H}/target/{ctn}/')
        while True:
            try: (o,cc),p=q.get_nowait()
            except queue.Empty: return
            objs,fe,dt,ok=bau.uebersetzen([j['text'] for j in p],ctn,o,cc)
            for k_,(j,ob) in enumerate(zip(p,objs)):
                j['rest'],j['fst']=messe(ob,LOT[j['u']]) if ob else ({},'')
                if not ob: j['fehler']=(fe.get(k_) or ['kein OBJ'])[0][:160]; j['fehler_alle']=fe.get(k_) or []   # worker: Compilerfehler mitloggen
            with lk:
                fort[0]+=len(p); f_=fort[0]; dt_=time.time()-fort[1]
                print(f'  {f_}/{ges} Varianten ({100*f_//max(1,ges)} %), {int(dt_)} s, noch ~{int(dt_/max(1,f_)*(ges-f_))} s',flush=True)
    th=[threading.Thread(target=arbeiter,args=(s,)) for s in range(PAR)]; [t.start() for t in th]; [t.join() for t in th]
t0=time.time(); lauf(alle)
rep=[]   # worker: Prototyp-Reparatur fuer Varianten, die an Signatur-Fehlern gescheitert sind
for j in jobs:
    if 'fehler_alle' in j and j.get('sig'):
        t=reparatur(j)
        if t: rep.append(dict(j,var=j['var']+'P',text=t,fehler_alle=[]))
if rep:
    print(f'Prototyp-Reparatur: {len(rep)} Varianten neu',flush=True); lauf(rep)
    for j in rep: j.pop('fehler',None) if j.get('rest') else None
    jobs+=rep
B={j['u']:j for j in alle if j['var']=='BASIS'}
if not os.path.exists(LOG): open(LOG,'w').write('einheit\tfkt\tvorlage_einheit\tvorlage_fkt\taehnl\tvariante\trest_vorher\trest_nachher\tstatus\n')
gut=collections.defaultdict(dict)
for k,(r,inf) in info.items():
    u,fk,vu,vf=k; b=B.get(u,{}).get('rest',{})   # worker: Einheit ohne Basis -> 'Basis fehlt' statt Absturz
    if fk not in b:
        open(LOG,'a').write(f'{u}\t{fk}\t{vu}\t{vf}\t{r:.2f}\t-\t-\t-\tBasis fehlt\n'); continue
    best=None
    for j in jobs:
        if (j['u'],j['fk'],j['vu'],j['vf'])!=k or 'rest' not in j: continue
        rr=j['rest']
        if fk in rr and rr[fk]<b[fk] and all(rr.get(x,99999)<=y for x,y in b.items() if x!=fk):
            if best is None or rr[fk]<best['rest'][fk]: best=j
    if best:
        if fk not in gut[u] or best['rest'][fk]<gut[u][fk]['rest'][fk]: gut[u][fk]=best
    st='GLEICH' if best and best['rest'][fk]==0 else 'besser' if best else ('kein' if any('rest' in j and j['rest'] for j in jobs if (j['u'],j['fk'],j['vu'],j['vf'])==k) else 'nicht uebersetzt')
    nach=best['rest'][fk] if best else min([j['rest'].get(fk,99999) for j in jobs if (j['u'],j['fk'],j['vu'],j['vf'])==k and j.get('rest')] or [99999])
    if st=='nicht uebersetzt': st+=': '+'; '.join(sorted({j.get('fehler','?') for j in jobs if (j['u'],j['fk'],j['vu'],j['vf'])==k}))[:300]   # worker
    open(LOG,'a').write(f'{u}\t{fk}\t{vu}\t{vf}\t{r:.2f}\t{best["var"] if best else "-"}\t{b[fk]}\t{nach if nach<99999 else "-"}\t{st}\n')
# --- je Einheit: alle besseren Bloecke zusammen, sonst bester einzelner
komb=[]
for u,d in gut.items():
    if len(d)<2: continue
    t=basis[u]
    for fk,j in sorted(d.items()):
        bz=block(j['text'],fk); i,e,L=bz; neu=L[i:e]
        b0=block(t,fk); i0,e0,L0=b0; t='\n'.join(L0[:i0]+neu+L0[e0:])
    komb.append(dict(u=u,var='KOMB',text=t))
if komb: lauf(komb)
gew=0; anz=0
for u,d in gut.items():
    b=B.get(u,{}).get('rest',{}); kand=[j for j in komb if j['u']==u and j.get('rest')]
    kand=[j for j in kand if all(j['rest'].get(x,99999)<=y for x,y in b.items())]
    w=min(kand+list(d.values()),key=lambda j:sum(j['rest'].get(x,99999) for x in b))
    ok,info_=sperre.schreibe(Q6,u,w['text'],w['fst'],basis_md5[u],'transplant')
    g=sum(b.values())-sum(w['rest'].get(x,0) for x in b); gew+=g; anz+=1
    print(f'{u}: {"p3" if ok else "Konflikt -> "+info_} ({w["var"]}, {g} Befehle weniger)',flush=True)
z=[l.split('\t') for l in lies(LOG).splitlines()[1:]]
print(f'Fertig in {int(time.time()-t0)} s: {anz} Einheiten verbessert, {gew} Befehle weniger. Log gesamt: {sum(1 for x in z if x[8]=="GLEICH")} GLEICH, {sum(1 for x in z if x[8]=="besser")} besser von {len(z)}',flush=True)
