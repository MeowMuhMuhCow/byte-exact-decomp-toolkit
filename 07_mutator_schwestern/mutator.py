#!/usr/bin/env python3
"""mutator.py QUELLE.CPP NAME [SEED] [MAXSTELLEN] - erzeugt $VMVAR/NAME.VT mit mechanischen Umformungen als Alternativen
(target worker). Danach: VMVAR=â¦ python3 gw/vmasch.py NAME LO MAX. Stellenbeschreibung in NAME.stellen.
Regeln: Typ von Lokalen, Reihenfolge zweier Deklarationen in einer Zeile, x op= y, *p++ = v, if(x==0)/if(!x),
Vergleich umdrehen, Wert vorab in Lokale (nur Doku)."""
import sys,re,random,os,itertools
src,NAME=sys.argv[1],sys.argv[2]; seed=int(sys.argv[3]) if len(sys.argv)>3 else 1; MAXS=int(sys.argv[4]) if len(sys.argv)>4 else 10
VD=os.environ.get('VMVAR',os.environ['HOME']+'/var_o'); random.seed(seed)
L=open(src).read().split('\n')
TYP={'char':['char','unsigned char','signed char','int'],'unsigned char':['unsigned char','char','int','unsigned'],
 'signed char':['signed char','char','int'],'short':['short','int','unsigned short'],'unsigned short':['unsigned short','short','int'],
 'int':['int','short','unsigned','long'],'unsigned':['unsigned','int','unsigned char','short'],'long':['long','int']}
sites=[]  # (zeile, alt_liste_von_zeilen, beschreibung)
tre='|'.join(sorted(map(re.escape,TYP),key=len,reverse=True))
for i,l in enumerate(L):
    if not l.startswith(' '): continue          # nur Funktionsrumpf
    a=[]
    m=re.match(r'^(\s*)('+tre+r')(\s+\**\w+\s*(=|;))',l)
    if m: a.append(([m.group(1)+t+l[m.end(2):] for t in TYP[m.group(2)]],f'Typ {m.group(2)}'))
    for m in re.finditer(r'\b('+tre+r')\s+(\w+\s*=[^;]+;)',l):
        if m.start()==len(l)-len(l.lstrip()): continue
        a.append(([l[:m.start()]+t+' '+m.group(2)+l[m.end():] for t in TYP[m.group(1)]],f'Typ {m.group(1)} (Mitte)'))
    m=re.match(r'^(\s*)([^;]+;)\s*([^;]+;)\s*$',l)
    if m and not l.strip().startswith(('for','if','while')): a.append(([l,m.group(1)+m.group(3)+' '+m.group(2)],'zwei Anweisungen tauschen'))
    m=re.search(r'\b(\w+)\s*([+\-*|&^])=\s*([^;]+);',l)
    if m: a.append(([l,l[:m.start()]+f'{m.group(1)} = {m.group(1)} {m.group(2)} {m.group(3)};'+l[m.end():]],'x op= y'))
    m=re.search(r'\*(\w+)\+\+\s*=\s*([^;]+);',l)
    if m: a.append(([l,l[:m.start()]+f'*{m.group(1)} = {m.group(2)}; {m.group(1)}++;'+l[m.end():],l[:m.start()]+f'*{m.group(1)} = {m.group(2)}; {m.group(1)} = {m.group(1)} + 1;'+l[m.end():]],'*p++ = v'))
    m=re.search(r'if \((\w+) == 0\)',l)
    if m: a.append(([l,l.replace(m.group(0),f'if (!{m.group(1)})'),l.replace(m.group(0),f'if (0 == {m.group(1)})')],'Nulltest'))
    m=re.search(r'if \((\w+) (<|>|<=|>=) (\w+)\)',l)
    if m:
        inv={'<':'>','>':'<','<=':'>=','>=':'<='}[m.group(2)]
        a.append(([l,l.replace(m.group(0),f'if ({m.group(3)} {inv} {m.group(1)})')],'Vergleich umdrehen'))
    m=re.match(r'^(\s{8,})('+tre+r')\s+(\w+)\s*=\s*([^;]+);(.*)$',l)
    if m:   # Deklaration aus innerem Block an den Funktionsanfang heben (verknuepfte Stelle)
        j=max(k for k in range(i) if L[k].strip()=='{' and not L[k].startswith(' '))
        a.append(([l,m.group(1)+f'{m.group(3)} = {m.group(4)};'+m.group(5)],'Deklaration nach oben',(j,f'    {m.group(2)} {m.group(3)};')))
    for x in a: sites.append((i,x[0],x[1])+((x[2],) if len(x)>2 else ()))
random.shuffle(sites); sel=sorted(sites[:MAXS],key=lambda s:s[0])
# je Zeile hoechstens eine Stelle (sonst Konflikte)
seen=set(); fin=[]
for s in sel:
    if s[0] in seen: continue
    seen.add(s[0]); fin.append(s)
out=list(L); desc=[]
for k,s in enumerate(fin):
    i,alts,d=s[:3]; n='M%02d'%k
    if len(s)>3:
        j,decl=s[3]; out[j]=out[j]+f'\n//?{n}\n//|\n{decl}\n//.'
    out[i]=f'//?{n}\n'+'\n//|\n'.join(dict.fromkeys(alts))+'\n//.'
    desc.append(f'{n}\tZeile {i+1}\t{d}\t'+' || '.join(x.strip() for x in dict.fromkeys(alts)))
open(f'{VD}/{NAME}.VT','w').write('\n'.join(out)); open(f'{VD}/{NAME}.stellen','w').write('\n'.join(desc)+'\n')
n=1
for s in fin: alts=s[1]; n*=len(dict.fromkeys(alts))
print(f'Stellen gefunden {len(sites)}, genutzt {len(fin)}, Kombinationen {n}')
