# vmasch.py NAME VA [MAX] [OPTIONEN] - Variantenmaschine (Phase 4, 21.10.2026)
# Vorlage $HOME/var/NAME.VT: Quelltext mit Alternativen
#   in einer Zeile:  {{A:text1##text2##text3}}
#   als Block:       //?A  (Zeile)  ... Alternative 1 ...  //|  ... Alternative 2 ...  //.
# Gleicher Name = gleiche Wahl an allen Stellen. Alle Kombinationen (hoechstens MAX, Standard 40) werden in EINEM DOSBox-Lauf
# uebersetzt (Endmarke FERTIG.TXT, Fehler einer Variante stoppen die anderen nicht) und mit ccmp.py gegen VA verglichen.
import sys,os,re,itertools,subprocess,time,signal
H=os.environ['HOME']; CTN=os.environ.get('VMCT','ct'); CT=f'{H}/target/{CTN}'; VD=os.environ.get('VMVAR',f'{H}/var'); os.makedirs(CT,exist_ok=True)
NAME,VA=sys.argv[1],sys.argv[2]; MAX=int(sys.argv[3]) if len(sys.argv)>3 else 40
OPT=sys.argv[4] if len(sys.argv)>4 else '-4r -oneatx -zp1 -s'
T=open(f'{VD}/{NAME}.VT').read()
dims={}
for m in re.finditer(r'//\?(\w+)[^\n]*\n(.*?)//\.[^\n]*\n',T,re.S): dims.setdefault(m.group(1),re.split(r'//\|[^\n]*\n',m.group(2)))
INNER=re.compile(r'\{\{(\w+):([^{}]*?)\}\}',re.S)
t=T
while INNER.search(t):
    for m in INNER.finditer(t): dims.setdefault(m.group(1),m.group(2).split('##'))
    t=INNER.sub('X',t)
names=list(dims); combos=list(itertools.product(*[range(len(dims[n])) for n in names]))
print(f'Stellen {len(names)} ({", ".join(f"{n}:{len(dims[n])}" for n in names)}), Kombinationen {len(combos)}, uebersetzt {min(len(combos),MAX)}')
import random
if len(combos)>MAX: random.seed(1); combos=[combos[0]]+random.sample(combos[1:],MAX-1)
def render(c):
    ch=dict(zip(names,c))
    t=re.sub(r'//\?(\w+)[^\n]*\n(.*?)//\.[^\n]*\n',lambda m: re.split(r'//\|[^\n]*\n',m.group(2))[ch[m.group(1)]],T,flags=re.S)
    while INNER.search(t): t=INNER.sub(lambda m: m.group(2).split('##')[ch[m.group(1)]],t)
    return t
for f in os.listdir(CT):
    if re.match(r'V\d{3}\.(CPP|OBJ)$',f) or f in ('FERTIG.TXT','E.TXT'): os.remove(f'{CT}/{f}')
bat='@echo off\r\nset WATCOM=C:\\\r\nset PATH=C:\\WB\r\nset INCLUDE=C:\\WC106\\H\r\n'
for k,c in enumerate(combos):
    open(f'{CT}/V{k:03d}.CPP','w',newline='\r\n').write(render(c)); bat+=f'wpp386 {OPT} -zq V{k:03d}.CPP >> E.TXT\r\n'
