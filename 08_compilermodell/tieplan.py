#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""tieplan.py QUELLE FKT ZIEL [VOR1,VOR2,...] - welche Aenderungen an der Konfliktliste (vor der Sortierung) bringen ZIEL
vor die genannten Konflikte? Rechnet die instabile Shell-Sortierung von 10.6 nach (shell.py, gegen Compiler geprueft).
Zuege: Konflikt entfernen (ein Temporaeres weniger), Dummy einfuegen (eins mehr, mit savings s), savings +-1."""
import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from irlist import liste
from shell import shell_sort
bf=lambda x,y: x['savings']>y['savings']
def key(d): return d['txt']+'#'+str(d['id'])
def plan(src,fkt,ziel,vor=None):
    pre=liste(src,fkt)
    base=[key(d) for d in shell_sort(pre,bf)]
    zk=[key(d) for d in pre if d['txt']==ziel or key(d)==ziel]
    if not zk: raise SystemExit('Ziel nicht gefunden')
    zk=zk[0]
    if not vor:
        s=[d for d in pre if key(d)==zk][0]['savings']; srt=shell_sort(pre,bf)
        i=base.index(zk); vor=[key(d) for d in srt[:i] if d['savings']==s]
    else:
        vor=[key(d) for d in pre if d['txt'] in vor or key(d) in vor]
    def ok(L):
        o=[key(d) for d in shell_sort(L,bf)]
        if zk not in o: return False
        return all(v not in o or o.index(zk)<o.index(v) for v in vor)
    R=[]
    for k in range(len(pre)):
        if key(pre[k])!=zk and pre[k]['txt']!='' and ok(pre[:k]+pre[k+1:]): R.append(('weg',k,pre[k]))
    for k in range(len(pre)+1):
        for s in sorted(set(d['savings'] for d in pre)|{0,1}):
            if ok(pre[:k]+[dict(txt='NEU',id=-1,savings=s,first='',last='')]+pre[k:]): R.append(('neu',k,dict(savings=s,txt='NEU',first='',last='')))
    for k in range(len(pre)):
        for dd in (-1,1,-2,2):
            L=[dict(x) for x in pre]; L[k]['savings']+=dd
            if L[k]['savings']>=0 and ok(L): R.append(('sav%+d'%dd,k,pre[k]))
    return pre,zk,vor,R
if __name__=='__main__':
    pre,zk,vor,R=plan(sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4].split(',') if len(sys.argv)>4 else None)
    print('Ziel %s vor %s'%(zk,', '.join(vor)))
    for art,k,d in R:
        print('  %-6s Pos %3d  %-8s sav %3d  %s | %s'%(art,k,d['txt'][:8],d['savings'],d.get('first','')[:34],d.get('last','')[:30]))
