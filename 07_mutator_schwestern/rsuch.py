#!/usr/bin/env python3
# rsuch.py REGEX [max] (worker, 08.11.2026) - "Rosetta": lokale Muster-Suche im ORIGINAL-Asm aller GLEICHen Funktionen (Stand live_fstand 08.11. mittags).
# Idee: der Compiler ist deterministisch. Erzeugt das Original an deiner Diff-Stelle ein Muster, das wir nicht treffen, such es hier:
# die GLEICHen Treffer zeigen, welche Quellform genau dieses Muster erzeugt (Quelle: grep -n "f_<adr>" src/p3/<unit>_P1.CPP).
# Normalisierung: Sprung/Call-Ziele -> J, [esp+..] -> [S], ds:0x.. -> ds:A, uebrige Hex-Zahlen -> I. Register bleiben konkret (Backrefs \1 moeglich).
# Befehle sind mit ' | ' verbunden. Beispiel (zwei Globale laden, Zaehler zuerst getestet):
#   python3 rsuch.py 'mov (e[a-d]x|esi|edi|ebp),DWORD PTR ds:A \| mov (e[a-d]x|esi|edi|ebp),DWORD PTR ds:A( \| [^|]+){0,3} \| test \1,\1'
# Ausschnitt einer Funktion (normalisiert) ansehen: python3 rsuch.py --zeig 1513cc 35 50
import re,sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import ros
if sys.argv[1]=='--zeig':
    a=sys.argv[2].lower().replace('f_',''); u,st,ins=ros.ORIG[a]; i1=int(sys.argv[3]) if len(sys.argv)>3 else 0; i2=int(sys.argv[4]) if len(sys.argv)>4 else len(ins)
    print('f_%s %s %s'%(a,u,'GLEICH' if st=='G' else 'Rest '+st))
    for i in range(i1,min(i2,len(ins))): print('%4d  %-40s %s'%(i,ins[i],ros.norm(ins[i])))
    sys.exit()
rx=re.compile(sys.argv[1]); mx=int(sys.argv[2]) if len(sys.argv)>2 else 15; hits=[]
for a,(u,st,ins) in ros.ORIG.items():
    if st!='G': continue
    s=' | '.join(ros.norm(x) for x in ins); m=rx.search(s)
    if m: hits.append((a,u,m.group(0)))
print('%d GLEICHe Funktionen mit dem Muster'%len(hits))
for a,u,g in hits[:mx]: print('f_%s %-18s %s'%(a,u,g[:220]))
