# operatoren.py - Operatorbibliothek des Such-Treibers (worker, 23.10.2026). Jede Funktion op_*(L,blk,info) liefert Stellen:
#   Stelle(op, stufe, alts): alts[0] = {} (unveraendert), alts[k] = {zeilenindex: neuer Text ('' = Zeile loeschen, '\n' erlaubt),
#   ('ins',idx): Text vor Zeile idx einfuegen}. Stufen: 2 bekannte Regeln (R88, R91, R92/R99, R93, R100, R109, R110, R49/R53,
#   Inlining), 3 Typbreite (Lokale, Parameter, Rueckgabe, (short)K, Globale, Rueckgabetyp Aufgerufener), 4 Ausdrucksform
#   (?:/if-else, Vergleich drehen, op=, +=-K, Nulltest, Zwischenvariable, Reihenfolge, x=y=n, Tail-return), 5 Gleichstand (R108, R102).
# Signatur (info['tags']) steuert in suche.py nur die Reihenfolge, nicht die Zulassung.
import re,itertools
TYPEN=['unsigned short','unsigned char','signed char','unsigned int','unsigned long','short','char','int','long','unsigned']
TRE='|'.join(re.escape(t) for t in sorted(TYPEN,key=len,reverse=True))
NAME=r'[A-Za-z_]\w*'; LIT=r'-?(?:0x[0-9a-fA-F]+|\d+)'
def lit(s): return int(s,16) if s.lower().startswith(('0x','-0x')) else int(s)
def kstr(k): return (0,k,'') if isinstance(k,int) else (1,k[1],k[0])
class Stelle:
    def __init__(s,op,stufe,alts,pos=None,info=''):
        s.op=op; s.stufe=stufe; s.alts=alts; s.pos=pos; s.info=info
        s.zeilen={k if isinstance(k,int) else k[1] for a in alts for k in a}
        s.key=(op,tuple(sorted(((kstr(k),v) for a in alts for k,v in a.items()))))
    def __repr__(s): return f'{s.op}@{sorted(s.zeilen)}x{len(s.alts)}'
def S(op,stufe,alts,blk=None,idx=None,info=''):
    """Alternativen deduplizieren; Position = Anteil der Zeile im Block (fuer Hunk-Naehe)."""
    uniq=[]; seen=set()
    for a in alts:
        k=tuple(sorted((kstr(x),v) for x,v in a.items()))
        if k in seen: continue
        seen.add(k); uniq.append(a)
    if len(uniq)<2: return None
    pos=None
    if blk and idx is not None and blk['ende']>blk['start']: pos=min(1.0,max(0.0,(idx-blk['start'])/(blk['ende']-blk['start'])))
    return Stelle(op,stufe,uniq,pos,info)
# ---------- Ausdruecke ----------
def links(s,p):
    """Operand links von Position p (exklusiv): (start, ende) mit balancierten Klammern."""
    i=p
    while i>0 and s[i-1]==' ': i-=1
    e=i
    while i>0:
        c=s[i-1]
        if c in ')]':
            d=0
            while i>0:
                i-=1
                if s[i] in ')]': d+=1
                elif s[i] in '([': d-=1
                if d==0: break
            continue
        if c.isalnum() or c in '_.': i-=1; continue
        if c=='>' and i>1 and s[i-2]=='-': i-=2; continue
        break
    while i>0 and s[i-1] in '*!-' and (i-1==0 or s[i-2] in ' (,'): i-=1
    return i,e
def rechts(s,p):
    i=p
    while i<len(s) and s[i]==' ': i+=1
    st=i
    while i<len(s) and s[i] in '-!*&~': i+=1
    if i<len(s) and s[i]=='(' :   # Cast oder Klammerausdruck
        pass
    while i<len(s):
        c=s[i]
        if c in '([':
            d=0
            while i<len(s):
                if s[i] in '([': d+=1
                elif s[i] in ')]': d-=1
                i+=1
                if d==0: break
            continue
        if c.isalnum() or c in '_.': i+=1; continue
        if c=='-' and i+1<len(s) and s[i+1]=='>': i+=2; continue
        break
    return st,i
CMP=re.compile(r'(?<![<>=!\-])(<=|>=|==|!=|<|>)(?![<>=])')
def vergleiche(l):
    """[(a0,a1,op,b0,b1)] aller zweistelligen Vergleiche der Zeile (Operanden mit balancierten Klammern)."""
    out=[]
    for m in CMP.finditer(l):
        a0,a1=links(l,m.start()); b0,b1=rechts(l,m.end())
        a=l[a0:a1]; b=l[b0:b1]
        if not a or not b or a in ('if','while','for','return') or '{' in a or ';' in a: continue
        out.append((a0,a1,m.group(1),b0,b1))
    return out
def aufrufe(l):
    """[(name, argstart, argende)] fuer f(...)-Aufrufe mit balancierten Klammern (name kann p->f_... sein)."""
    out=[]
    for m in re.finditer(r'((?:\w+(?:->|\.))*\w+)\s*\(',l):
        if m.group(1) in ('if','while','for','switch','return','sizeof') or re.match(r'^('+TRE+')$',m.group(1)): continue
        i=m.end()-1; d=0
        while i<len(l):
            if l[i]=='(': d+=1
            elif l[i]==')': d-=1
            i+=1
            if d==0: break
        if d==0: out.append((m.group(1),m.end(),i-1))
    return out
def ist_lit(s): return bool(re.match(r'^'+LIT+'$',s.strip()))
# ---------- Block-Analyse ----------
KOPF_ALT=re.compile(r'^\s*(static\s+|inline\s+)*((?:(?:unsigned|signed|const|struct)\s+)*\w+(?:\s*\*+)?(?:\s*&)?)\s*((?:\w+::)?[~\w]+)\s*\((.*?)\)\s*(const)?\s*\{?\s*$')
KOPF=re.compile(r'^\s*(static\s+|inline\s+)*((?:(?:unsigned|signed|const|struct)\s+)*\w+(?:\s*\*+)?(?:\s*&)?)' r'(?:(?<=\w)\s+|(?<=[*&])\s*)' r'(?:(?:__(?:cdecl|stdcall|fastcall|pascal|watcall|near|far)|_(?:cdecl|stdcall|fastcall|pascal)|cdecl|stdcall|fastcall|pascal)\s+)*((?:\w+::)?[~\w]+)\s*\((.*?)\)\s*(const)?\s*\{?\s*$')

def _einzeiler_teile(zeile):
    """Nur eindeutig abgeschlossene Einzeiler zerlegen; Strings/Kommentare bleiben atomar."""
    if '{' not in zeile or '}' not in zeile or '//' in zeile or '/*' in zeile: return None
    kopf, rest = zeile.split('{', 1)
    if not KOPF.match(kopf.strip()+' {'): return None
    if not rest.rstrip().endswith('}'): return None
    rumpf=rest[:rest.rfind('}')]
    if '}' in rest[rest.rfind('}')+1:]: return None
    teile=[]; start=0; par=0; q=None; esc=False
    for i,c in enumerate(rumpf):
        if q:
            if esc: esc=False
            elif c=='\\': esc=True
            elif c==q: q=None
            continue
        if c in ('"', "'"): q=c; continue
        if c=='(': par+=1
        elif c==')': par-=1
        if par<0: return None
        if par==0 and c in '{};':
            t=rumpf[start:i].strip()
            if t: teile.append(t + (';' if c==';' else ''))
            elif c==';' and teile and teile[-1]=='}': teile[-1]='};'
            if c in '{}': teile.append(c)
            start=i+1
    if q or par or rumpf[start:].strip(): return None
    d=0
    for t in teile:
        if t=='{': d+=1
        elif t in ('}','};'):
            d-=1
            if d<0: return None
    if d: return None
    einzug=zeile[:len(zeile)-len(zeile.lstrip())]
    return [kopf.rstrip(),einzug+'{']+[einzug+'    '+t if t not in ('{','}') else einzug+t for t in teile]+[einzug+'}']

def vorbereiten(L):
    """Markierte Einzeiler vor Parser und Compiler gleichermaÃen normalisieren."""
    if __import__('os').environ.get('KD_EINZEILER','0')!='1': return list(L)
    out=[]; mark=None
    for zeile in L:
        m=re.match(r'//@ f_([0-9a-f]{6})',zeile)
        if m: mark=m.group(1)
        elif mark and zeile.strip() and not zeile.lstrip().startswith('//'):
            # Ein Markierungsblock kann zuerst Hilfsfunktionen enthalten.
            # Nur den Kopf der markierten Funktion zerlegen.
            if not re.search(r'\bf_'+mark+r'\s*\(',zeile):
                out.append(zeile); continue
            teile=_einzeiler_teile(zeile)
            if teile:
                out.extend(teile); mark=None; continue
            mark=None
        out.append(zeile)
    return out
def bloecke(L):
    """Funktionsbloecke ueber //@ f_xxxxxx: {ad: dict(mark,kopf,start,ende,name,rettyp,params,lokale)}."""
    marks=[(i,int(m.group(1),16)) for i,l in enumerate(L) for m in [re.match(r'//@ f_([0-9a-f]{6})',l)] if m]
    out={}
    for k,(i,ad) in enumerate(marks):
        grenze=marks[k+1][0] if k+1<len(marks) else len(L)
        kopf=start=ende=None; tiefe=0
        zielkopf=(next((j for j in range(i+1,grenze) if re.search(r'\bf_'+f'{ad:06x}'+r'\s*\(',L[j]) and not L[j].lstrip().startswith('//')),None)
                  if __import__('os').environ.get('KD_EINZEILER','0')=='1' else None)
        for j in range(i+1,grenze):
            s=L[j].strip()
            if kopf is None and s and not s.startswith('//') and not s.startswith('#') and (zielkopf is None or j>=zielkopf): kopf=j
            if kopf is not None and start is None and (L[j].rstrip()=='{' or (L[j].rstrip().endswith('{') and L[j].count('(')==L[j].count(')') and not re.search(r'\{.*\}',L[j]))): start=j
            if start is not None:
                if __import__('os').environ.get('KD_EINZEILER','0')=='1':
                    tiefe+=L[j].count('{')-L[j].count('}')
                    if tiefe==0 and j>start: ende=j; break
                elif L[j].rstrip()=='}': ende=j; break
        if kopf is None or start is None or ende is None or ende<=start: continue
        hl=' '.join(x.strip() for x in L[kopf:start+1]); m=(KOPF.match(hl) or KOPF_ALT.match(hl)) if __import__('os').environ.get('KD_EINZEILER','0')=='1' else KOPF_ALT.match(hl)
        params=[]; rettyp=None; name=None
        if m:
            rettyp,name,pl=re.sub(r'\s+',' ',m.group(2).strip()),m.group(3),m.group(4)
            for p in [x.strip() for x in pl.split(',') if x.strip() and x.strip()!='void']:
                mm=re.match(r'^((?:(?:unsigned|signed|const)\s+)*\w+)\s*(\**)\s*(\w+)$',p)
                params.append((re.sub(r'\s+',' ',mm.group(1)),mm.group(2),mm.group(3)) if mm else (None,None,p))
        lokale={}
        for j in range(start+1,ende):
            m2=re.match(r'^\s*(?:const\s+)?('+TRE+r')\s+(\**\w+(?:\s*=[^;,]+)?(?:\s*,\s*\**\w+(?:\s*=[^;,]+)?)*)\s*;',L[j])
            if m2:
                for v in re.findall(r'\**(\w+)',re.sub(r'=[^,;]+','',m2.group(2))): lokale[v]=(m2.group(1),j)
        out[ad]=dict(ad=ad,mark=i,kopf=kopf,start=start,ende=ende,grenze=grenze,name=name,rettyp=rettyp,params=params,lokale=lokale)
    return out
def einheit_info(L):
    """Unit-weite Deklarationen: Prototypzeilen je Funktionsname, extern-Zeilen je Globale, vorhandene Makros."""
    proto={}; ext={}; makros=set()
    for i,l in enumerate(L):
        if l.startswith(' ') or l.startswith('//'): continue
        m=re.match(r'^((?:(?:unsigned|signed|const|static|extern)\s+)*\w+)(\s*\**)\s*(f_[0-9a-f]{6}|\w+)\s*\(([^()]*)\)\s*;',l)
        if m: proto.setdefault(m.group(3),i)
        m=re.match(r'^extern\s+(volatile\s+)?((?:(?:unsigned|signed|const)\s+)*\w+)\s+(.*);',l)
        if m:
            for v in re.findall(r'\b(d_[0-9a-f]{6})\b',m.group(3)): ext[v]=i
        m=re.match(r'#define\s+(\w+)',l)
        if m: makros.add(m.group(1))
        if 'EQBF(' in l and 'inline' in l: makros.add('EQBF')
    return dict(proto=proto,ext=ext,makros=makros)
def ind(l): return l[:len(l)-len(l.lstrip())]
def body(L,blk): return range(blk['start']+1,blk['ende'])
def ptyp(blk,v):
    if v in blk['lokale']: return blk['lokale'][v][0]
    for t,st,nm in blk['params']:
        if nm==v and t and not st: return t
    return None
# ---------- Typ-Evidenz aus dem Original ----------
def typ_evidenz(O,A):
    o=' ; '.join(O); a=' ; '.join(A)
    return dict(w16=bool(re.search(r'\bWORD PTR|movsx \w+,\w*x\b|movzx \w+,\w*x\b|cwde|\b(cmp|add|sub|mov|and|or|xor|test|inc|dec|shl|shr|sar) [abcd]x,',o)),
        b8=bool(re.search(r'BYTE PTR|movsx \w+,[abcd][lh]\b|movzx \w+,[abcd][lh]\b|\b(cmp|add|sub|mov|and|or|xor|test|inc|dec) [abcd][lh],',o)),
        sx=bool(re.search(r'movsx',o)), zx=bool(re.search(r'movzx|and \w+,0xff\b|and \w+,0xffff\b',o)),
        w16a=bool(re.search(r'\bWORD PTR|movsx \w+,\w*x\b|movzx \w+,\w*x\b|cwde',a)), b8a=bool(re.search(r'BYTE PTR|movsx \w+,[abcd][lh]\b|movzx \w+,[abcd][lh]\b',a)))
