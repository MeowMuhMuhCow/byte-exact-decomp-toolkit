# abschnitt.py OBJ LO FUNC [-v] - Measure structural Core per basic-block section (register/stack masked).
# Struktur-Rest: Diff mit normierten Registern/Stapeloffsets (nur Befehlsart, Reihenfolge, Konstanten, Globale).
# Abschnitte: Original in Bloecke geteilt nach jedem call/ret/jmp; Zuordnung zu unseren Bloecken ueber die Folge der Aufrufziele.
# Ausgabe: Kopfzeile + je Abschnitt: Nr, Befehle O/A, exakt/struktur/ABWEICHEND, erster Unterschied. -v: Diffs der abweichenden Abschnitte.
import sys,os,re,difflib
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import fsmod
REG=r'\b(e?[abcd]x|[abcd][lh]|e?[sd]i|e?bp|[sd]il)\b'
def st(x):
    x=re.sub(REG,'R',x); x=re.sub(r'\[esp\+0x[0-9a-f]+\]|\[esp\]','[S]',x); x=re.sub(r'\[ebp-0x[0-9a-f]+\]|\[ebp\+0x[0-9a-f]+\]','[S]',x)
    x=re.sub(r'^(j\w+) \+[0-9a-f]+$',r'\1 L',x); x=re.sub(r'^call \S+$','call',x); return x
def blocks(L):
    b=[[]]
    for x in L:
        b[-1].append(x)
        if re.match(r'(call|ret|jmp)\b',x): b.append([])
    return [k for k in b if k]
def anker(b): return next((x for x in reversed(b) if re.match(r'(call|ret|jmp)\b',x)),'')
def rest(a,b,f=lambda x:x):
    sm=difflib.SequenceMatcher(None,[f(x) for x in a],[f(x) for x in b],autojunk=False)
    return sum(max(i2-i1,j2-j1) for t,i1,i2,j1,j2 in sm.get_opcodes() if t!='equal')
def mess(obj,lo,f,E=None):
    """-> dict(so,sn,exakt,struktur,n,falsch=[(i,len,strukt_rest,anker_orig)],gl)"""
    E=E or fsmod.Einheit(obj,lo); r=E.funktion(f); O,A=r['O'],r['A']
    of,on,an=E.fkt[f]; OR,_=fsmod.dis(fsmod.ORG[f-fsmod.B:an-fsmod.B],f,E.res_o)
    BO,BA=blocks(O),blocks(A)
    ko=[re.sub(r'^(jmp) \S+$',r'\1',st(anker(b))) for b in BO]; ka=[re.sub(r'^(jmp) \S+$',r'\1',st(anker(b))) for b in BA]
    sm=difflib.SequenceMatcher(None,ko,ka,autojunk=False); paar={}
    for t,i1,i2,j1,j2 in sm.get_opcodes():
        if t=='equal':
            for k in range(i2-i1): paar[i1+k]=j1+k
    frei=[j for j in range(len(BA)) if j not in paar.values()]          # 2. Durchgang: aehnlichster freier Block (Reihenfolge vertauscht), Aehnlichkeit >= 0.6
    SO=[[st(x) for x in b] for b in BO]; SA=[[st(x) for x in b] for b in BA]
    for i in sorted((i for i in range(len(BO)) if i not in paar),key=lambda i:-len(BO[i])):
        best=max(frei,key=lambda j:difflib.SequenceMatcher(None,SO[i],SA[j],autojunk=False).ratio(),default=None)
        if best is not None and difflib.SequenceMatcher(None,SO[i],SA[best],autojunk=False).ratio()>=0.6: paar[i]=best; frei.remove(best)
    vert=sum(1 for i,j in paar.items() if i in paar and any(i2>i and paar[i2]<j for i2 in paar if i2<len(BO)))
    ex=sum(1 for i,j in paar.items() if BO[i]==BA[j]); sg=sum(1 for i,j in paar.items() if [st(x) for x in BO[i]]==[st(x) for x in BA[j]])
    BR=blocks(OR); falsch=[]
    for i,b in enumerate(BO):
        j=paar.get(i); sr=len(b) if j is None else (0 if [st(x) for x in b]==[st(x) for x in BA[j]] else rest(b,BA[j],st))
        if sr: falsch.append((i,len(b),sr,anker(BR[i]) if i<len(BR) else ''))
    return dict(so=r['so'],sn=r['sn'],exakt=r['nd'] or 0,struktur=rest(O,A,st),n=len(BO),falsch=falsch,gl=r['gl'],BO=BO,BA=BA,paar=paar,ex=ex,sg=sg,vert=vert)
if __name__=='__main__':
    obj,lo,f=sys.argv[1],int(sys.argv[2],16),int(sys.argv[3].replace('f_',''),16); V='-v' in sys.argv
    m=mess(obj,lo,f); BO,BA,paar=m['BO'],m['BA'],m['paar']
    print(f"f_{f:06x}: Groesse {m['so']}/{m['sn']}, Rest exakt {m['exakt']}, Rest Struktur {m['struktur']}, Abschnitte {len(BO)} (unsere {len(BA)}), "
          f"zugeordnet {len(paar)}, exakt gleich {m['ex']}, strukturgleich {m['sg']}, ausser Reihenfolge {m['vert']}")
    for i,b in enumerate(BO):
        j=paar.get(i)
        if j is None: print(f"  {i:3d} {len(b):3d}/  -  OHNE GEGENSTUECK  {b[-1][:60]}"); continue
        a=BA[j]
        if b==a: s='exakt'
        elif [st(x) for x in b]==[st(x) for x in a]: s='struktur'
        else: s=f'ABWEICHEND ({rest(b,a,st)} strukt.)'
        d=next((f'{x[:38]} | {y[:38]}' for x,y in zip(b,a) if x!=y),'') if s!='exakt' else ''
        print(f"  {i:3d} {len(b):3d}/{len(a):3d} @{j:3d} {s:24s} {d}")
        if V and s.startswith('ABW'):
            for l in difflib.unified_diff(b,a,'orig','neu',lineterm='',n=1): print('      '+l)
