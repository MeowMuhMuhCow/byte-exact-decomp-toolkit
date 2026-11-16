import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""editsuche.py - Liste von (alt, neu)-Textersetzungen einzeln messen (parallel), Zielfunktion + Einheit."""
import sys,os,multiprocessing as mp; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); from variante import stand
import w106cfg as C
_G={}
def _job(i):
    s,unit,fs,fkt,edits=_G['a']; a,b=edits[i]
    if a not in s: return i,None,'alt fehlt',None
    p=os.path.join(C.TMP,'es%d.CPP'%os.getpid()); open(p,'w',errors='replace').write(s.replace(a,b,1)); g,off=stand(unit,p,fs)
    return i,g,(off.get(fkt,'GLEICH') if isinstance(off,dict) else str(off)[:60]),off
def run(src,unit,fs,fkt,edits,procs=2):
    _G['a']=(open(src,errors='replace').read(),unit,fs,fkt,edits)
    with mp.get_context('fork').Pool(procs,maxtasksperchild=40) as pool: return pool.map(_job,range(len(edits)))