def typ_alts(t,ev,max_alt=4):
    t=re.sub(r'\s+',' ',t.strip()); k=[t]
    def add(x):
        if x not in k: k.append(x)
    if ev.get('w16'):
        if ev.get('sx') or not ev.get('zx'): add('short'); add('unsigned short')
        else: add('unsigned short'); add('short')
    if ev.get('b8'):
        if ev.get('sx') or not ev.get('zx'): add('signed char'); add('unsigned char')
        else: add('unsigned char'); add('signed char')
    if not ev.get('w16') and not ev.get('b8'):   # keine Evidenz: Nachbarbreiten
        if t in ('short','unsigned short'): add('int'); add('unsigned short' if t=='short' else 'short')
        elif t in ('char','signed char','unsigned char'): add('int'); add('signed char'); add('unsigned char')
        else: add('short'); add('unsigned')
    add('int')
    return k[:max_alt]
def als_zeiger(L,blk):
    """Funktion wird irgendwo in der Einheit als Funktionszeiger uebergeben (Typaenderung des Kopfs scheitert dann)."""
    nm=blk['name']
    if not nm: return False
    pat=re.compile(r'[(,=]\s*&?'+re.escape(nm.split('::')[-1])+r'\s*[,);]')
    return any(pat.search(l) for i,l in enumerate(L) if i!=blk['kopf'] and not l.startswith('//'))
def proto_zeile(L,blk,info):
    """Prototypzeile der Funktion in der Einheit (ohne Klassenpraefix), sonst None."""
    if not blk['name'] or '::' in blk['name']: return None
    i=info['unit']['proto'].get(blk['name']); return i if i is not None and i!=blk['kopf'] else None
# ---------- Stufe 3: Typbreite ----------
def op_typ_lokal(L,blk,info):
    ev=info['ev']; out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)(const\s+)?('+TRE+r')(\s+\**\w+.*;)\s*$',L[j])
        if not m or '*' in m.group(4).split('=')[0] or '[' in m.group(4).split('=')[0]: continue
        alts=[{}]+[{j:m.group(1)+(m.group(2) or '')+t+m.group(4)} for t in typ_alts(m.group(3),ev)[1:]]
        s=S('T_LOKAL',3,alts,blk,j,m.group(3))
        if s: out.append(s)
    return out
def op_typ_param(L,blk,info):
    ev=info['ev']; out=[]; k=blk['kopf']; l=L[k]
    if als_zeiger(L,blk): return out
    for typ,st,nm in blk['params']:
        if typ is None or typ not in TYPEN or st: continue
        pat=re.compile(r'(?<![\w])'+re.escape(typ)+r'\s+'+re.escape(nm)+r'(?![\w])')
        if len(pat.findall(l))!=1: continue
        pi=proto_zeile(L,blk,info)
        alts=[{}]+[{k:pat.sub(t+' '+nm,l),**({pi:pat.sub(t+' '+nm,L[pi])} if pi is not None and len(pat.findall(L[pi]))==1 else {})} for t in typ_alts(typ,ev)[1:]]
        s=S('T_PARAM',3,alts,blk,k,nm)
        if s: out.append(s)
    return out
def op_typ_ret(L,blk,info):
    ev=info['ev']; k=blk['kopf']; l=L[k]; rt=blk['rettyp']
    if not rt or rt not in TYPEN or als_zeiger(L,blk): return []
    m=re.match(r'^(\s*(?:static\s+|inline\s+)*)'+re.escape(rt)+r'(\s+)',l)
    if not m: return []
    o=' ; '.join(info['O'][-6:]); ev2=dict(ev)
    if re.search(r'and eax,0xff\b|movzx eax,al|movsx eax,al|\bal\b',o): ev2['b8']=True
    if re.search(r'and eax,0xffff\b|cwde|movzx eax,ax|movsx eax,ax|\bax\b',o): ev2['w16']=True
    pi=proto_zeile(L,blk,info); mp=re.match(r'^(\s*(?:static\s+|inline\s+)*)'+re.escape(rt)+r'(\s+)',L[pi]) if pi is not None else None
    alts=[{}]+[{k:m.group(1)+t+l[m.end(1)+len(rt):],**({pi:mp.group(1)+t+L[pi][mp.end(1)+len(rt):]} if mp else {})} for t in typ_alts(rt,ev2)[1:]]
    s=S('T_RET',3,alts,blk,k,rt); return [s] if s else []
def op_typ_konst(L,blk,info):
    """(short)K / (signed char)K an Vergleichen Variable op Literal (R100)."""
    out=[]
    for j in body(L,blk):
        l=L[j]
        for a0,a1,op,b0,b1 in vergleiche(l):
            a=l[a0:a1]; b=l[b0:b1]
            if not ist_lit(b) or not re.match(r'^'+NAME+'$',a) or a in ('return',): continue
            t=ptyp(blk,a) or ''
            alts=[{},{j:l[:b0]+f'(short){b}'+l[b1:]}]
            if 'char' in t: alts.append({j:l[:b0]+f'(signed char){b}'+l[b1:]})
            s=S('T_KONST',3,alts,blk,j,a)
            if s: out.append(s)
    return out
def op_typ_global(L,blk,info):
    """extern-Deklaration einer im Block benutzten (Nicht-Zeiger-)Globalen anders breit (nur bei WORD/BYTE-Evidenz)."""
    ev=info['ev']; out=[]
    if not (ev['w16'] or ev['b8']): return out
    used=set()
    for j in body(L,blk): used|=set(re.findall(r'\b(d_[0-9a-f]{6})\b',L[j]))
    for v in sorted(used):
        i=info['unit']['ext'].get(v)
        if i is None: continue
        m=re.match(r'^extern\s+(volatile\s+)?((?:(?:unsigned|signed|const)\s+)*\w+)\s+(.*);(.*)$',L[i])
        if not m or re.sub(r'\s+',' ',m.group(2)) not in TYPEN: continue
        namen=[x.strip() for x in m.group(3).split(',')]
        if len(namen)>8: continue
        mine=[x for x in namen if re.sub(r'\[.*','',x).strip()==v]; rest=[x for x in namen if x not in mine]
        if not mine: continue
        alts=[{}]
        for t in typ_alts(m.group(2),ev)[1:]:
            z=(f'extern {m.group(1) or ""}{m.group(2)} {", ".join(rest)};\n' if rest else '')+f'extern {m.group(1) or ""}{t} {", ".join(mine)};'+m.group(4)
            alts.append({i:z})
        s=S('T_GLOBAL',3,alts,blk,blk['start'],v)
        if s: out.append(s)
    return out
def op_typ_aufruf(L,blk,info):
    """Rueckgabetyp eines Aufgerufenen (Prototyp in der Einheit) char/short/int, wenn sein Ergebnis im Block verglichen/zugewiesen wird (R93/R100)."""
    out=[]; seen=set()
    for j in body(L,blk):
        l=L[j]
        for fn,a0,a1 in aufrufe(l):
            fn=fn.split('->')[-1].split('.')[-1]
            if not re.match(r'^f_[0-9a-f]{6}$',fn): continue
            i=info['unit']['proto'].get(fn)
            if i is None or fn in seen: continue
            nach=l[a1+1:a1+6]; vor=l[:l.rfind(fn,0,a0)]
            if not (re.match(r'\s*(==|!=|<|>|<=|>=)',nach) or re.search(r'(if|while)\s*\(\s*!?\s*$',vor) or re.search(r'\b('+TRE+r')\s+\w+\s*=\s*$',vor) or re.search(r'\breturn\s+$',vor)): continue
            seen.add(fn); p=L[i]; mm=re.match(r'^((?:static\s+)?)('+TRE+r')(\s+)',p)
            if not mm: continue
            ev2=dict(info['ev']); o=' ; '.join(info['O'])
            if re.search(r'call \S+ ; (test al,al|and eax,0xff\b|movsx \w+,al|movzx \w+,al)',o): ev2['b8']=True
            if re.search(r'call \S+ ; (cwde|cmp ax,|and eax,0xffff\b|movsx \w+,ax|movzx \w+,ax)',o): ev2['w16']=True
            alts=[{}]+[{i:mm.group(1)+t+p[mm.end(2):]} for t in typ_alts(mm.group(2),ev2)[1:]]
            s=S('T_AUFRUF',3,alts,blk,j,fn)
            if s: out.append(s)
    return out
# ---------- Stufe 2: bekannte Regeln ----------
def op_r91(L,blk,info):
    """R91: Vergleichskonstante/-richtung woertlich: x < K <-> x <= K-1, x >= K <-> x > K-1 (und umgekehrt), K < x <-> x > K."""
    out=[]
    for j in body(L,blk):
        l=L[j]
        for a0,a1,op,b0,b1 in vergleiche(l):
            if op not in ('<','<=','>','>='): continue
            a=l[a0:a1]; b=l[b0:b1]; inv={'<':'>','>':'<','<=':'>=','>=':'<='}[op]
            if ist_lit(b) and not ist_lit(a):
                k=lit(b); fmt=(lambda v: ('0x%x'%v) if b.lower().startswith('0x') and v>=0 else str(v))
                neu={'<':f'{a} <= {fmt(k-1)}','<=':f'{a} < {fmt(k+1)}','>=':f'{a} > {fmt(k-1)}','>':f'{a} >= {fmt(k+1)}'}[op]
                alts=[{},{j:l[:a0]+neu+l[b1:]},{j:l[:a0]+f'{b} {inv} {a}'+l[b1:]}]
            elif ist_lit(a) and not ist_lit(b):
                k=lit(a); neu={'>':f'{b} <= {k-1}','>=':f'{b} < {k+1}','<=':f'{b} > {k-1}','<':f'{b} >= {k+1}'}[op]
                alts=[{},{j:l[:a0]+f'{b} {inv} {a}'+l[b1:]},{j:l[:a0]+neu+l[b1:]}]
            else: continue
            s=S('R91',2,alts,blk,j,op)
            if s: out.append(s)
    return out
def makro_zeilen(info,welche):
    d={'EQ':'#define EQ(x,v) (((x)==(v))?1:0)','EQI':'#define EQI(x,v) (((x)==(v))?1:0)',
       'EQB':'static inline int EQBF(const signed char &x,int v){return x==v;}\n#define EQB(x,v) EQBF((x),(v))'}
    z=[d[w] for w in welche if w not in info['unit']['makros'] and not (w=='EQB' and 'EQBF' in info['unit']['makros'])]
    return '\n'.join(z) if z else None
def op_r92(L,blk,info):
    """R92/R99: globale Flag-Abfrage als Merkvariable: d_x == K <-> EQ(d_x,K) <-> EQB(d_x,K); nur in if/while-Bedingungen."""
    out=[]; first=info['first_mark']
    for j in body(L,blk):
        l=L[j]
        if not re.search(r'\b(if|while)\s*\(',l): continue
        for a0,a1,op,b0,b1 in vergleiche(l):
            a=l[a0:a1]; b=l[b0:b1]
            if op!='==' or not re.match(r'^d_[0-9a-f]{6}(\[[^\]]*\])?$',a) or not ist_lit(b): continue
            alts=[{}]
            for mk,form in (('EQ',f'EQ({a}, {b})'),('EQB',f'EQB({a}, {b})')):
                x={j:l[:a0]+form+l[b1:]}; mz=makro_zeilen(info,[mk])
                if mz: x[('ins',first)]=mz
                alts.append(x)
            s=S('R92',2,alts,blk,j,'==')
            if s: out.append(s)
        for m in re.finditer(r'\b(EQ|EQI|EQB)\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\)',l):
            alts=[{},{j:l[:m.start()]+f'{m.group(2)} == {m.group(3)}'+l[m.end():]}]
            if m.group(1)!='EQB':
                x={j:l[:m.start()]+f'EQB({m.group(2)}, {m.group(3)})'+l[m.end():]}; mz=makro_zeilen(info,['EQB'])
                if mz: x[('ins',first)]=mz
                alts.append(x)
            else:
                x={j:l[:m.start()]+f'EQ({m.group(2)}, {m.group(3)})'+l[m.end():]}; mz=makro_zeilen(info,['EQ'])
                if mz: x[('ins',first)]=mz
                alts.append(x)
            s=S('R92',2,alts,blk,j,'EQ->')
            if s: out.append(s)
    return out
def op_r93(L,blk,info):
    """R93/Nulltest: e == 0 <-> !e <-> 0 == e; e != 0 <-> e <-> 0 != e; !f(..) -> f(..) == 0; if (f(..)) -> f(..) != 0."""
    out=[]
    for j in body(L,blk):
        l=L[j]
        if re.match(r'^\s*(?:const\s+)?('+TRE+r')\s+\w+\s*=',l): continue
        for a0,a1,op,b0,b1 in vergleiche(l):
            a=l[a0:a1]; b=l[b0:b1]
            if op not in ('==','!=') or b!='0' or ist_lit(a): continue
            ist_call='(' in a
            if op=='==': alts=[{},{j:l[:a0]+f'!{a}'+l[b1:]},{j:l[:a0]+f'0 == {a}'+l[b1:]}]
            else: alts=[{},{j:l[:a0]+a+l[b1:]},{j:l[:a0]+f'0 != {a}'+l[b1:]}]
            s=S('R93' if ist_call else 'F_NULL',2 if ist_call else 4,alts,blk,j,op)
            if s: out.append(s)
        for m in re.finditer(r'(?<![\w!=<>])!\s*(?=\w)',l):
            b0,b1=rechts(l,m.end()); e=l[b0:b1]
            if '(' not in e or not re.match(r'^(?:\w+(?:->|\.))*\w+\(',e): continue
            s=S('R93',2,[{},{j:l[:m.start()]+f'{e} == 0'+l[b1:]}],blk,j,'!f')
            if s: out.append(s)
        for m in re.finditer(r'\b(if|while)\s*\(',l):
            b0,b1=rechts(l,m.end()); e=l[b0:b1]
            if b1<len(l) and l[b1]==')' and re.match(r'^(?:\w+(?:->|\.))*f_[0-9a-f]{6}\(',e):
                s=S('R93',2,[{},{j:l[:b0]+f'{e} != 0'+l[b1:]}],blk,j,'f!=0')
                if s: out.append(s)
    return out
