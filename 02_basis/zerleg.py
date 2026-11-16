# zerleg.py - Function boundary map from LE binary: call/jump targets, OMF runtime libraries, assertion path strings
import re,os,sys,collections,struct
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from le import *; import omf
DIS=sys.argv[1]; OUT=sys.argv[2]; LIBDIR=sys.argv[3]
CE=CB+len(CODE)
ins=[]  # (va,len,mn,op)
rx=re.compile(r'^\s+([0-9a-f]+):\t([0-9a-f ]+?)\s*\t(\S+)\s*(.*)$')
for l in open(DIS):
    m=rx.match(l)
    if m: ins.append((int(m.group(1),16),len(m.group(2).split()),m.group(3),m.group(4).strip()))
FILL=re.compile(r'^0x0\((%e\w\w)(,%eiz,1)?\),\1$')
def isfill(mn,op):
    return mn=='nop' or (mn=='lea' and FILL.match(op)) or (mn=='mov' and re.match(r'^(%e\w\w),\1$',op)) or (mn=='xchg' and op=='%ax,%ax')
calls=set(); jcc=set(); jmpt=set()
for va,n,mn,op in ins:
    m=re.match(r'^0x([0-9a-f]+)$',op)
    if m:
        t=int(m.group(1),16)
        if mn.startswith('call'): calls.add(t)
        elif mn.startswith('jmp'): jmpt.add(t)
        elif mn.startswith('j'): jcc.add(t)
# Sprungtabellen: Laeufe von Code-Fixups im Abstand 4 mit Ziel im Code
cf=sorted((s,tv) for s,t,tv in fixups if CB<=s<CE and CB<=tv<CE)
cfs={s:tv for s,tv in cf}
table_entry=set(); table_tgt=set()
for s,tv in cf:
    if (s+4 in cfs) or (s-4 in cfs):
        table_entry.add(s); table_tgt.add(tv)
table_start={tv for s,t,tv in fixups if CB<=tv<CE and tv in table_entry}
ptr_tgt={tv for s,t,tv in fixups if CB<=tv<CE and s not in table_entry and tv not in table_start}
starts={CB}|{c for c in calls if CB<=c<CE}|ptr_tgt
# nach ret/jmp + Fueller auf 16 ausgerichtet
for i,(va,n,mn,op) in enumerate(ins):
    if mn.startswith('ret') or mn=='jmp' or mn=='jmp*' or (mn.startswith('jmp')) :
        j=i+1
        while j<len(ins) and isfill(ins[j][2],ins[j][3]): j+=1
        if j<len(ins):
            a=ins[j][0]
            if a%16==0 and a not in jcc and a not in table_tgt and a not in table_entry: starts.add(a)
starts=sorted(s for s in starts if CB<=s<CE)
# Tabellen-Bereiche sind keine Funktionsanfaenge
fn=[]
for k,s in enumerate(starts):
    e=starts[k+1] if k+1<len(starts) else CE
    fn.append([s,e])
# Bibliotheken
def items(path):
    out=[]
    for m in omf.modules(path):
        for sg in m['segs'].values():
            if sg['cls']=='CODE' and len(sg['data'])>=8: out.append((m['name'],sg))
        for c in m['comdats']:
            if len(c['data'])>=8: out.append((m['name']+':'+c['name'],c))
    return out
def find(it):
    data,mask=it['data'],it['mask']; best=(0,0); st=None
    for k in range(len(data)+1):
        if k<len(data) and not mask[k]:
            if st is None: st=k
        else:
            if st is not None and k-st>best[1]-best[0]: best=(st,k)
            st=None
    a,b=best
    if b-a<6: return []
    anc=bytes(data[a:b]); hits=[]; p=CODE.find(anc)
    while p>=0:
        base=p-a
        if base>=0 and all(mask[k] or CODE[base+k]==data[k] for k in range(len(data))): hits.append(CB+base)
        p=CODE.find(anc,p+1)
    return hits
libhit={}
for lib in ['DOS/CLIB3R.LIB','PLIB3R.LIB','MATH387R.LIB','MATH3R.LIB','CPLX3R.LIB','DOS/EMU387.LIB','NOEMU387.LIB','DOS/CSTRTX3R.OBJ']:
    p=os.path.join(LIBDIR,lib)
    for name,it in items(p):
        h=find(it)
        if len(h)==1: libhit[h[0]]=(lib.split('/')[-1],name,len(it['data']))
