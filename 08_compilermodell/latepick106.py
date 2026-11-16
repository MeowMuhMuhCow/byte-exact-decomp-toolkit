#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""latepick106.py DATEI.CPP [--fkt f_xxxxxx] - spaete Registerwahl des echten 10.6 mitlesen (worker, 29.10.2026).
10.6-Abbild: 0x9EBFE waehlt fuer eine Konstante, die erst spaet in ein Register wandert, das Register per Rotation:
  Zustand je Groesse (Zeiger auf zuletzt gewaehlten Tabelleneintrag): Byte 0xC707C (Tabelle 0xC1100 AL AH DL DH BL BH CL CH),
  Wort 0xC7078, Dword 0xC7080. Startet beim 2. Eintrag, ueberspringt belegte Register (live | clobber des Befehls).
  ANDERS ALS 10.0 GA: 0x9EF5B setzt alle drei Zustaende zurueck (Aufruf aus 0x7D4DC, je Funktionsdurchgang), nur ab -4r
  (CPU-Stufe >= 4) und Optimierungsstufe <= 0x32.
Ausgabe: je Wahl Funktion, Quellzeile, Groesse, Position vorher, gewaehltes Register."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp

TAB = {0xC707C: ('byte', 0xC1100), 0xC7078: ('wort', 0xC1124), 0xC7080: ('dword', 0xC1330)}
BYTE = {2: 'AL', 1: 'AH', 0x80: 'DL', 0x40: 'DH', 8: 'BL', 4: 'BH', 0x20: 'CL', 0x10: 'CH'}


def fname(e):
    try:
        cp = e.u32(BASE + 0xC6894); fs = e.u32(e.u32(cp + 0x84) + 8)
        return e.cstr(e.u32(e.u32(fs + 0xc) + 0xc), 80)
    except Exception: return '?'


def run(src, fkt=None):
    picks = []; st = {}
    def hook(e):
        def enter(uc, a, s, _):
            ins = e.r(X.UC_X86_REG_EAX); tc = e.rd(ins + 0x38, 1)[0]
            var = 0xC707C if tc < 2 else (0xC7078 if tc <= 3 else (0xC7080 if tc <= 5 else None))
            st['cur'] = dict(fkt=fname(e), line=struct.unpack('<H', e.rd(ins + 0x20, 2))[0], var=var,
                             vorher=(e.u32(BASE + var) - BASE) if var and e.u32(BASE + var) else 0, ins=ins)
        def store(uc, a, s, _):
            c = st.get('cur')
            if not c: return
            p = e.r(X.UC_X86_REG_EAX) - BASE; name, tab = TAB[c['var']]
            regset = e.u32(BASE + p)
            c['groesse'] = name; c['pos'] = (p - tab) // 4; c['vpos'] = ((c['vorher'] - tab) // 4) if c['vorher'] else None
            c['reg'] = BYTE.get(regset, '%x' % regset) if name == 'byte' else '%x' % regset
            picks.append(c); st['cur'] = None
        def reset(uc, a, s, _):
            picks.append(dict(fkt=fname(e), reset=True))
        e.uc.hook_add(U.UC_HOOK_CODE, enter, begin=BASE + 0x9EBFE, end=BASE + 0x9EBFE)
        e.uc.hook_add(U.UC_HOOK_CODE, store, begin=BASE + 0x9EC84, end=BASE + 0x9EC84)
        e.uc.hook_add(U.UC_HOOK_CODE, reset, begin=BASE + 0x9EF5E, end=BASE + 0x9EF5E)
    ok, out, e = comp(src, os.path.join(__import__('w106cfg').TMP, 'lp.obj'), hook=hook)
    return [p for p in picks if not fkt or fkt in p['fkt']]


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('--fkt'); a = ap.parse_args()
    for p in run(a.src, a.fkt):
        if p.get('reset'): print('%-12s ---- Rotation zurueckgesetzt' % p['fkt']); continue
        print('%-12s Zeile %5d  %-5s Position %s -> %d  %s' % (p['fkt'], p['line'], p['groesse'], p['vpos'], p['pos'], p['reg']))