def bedingungen(L,blk):
    """Zeile -> {Variable: Wert} aus umschliessendem if (v == K) (nach Einrueckung)."""
    bed={}
    for j in body(L,blk):
        m=re.search(r'\bif\s*\(\s*('+NAME+r')\s*==\s*('+LIT+r')\s*\)',L[j])
        if not m or (m.group(1) not in blk['lokale'] and m.group(1) not in [p[2] for p in blk['params']]): continue
        d=len(ind(L[j]))
        for q in range(j+1,blk['ende']):
            if L[q].strip() and len(ind(L[q]))<=d and not L[q].strip().startswith('}'): break
            if L[q].strip().startswith('}') and len(ind(L[q]))<=d: break
            bed.setdefault(q,{})[m.group(1)]=lit(m.group(2))
    return bed
def op_r109(L,blk,info):
    """R109: return LIT -> return v, wenn eine Lokale v irgendwo im Block den Wert LIT zugewiesen bekommt."""
    out=[]; zuw={}
    for j in body(L,blk):
        for m in re.finditer(r'(?<![\w.>])('+NAME+r')\s*=\s*('+LIT+r')\s*;',L[j]):
            if m.group(1) in blk['lokale']: zuw.setdefault(m.group(1),set()).add(lit(m.group(2)))
    bed=bedingungen(L,blk)
    for j in body(L,blk):
        m=re.search(r'\breturn\s+('+LIT+r')\s*;',L[j])
        if not m: continue
        k=lit(m.group(1)); kand=[v for v,ws in zuw.items() if k in ws]+[v for v,w in bed.get(j,{}).items() if w==k]
        if not kand: continue
        alts=[{}]+[{j:L[j][:m.start(1)]+v+L[j][m.end(1):]} for v in kand[:3]]
        s=S('R109',2,alts,blk,j,str(k))
        if s: out.append(s)
    return out
def op_r88(L,blk,info):
    """R88: Literal-Argument durch die gerade verglichene Variable ersetzen: if (v == K) { ... f(..K..) }; und x = K; f(..K..)."""
    out=[]
    def ersetze(q,k,v):
        for fn,a0,a1 in aufrufe(L[q]):
            if not re.search(r'f_[0-9a-f]{6}$',fn): continue
            for ma in re.finditer(r'(?<![\w.])'+re.escape(k)+r'(?![\w.])',L[q][a0:a1]):
                p=a0+ma.start(); s=S('R88',2,[{},{q:L[q][:p]+v+L[q][p+len(k):]}],blk,q,v)
                if s: out.append(s)
    for j in body(L,blk):
        m=re.search(r'\bif\s*\(\s*('+NAME+r')\s*==\s*('+LIT+r')\s*\)',L[j])
        if m and (m.group(1) in blk['lokale'] or m.group(1) in [p[2] for p in blk['params']]):
            v,k=m.group(1),m.group(2); d=len(ind(L[j]))
            for q in range(j,min(blk['ende'],j+12)):
                if q>j and L[q].strip() and len(ind(L[q]))<=d: break
                ersetze(q,k,v)
        m=re.match(r'^\s*('+NAME+r')\s*=\s*('+LIT+r')\s*;\s*$',L[j])
        if m and m.group(1) in blk['lokale'] and j+1<blk['ende']: ersetze(j+1,m.group(2),m.group(1))
    return out
def op_r110(L,blk,info):
    """R110: Feldwert vor if (x) f(x) als Lokale: if (p->f) f_x(p->f); -> { int t = p->f; if (t) f_x(t); }"""
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)if\s*\(\s*([\w>.\-\[\]]+)\s*\)\s*((?:\w+(?:->|\.))*f_[0-9a-f]{6}\()([^;]*)\)\s*;\s*$',L[j])
        if not m or '(' in m.group(2): continue
        e=m.group(2); i=m.group(1); args=m.group(4)
        if e not in args: continue
        alts=[{}]+[{j:f'{i}{{ {t} t_{j} = ({t})({e}); if (t_{j}) {m.group(3)}{args.replace(e,"t_%d"%j)}); }}'} for t in ('int','void *','char *')]
        s=S('R110',2,alts,blk,j,e)
        if s: out.append(s)
    return out
def op_volatile(L,blk,info):
    """R49/R53: Globale, die im Block eine Konstante zugewiesen bekommt, volatile deklarieren."""
    out=[]; seen=set()
    for j in body(L,blk):
        for m in re.finditer(r'(?<![\w.>])(d_[0-9a-f]{6})\s*=\s*'+LIT+r'\s*;',L[j]):
            v=m.group(1); i=info['unit']['ext'].get(v)
            if i is None or v in seen: continue
            seen.add(v); l=L[i]; mm=re.match(r'^extern\s+(volatile\s+)?((?:(?:unsigned|signed|const)\s+)*\w+)\s+(.*);(.*)$',l)
            if not mm or mm.group(1): continue
            namen=[x.strip() for x in mm.group(3).split(',')]
            mine=[x for x in namen if re.sub(r'\[.*','',x).strip()==v]; rest=[x for x in namen if x not in mine]
            if not mine: continue
            z=(f'extern {mm.group(2)} {", ".join(rest)};\n' if rest else '')+f'extern volatile {mm.group(2)} {", ".join(mine)};'+mm.group(4)
            s=S('R49',2,[{},{i:z}],blk,j,v)
            if s: out.append(s)
    return out
def op_inline(L,blk,info):
    """Inlining: Original ruft, wir inlinen -> #pragma inline_depth(0) um den Block."""
    if 'INLINE' not in info['tags']: return []
    a={('ins',blk['mark']):'#pragma inline_depth(0)',('ins',blk['ende']+1):'#pragma inline_depth(3)'}
    s=S('INLINE0',2,[{},a],blk,blk['start'],''); return [s] if s else []
# ---------- Stufe 4: Ausdrucksform ----------
def op_zwischen(L,blk,info):
    """Zwischenvariable ein: if (f(..) op K) -> T t = f(..); if (t op K) (T short mit (short)K = R100, int); aus: T v = f(..); if (v op X) -> if (f(..) op X)."""
    out=[]
    for j in body(L,blk):
        l=L[j]; m=re.match(r'^(\s*)if\s*\(',l)
        if m:
            vg=vergleiche(l)
            if len(vg)==1:
                a0,a1,op,b0,b1=vg[0]; a=l[a0:a1]; b=l[b0:b1]; i=m.group(1)
                if '(' in a and re.match(r'^(?:\w+(?:->|\.))*\w+\(',a) and ist_lit(b) and l[b1:].startswith(')'):
                    rest=l[b1+1:]
                    alts=[{},{j:f'{i}short t_{j} = {a};\n{i}if (t_{j} {op} (short){b}){rest}'},{j:f'{i}int t_{j} = {a};\n{i}if (t_{j} {op} {b}){rest}'},{j:f'{i}short t_{j} = {a};\n{i}if (t_{j} {op} {b}){rest}'}]
                    s=S('F_ZWISCHEN',4,alts,blk,j,'ein')
                    if s: out.append(s)
        m=re.match(r'^(\s*)('+TRE+r')\s+(\w+)\s*=\s*((?:\w+(?:->|\.))*f_[0-9a-f]{6}\(.*\))\s*;\s*$',l)
        if m and j+1<blk['ende']:
            v=m.group(3); n2=L[j+1]; cnt=sum(len(re.findall(r'\b'+re.escape(v)+r'\b',L[q])) for q in body(L,blk))
            mm=re.match(r'^(\s*)if\s*\(\s*'+re.escape(v)+r'\s*(==|!=|<|>|<=|>=)\s*([^()]+?)\s*\)(.*)$',n2)
            if mm and cnt==2:
                s=S('F_ZWISCHEN',4,[{},{j:'',j+1:f'{mm.group(1)}if ({m.group(4)} {mm.group(2)} {mm.group(3)}){mm.group(4)}'}],blk,j,'aus')
                if s: out.append(s)
            mm=re.match(r'^(\s*)return\s+'+re.escape(v)+r'\s*;\s*$',n2)
            if mm and cnt==2:
                s=S('F_TAIL',4,[{},{j:'',j+1:f'{mm.group(1)}return {m.group(4)};'}],blk,j,'aus')
                if s: out.append(s)
    return out
def op_tern(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]; m=re.match(r'^(\s*)([\w>.\-\[\]\*\(\)]+)\s*=\s*([^?;]+?)\s*\?\s*([^:;]+?)\s*:\s*([^;]+?)\s*;\s*$',l)
        if m and not l.strip().startswith(('if','while','for','return')) and '::' not in l:
            i,x,c,a,b=m.groups()
            alts=[{},{j:f'{i}if ({c}) {x} = {a}; else {x} = {b};'},{j:f'{i}if ({c}) {{\n{i}    {x} = {a};\n{i}}} else {{\n{i}    {x} = {b};\n{i}}}'}]
            s=S('F_TERN',4,alts,blk,j,'?:->if')
            if s: out.append(s)
        m=re.match(r'^(\s*)if\s*\((.*)\)\s*([\w>.\-\[\]\*]+)\s*=\s*([^;]+);\s*else\s+\3\s*=\s*([^;]+);\s*$',l)
        if m:
            i,c,x,a,b=m.groups()
            alts=[{},{j:f'{i}{x} = ({c}) ? {a} : {b};'},{j:f'{i}if ({c}) {{\n{i}    {x} = {a};\n{i}}} else {{\n{i}    {x} = {b};\n{i}}}'},{j:f'{i}{x} = {b};\n{i}if ({c}) {x} = {a};'},{j:f'{i}{x} = {a};\n{i}if (!({c})) {x} = {b};'}]
            s=S('F_TERN',4,alts,blk,j,'if-else->')
            if s: out.append(s)
        m=re.match(r'^(\s*)return\s+([^?;]+?)\s*\?\s*([^:;]+?)\s*:\s*([^;]+?)\s*;\s*$',l)
        if m and '::' not in l:
            i,c,a,b=m.groups(); alts=[{},{j:f'{i}if ({c}) return {a};\n{i}return {b};'}]
            s=S('F_TERN',4,alts,blk,j,'return ?:')
            if s: out.append(s)
        if j+4<blk['ende']+1:
            m1=re.match(r'^(\s*)if\s*\((.*)\)\s*\{\s*$',L[j])
            if m1 and L[j+2].strip()=='} else {' and L[j+4].strip()=='}':
                a=re.match(r'^\s*([\w>.\-\[\]\*]+)\s*=\s*([^;]+);\s*$',L[j+1]); b=re.match(r'^\s*([\w>.\-\[\]\*]+)\s*=\s*([^;]+);\s*$',L[j+3])
                if a and b and a.group(1)==b.group(1):
                    i=m1.group(1); s=S('F_TERN',4,[{},{j:f'{i}{a.group(1)} = ({m1.group(2)}) ? {a.group(2)} : {b.group(2)};',j+1:'',j+2:'',j+3:'',j+4:''}],blk,j,'if->?:')
                    if s: out.append(s)
                ra=re.match(r'^\s*return\s+([^;]+);\s*$',L[j+1]); rb=re.match(r'^\s*return\s+([^;]+);\s*$',L[j+3])
                if ra and rb:
                    i=m1.group(1); s=S('F_TERN',4,[{},{j:f'{i}return ({m1.group(2)}) ? {ra.group(1)} : {rb.group(1)};',j+1:'',j+2:'',j+3:'',j+4:''}],blk,j,'if->return ?:')
                    if s: out.append(s)
        m=re.match(r'^(\s*)if\s*\((.*)\)\s*return\s+([^;]+);\s*$',L[j])
        if m and j+1<blk['ende'] and re.match(r'^\s*return\s+([^;]+);\s*$',L[j+1]) and len(ind(L[j+1]))==len(m.group(1)):
            rb=re.match(r'^\s*return\s+([^;]+);\s*$',L[j+1]); i=m.group(1)
            s=S('F_TERN',4,[{},{j:f'{i}return ({m.group(2)}) ? {m.group(3)} : {rb.group(1)};',j+1:''}],blk,j,'if return->?:')
            if s: out.append(s)
    return out
def op_cmpflip(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]
        if not re.search(r'\b(if|while|for)\s*\(|\?',l): continue
        for a0,a1,op,b0,b1 in vergleiche(l):
            a=l[a0:a1]; b=l[b0:b1]
            if ist_lit(a) or ist_lit(b): continue
            inv={'<':'>','>':'<','<=':'>=','>=':'<=','==':'==','!=':'!='}[op]
            s=S('F_CMPFLIP',4,[{},{j:l[:a0]+f'{b} {inv} {a}'+l[b1:]}],blk,j,op)
            if s: out.append(s)
    return out
def op_opassign(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]
        if l.strip().startswith('for'): continue
        m=re.search(r'(?<![\w.>\]])([\w>.\-\[\]\*\(\)]+?)\s*([+\-*|&^])=\s*([^;]+);',l)
        if m:
            x,op,y=m.groups(); alts=[{},{j:l[:m.start()]+f'{x} = {x} {op} {y};'+l[m.end():]}]
            mk=re.match(r'^-\s*('+LIT+')$',y.strip())
            if mk and op in '+-': alts.append({j:l[:m.start()]+f'{x} {"-" if op=="+" else "+"}= {mk.group(1)};'+l[m.end():]})
            if y.strip()=='1' and op in '+-': alts.append({j:l[:m.start()]+f'{x}{op}{op};'+l[m.end():]}); alts.append({j:l[:m.start()]+f'{op}{op}{x};'+l[m.end():]})
            s=S('F_OPASSIGN',4,alts,blk,j,op+'=')
            if s: out.append(s)
        m=re.search(r'(?<![\w.>\]])([\w>.\-\[\]\*\(\)]+?)\s*=\s*\1\s*([+\-*|&^])\s*([^;]+);',l)
        if m:
            x,op,y=m.groups(); alts=[{},{j:l[:m.start()]+f'{x} {op}= {y};'+l[m.end():]}]
            if y.strip()=='1' and op in '+-': alts.append({j:l[:m.start()]+f'{x}{op}{op};'+l[m.end():]})
            s=S('F_OPASSIGN',4,alts,blk,j,'x=x op')
            if s: out.append(s)
        m=re.match(r'^(\s*)([\w>.\-\[\]\*\(\)]+?)(\+\+|--)\s*;\s*$',l) or re.match(r'^(\s*)(\+\+|--)([\w>.\-\[\]\*\(\)]+?)\s*;\s*$',l)
        if m:
            g=m.groups(); i=g[0]; x=g[1] if g[1] not in ('++','--') else g[2]; op=g[2] if g[2] in ('++','--') else g[1]
            alts=[{},{j:f'{i}{x} {op[0]}= 1;'},{j:f'{i}{x} = {x} {op[0]} 1;'},{j:f'{i}{op}{x};'},{j:f'{i}{x}{op};'}]
            s=S('F_OPASSIGN',4,alts,blk,j,op)
            if s: out.append(s)
    return out
