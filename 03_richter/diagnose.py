# diagnose.py - Classify instruction diff lines into root-cause categories (Form, Call, Width, Offset, Order, Register, Stack).
# Eingabe: unified diff (--- original / +++ neu) der Befehlstexte. Ausgabe: eine Zeile je Klasse + passende Pruefliste.
import sys,re
REG=r'\b(e?[abcd]x|[abcd][lh]|e?[sd]i|e?[sb]p)\b'
def opc(l): return l.split()[0] if l.split() else ''
FUELL=re.compile(r'^(nop|mov (\w+),\2|lea (\w+),\[\3\+0x0\]|xchg (\w+),\4)$')   # Watcom-Fueller hinter ret
def sauber(l): return ' '.join(l.replace(', ',',').split())
def ohne(l,was):
    if was=='reg': return re.sub(REG,'R',l)
    if was=='slot': return re.sub(r'\[(e[bs]p)[+-]0x[0-9a-f]+\]',r'[\1+S]',l)
    if was=='imm': return re.sub(r'0x[0-9a-f]+|\b\d+\b','K',l)
    if was=='breite': return re.sub(r'\b(BYTE|WORD|DWORD) PTR ','',re.sub(r'^mov(sx|zx)\b','mov',l))
def klasse(a,b):
    if opc(a)==opc(b) and opc(a).startswith('j'):   
        if re.search(r'f_[0-9a-f]{6}\+',a) and re.search(r'f_[0-9a-f]{6}\+',b) and a.split('+')[0]==b.split('+')[0]: return 'Nachbar-Sprung'
        return 'Sprungziel'
    if opc(a)==opc(b)=='xor' and re.sub(REG,'R',a)==re.sub(REG,'R',b) and len(a.split()[1])!=len(b.split()[1]): return 'Typbreite'   # xor edx,edx vs xor dh,dh
    if opc(a)==opc(b)=='call':
        if 'EXT' in (a.split()[-1],b.split()[-1]): return None   
        return 'Aufrufziel'
    if opc(a)==opc(b) or {opc(a),opc(b)}<={'mov','movsx','movzx'}:
        for w,k in (('reg','Register'),('slot','Stapelplatz'),('imm','Konstante/Offset'),('breite','Typbreite')):
            if ohne(a,w)==ohne(b,w): return k
        if ohne(ohne(a,'reg'),'slot')==ohne(ohne(b,'reg'),'slot'): return 'Register+Stapelplatz'
        if ohne(ohne(a,'reg'),'breite')==ohne(ohne(b,'reg'),'breite'): return 'Typbreite'
    return 'Form'
TIPP={'Nachbar-Sprung':'Sprung in eine Nachbarfunktion mit anderem Ziel: Die Abweichung liegt in der GROESSE/dem Ende der Nachbarfunktion, nicht hier - Nachbarn zuerst loesen, hier nichts aendern',
 'Sprungziel':'Sprungweiten folgen aus anderen Unterschieden - ignorieren, solange sonst etwas abweicht',
 'Aufrufziel':'Aufrufziel: falsche Funktion oder extern/Methode statt Funktion (EXT = nicht aufgeloest) - Deklaration/Klasse/Name pruefen','Register':'Registerwahl: Variable zusammenlegen/trennen, Wahrheitstest-Form (if(x) vs x!=0), Block-Lokale, Zap-Set des Aufgerufenen (#pragma aux modify), andere Anweisungen variieren',
 'Stapelplatz':'Stapelplatz: Deklarationsreihenfolge/Block, Byte-Temps (?:, switch auf char), Arraygroesse; unter -oneatx folgen Slots oft der Registerzuteilung - erst Register/Form loesen',
 'Register+Stapelplatz':'Register+Slot gemeinsam: meist EINE Ursache (Phasenverschiebung) - eine Variable zu viel/zu wenig oder falsche Lebensdauer',
 'Konstante/Offset':'Konstante/Offset: Strukturfeld vs Global, Arrayindex/Elementgroesse, Vorzeichen der Konstante, Objektgroesse',
 'Typbreite':'Typbreite: short/char/unsigned (movsx=signed, movzx=unsigned, WORD=short), Vergleich mit (short)0/(char)0, Kopfprototyp/Parameterbreite',
 'Reihenfolge':'Reihenfolge: Auswertungsreihenfolge (groesserer Ausdrucksbaum zuerst, Cast zaehlt), Klammerung, Store-Reihenfolge (volatile), Temp-Variable',
 'Form':'Form/Struktur: Kontrollfluss (for rotiert/while oben, &&-Kette, if/else statt ?:, fruehe Returns), fehlender/zusaetzlicher Aufruf, Inline-Entscheidung'}
def diagnose(diff):
    z={}; hk=[]; cur=None
    for l in diff.splitlines():
        if l.startswith('@@'): cur=([],[]); hk.append(cur); continue
        if cur is None or l.startswith(('---','+++')): continue
        x=sauber(l[1:])
        if FUELL.match(x): continue
        if l.startswith('-'): cur[0].append(x)
        elif l.startswith('+'): cur[1].append(x)
    for o,n in hk:
        if not o and not n: continue
        if len(o)==len(n):
            if sorted(o)==sorted(n): z['Reihenfolge']=z.get('Reihenfolge',0)+len(o); continue
            for a,b in zip(o,n):
                k=klasse(a,b)
                if k: z[k]=z.get(k,0)+1
        elif sorted(o)!=sorted(n) and len(o)+len(n)>0:
            if sorted(map(lambda x:ohne(x,'reg'),o))==sorted(map(lambda x:ohne(x,'reg'),n)): z['Reihenfolge']=z.get('Reihenfolge',0)+max(len(o),len(n)); continue
            z['Form']=z.get('Form',0)+max(len(o),len(n))
    return z
def text(diff,kurz=False):
    z=diagnose(diff)
    if not z: return ''
    r=['Diagnose (Zeilen je Ursachenklasse, groesste zuerst; erst Form, dann Typbreite/Konstante, dann Reihenfolge, zuletzt Register/Slot):']
    rang=['Form','Aufrufziel','Typbreite','Konstante/Offset','Reihenfolge','Register+Stapelplatz','Register','Stapelplatz','Sprungziel','Nachbar-Sprung']
    for k in sorted(z,key=lambda k:(rang.index(k),-z[k])): r.append(f'  {k}: {z[k]}' + ('' if kurz else f'  -> {TIPP[k]}'))
    return '\n'.join(r)
if __name__=='__main__': print(text(sys.stdin.read()))
