# zerleg2.py - Grenzfunktionen per Datenreferenzen (CONST in Modulreihenfolge) Dateien zuordnen
import re,bisect,collections,csv,os,sys
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from le import *
A=sys.argv[1]; CE=CB+len(CODE)
P=[(DB+m.start(),m.group().decode().split('\\')[-1]) for m in re.finditer(os.environ.get('PATH_REGEX', r'[a-zA-Z]:\\[a-z0-9_\\]+\.c(?:pp)?').encode('ascii'),DATA)][:265]
PV=[v for v,n in P]; PN=[n for v,n in P]; MI={n:i for i,n in enumerate(PN)}
F=list(csv.DictReader(open(os.path.join(A,'funktionen.tsv')),delimiter='\t'))
S=[int(f['va'],16) for f in F]
pvset=set(PV); lo,hi=PV[0]-0x40,PV[-1]+0x200
votes=collections.defaultdict(collections.Counter)
for s,t,tv in fixups:
    if CB<=s<CE and lo<=tv<hi and tv not in pvset:
        k=bisect.bisect_right(S,s)-1; i=bisect.bisect_right(PV,tv)-1; j=bisect.bisect_left(PV,tv)
        if i>=0: votes[k][i]+=1
        if j<len(PV): votes[k][j]+=1
known=[k for k,f in enumerate(F) if f['zuordnung'] in ('pfad',)]
stat=collections.Counter()
for a,b in zip(known,known[1:]):
    ia,ib=MI[F[a]['datei']],MI[F[b]['datei']]
    idx=[k for k in range(a+1,b) if not F[k]['bibliothek']]
    if not idx: continue
    if ia==ib:
        continue
    mods=list(range(ia,ib+1)); n=len(idx); M=len(mods)
    # DP: nicht fallende Modulzuordnung, maximiere Stimmen
    NEG=-1e9; best=[[NEG]*M for _ in range(n)]; back=[[0]*M for _ in range(n)]
    for x,k in enumerate(idx):
        run=NEG; arg=0
        for y,m in enumerate(mods):
            prev=0 if x==0 else best[x-1][y]
            if x==0: prev = 0 if y==0 or True else NEG
            if prev>run: run=prev; arg=y
            sc=votes[k][m]
            best[x][y]=(run if x>0 else 0)+sc; back[x][y]=arg
    y=max(range(M),key=lambda q:(best[n-1][q],-abs(q-M+1)))
    assign=[0]*n
    for x in range(n-1,-1,-1):
        assign[x]=mods[y]; y=back[x][y]
    for x,k in enumerate(idx):
        m=assign[x]; f=F[k]
        if votes[k][m]>0: f['datei']=PN[m]; f['zuordnung']='daten'; stat['daten']+=1
    # dazwischen ohne Stimmen: wenn Nachbarn mit Beleg dieselbe Datei haben
    lastm=ia
    seq=[(k,MI[F[k]['datei']] if F[k]['zuordnung']=='daten' else None) for k in idx]+[(b,ib)]
    prevm=ia; buf=[]
    for k,m in seq:
        if m is None: buf.append(k); continue
        for q in buf:
            if prevm==m: F[q]['datei']=PN[m]; F[q]['zuordnung']='zwischen'; stat['zwischen+']+=1
            else: F[q]['datei']=f'{PN[prevm]}|{PN[m]}'; F[q]['zuordnung']='grenze'; stat['grenze']+=1
        buf=[]; prevm=m
with open(os.path.join(A,'funktionen.tsv'),'w') as o:
    o.write('va\tende\tbytes\tdatei\tzuordnung\tbibliothek\n')
    for f in F: o.write('\t'.join(f[c] for c in ['va','ende','bytes','datei','zuordnung','bibliothek'])+'\n')
cnt=collections.Counter(); byt=collections.Counter()
for f in F:
    k='bibliothek' if f['bibliothek'] else f['zuordnung']; cnt[k]+=1; byt[k]+=int(f['bytes'])
for k in ['pfad','daten','zwischen','grenze','bibliothek','fremd?']: print(f'  {k:11s} {cnt[k]:6d} Funktionen {byt[k]:9d} Bytes')
files=set(f['datei'] for f in F if f['zuordnung'] in('pfad','daten','zwischen'))
print('Dateien mit Code', len(files),'von',len(PN))
