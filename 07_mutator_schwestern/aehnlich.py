# aehnlich.py - zu jeder offenen Funktion die aehnlichsten GELOESTEN Funktionen finden (worker, 24.10.2026; Idee aus der
# Decomp-Szene: aehnliche gematchte Funktionen als C<->ASM-Vorlage mitgeben). Aehnlichkeit = Befehlsfolge (Mnemonics + Operandenart)
# des ORIGINALS, Vorauswahl ueber 3-Gramm-Jaccard, Feinmass difflib-Ratio. 0 Tokens, lokal.
# Aufruf: python3 aehnlich.py [FSTAND_DIR] -> logs/similar.tsv (einheit fkt bytes rest | 3x vorlage_einheit vorlage_fkt aehnlichkeit)
import os,re,sys,glob,subprocess,difflib,collections
Q6=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..'))
H=os.path.expanduser('~'); H=H+'/target' if os.path.isdir(H+'/target/gw') else H
FS=sys.argv[1] if len(sys.argv)>1 else (os.path.join(PC.resolve_path('logs_dir', _CFG), 'live_fstand') if os.path.isdir(os.path.join(PC.resolve_path('logs_dir', _CFG), 'live_fstand')) else os.path.join(PC.resolve_path('logs_dir', _CFG), 'count_fstand'))
import project_config as PC; _CFG=PC.load_config(); img=PC.resolve_path('flat_bin',_CFG); dump=os.path.join(PC.resolve_path('tmp_dir',_CFG,'/tmp'),'target_objdump.txt')
if not os.path.exists(dump):
    os.makedirs(os.path.dirname(dump),exist_ok=True)
    open(dump,'w').write(subprocess.run(['objdump','-D','-b','binary','-mi386','-Mintel','--no-show-raw-insn','--adjust-vma=0x10000',img],capture_output=True,text=True).stdout)
ins={}   # adresse -> normierter Befehl
for l in open(dump,errors='replace'):
    m=re.match(r'\s*([0-9a-f]+):\s+(\S+)\s*(.*)',l)
    if not m: continue
    op=m.group(2); a=m.group(3)
    a=re.sub(r'\b(e?[abcd]x|[abcd][lh]|e?[sd]i|e?bp|e?sp)\b','R',a); a=re.sub(r'0x[0-9a-f]+|\b\d+\b','K',a)
    ins[int(m.group(1),16)]=op+' '+a
adr=sorted(ins)
import bisect
fk={}
for f in glob.glob(FS+'/*.fstand'):
    u=os.path.basename(f)[:-7]
    for l in open(f,errors='replace'):
        m=re.match(r'([0-9A-F]{6})\s+(\d+)/(\d+)\s+(GLEICH|(\d+) Befehle)',l.strip())
        if m: fk[(u,int(m.group(1),16))]=(int(m.group(2)),0 if m.group(4)=='GLEICH' else int(m.group(5)))
def folge(a,n):
    i=bisect.bisect_left(adr,a); out=[]
    while i<len(adr) and adr[i]<a+n: out.append(ins[adr[i]]); i+=1
    return out
seq={k:folge(k[1],v[0]) for k,v in fk.items() if v[0]>=16}
ids={}; num=lambda s:[ids.setdefault(x,len(ids)) for x in s]
nseq={k:num(s) for k,s in seq.items()}
def gram(s): return set(zip(s,s[1:],s[2:])) if len(s)>=3 else set(map(tuple,[s]))
gl=[k for k in nseq if fk[k][1]==0]; of=[k for k in nseq if fk[k][1]>0]
G={k:gram(nseq[k]) for k in nseq}
inv=collections.defaultdict(list)
for k in gl:
    for g in G[k]: inv[g].append(k)
out=open(Q6+'/logs/similar.tsv','w'); out.write('einheit\tfkt\tbytes\trest\tv1_einheit\tv1_fkt\tv1_aehnl\tv2_einheit\tv2_fkt\tv2_aehnl\tv3_einheit\tv3_fkt\tv3_aehnl\n')
for k in sorted(of,key=lambda k:-fk[k][0]):
    cnt=collections.Counter()
    for g in G[k]:
        lst=inv.get(g,[])
        if len(lst)<400:
            for c in lst: cnt[c]+=1
    L=len(nseq[k]); kand=[c for c,_ in cnt.most_common(40) if c[0]!=k[0] or c[1]!=k[1]]
    kand=[c for c in kand if 0.5<=len(nseq[c])/max(L,1)<=2.0][:15]
    sc=[]
    for c in kand:
        r=difflib.SequenceMatcher(None,nseq[k],nseq[c],autojunk=False).ratio() if L<=1500 else len(G[k]&G[c])/max(1,len(G[k]|G[c]))
        sc.append((r,c))
    sc.sort(reverse=True); sc=sc[:3]
    z=[k[0],f'f_{k[1]:06x}',str(fk[k][0]),str(fk[k][1])]
    for r,c in sc: z+=[c[0],f'f_{c[1]:06x}',f'{r:.2f}']
    out.write('\t'.join(z)+'\n')
out.close(); print('offen',len(of),'geloest',len(gl))