def einfach(l):
    s=l.strip()
    return bool(re.match(r'^\*?[\w>.\-\[\]\(\)]+\s*(=|[+\-*|&^]=)\s*[^;{}]+;$',s) or re.match(r'^\w+\([^;()]*\)\s*(=|[+\-*|&^]=)\s*[^;{}]+;$',s) or re.match(r'^(?:\w+(?:->|\.))*\w+\([^;{}]*\);$',s)) and not s.startswith(('if','while','for','return','else','delete','new'))
def lhs(l):
    m=re.match(r'^\s*\*?([\w>.\-\[\]]+)\s*(=|[+\-*|&^]=)',l) or re.match(r'^\s*\w+\(\s*([\w>.\-\[\]]+)[^;()]*\)\s*(=|[+\-*|&^]=)',l); return m.group(1) if m else None
def op_assoz(L,blk,info):
    """Klammerung einer Dreierkette: x = A + B - C -> x = A + (B - C), x = (A + B) - C, x = B + A - C."""
    out=[]
    for j in body(L,blk):
        l=L[j]; m=re.match(r'^(\s*)([^=;]+?)\s*=\s*(.+);\s*$',l)
        if not m or l.strip().startswith(('if','while','for','return')) or '==' in l: continue
        i,x,e=m.groups(); ops=[mm for mm in re.finditer(r'\s([+\-])\s',e)]
        if len(ops)!=2: continue
        a=e[:ops[0].start()].strip(); o1=ops[0].group(1); b=e[ops[0].end():ops[1].start()].strip(); o2=ops[1].group(1); c=e[ops[1].end():].strip()
        if not a or not b or not c or any(('(' in q)!=(')' in q) for q in (a,b,c)): continue
        o2i={'+':'-','-':'+'}[o2]
        alts=[{},{j:f'{i}{x} = {a} {o1} ({b} {o2 if o1=="+" else o2i} {c});'},{j:f'{i}{x} = ({a} {o1} {b}) {o2} {c};'}]
        if o1=='+': alts.append({j:f'{i}{x} = {b} + {a} {o2} {c};'})
        s=S('F_ASSOZ',4,alts,blk,j,'')
        if s: out.append(s)
    return out
def op_swap2(L,blk,info):
    """Lade-Reihenfolge: zwei aufeinanderfolgende einfache Anweisungen ohne gemeinsame Namen tauschen."""
    out=[]
    for j in body(L,blk):
        if j+1>=blk['ende'] or not einfach(L[j]) or not einfach(L[j+1]) or ind(L[j])!=ind(L[j+1]): continue
        w1=set(re.findall(r'\b[A-Za-z_]\w*\b',L[j])); w2=set(re.findall(r'\b[A-Za-z_]\w*\b',L[j+1]))
        a,b=lhs(L[j]),lhs(L[j+1])
        if (a and re.split(r'->|\.|\[',a)[0] in w2) or (b and re.split(r'->|\.|\[',b)[0] in w1): continue
        if '(' in L[j] and '(' in L[j+1]: continue   # zwei Aufrufe: Nebenwirkungen
        s=S('F_SWAP2',4,[{},{j:L[j+1],j+1:L[j]}],blk,j,'')
        if s: out.append(s)
    return out
def op_multiassign(L,blk,info):
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)(\*?[\w>.\-\[\]]+)\s*=\s*(\*?[\w>.\-\[\]]+)\s*=\s*([^;=]+);\s*$',L[j])
        if m:
            i,x,y,n=m.groups()
            alts=[{},{j:f'{i}{y} = {n};\n{i}{x} = {n};'},{j:f'{i}{x} = {n};\n{i}{y} = {n};'},{j:f'{i}{y} = {x} = {n};'},{j:f'{i}{y} = {n};\n{i}{x} = {y};'}]
            s=S('F_MULTI',4,alts,blk,j,'x=y=n')
            if s: out.append(s)
        m=re.match(r'^(\s*)(\*?[\w>.\-\[\]]+)\s*=\s*('+LIT+r')\s*;\s*$',L[j])
        if m and j+1<blk['ende']:
            m2=re.match(r'^(\s*)(\*?[\w>.\-\[\]]+)\s*=\s*'+re.escape(m.group(3))+r'\s*;\s*$',L[j+1])
            if m2 and m2.group(1)==m.group(1) and m2.group(2)!=m.group(2):
                s=S('F_MULTI',4,[{},{j:f'{m.group(1)}{m2.group(2)} = {m.group(2)} = {m.group(3)};',j+1:''},{j:f'{m.group(1)}{m.group(2)} = {m2.group(2)} = {m.group(3)};',j+1:''}],blk,j,'->x=y=n')
                if s: out.append(s)
    return out
def op_tail(L,blk,info):
    """Tail: letzte Anweisung f(..); in void-Funktion <-> return f(..); ; return f(..) <-> T r = f(..); return r;"""
    out=[]; e=blk['ende']; rt=blk['rettyp']
    if rt is None: return out
    for j in body(L,blk):
        l=L[j]; m=re.match(r'^(\s*)return\s+((?:\w+(?:->|\.))*f_[0-9a-f]{6}\(.*\))\s*;\s*$',l)
        if m and rt!='void':
            i=m.group(1); s=S('F_TAIL',4,[{},{j:f'{i}{rt} r_{j} = {m.group(2)};\n{i}return r_{j};'}],blk,j,'return f->r')
            if s: out.append(s)
        if m and rt=='void':   # Watcom: 'return f();' in void-Funktion ist Fehler E056 -> nur Rueckrichtung
            s=S('F_TAIL',4,[{},{j:f'{m.group(1)}{m.group(2)};\n{m.group(1)}return;'}],blk,j,'void return f')
            if s: out.append(s)
    return out
def op_forinc(L,blk,info):
    """for-Inkrement: letzte Anweisung des Schleifenrumpfs in den for-Kopf (Komma) und umgekehrt; i = i + 1 <-> i++ im Kopf."""
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)for\s*\((.*);(.*);(.*)\)\s*\{\s*$',L[j])
        if not m: continue
        i=m.group(1); e=None
        for q in range(j+1,blk['ende']+1):
            if L[q].rstrip()==i+'}': e=q; break
        if e is None or e-1<=j: continue
        inc=m.group(4).strip(); last=L[e-1]
        if einfach(last) and len(ind(last))==len(i)+4 and '(' not in last:
            st=last.strip()[:-1]
            out.append(S('F_FORINC',4,[{},{j:f'{i}for ({m.group(2).strip()}; {m.group(3).strip()}; {inc}, {st}) {{',e-1:''}],blk,j,'rein'))
        if ',' in inc:
            a,b=inc.rsplit(',',1)
            out.append(S('F_FORINC',4,[{},{j:f'{i}for ({m.group(2).strip()}; {m.group(3).strip()}; {a.strip()}) {{',e-1:L[e-1]+f'\n{i}    {b.strip()};'}],blk,j,'raus'))
        mi=re.match(r'^(\w+)\s*=\s*\1\s*([+-])\s*1$',inc)
        if mi: out.append(S('F_FORINC',4,[{},{j:f'{i}for ({m.group(2).strip()}; {m.group(3).strip()}; {mi.group(1)}{mi.group(2)}{mi.group(2)}) {{'},{j:f'{i}for ({m.group(2).strip()}; {m.group(3).strip()}; {mi.group(1)} {mi.group(2)}= 1) {{'}],blk,j,'i=i+1'))
        mi=re.match(r'^(\w+)(\+\+|--)$',inc) or re.match(r'^(\+\+|--)(\w+)$',inc)
        if mi:
            v=mi.group(1) if mi.group(1) not in ('++','--') else mi.group(2); o=mi.group(2) if mi.group(2) in ('++','--') else mi.group(1)
            out.append(S('F_FORINC',4,[{},{j:f'{i}for ({m.group(2).strip()}; {m.group(3).strip()}; {v} = {v} {o[0]} 1) {{'},{j:f'{i}for ({m.group(2).strip()}; {m.group(3).strip()}; {v} {o[0]}= 1) {{'}],blk,j,'i++'))
    return [s for s in out if s]
def op_komm(L,blk,info):
    """Kommutative Operanden tauschen: x = A + B <-> x = B + A (auch *, &, |, ^), rechts einer Zuweisung oder in Argumenten."""
    out=[]
    for j in body(L,blk):
        l=L[j]
        if l.strip().startswith(('for','if','while')) or '=' not in l: continue
        for m in re.finditer(r'(?<![+\-*&|^=<>!])\s([+*&|^])\s(?![=])',l):
            a0,a1=links(l,m.start()); b0,b1=rechts(l,m.end()); a=l[a0:a1]; b=l[b0:b1]
            if not a or not b or a==b or (a1<len(l) and a1>m.start()): continue
            if (l[a0-1:a0]=='*' and a0>0) or ((ist_lit(a) or ist_lit(b)) and l[a0-1:a0]=='(' and l[b1:b1+1]==')'): continue
            s=S('F_KOMM',4,[{},{j:l[:a0]+f'{b} {m.group(1)} {a}'+l[b1:]}],blk,j,m.group(1))
            if s: out.append(s)
    return out
def op_elseif(L,blk,info):
    """R109b: fruehes return V im if-Block vor einem zweiten if, Funktion endet mit return V -> ein return: } else if (..) {"""
    out=[]; e=blk['ende']
    me=re.match(r'^\s*return\s+([^;]+);\s*$',L[e-1]) if e-1>blk['start'] else None
    if not me: return out
    V=me.group(1).strip(); bed=bedingungen(L,blk)
    for j in body(L,blk):
        m=re.match(r'^(\s*)return\s+([^;]+);\s*$',L[j])
        if not m or j+2>=e: continue
        W=m.group(2).strip()
        if W!=V and not (ist_lit(W) and bed.get(j,{}).get(V)==lit(W)): continue
        i=ind(L[j+1])
        if L[j+1].rstrip()!=i+'}' or len(i)+4!=len(m.group(1)): continue
        m2=re.match(r'^'+re.escape(i)+r'if\s*\((.*)\)\s*\{\s*$',L[j+2])
        if not m2: continue
        s=S('R109',2,[{},{j:'',j+1:'',j+2:f'{i}}} else if ({m2.group(1)}) {{'}],blk,j,'else-if')
        if s: out.append(s)
    return out
# ---------- Stufe 5: Gleichstand ----------
def op_r108(L,blk,info):
    """R108: Reihenfolge der Deklarationszeilen im Kopfblock permutieren (bis 5 Alternativen)."""
    decl=[]
    for j in body(L,blk):
        if re.match(r'^\s*(?:const\s+)?(?:'+TRE+r'|\w+\s*\*|\w+)\s+\**\w+(\s*=\s*[^;]+)?\s*;\s*$',L[j]) and not re.match(r'^\s*return\b',L[j]) and (re.match(r'^\s*(?:const\s+)?('+TRE+r')\b',L[j]) or re.match(r'^\s*\w+\s*\*\s*\w+',L[j])): decl.append(j)
        elif L[j].strip(): break
    if len(decl)<2 or any('(' in L[j] for j in decl): return []
    perms=list(itertools.permutations(decl))[1:]
    import random,os; random.Random(int(os.environ.get('SUCHE_SEED','1'))*1000+len(decl)).shuffle(perms); perms=perms[:5]
    alts=[{}]+[{decl[i]:L[p[i]] for i in range(len(decl)) if p[i]!=decl[i]} for p in perms]
    s=S('R108',5,alts,blk,decl[0],str(len(decl))); return [s] if s else []
def op_r102(L,blk,info):
    """R102/Initialisierer: T x = e; <-> T x; x = e; (Kopfblock) und Deklaration aus innerem Block nach oben."""
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)(?:const\s+)?('+TRE+r'|\w+\s*\*)\s*(\w+)\s*=\s*([^;]+);\s*$',L[j])
        if not m: continue
        i,t,v,e=m.groups()
        if len(i)<=4: out.append(S('R102',5,[{},{j:f'{i}{t} {v};\n{i}{v} = {e};'}],blk,j,'init->zuw'))
        else:
            top=blk['start']+1; out.append(S('R102',5,[{},{j:f'{i}{v} = {e};',('ins',top):f'    {t} {v};'}],blk,j,'hoch'))
    return [s for s in out if s]
ALLE=[op_r91,op_r92,op_r93,op_r109,op_r88,op_r110,op_volatile,op_inline,
      op_typ_lokal,op_typ_param,op_typ_ret,op_typ_konst,op_typ_global,op_typ_aufruf,
      op_elseif,op_zwischen,op_tern,op_cmpflip,op_opassign,op_swap2,op_multiassign,op_tail,op_forinc,op_komm,op_assoz,
      op_r108,op_r102]
def stellen(L,blk,info):
    out=[]
    for f in ALLE:
        try: out+= [s for s in f(L,blk,info) if s]
        except Exception as ex: info.setdefault('fehler',[]).append(f'{f.__name__}: {ex}')
    return out
