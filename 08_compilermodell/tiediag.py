#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""tiediag.py QUELLE.CPP EINHEIT FKT [--procs 16] - Ist der Rest einer Funktion nur ein Gleichstand im Registerverteiler?
(worker, 29.10.2026). Im echten 10.6 wird nach SortConflicts (Durchgang 0) jeder Konflikt einmal an den Anfang
seines Laufs gleicher savings gesetzt (= eine Reihenfolge, die die instabile Shell-Sortierung auch liefern kann) und die
Funktion gegen das Original gemessen. Ergebnis: Bestwert je Verschiebung; 0 = Quelle stimmt, nur die Gleichstandsreihenfolge
fehlt. Dann sagt die Zeile, WELCHER Konflikt vor welchen muss."""
import sys,os,multiprocessing as mp,argparse; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from tiesuche import lauf
A=None
def info(L): A_['L']=[(d['txt'],d['id'],d['savings']) for d in L]; return L
A_={}
def job(k):
    def ordne(L):
        L=list(L); s=L[k]['savings']; first=min(i for i,d in enumerate(L) if d['savings']==s)
        x=L.pop(k); L.insert(first,x); return L
    n,_=lauf(A.src,A.fkt,A.einheit,ordne); return k,n
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('einheit'); ap.add_argument('fkt'); ap.add_argument('--procs',type=int,default=16)
    A=ap.parse_args()
    n0,_=lauf(A.src,A.fkt,A.einheit,info); L=A_['L']
    print('%s %s: %d abweichende Befehle ohne Eingriff, %d Konflikte'%(A.einheit,A.fkt,n0,len(L)))
    ks=[k for k,(t,i,s) in enumerate(L) if k>0 and L[k-1][2]==s]
    with mp.get_context('fork').Pool(A.procs,maxtasksperchild=40) as p: R=p.map(job,ks)
    R.sort(key=lambda r:r[1])
    for k,n in R[:10]:
        t,i,s=L[k]; first=min(j for j,x in enumerate(L) if x[2]==s)
        print('  %4d Befehle: %s (id %d, savings %d) vor %s'%(n,t,i,s,', '.join(x[0] for x in L[first:k][:6])+(' ...' if k-first>6 else '')))
