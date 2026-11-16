import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
def shell_sort(a,before):
    a=list(a); n=len(a); gap=n; adjust=1
    while True:
        adjust=1-adjust; gap=gap//2+adjust
        while True:
            swap=False
            for i in range(n-gap):
                if before(a[i+gap],a[i]): a[i],a[i+gap]=a[i+gap],a[i]; swap=True
            if not swap: break
        if gap==1: break
    return a