def render(L,wahl):
    """wahl: Liste von alts-Dicts -> neue Zeilenliste."""
    rep={}; ins={}
    for a in wahl:
        for k,v in a.items():
            if isinstance(k,int): rep[k]=v
            else: ins.setdefault(k[1],[]).append(v)
    out=[]
    for i,l in enumerate(L):
        if i in ins: out+=ins[i]
        if i in rep:
            if rep[i]!='': out.append(rep[i])
        else: out.append(l)
    if len(L) in ins: out+=ins[len(L)]
    return out

# ======================================================================================================================
# Neue Operatoren (worker, 23.10.2026) - Anhang zu operatoren.py. Quelle der Muster: Cluster des Diff-Korpus
# (diff corpus) und funde.txt. Jeder op_* liefert Stellen wie oben; alts[0] = {} bleibt die Basis.
# ======================================================================================================================
SIMPLE=r'[\w>.\-\[\]]+'            # einfacher Operand (Name, Feld, Index)
def ist_name(s): return bool(re.match(r'^'+NAME+'$',s.strip()))
def block_ende(L,j,blk):
    """Zeile j endet mit '{' -> Index der schliessenden '}' gleicher Einrueckung (oder '} else'), sonst None."""
    i=ind(L[j])
    for q in range(j+1,blk['ende']+1):
        if L[q].startswith(i+'}') and len(ind(L[q]))==len(i): return q
    return None
def verwendungen(L,blk,v,von=None):
    pat=re.compile(r'(?<![\w.>])'+re.escape(v)+r'(?![\w])')
    return [j for j in body(L,blk) if (von is None or j>=von) and pat.search(L[j])]
def neg(c):
    """Bedingung verneinen: einzelner Vergleich -> Operator drehen, !x -> x, sonst !(c)."""
    c=c.strip(); vg=vergleiche(c)
    if len(vg)==1 and '&&' not in c and '||' not in c:
        a0,a1,op,b0,b1=vg[0]
        if a0==0 and b1==len(c): return c[:a1]+' '+{'==':'!=','!=':'==','<':'>=','>':'<=','<=':'>','>=':'<'}[op]+' '+c[b0:]
    if re.match(r'^!\s*'+NAME+r'$',c): return c[1:].strip()
    if re.match(r'^!\s*\(.*\)$',c) and c.count('(')==1: return c[2:-1]
    if re.match(r'^'+SIMPLE+r'$',c): return '!'+c
    return f'!({c})'
def ist_zeiger(L,blk,v):
    """Name v ist als Zeiger deklariert (Lokale mit *, Zeigerparameter)?"""
    if v in blk['lokale']: return bool(re.search(r'\*\s*'+re.escape(v)+r'(?![\w])',L[blk['lokale'][v][1]]))
    return any(nm==v and st for t,st,nm in blk['params'])
# ---------- R92X: EQ-Makro um beliebige Vergleiche in Bedingungen (sete/and-Muster des Originals) ----------
def op_eq_x(L,blk,info):
    out=[]; first=info['first_mark']
    for j in body(L,blk):
        l=L[j]
        if not re.search(r'\b(if|while)\s*\(|\?',l) or 'EQ' in l: continue
        mk0=re.search(r'\b(if|while)\s*\(',l); kl=None
        if mk0:
            d=0
            for p in range(mk0.end()-1,len(l)):
                d+=(l[p]=='(')-(l[p]==')')
                if d==0: kl=p; break
        cpp=not any(re.match(r'^// CC wcc386',z) for z in L[:40])
        for a0,a1,op,b0,b1 in vergleiche(l):
            a=l[a0:a1]; b=l[b0:b1]
            if op not in ('==','!=') or not ist_lit(b) or ist_lit(a): continue
            if mk0 and not (mk0.end()<=a0 and (kl is None or b1<=kl)): continue
            if re.match(r'^d_[0-9a-f]{6}$',a) and op=='==': continue      # das macht R92
            t=ptyp(blk,a) if ist_name(a) else None
            eqb=cpp and ((t and 'char' in t) or re.match(r'^d_[0-9a-f]{6}$',a))
            alts=[{}]
            for mk in (('EQ','EQB') if eqb else ('EQ',)):
                form=f'{mk}({a}, {b})' if op=='==' else f'!{mk}({a}, {b})'
                x={j:l[:a0]+form+l[b1:]}; mz=makro_zeilen(info,[mk])
                if mz: x[('ins',first)]=mz
                alts.append(x)
            s=S('R92X',2,alts,blk,j,op)
            if s: out.append(s)
    return out
# ---------- F_RELOC: Datenadresse als Literal -> (int)&d_xxxxxx (Reloc statt Konstante) ----------
def op_reloc(L,blk,info):
    out=[]; first=info['first_mark']
    for j in body(L,blk):
        l=L[j]
        for m in re.finditer(r'(?<![\w.])0x(1[9abcd][0-9a-f]{4})(?![\w])',l):
            if l[:m.start()].rstrip().endswith(('&','d_')): continue
            v='d_'+m.group(1); x={j:l[:m.start()]+f'(int)&{v}'+l[m.end():]}
            if v not in info['unit']['ext'] and not re.search(r'\b'+v+r'\b',' '.join(L[:blk['mark']])): x[('ins',first)]=f'extern char {v}[];'
            s=S('F_RELOC',2,[{},x],blk,j,v)
            if s: out.append(s)
    return out
# ---------- F_SHLMUL: x * 2^k <-> x << k ----------
def op_shlmul(L,blk,info):
    out=[]; P={'2':'1','4':'2','8':'3','16':'4','0x10':'4','32':'5','0x20':'5'}; Q={v:k for k,v in P.items() if not k.startswith('0x')}
    for j in body(L,blk):
        l=L[j]
        if l.strip().startswith(('//','#')): continue
        for m in re.finditer(r'\s\*\s(2|4|8|16|0x10|32|0x20)(?![\w.])',l):
            a0,a1=links(l,m.start())
            if not l[a0:a1] or (ist_name(l[a0:a1]) and ist_zeiger(L,blk,l[a0:a1])): continue
            s=S('F_SHLMUL',4,[{},{j:l[:a0]+f'({l[a0:a1]} << {P[m.group(1)]})'+l[m.end():]},{j:l[:a0]+f'{l[a0:a1]} << {P[m.group(1)]}'+l[m.end():]}],blk,j,'*->'+'<<')
            if s: out.append(s)
        for m in re.finditer(r'\s<<\s([1-5])(?![\w.])',l):
            a0,a1=links(l,m.start())
            if not l[a0:a1]: continue
            s=S('F_SHLMUL',4,[{},{j:l[:a0]+f'{l[a0:a1]} * {Q[m.group(1)]}'+l[m.end():]}],blk,j,'<<->*')
            if s: out.append(s)
    return out
# ---------- F_NEGK: x -= K <-> x += -K; x = x - K -> x = x + -K ----------
def op_negk(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]
        m=re.search(r'(?<![\w.>\]])('+SIMPLE+r')\s*-=\s*('+LIT+r')\s*;',l)
        if m and not m.group(2).startswith('-'):
            s=S('F_NEGK',4,[{},{j:l[:m.start()]+f'{m.group(1)} += -{m.group(2)};'+l[m.end():]}],blk,j,'-=')
            if s: out.append(s)
        m=re.search(r'(?<![\w.>\]])('+SIMPLE+r')\s*=\s*\1\s*-\s*('+LIT+r')\s*;',l)
        if m and not m.group(2).startswith('-'):
            s=S('F_NEGK',4,[{},{j:l[:m.start()]+f'{m.group(1)} = {m.group(1)} + -{m.group(2)};'+l[m.end():]}],blk,j,'x=x-K')
            if s: out.append(s)
    return out
# ---------- F_ANDTEMP: if (E & K) -> Maskenwert in Lokale (and statt test) ----------
def op_andtemp(L,blk,info):
    out=[]; top=blk['start']+1
    for j in body(L,blk):
        l=L[j]; m=re.search(r'\b(if|while)\s*\(\s*(!?)\s*\(?\s*('+SIMPLE+r')\s*&\s*('+LIT+r')\s*\)?\s*(==\s*0|!=\s*0)?\s*\)',l)
        if not m: continue
        e,k=m.group(3),m.group(4); null=(m.group(2)=='!') or (m.group(5) or '').startswith('==')
        alts=[{}]
        for t in ('signed char','unsigned char','int','short'):
            alts.append({j:l[:m.start()]+f'{m.group(1)} ((t_{j} = {e} & {k}) {"==" if null else "!="} 0)'+l[m.end():],('ins',top):f'    {t} t_{j};'})
        s=S('F_ANDTEMP',4,alts,blk,j,e)
        if s: out.append(s)
    return out
# ---------- F_LEA: v = e +- K  <->  v = e; v +-= K (lea gegen mov/add) ----------
def op_lea(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]; m=re.match(r'^(\s*)((?:(?:'+TRE+r')\s+)?)('+SIMPLE+r')\s*=\s*('+SIMPLE+r')\s*([+-])\s*('+LIT+r')\s*;\s*$',l)
        if m and not ist_lit(m.group(4)) and m.group(3)!=m.group(4):
            i,t,v,e,o,k=m.groups(); alts=[{},{j:f'{i}{t}{v} = {e};\n{i}{v} {o}= {k};'}]
            if k=='1': alts.append({j:f'{i}{t}{v} = {e};\n{i}{v}{o}{o};'})
            s=S('F_LEA',4,alts,blk,j,'split')
            if s: out.append(s)
        m=re.match(r'^(\s*)((?:(?:'+TRE+r')\s+)?)('+SIMPLE+r')\s*=\s*('+SIMPLE+r')\s*;\s*$',l)
        if m and j+1<blk['ende']:
            i,t,v,e=m.groups(); n=L[j+1]
            m2=re.match(r'^'+re.escape(i)+re.escape(v)+r'\s*([+-])=\s*('+LIT+r')\s*;\s*$',n) or re.match(r'^'+re.escape(i)+re.escape(v)+r'(\+\+|--)\s*;\s*$',n)
            if m2:
                o=m2.group(1)[0]; k=m2.group(2) if len(m2.groups())>1 else '1'
                s=S('F_LEA',4,[{},{j:f'{i}{t}{v} = {e} {o} {k};',j+1:''}],blk,j,'join')
                if s: out.append(s)
    return out
# ---------- F_WHILE2FOR: while (c) { ...; i++; } <-> for (; c; i++) { ... }  und for (init; ..) <-> init; for (; ..) ----------
def op_while2for(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]; i=ind(l)
        m=re.match(r'^(\s*)while\s*\((.*)\)\s*\{\s*$',l)
        if m:
            e=block_ende(L,j,blk)
            if e and e-1>j and einfach(L[e-1]) and '(' not in L[e-1] and len(ind(L[e-1]))==len(i)+4:
                st=L[e-1].strip()[:-1]
                s=S('F_WHILE2FOR',4,[{},{j:f'{i}for (; {m.group(2)}; {st}) {{',e-1:''}],blk,j,'while->for')
                if s: out.append(s)
        m=re.match(r'^(\s*)for\s*\((.*?);(.*?);(.*?)\)\s*\{\s*$',l)
        if m:
            init,c,inc=[x.strip() for x in m.groups()[1:]]; e=block_ende(L,j,blk)
            if e and inc and c and ',' not in inc:
                alts=[{}]
                if not init: alts.append({j:f'{i}while ({c}) {{',e-1:L[e-1]+f'\n{i}    {inc};'})
                if init and not re.match(r'^('+TRE+r')\s',init): alts.append({j:f'{i}{init};\n{i}for (; {c}; {inc}) {{'})
                mi=re.match(r'^('+TRE+r')\s+(\w+)\s*=\s*(.+)$',init)
                if mi: alts.append({j:f'{i}{mi.group(1)} {mi.group(2)} = {mi.group(3)};\n{i}for (; {c}; {inc}) {{'}); alts.append({j:f'{i}{mi.group(1)} {mi.group(2)};\n{i}{mi.group(2)} = {mi.group(3)};\n{i}for (; {c}; {inc}) {{'})
                s=S('F_WHILE2FOR',4,alts,blk,j,'for')
                if s: out.append(s)
        m=re.match(r'^(\s*)('+SIMPLE+r')\s*=\s*([^;]+);\s*$',l)
        if m and j+1<blk['ende']:
            m2=re.match(r'^'+re.escape(i)+r'for\s*\(\s*;(.*?);(.*?)\)\s*\{\s*$',L[j+1])
            if m2:
                s=S('F_WHILE2FOR',4,[{},{j:'',j+1:f'{i}for ({m.group(2)} = {m.group(3)};{m2.group(1)};{m2.group(2)}) {{'}],blk,j,'init->for')
                if s: out.append(s)
    return out
# ---------- F_MERK: Merkvariable statt mehrerer return; return COND -> r=0; if (COND) r=1 ----------
def op_merk(L,blk,info):
    out=[]; e=blk['ende']; rt=blk['rettyp'] or 'int'
    if rt=='void': return out
    typen=[rt] if rt in ('int','short') else ['int']
    typen+=[t for t in ('int','short') if t not in typen]
    for j in body(L,blk):
        m=re.match(r'^(\s*)return\s+(.+);\s*$',L[j])
        if m and j==e-1 and len(m.group(1))==4:
            c=m.group(2).strip()
            if (vergleiche(c) or c.startswith('!')) and '?' not in c:
                i=m.group(1); alts=[{}]+[{j:f'{i}{t} r_ = 0;\n{i}if ({c}) r_ = 1;\n{i}return r_;'} for t in typen]
                s=S('F_MERK',4,alts,blk,j,'return cond')
                if s: out.append(s)
    # Kette if (c) return K; ... return V; am Ende des Rumpfs
    me=re.match(r'^    return\s+([^;]+);\s*$',L[e-1]) if e-1>blk['start'] else None
    if me:
        V=me.group(1).strip(); kette=[]; q=e-2
        while q>blk['start']:
            m=re.match(r'^    if\s*\((.*)\)\s*return\s+([^;]+);\s*$',L[q])
            if not m: break
            kette.append((q,m.group(1),m.group(2).strip())); q-=1
        kette.reverse()
        if kette:
            i='    '; alts=[{}]
            for t in typen:
                x={kette[0][0]:f'{i}{t} r_ = {V};\n'+'\n'.join(f'{i}{"if" if k==0 else "else if"} ({c}) r_ = {K};' for k,(q,c,K) in enumerate(kette)),e-1:f'{i}return r_;'}
                for q,c,K in kette[1:]: x[q]=''
                alts.append(x)
                if all(K==kette[0][2] for q,c,K in kette) and len(kette)>1:
                    x={kette[0][0]:f'{i}{t} r_ = {V};\n{i}if ({" || ".join("("+c+")" if "||" in c else c for q,c,K in kette)}) r_ = {kette[0][2]};',e-1:f'{i}return r_;'}
                    for q,c,K in kette[1:]: x[q]=''
                    alts.append(x)
            s=S('F_MERK',4,alts,blk,kette[0][0],f'{len(kette)} return')
            if s: out.append(s)
    return out
