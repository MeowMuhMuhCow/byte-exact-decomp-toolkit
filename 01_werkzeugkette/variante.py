"""variante.py UNIT SOURCE 'old' 'new' [...] - Apply text replacements, compile in emu106, and score per function."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bytecmp as B
from comp import comp
from fdiff2 import diff
import w106cfg as C

MASS = os.environ.get('W106_MASS', 'fstand')
_FSTAND = os.path.normpath(os.path.join(C.HERE, '..', '03_richter', 'fstand.py'))
_LO = None


def lo_von(u):
    global _LO
    if _LO is None:
        _LO = {}
        try:
            for l in open(C.UNITS_TSV, errors='replace'):
                x = l.rstrip('\n').split('\t')
                if len(x) > 3 and re.match(r'[0-9a-fA-F]{4,8}$', x[2]):
                    _LO.setdefault(x[1], (x[2], x[3]))
        except OSError:
            pass
    return _LO.get(u)


def nativmass(obj, bounds):
    """Run exact judge fstand.py on OBJ -> {addr_lower: rest} (0 = Match); None on failure."""
    if not (os.path.exists(_FSTAND) and bounds):
        return None
    lo, hi = bounds
    try:
        out = subprocess.run(
            [sys.executable, _FSTAND, obj, lo, hi],
            capture_output=True, text=True, timeout=300
        ).stdout
    except Exception:
        return None
    R = {}
    for l in out.split('\n'):
        m = re.match(r'^([0-9A-F]{4,8})\s+\d+/\d+\s+(GLEICH|MATCH|(\d+) (?:Befehle|insns))', l)
        if m:
            R[m.group(1).lower()] = 0 if m.group(2) in ('GLEICH', 'MATCH') else int(m.group(3))
    return R if R else None


def stand(u, src, fs=None):
    obj = os.path.join(C.TMP, f'{u}_v{os.getpid()}.obj')
    ok, out, e = comp(src, obj)
    if not ok:
        return None, out[-300:]
    R = nativmass(obj, lo_von(u)) if MASS in ('fstand', 'fdiff') else None
    if R is not None and (not fs or not os.path.exists(fs)):
        g = sum(1 for v in R.values() if v == 0)
        offen = {k: v for k, v in R.items() if v != 0}
        return g, offen
    F = None
    g = 0
    offen = {}
    if fs and os.path.exists(fs):
        for l in open(fs):
            z = l.split()
            if len(z) < 3 or not re.match(r'^[0-9A-F]{4,8}$', z[0]):
                continue
            a = z[0].lower()
            sz = int(z[1].split('/')[0])
            if R is not None and a in R:
                if R[a] == 0:
                    g += 1
                else:
                    offen[a] = R[a]
                continue
            if F is None:
                F = B.funcs(obj)
            if a not in F:
                continue
            if B.gleich(F[a], int(a, 16), sz):
                g += 1
            else:
                offen[a] = diff(u, a, obj, 0)[0]
    return g, offen


if __name__ == '__main__':
    u, src = sys.argv[1], sys.argv[2]
    s = open(src, errors='replace').read()
    for i in range(3, len(sys.argv) - 1, 2):
        s = s.replace(sys.argv[i], sys.argv[i + 1])
    p = os.path.join(C.TMP, f'{u}_var.CPP')
    open(p, 'w', errors='replace').write(s)
    g, o = stand(u, p, os.path.join(C.LIVE, u + '.fstand'))
    print(g, o)