bat+='echo fertig > FERTIG.TXT\r\n'; open(f'{CT}/GO.BAT','w',newline='').write(bat)
t0=time.time(); env=dict(os.environ,DOSTIMEOUT='600')
p=subprocess.Popen(['bash',f'{H}/sws/dosrun.sh',CTN,'GO.BAT'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,start_new_session=True)
while time.time()-t0<int(os.environ.get('VMZEIT','150')) and not os.path.exists(f'{CT}/FERTIG.TXT'): time.sleep(1)
time.sleep(1); os.killpg(p.pid,signal.SIGKILL)
print(f'DOSBox {time.time()-t0:.0f} s')
sys.path.insert(0,f'{H}/gw'); import omf,difflib
os.environ.setdefault('TARGET_EXE',f'{H}/target.exe'); import le
img=open(f'{H}/gw/target_flat.bin','rb').read(); va=int(VA,16)
def dis(buf):
    open(f'{H}/tmp/vm_{CTN}.bin','wb').write(bytes(buf))
    o=subprocess.run(['objdump','-D','-b','binary','-mi386','-Mintel','--no-show-raw-insn',f'{H}/tmp/vm_{CTN}.bin'],capture_output=True,text=True).stdout
    r=[]
    for l in o.splitlines():
        if l[:1]!=' ' or ':' not in l: continue
        x=l.split('\t',1)[-1].strip(); x=re.sub(r'^(call|j\w+)\s+0x[0-9a-f]+$',r'\1',x); r.append(x)
    return r
L0=2000; ob=bytearray(img[va-0x10000:va-0x10000+L0]); SZ={7:4,5:2,6:6}
for s_,t_,g_ in le.fixups:
    if va-8<=s_<va+L0:
        for q in range(SZ.get(t_,4)):
            if 0<=s_-va+q<L0: ob[s_-va+q]=0

def groessen(obj):
    """Groesse je Funktion f_<Adresse>: OBJ-Abstaende gegen Originaladressen (Publics und lokale Publics)."""
    import struct
    d=open(obj,'rb').read(); i=0; pubs=[]
    while i<len(d):
        t=d[i]; n=struct.unpack_from('<H',d,i+1)[0]; b=d[i+3:i+2+n]
        if t in (0x90,0x91,0xB6,0xB7):
            j=1 if b[0]<0x80 else 2; j+=1 if b[j]<0x80 else 2
            while j<len(b):
                L=b[j]; nm=b[j+1:j+1+L].decode('latin1'); j+=1+L
                off=struct.unpack_from('<I' if t&1 else '<H',b,j)[0]; j+=4 if t&1 else 2; j+=1 if b[j]<0x80 else 2
                mm=re.search(r'\bW?\??f_([0-9a-f]{6})\b',nm)
                if mm: pubs.append((off,int(mm.group(1),16)))
        i+=3+n
    pubs=sorted(set(pubs)); out=[]
    for k in range(len(pubs)-1):
        (o1,a1),(o2,a2)=pubs[k],pubs[k+1]
        out.append(f'{a1:06X} {a2-a1:4d}/{o2-o1:<4d}{"" if a2-a1==o2-o1 else " <-- "+format(o2-o1-(a2-a1),"+d")}')
    return out
res=[]
for k,c in enumerate(combos):
    o=f'{CT}/V{k:03d}.OBJ'
    if not os.path.exists(o): res.append((10**6,k,c,'nicht uebersetzt')); continue
    m=omf.modules(o)[0]; cs=[s for s in m['segs'].values() if s['cls']=='CODE']+m['comdats']
    sg=max(cs,key=lambda s:len(s['data'])); d,mk=sg['data'],sg['mask']
    nb=sum(1 for i in range(len(d)) if not mk[i] and img[va-0x10000+i]!=d[i])
    a=bytearray(d)
    for i in range(len(d)):
        if mk[i]: a[i]=0
    A=dis(a); O=dis(ob[:len(d)+16])[:len(A)]
    sm=difflib.SequenceMatcher(None,O,A,autojunk=False); nd=sum(max(i2-i1,j2-j1) for tg,i1,i2,j1,j2 in sm.get_opcodes() if tg!='equal')
    res.append((0 if nb==0 else nd,k,c,('GLEICH' if nb==0 else f'{nd} Befehle / {nb} Bytes abweichend')+f' ({len(d)} B)'))
res.sort()
for n,k,c,r in res[:6]: print(f'V{k:03d} {" ".join(f"{a}{b}" for a,b in zip(names,c))}: {r}')
fehl=[x for x in res if x[0]==10**6]
if fehl: print('nicht uebersetzt:',len(fehl)); print(open(f'{CT}/E.TXT',errors='replace').read().replace('\r','')[:300])
g=groessen(f'{CT}/V{res[0][1]:03d}.OBJ') if res[0][0]<10**6 else []
if g: print('Groesse je Funktion (Original/neu):', ' | '.join(g))
b=res[0]; open(f'{VD}/{NAME}_BEST.CPP','w',newline='\r\n').write(render(b[2])); print(f'beste -> var/{NAME}_BEST.CPP (V{b[1]:03d})')