# ---------- F_ORRET: if (A) return X; if (B) return X; <-> if (A || B) return X; ----------
def op_orret(L,blk,info):
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)if\s*\((.*)\)\s*return\s+([^;]+);\s*$',L[j])
        if not m or j+1>=blk['ende']: continue
        i=m.group(1); m2=re.match(r'^'+re.escape(i)+r'if\s*\((.*)\)\s*return\s+([^;]+);\s*$',L[j+1])
        if m2 and m2.group(2).strip()==m.group(3).strip():
            a=m.group(2); b=m2.group(1); a='('+a+')' if '||' in a or '&&' in a else a; b='('+b+')' if '||' in b or '&&' in b else b
            s=S('F_ORRET',4,[{},{j:f'{i}if ({a} || {b}) return {m.group(3)};',j+1:''}],blk,j,'join')
            if s: out.append(s)
        if ' || ' in m.group(2) and '&&' not in m.group(2) and m.group(2).count('(')==m.group(2).count(')'):
            teile=[t.strip() for t in re.split(r'\s\|\|\s',m.group(2))]
            if all(t.count('(')==t.count(')') for t in teile) and len(teile)>=2:
                s=S('F_ORRET',4,[{},{j:'\n'.join(f'{i}if ({t}) return {m.group(3)};' for t in teile)}],blk,j,'split')
                if s: out.append(s)
    return out
# ---------- F_IFSWAP: if (c) {A} else {B} -> if (!c) {B} else {A} ----------
def op_ifswap(L,blk,info):
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)if\s*\((.*)\)\s*\{\s*$',L[j])
        if m:
            i=m.group(1); k=block_ende(L,j,blk)
            if k is None or L[k].rstrip()!=i+'} else {': continue
            e=block_ende(L,k,blk)
            if e is None or L[e].rstrip()!=i+'}': continue
            A=L[j+1:k]; B=L[k+1:e]
            x={j:f'{i}if ({neg(m.group(2))}) {{'}
            for q in range(j+1,e): x[q]=''
            x[k]='\n'.join(B)+f'\n{i}}} else {{\n'+'\n'.join(A)
            s=S('F_IFSWAP',4,[{},x],blk,j,'block')
            if s: out.append(s)
        m=re.match(r'^(\s*)if\s*\((.*)\)\s*([^;{]+;)\s*else\s+([^;{]+;)\s*$',L[j])
        if m and '?' not in L[j]:
            i,c,a,b=m.groups()
            s=S('F_IFSWAP',4,[{},{j:f'{i}if ({neg(c)}) {b.strip()} else {a.strip()}'}],blk,j,'zeile')
            if s: out.append(s)
    return out
# ---------- F_NEWCTOR: q = new; if (q) q = ctor(q,..) <-> { int t_ = new; q = (t_ != 0) ? ctor(t_,..) : t_; } ----------
def op_newctor(L,blk,info):
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)((?:int\s+)?)(\w+)\s*=\s*(\(int\)\s*operator new(?:\[\])?\(.*\))\s*;\s*$',L[j])
        if not m or j+1>=blk['ende']: continue
        i,decl,q,ne=m.groups(); ctor=None; n=1
        m1=re.match(r'^'+re.escape(i)+r'if\s*\(\s*'+re.escape(q)+r'(?:\s*!=\s*0)?\s*\)\s*'+re.escape(q)+r'\s*=\s*([^;]+);\s*$',L[j+1])
        if m1: ctor=m1.group(1); n=1
        elif re.match(r'^'+re.escape(i)+r'if\s*\(\s*'+re.escape(q)+r'(?:\s*!=\s*0)?\s*\)\s*\{\s*$',L[j+1]) and j+3<=blk['ende']:
            m2=re.match(r'^\s*'+re.escape(q)+r'\s*=\s*([^;]+);\s*$',L[j+2])
            if m2 and L[j+3].rstrip()==i+'}': ctor=m2.group(1); n=3
        if not ctor: continue
        ct=re.sub(r'(?<![\w.>])'+re.escape(q)+r'(?![\w])','t_',ctor)
        if decl: x={j:f'{i}int t_ = {ne};\n{i}int {q} = (t_ != 0) ? {ct} : t_;'}
        else: x={j:f'{i}{{ int t_ = {ne}; {q} = (t_ != 0) ? {ct} : t_; }}'}
        for k in range(1,n+1): x[j+k]=''
        s=S('F_NEWCTOR',4,[{},x],blk,j,q)
        if s: out.append(s)
    return out
# ---------- F_DELIF: delete X; X = 0; <-> if (X) { delete X; X = 0; } ----------
def op_delif(L,blk,info):
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)(delete\s+(?:\[\]\s*)?(?:\([^;]*\)\s*)?('+SIMPLE+r')\s*;|DELP\(('+SIMPLE+r')\)\s*;?|operator delete\(\(void \*\)('+SIMPLE+r')\)\s*;)\s*$',L[j])
        if m and j+1<blk['ende']:
            i=m.group(1); X=m.group(3) or m.group(4) or m.group(5)
            if re.match(r'^'+re.escape(i)+re.escape(X)+r'\s*=\s*0\s*;\s*$',L[j+1]):
                s=S('F_DELIF',4,[{},{j:f'{i}if ({X}) {{\n{i}    {m.group(2)}\n{i}    {X} = 0;\n{i}}}',j+1:''},{j:f'{i}if ({X} != 0) {{\n{i}    {m.group(2)}\n{i}    {X} = 0;\n{i}}}',j+1:''}],blk,j,X)
                if s: out.append(s)
        m=re.match(r'^(\s*)if\s*\(\s*('+SIMPLE+r')(?:\s*!=\s*0)?\s*\)\s*\{\s*$',L[j])
        if m and j+3<=blk['ende'] and re.match(r'^\s*(delete\b|DELP\(|operator delete)',L[j+1]) and re.match(r'^\s*'+re.escape(m.group(2))+r'\s*=\s*0\s*;',L[j+2]) and L[j+3].rstrip()==m.group(1)+'}':
            i=m.group(1); s=S('F_DELIF',4,[{},{j:'',j+1:i+L[j+1].strip(),j+2:i+L[j+2].strip(),j+3:''}],blk,j,'aus')
            if s: out.append(s)
    return out
# ---------- T_CAST: Breite/Vorzeichen von Casts im Rumpf: *(short *) <-> *(unsigned short *), (signed char) <-> (unsigned char) ... ----------
CASTALT={'short':['unsigned short','int'],'unsigned short':['short','int'],'signed char':['unsigned char','char'],'unsigned char':['signed char','char'],
         'char':['signed char','unsigned char'],'int':['short','unsigned short'],'unsigned':['int','unsigned short']}
def op_tcast(L,blk,info):
    out=[]; n=0
    for j in body(L,blk):
        l=L[j]
        for m in re.finditer(r'\(\s*('+TRE+r')\s*(\*?)\s*\)',l):
            t=re.sub(r'\s+',' ',m.group(1)); st=m.group(2)
            if t not in CASTALT: continue
            if st and l[m.start()-1:m.start()]!='*': continue       # Zeiger-Cast nur in *(T *)-Form
            if not st and t=='int' and not re.search(r'cwde|movsx|movzx',' '.join(info['O'])): continue
            alts=[{}]+[{j:l[:m.start()]+f'({a}{" *" if st else ""})'+l[m.end():]} for a in CASTALT[t] if not (st and a=='int' and t!='short')]
            s=S('T_CAST',3,alts,blk,j,t+('*' if st else ''))
            if s: out.append(s); n+=1
            if n>=10: return out
        for m in re.finditer(r'\b(W16|U16|S16|SB|UB)\(',l):
            mk=m.group(1); alt={'W16':['U16'],'U16':['W16'],'S16':['U16'],'SB':['UB'],'UB':['SB']}.get(mk)
            if not alt or not all(a in info['unit']['makros'] for a in alt): continue
            s=S('T_CAST',3,[{}]+[{j:l[:m.start()]+a+'('+l[m.end():]} for a in alt],blk,j,mk)
            if s: out.append(s)
    return out
# ---------- T_KONST2: (short)K / (signed char)K an Vergleichen mit Feld-/Index-/Deref-Operanden (R100 fuer Nicht-Namen) ----------
def op_tkonst2(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]
        for a0,a1,op,b0,b1 in vergleiche(l):
            a=l[a0:a1]; b=l[b0:b1]
            if not ist_lit(b) or ist_name(a) or ist_lit(a) or re.search(r'\bf_[0-9a-f]{6}\(',a) or b.startswith('(') : continue
            if re.search(r'\((short|signed char|unsigned char|unsigned short)\)\s*$',l[:b0]): continue
            alts=[{},{j:l[:b0]+f'(short){b}'+l[b1:]},{j:l[:b0]+f'(signed char){b}'+l[b1:]},{j:l[:b0]+f'(unsigned char){b}'+l[b1:]}]
            s=S('T_KONST2',3,alts,blk,j,a[:20])
            if s: out.append(s)
    return out
# ---------- F_SHORTTEST: if (v) / if (!v) bei short/char-Variablen -> v != (short)0 / v == (short)0 (test ax,ax statt cwde) ----------
def op_shorttest(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]
        for m in re.finditer(r'\b(if|while)\s*\(\s*(!?)\s*('+NAME+r')\s*\)',l):
            v=m.group(3); t=ptyp(blk,v)
            if not t: continue
            c='short' if 'short' in t or t=='int' else 'signed char'
            op='==' if m.group(2) else '!='
            alts=[{},{j:l[:m.start()]+f'{m.group(1)} ({v} {op} ({c})0)'+l[m.end():]},{j:l[:m.start()]+f'{m.group(1)} (({c}){v} {op} 0)'+l[m.end():]}]
            s=S('F_SHORTTEST',4,alts,blk,j,v)
            if s: out.append(s)
        for a0,a1,op,b0,b1 in vergleiche(l):
            a=l[a0:a1]; b=l[b0:b1]
            if op in ('==','!=') and b=='0' and ist_name(a) and ptyp(blk,a) and ('if' in l or 'while' in l):
                t=ptyp(blk,a); c='short' if 'short' in t or t=='int' else 'signed char'
                s=S('F_SHORTTEST',4,[{},{j:l[:b0]+f'({c})0'+l[b1:]}],blk,j,a)
                if s: out.append(s)
    return out
# ---------- F_INIT: T v; ... v = e;  <->  T v = e;  und  T v = e; -> Zuweisung erst vor der ersten Verwendung ----------
def op_init(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]; m=re.match(r'^(    )((?:const\s+)?(?:'+TRE+r'|\w+\s*\*))\s*(\w+)\s*;\s*$',l)
        if m:
            t,v=m.group(2),m.group(3); uses=verwendungen(L,blk,v,j+1)
            if uses:
                q=uses[0]; m2=re.match(r'^    '+re.escape(v)+r'\s*=\s*([^;=]+);\s*$',L[q])
                if m2 and q>j+1 and all(blk['lokale'][w][1]<j for w in re.findall(r'(?<![\w.>])('+NAME+r')(?![\w(])',m2.group(1)) if w in blk['lokale']):
                    s=S('F_INIT',5,[{},{j:f'    {t} {v} = {m2.group(1)};',q:''}],blk,j,'merge')
                    if s: out.append(s)
        m=re.match(r'^(    )((?:const\s+)?(?:'+TRE+r'|\w+\s*\*))\s*(\w+)\s*=\s*([^;]+);\s*$',l)
        if m and '(' not in m.group(4) and ',' not in m.group(4):
            t,v,e=m.group(2),m.group(3),m.group(4); uses=verwendungen(L,blk,v,j+1)
            if uses and uses[0]>j+1:
                q=uses[0]
                while q>j+1 and len(ind(L[q]))>4: q-=1
                if q>j+1 and not re.match(r'^\s*\}',L[q]):
                    s=S('F_INIT',5,[{},{j:f'    {t} {v};',('ins',q):f'    {v} = {e};'}],blk,j,'spaet')
                    if s: out.append(s)
    return out
# ---------- F_REUSE: zweite Lokale gleichen Typs, die erst nach der letzten Verwendung der ersten benutzt wird, durch die erste ersetzen ----------
def op_reuse(L,blk,info):
    out=[]; lok=blk['lokale']; namen=list(lok)
    for a in namen:
        for b in namen:
            if a==b or lok[a][0]!=lok[b][0] or lok[a][1]>lok[b][1] or len(ind(L[lok[a][1]]))!=4 or len(ind(L[lok[b][1]]))!=4 or ist_zeiger(L,blk,a)!=ist_zeiger(L,blk,b): continue
            ua=[q for q in verwendungen(L,blk,a) if q!=lok[a][1]]; ub=[q for q in verwendungen(L,blk,b) if q!=lok[b][1]]
            if not ua or not ub or max(ua)>=min(ub): continue
            dj=lok[b][1]; dl=L[dj]; x={}
            md=re.match(r'^(\s*)((?:const\s+)?'+TRE+r')\s+(.*);\s*$',dl)
            if not md: continue
            teile=[t.strip() for t in md.group(3).split(',')]; rest=[t for t in teile if re.sub(r'\s*=.*','',t).lstrip('*')!=b]
            if len(rest)==len(teile): continue
            x[dj]=f'{md.group(1)}{md.group(2)} {", ".join(rest)};' if rest else ''
            pat=re.compile(r'(?<![\w.>])'+re.escape(b)+r'(?![\w])')
            for q in ub: x[q]=pat.sub(a,L[q])
            init=re.search(r'(?<![\w])'+re.escape(b)+r'\s*=\s*([^,;]+)',md.group(3))
            if init: x[('ins',ub[0])]=f'{ind(L[ub[0]])}{a} = {init.group(1).strip()};'
            s=S('F_REUSE',5,[{},x],blk,dj,f'{b}->{a}')
            if s: out.append(s)
    return out