# Pfade
paths={DB+m.start():m.group().decode().split('\\')[-1] for m in re.finditer(os.environ.get('PATH_REGEX', r'[a-zA-Z]:\\[a-z0-9_\\]+\.c(?:pp)?').encode('ascii'),DATA)}
import bisect
S=[f[0] for f in fn]
def fidx(va): return bisect.bisect_right(S,va)-1
fdat=[dict(va=f[0],end=f[1],file=None,lib=None,sure='') for f in fn]
for va,(lb,name,ln) in libhit.items():
    k=fidx(va); fdat[k]['lib']=f'{lb}:{name}'
    # Bibliotheksroutine kann mehrere unserer Kandidaten ueberdecken
    j=k+1
    while j<len(fdat) and fdat[j]['va']<va+ln: fdat[j]['lib']=f'{lb}:{name}'; j+=1
refs=collections.defaultdict(set)
for s,t,tv in fixups:
    if tv in paths and CB<=s<CE: refs[fidx(s)].add(paths[tv])
multi=0
for k,fs in refs.items():
    if len(fs)>1: multi+=1
    fdat[k]['file']=sorted(fs)[0]; fdat[k]['sure']='pfad'
last_path_func=max(refs)
# Luecken fuellen
known=[k for k in range(len(fdat)) if fdat[k]['file']]
for a,b in zip(known,known[1:]):
    fa,fb=fdat[a]['file'],fdat[b]['file']
    for k in range(a+1,b):
        if fdat[k]['lib']: continue
        if fa==fb: fdat[k]['file']=fa; fdat[k]['sure']='zwischen'
        else: fdat[k]['file']=f'{fa}|{fb}'; fdat[k]['sure']='grenze'
for k in range(0,known[0]):
    if not fdat[k]['lib']: fdat[k]['file']='?|'+fdat[known[0]]['file']; fdat[k]['sure']='grenze'
for k in range(last_path_func+1,len(fdat)):
    if not fdat[k]['lib']: fdat[k]['file']='(after_paths)'; fdat[k]['sure']='fremd?'
# Ausgabe
os.makedirs(OUT,exist_ok=True)
def size(f):
    return f['end']-f['va']
with open(os.path.join(OUT,'funktionen.tsv'),'w') as o:
    o.write('va\tende\tbytes\tdatei\tzuordnung\tbibliothek\n')
    for f in fdat: o.write(f"{f['va']:06X}\t{f['end']:06X}\t{size(f)}\t{f['file'] or ''}\t{f['sure']}\t{f['lib'] or ''}\n")
per=collections.OrderedDict()
for f in fdat:
    if f['lib'] or not f['file'] or '|' in f['file'] or f['file'].startswith('('): continue
    p=per.setdefault(f['file'],[f['va'],f['end'],0,0]); p[1]=f['end']; p[2]+=1; p[3]+=size(f)
with open(os.path.join(OUT,'dateien.tsv'),'w') as o:
    o.write('datei\tvon\tbis\tfunktionen\tbytes\n')
    for n,(a,b,c,s) in per.items(): o.write(f'{n}\t{a:06X}\t{b:06X}\t{c}\t{s}\n')
cnt=collections.Counter(f['sure'] if not f['lib'] else 'bibliothek' for f in fdat)
byt=collections.Counter()
for f in fdat: byt[f['sure'] if not f['lib'] else 'bibliothek']+=size(f)
order=sorted(per); alpha=sum(1 for x,y in zip(list(per),list(per)[1:]) if x>y)
print('Funktionen',len(fdat),'| Pfaddateien im Code',len(per),'von',len(paths),'| Funktionen mit >1 Pfad',multi)
for k in ['pfad','zwischen','grenze','bibliothek','fremd?']: print(f'  {k:11s} {cnt[k]:6d} Funktionen {byt[k]:9d} Bytes')
print('Bibliotheks-Treffer (eindeutig)',len(libhit),'| Last path anchor after',hex(fdat[last_path_func]['end']),'| Reihenfolge-Verstoesse',alpha)