# ---------- F_INNER: Deklaration aus dem Kopfblock in den inneren Block der Verwendung verschieben ----------
def op_inner(L,blk,info):
    out=[]
    for j in body(L,blk):
        m=re.match(r'^    ((?:const\s+)?(?:'+TRE+r'|\w+\s*\*))\s*(\w+)(\s*=\s*'+LIT+r')?\s*;\s*$',L[j])
        if not m: continue
        t,v=m.group(1),m.group(2); uses=verwendungen(L,blk,v,j+1)
        if not uses or len(ind(L[uses[0]]))<=4: continue
        q=uses[0]; d=len(ind(L[q])); st=None
        for p in range(q-1,blk['start'],-1):
            if len(ind(L[p]))<d and L[p].strip() and L[p].rstrip().endswith('{'): st=p; break
        if st is None: continue
        bi=ind(L[st]); en=None
        for p in range(st+1,blk['ende']+1):
            if L[p].startswith(bi+'}') and len(ind(L[p]))==len(bi): en=p; break
        if en is None or any(u<=st or u>=en for u in uses): continue
        x={j:'',('ins',st+1):f'{bi}    {t} {v}{m.group(3) or ""};'}
        s=S('F_INNER',5,[{},x],blk,j,v)
        if s: out.append(s)
    return out
# ---------- F_HIDDENARG: Original laedt vor dem Call eine Konstante in das naechste Argumentregister -> verdeckter Parameter (Default-Argument, nur C++) ----------
REGIDX={'eax':1,'edx':2,'ebx':3,'ecx':4}
def op_hiddenarg(L,blk,info):
    out=[]
    if any(re.match(r'^// CC wcc386',l) for l in L[:40]): return out
    O=info['O']; A=info['A']; seen=set()
    for k in range(1,len(O)):
        m=re.match(r'^call (f_[0-9a-f]{6})$',O[k]); m0=re.match(r'^mov (eax|edx|ebx|ecx),(0x[0-9a-f]+)$',O[k-1])
        if not m or not m0: continue
        fn=m.group(1); r=m0.group(1); K=m0.group(2)
        if (fn,r) in seen or any(A[q-1]==O[k-1] and A[q].endswith(fn) for q in range(1,len(A))): continue
        seen.add((fn,r)); pi=info['unit']['proto'].get(fn)
        if pi is None: continue
        p=L[pi]; mp=re.match(r'^(.*\b'+fn+r'\s*\()([^()]*)\)(\s*;.*)$',p)
        if not mp: continue
        params=[x.strip() for x in mp.group(2).split(',') if x.strip() and x.strip()!='void']
        if len(params)+1!=REGIDX[r] or any('...' in x for x in params): continue
        neu=f'{mp.group(1)}{", ".join(params+["int p_h = "+K])}){mp.group(3)}'
        x={pi:neu}
        for b2 in bloecke(L).values():   # Definition in der Einheit bekommt den Parameter ohne Default
            if b2['name']==fn:
                kl=L[b2['kopf']]; mk=re.match(r'^(.*\b'+fn+r'\s*\()([^()]*)\)(.*)$',kl)
                if mk:
                    ps=[y.strip() for y in mk.group(2).split(',') if y.strip() and y.strip()!='void']
                    x[b2['kopf']]=f'{mk.group(1)}{", ".join(ps+["int p_h"])}){mk.group(3)}'
        s=S('F_HIDDENARG',2,[{},x],blk,blk['start'],f'{fn} {r}={K}')
        if s: out.append(s)
    return out
# ---------- F_HOIST: Speicheroperand eines Aufrufs vorher in eine Lokale; umgekehrt: einmal benutzte Lokale einsetzen ----------
def argliste(args):
    teile=[]; d=0; cur=''
    for ch in args:
        if ch in '([': d+=1
        elif ch in ')]': d-=1
        if ch==',' and d==0: teile.append(cur); cur=''
        else: cur+=ch
    teile.append(cur); return [t.strip() for t in teile]
def op_hoist(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]; s=l.strip()
        m=re.match(r'^(\s*)((?:'+SIMPLE+r'\s*=\s*)?)((?:\w+(?:->|\.))*f_[0-9a-f]{6})\((.*)\)\s*;\s*$',l)
        if m and not s.startswith(('if','while','for','return')):
            i,lhs,fn,args=m.groups(); teile=argliste(args); n=0
            pi=info['unit']['proto'].get(fn.split('->')[-1].split('.')[-1]); ptypen=None
            if pi is not None:
                mp=re.search(r'\(([^()]*)\)\s*;',L[pi])
                if mp: ptypen=[re.sub(r'\s*\w+$','',x.strip()) if not x.strip().endswith('*') else x.strip() for x in mp.group(1).split(',')]
            if not ptypen or len(ptypen)!=len(teile): continue
            for k,t in enumerate(teile):
                if not t or '(' in t or ist_lit(t) or (ist_name(t) and not t.startswith('d_')): continue
                if not re.match(r'^[\w>.\-\[\]*&]+$',t) or not re.search(r'->|\.|\[|^\*|^d_',t) or t.startswith('-'): continue
                pt=re.sub(r'\s+',' ',ptypen[k].strip()); pt=re.sub(r'\s*\*\s*$',' *',pt)
                if not pt or pt=='...': continue
                alts=[{}]
                for ty in ([pt]+(['short'] if pt=='int' else [])):
                    neu=list(teile); neu[k]='t_'; alts.append({j:f'{i}{{ {ty} t_ = ({ty})({t}); {lhs}{fn}({", ".join(neu)}); }}'})
                st=S('F_HOIST',4,alts,blk,j,t[:16])
                if st: out.append(st); n+=1
                if n>=2: break
        m=re.match(r'^(\s*)('+TRE+r')\s+(\w+)\s*=\s*([^;()]+);\s*$',l)
        if m and j+1<blk['ende']:
            v=m.group(3); e=m.group(4); uses=verwendungen(L,blk,v,j+1)
            if len(uses)==1 and len(re.findall(r'(?<![\w.>])'+re.escape(v)+r'(?![\w])',L[uses[0]]))==1 and not re.match(r'^\s*(if|while|return)\b',L[uses[0]]):
                q=uses[0]; neu=re.sub(r'(?<![\w.>])'+re.escape(v)+r'(?![\w])',e if re.match(r'^[\w>.\-\[\]]+$',e) else f'({e})',L[q])
                st=S('F_HOIST',4,[{},{j:'',q:neu}],blk,j,'aus '+v)
                if st: out.append(st)
    return out
# ---------- F_ANDNEST: if (A && B) {..} <-> if (A) { if (B) {..} } ----------
def op_andnest(L,blk,info):
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)if\s*\((.*)\)\s*\{\s*$',L[j])
        if m and ' && ' in m.group(2) and '||' not in m.group(2):
            i=m.group(1); e=block_ende(L,j,blk)
            if e is not None and L[e].rstrip()==i+'}':
                a,b=m.group(2).split(' && ',1)
                if a.count('(')==a.count(')') and b.count('(')==b.count(')'):
                    x={j:f'{i}if ({a}) {{\n{i}if ({b}) {{',e:f'{i}}}\n{i}}}'}
                    s=S('F_ANDNEST',4,[{},x],blk,j,'nest')
                    if s: out.append(s)
        m=re.match(r'^(\s*)if\s*\((.*)\)\s*([^;{]+;)\s*$',L[j])
        if m and ' && ' in m.group(2) and '||' not in m.group(2) and 'else' not in L[j]:
            i,c,st=m.groups(); a,b=c.split(' && ',1)
            if a.count('(')==a.count(')') and b.count('(')==b.count(')'):
                s=S('F_ANDNEST',4,[{},{j:f'{i}if ({a}) if ({b}) {st}'}],blk,j,'nest1')
                if s: out.append(s)
        m=re.match(r'^(\s*)if\s*\((.*)\)\s*\{\s*$',L[j])
        if m and j+1<blk['ende']:
            i=m.group(1); m2=re.match(r'^'+re.escape(i)+r'    if\s*\((.*)\)\s*\{\s*$',L[j+1])
            e=block_ende(L,j,blk) if m2 else None
            if m2 and e and L[e].rstrip()==i+'}' and L[e-1].rstrip()==i+'    }':
                x={j:f'{i}if ({m.group(2)} && {m2.group(1)}) {{',j+1:'',e-1:''}
                s=S('F_ANDNEST',4,[{},x],blk,j,'flach')
                if s: out.append(s)
    return out
# ---------- F_RETVOID: void-Funktion, Original endet mit mov eax,K; ret -> int + return K;  und umgekehrt ----------
def op_retvoid(L,blk,info):
    out=[]; rt=blk['rettyp']; k=blk['kopf']; e=blk['ende']
    if not rt or als_zeiger(L,blk) or '::' in (blk['name'] or ''): return out
    O=info['O']; A=info['A']
    mo=re.search(r'(xor eax,eax|mov eax,(0x[0-9a-f]+)) ; ret',' ; '.join(O[-3:])) if O else None
    pi=proto_zeile(L,blk,info)
    if rt=='void' and mo and not re.search(r'(xor eax,eax|mov eax,0x[0-9a-f]+) ; ret',' ; '.join(A[-3:])):
        K='0' if mo.group(1).startswith('xor') else mo.group(2); x={k:re.sub(r'^(\s*)void\b',r'\1int',L[k]),('ins',e):f'    return {K};'}
        if pi is not None: x[pi]=re.sub(r'^(\s*)void\b',r'\1int',L[pi])
        for q in body(L,blk):
            if re.match(r'^\s*return\s*;',L[q]): x[q]=L[q].replace('return;',f'return {K};')
        s=S('F_RETVOID',2,[{},x],blk,k,'void->int')
        if s: out.append(s)
    if rt in ('int','short') and not mo and O and O[-1]=='ret' and not re.search(r'mov eax|xor eax|movsx eax|movzx eax',' ; '.join(O[-2:])):
        rets=[q for q in body(L,blk) if re.match(r'^\s*return\b',L[q])]
        if rets and all(re.match(r'^\s*return\s+'+LIT+r'\s*;',L[q]) for q in rets):
            x={k:re.sub(r'^(\s*)'+rt+r'\b',r'\1void',L[k])}
            if pi is not None: x[pi]=re.sub(r'^(\s*)'+rt+r'\b',r'\1void',L[pi])
            for q in rets: x[q]='' if q==e-1 else re.sub(r'return\s+'+LIT,'return',L[q])
            s=S('F_RETVOID',2,[{},x],blk,k,'int->void')
            if s: out.append(s)
    return out
# ---------- F_ADDSUB: Original add, wir sub (oder umgekehrt) -> Vorzeichen eines Nicht-Literal-Terms drehen ----------
def op_addsub(L,blk,info):
    out=[]; O=' ; '.join(info['O']); A=' ; '.join(info['A'])
    ao=len(re.findall(r'\badd \w+,\w+',O)); so=len(re.findall(r'\bsub \w+,\w+',O)); aa=len(re.findall(r'\badd \w+,\w+',A)); sa=len(re.findall(r'\bsub \w+,\w+',A))
    if (ao,so)==(aa,sa): return out
    for j in body(L,blk):
        l=L[j]
        for m in re.finditer(r'\s([+-])\s(?![=])',l):
            a0,a1=links(l,m.start()); b0,b1=rechts(l,m.end())
            if not l[a0:a1] or not l[b0:b1] or ist_lit(l[b0:b1]) or ist_lit(l[a0:a1]): continue
            o='-' if m.group(1)=='+' else '+'
            s=S('F_ADDSUB',4,[{},{j:l[:m.start()]+f' {o} '+l[m.end():]}],blk,j,m.group(1)+'->'+o)
            if s: out.append(s)
    return out
# ---------- F_LOCALCOPY: Zeigerparameter/this in lokale Kopie (q_ = p), ganz oben oder im ersten Schleifenrumpf ----------
def op_localcopy(L,blk,info):
    out=[]
    kand=[(t,nm) for t,st,nm in blk['params'] if t and st=='*']
    if blk['name'] and '::' in blk['name']: kand.append((blk['name'].split('::')[0],'this'))
    for t,p in kand:
        pat=re.compile(r'(?<![\w.>])'+re.escape(p)+r'->')
        uses=[j for j in body(L,blk) if pat.search(L[j])]
        if len(uses)<2: continue
        x={('ins',blk['start']+1):f'    {t} *q_ = {p};'}
        for j in uses: x[j]=pat.sub('q_->',L[j])
        alts=[{},x]
        for j in body(L,blk):
            m=re.match(r'^(\s*)(for|while)\s*\(.*\)\s*\{\s*$',L[j]); e=block_ende(L,j,blk) if m else None
            if m and e and all(j<u<e for u in uses):
                y={('ins',j+1):f'{m.group(1)}    {t} *q_ = {p};'}
                for u in uses: y[u]=pat.sub('q_->',L[u])
                alts.append(y); break
        s=S('F_LOCALCOPY',4,alts,blk,uses[0],p)
        if s: out.append(s)
    return out
# ---------- F_UMUL: E * K -> E * Ku (unsigned Literal, verhindert CSE der Vorzeichenerweiterung) ----------
def op_umul(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]
        for m in re.finditer(r'\s\*\s('+LIT+r')(?![\w.u])',l):
            if m.group(1).startswith('-'): continue
            s=S('F_UMUL',4,[{},{j:l[:m.end()]+'u'+l[m.end():]}],blk,j,m.group(1))
            if s: out.append(s)
    return out
# ---------- F_RETARG: return strcpy(a, b); -> char *r_ = a; strcpy(a, b); return r_; ----------
def op_retarg(L,blk,info):
    out=[]
    for j in body(L,blk):
        m=re.match(r'^(\s*)return\s+((strcpy|strcat|memcpy|memset|memmove|strncpy)\(\s*([^,]+),.*\))\s*;\s*$',L[j])
        if m:
            i=m.group(1); s=S('F_RETARG',4,[{},{j:f'{i}char *r_ = (char *){m.group(4).strip()};\n{i}{m.group(2)};\n{i}return r_;'}],blk,j,m.group(3))
            if s: out.append(s)
    return out
# ---------- F_GLOBPTR: Tabellenbasis d_x + E * K -> Zeigerzugriff ueber struct (getrenntes mov/add wie Original) ----------
def op_globptr(L,blk,info):
    out=[]; first=info['first_mark']
    for j in body(L,blk):
        l=L[j]
        for m in re.finditer(r'(?<![\w.>])(d_[0-9a-f]{6})\s*\+\s*('+SIMPLE+r')\s*\*\s*('+LIT+r')(?![\w.])',l):
            g,E,K=m.groups(); i=info['unit']['ext'].get(g)
            if i is None or l[:m.start()].rstrip().endswith('&') or not re.match(r'^extern\s+(volatile\s+)?int\s',L[i]): continue
            k=lit(K); st=f'S_{k:x}'
            x={j:l[:m.start()]+f'(int)(*(struct {st} **)&{g} + ({E}))'+l[m.end():]}
            if not any(f'struct {st} ' in z for z in L[:blk['mark']]): x[('ins',first)]=f'struct {st} {{ char b[{K}]; }};'
            y={j:l[:m.start()]+f'((int)*(struct {st} **)&{g} + ({E}) * {K})'+l[m.end():]}
            if ('ins',first) in x: y[('ins',first)]=x[('ins',first)]
            s=S('F_GLOBPTR',4,[{},x,y],blk,j,g)
            if s: out.append(s)
    return out
# ---------- F_INCSTMT: a[n++] = w <-> a[n] = w; n++;   *q++ = x <-> *q = x; q++; ----------
def op_incstmt(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]; i=ind(l)
        m=re.match(r'^\s*(.*?)\b(\w+)(\+\+|--)(.*;)\s*$',l)
        if m and not l.strip().startswith(('for','while','if','return')) and l.count('++')+l.count('--')==1 and '=' in l and not re.match(r'^\s*\w+\s*(\+\+|--)\s*;',l):
            v=m.group(2); o=m.group(3)
            s=S('F_INCSTMT',4,[{},{j:f'{i}{m.group(1)}{v}{m.group(4)}\n{i}{v}{o};'}],blk,j,v)
            if s: out.append(s)
        if j+1<blk['ende'] and '=' in l and not l.strip().startswith(('for','while','if','return')):
            m2=re.match(r'^'+re.escape(i)+r'(\w+)(\+\+|--)\s*;\s*$',L[j+1])
            if m2 and len(re.findall(r'(?<![\w.>])'+re.escape(m2.group(1))+r'(?![\w])',l))==1 and re.search(r'\['+re.escape(m2.group(1))+r'\]|\*'+re.escape(m2.group(1))+r'\b',l):
                neu=re.sub(r'(?<![\w.>])'+re.escape(m2.group(1))+r'(?![\w])',m2.group(1)+m2.group(2),l,count=1)
                s=S('F_INCSTMT',4,[{},{j:neu,j+1:''}],blk,j,'join')
                if s: out.append(s)
    return out
# ---------- F_TERNCALL: Aufruf mit ?:-Argument -> zwei volle Aufrufe in if/else (Watcom faltet den Schwanz); R115 umgekehrt ----------
def op_terncall(L,blk,info):
    out=[]
    for j in body(L,blk):
        l=L[j]; m=re.match(r'^(\s*)((?:return\s+)?(?:'+SIMPLE+r'\s*=\s*)?)((?:\w+(?:->|\.))*f_[0-9a-f]{6}\()(.*)\)\s*;\s*$',l)
        if m and l.count('?')==1 and not l.strip().startswith(('if','while','for')):
            i,pre,fn,args=m.groups(); teile=argliste(args); k=next((k for k,t in enumerate(teile) if '?' in t),None)
            if k is not None and teile[k].count('(')==teile[k].count(')'):
                t=teile[k]; d=0; q=c=None
                for p,ch in enumerate(t):
                    if ch in '([': d+=1
                    elif ch in ')]': d-=1
                    elif d==0 and ch=='?' and q is None: q=p
                    elif d==0 and ch==':' and q is not None: c=p; break
                if q is not None and c is not None:
                    cond,a,b=t[:q].strip(),t[q+1:c].strip(),t[c+1:].strip()
                    TA=list(teile); TA[k]=a; TB=list(teile); TB[k]=b; A=', '.join(TA); B=', '.join(TB)
                    if pre.startswith('return'): x={j:f'{i}if ({cond}) return {fn}{A});\n{i}return {fn}{B});'}
                    else: x={j:f'{i}if ({cond}) {pre}{fn}{A}); else {pre}{fn}{B});'}
                    y={j:f'{i}if ({cond}) {{\n{i}    {pre}{fn}{A});\n{i}}} else {{\n{i}    {pre}{fn}{B});\n{i}}}'}
                    s=S('F_TERNCALL',4,[{},x,y],blk,j,fn)
                    if s: out.append(s)
        m=re.match(r'^(\s*)(?:(?:'+TRE+r')\s+)?(\w+)\s*=\s*([^?;]+?)\s*\?\s*([^:;]+?)\s*:\s*([^;]+?)\s*;\s*$',l)
        if m and j+1<blk['ende']:
            i,v,c,a,b=m.groups(); n=L[j+1]
            if re.match(r'^\s*(?:return\s+)?(?:\w+(?:->|\.))*f_[0-9a-f]{6}\(.*\)\s*;\s*$',n) and len(re.findall(r'(?<![\w.>])'+re.escape(v)+r'(?![\w])',n))==1 and len(verwendungen(L,blk,v,j+1))==1:
                pat=re.compile(r'(?<![\w.>])'+re.escape(v)+r'(?![\w])')
                s=S('F_TERNCALL',4,[{},{j:'',j+1:f'{i}if ({c}) {pat.sub(a,n.strip())} else {pat.sub(b,n.strip())}'},{j:'',j+1:f'{i}if ({c}) {{\n{i}    {pat.sub(a,n.strip())}\n{i}}} else {{\n{i}    {pat.sub(b,n.strip())}\n{i}}}'}],blk,j,v)
                if s: out.append(s)
    return out
NEU=[op_eq_x,op_reloc,op_shlmul,op_negk,op_andtemp,op_lea,op_while2for,op_merk,op_orret,op_ifswap,op_newctor,op_delif,
     op_tcast,op_tkonst2,op_shorttest,op_init,op_reuse,op_inner,op_hiddenarg,op_hoist,op_andnest,op_retvoid,op_addsub,op_localcopy,
     op_umul,op_retarg,op_globptr,op_incstmt,op_terncall]
ALLE+=NEU

# --- R143 ff. (worker, 24.10.2026): nur mit SUCHE_R3=1 aktiv (Runde 4) ---
import os as _os
if _os.environ.get('SUCHE_R3')=='1':
    try:
        from operatoren_r3 import NEU as _NEU3
        ALLE += [o for o in _NEU3 if o not in ALLE]
    except Exception as _e:
        import sys as _s; print('operatoren_r3 nicht geladen:',_e,file=_s.stderr)

# --- T2 (worker, 24.10.2026, operatoren_t2.py: F_SWITCH, F_CASEORDER, F_VOLFIELD, F_SHORTCAST, F_EARLYRET, F_SPILL, F_GT0, F_INTTEMP,
#     F_SWITCHCAST, F_KSHIFT, F_SPLITADD, F_SCOPE, F_PARMCOPY): nur mit SUCHE_T2=1 aktiv ---
if _os.environ.get('SUCHE_T2')=='1':
    try:
        from operatoren_t2 import NEU as _NEUT2
        ALLE += [o for o in _NEUT2 if o not in ALLE]
    except Exception as _e:
        import sys as _s; print('operatoren_t2 nicht geladen:',_e,file=_s.stderr)

# --- C1 (rule-based operator set C1, ab 24.10.2026, operatoren_c1.py): nur mit SUCHE_C1=1 aktiv ---
if _os.environ.get('SUCHE_C1')=='1':
    try:
        from operatoren_c1 import NEU as _NEUC1
        ALLE += [o for o in _NEUC1 if o not in ALLE]
    except Exception as _e:
        import sys as _s; print('operatoren_c1 nicht geladen:',_e,file=_s.stderr)

# --- W1 (Recherche Theme Hospital/KKND, 24.10.2026, operatoren_w1.py: W_MUL2, W_DOWHILE0, W_CHAIN, W_BOOLSET, W_ADDNEG, W_PREINC,
#     W_BYTETERN, W_ROTATE, W_TRUTH): nur mit SUCHE_W1=1 aktiv (suchlauf.sh setzt es standardmaessig) ---
if _os.environ.get('SUCHE_W1')=='1':
    try:
        from operatoren_w1 import NEU as _NEUW1
        ALLE += [o for o in _NEUW1 if o not in ALLE]
    except Exception as _e:
        import sys as _s; print('operatoren_w1 nicht geladen:',_e,file=_s.stderr)

# --- D1 (Demo-Typen, 24.10.2026, operatoren_d1.py: D_PARAM, D_RET, D_LOKAL aus meta/demo_types.tsv): nur mit SUCHE_D1=1 ---
if _os.environ.get('SUCHE_D1')=='1':
    try:
        from operatoren_d1 import NEU as _NEUD1
        ALLE += [o for o in _NEUD1 if o not in ALLE]
    except Exception as _e:
        import sys as _s; print('operatoren_d1 nicht geladen:',_e,file=_s.stderr)

# --- worker (worker-Auswertung 147 geloester Funktionen, 25.10.2026, operatoren_i11.py: I11_UNCACHE, I11_STOREARG, I11_BOOLCONST): nur mit SUCHE_I11=1 ---
if _os.environ.get('SUCHE_I11')=='1':
    try:
        from operatoren_i11 import NEU as _NEUI11
        ALLE += [o for o in _NEUI11 if o not in ALLE]
    except Exception as _e:
        import sys as _s; print('operatoren_i11 nicht geladen:',_e,file=_s.stderr)

# A2: worker, nur ausdruecklich aktivieren; Importfehler nicht verschweigen.
if _os.environ.get('SUCHE_A2')=='1':
    from operatoren_a2 import NEU as _NEUA2
    ALLE += [o for o in _NEUA2 if o not in ALLE]

# A3: nur explizit, standardmaessig aus. Keine Defaultargumente oder ASM.
if _os.environ.get('SUCHE_PROTO')=='1':
    from operatoren_proto import NEU as _NEUPROTO
    ALLE += [o for o in _NEUPROTO if o not in ALLE]

# worker: Erweiterung genau zweier C1-Operatoren, standardmaessig AUS.
# SUCHE_I12 hat Vorrang vor dem Mutator-Alias KD_I12.
if _os.environ.get('SUCHE_I12', _os.environ.get('KD_I12', '0'))=='1':
    from operatoren_i12 import erweitere_c1 as _i12_erweitere_c1
    ALLE = _i12_erweitere_c1(ALLE)

# worker (worker, 26.10.2026, operatoren_i13.py: I13_CALLCLOBBER_EBX, I13_WORDPROMOTE_AUX, I13_LOCAL_HIDDENARG_EBX), standardmaessig AUS.
# SUCHE_I13 hat Vorrang vor dem Mutator-Alias KD_I13. Belege: gfx_t2 f_400010, char_opt f_400010, sewerag3_t2 f_400010 (je Rest 2 -> GLEICH).
if _os.environ.get('SUCHE_I13', _os.environ.get('KD_I13', '0'))=='1':
    from operatoren_i13 import NEU as _NEUI13
    ALLE += [o for o in _NEUI13 if o not in ALLE]

# worker (worker, Regelrunde 3, 28.10.2026, operatoren_i14.py: I14_BYTE_COMPARE_REF, I14_ZERO_INLINE_LITERAL). target 28.10.: standardmaessig AN (SUCHE_I14=0 schaltet ab).
if _os.environ.get('SUCHE_I14', _os.environ.get('KD_I14', '1'))=='1':
    from operatoren_i14 import NEU as _NEUI14
    ALLE += [o for o in _NEUI14 if o not in ALLE]

# P123 (worker): getrennte, standardmaessig ausgeschaltete Generatoren.
if any(_os.environ.get(n, '0') == '1' for n in (
        'SUCHE_P123', 'SUCHE_P123_PAKETE', 'SUCHE_P123_RAHMEN', 'SUCHE_P123_AUSDRUCK')):
    from operatoren_p123 import NEU as _NEUP123
    ALLE += [o for o in _NEUP123 if o not in ALLE]

# worker (worker, 30.10.2026 abends, operatoren_i15.py: I15_DIREKT, I15_CASETEIL) - Hebel aus Blind 831 ship2 f_400010 (Auto-Inlining, switch-Bereiche). Standardmaessig AN.
if _os.environ.get('SUCHE_I15', _os.environ.get('KD_I15', '1'))=='1':
    try:
        from operatoren_i15 import NEU as _NEUI15
        ALLE += [o for o in _NEUI15 if o not in ALLE]
    except Exception as _e:
        import sys as _s; print('operatoren_i15 nicht geladen:',_e,file=_s.stderr)

# E13 (worker + worker, 29.10.2026, operatoren_e13.py: F_MASK16, F_VOLBASE) â Gleichstands-Hebel aus dem echten 10.6 (emu106). Standardmaessig AN (SUCHE_E13=0 schaltet ab).
# Belege: unit_example f_400010, unit_example f_400010, spell3_t1 f_400010, unit_example f_400010 (F_MASK16), use_t2 f_400010 (F_VOLBASE).
if _os.environ.get('SUCHE_E13', _os.environ.get('KD_E13', '1'))=='1':
    from operatoren_e13 import NEU as _NEUE13
    ALLE += [o for o in _NEUE13 if o not in ALLE]
