#!/usr/bin/env python3
"""adr_pruefung.py [EINHEIT ...] (Address-literal verification tool)
Prueft fuer alle GLEICH-Funktionen (live_fstand), ob die globalen Adressen in derselben REIHENFOLGE angesprochen werden
wie im Original. Der Richter maskiert Fixup-Ziele (Platzhalter) und sieht vertauschte Globale nicht.
Aendert nichts. Ergebnis: logs/adr_pruefung/ERGEBNIS.tsv (einheit fkt status n_orig n_neu erste_abweichung)
  status OK | ABWEICHUNG (gleiche Anzahl, andere Folge = echter Verdacht) | UNSICHER (Anzahl verschieden, z.B. andere Symbolnamen)
Aufruf aus dem Projektordner:  ALLE=1 python3 Werkzeuge/wsl/adr_pruefung.py     (alle Einheiten)
                               python3 03_richter/adr_pruefung.py demo_unit  (Test: f_400010)
"""
import os, re, sys, glob, subprocess, tempfile, bisect
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
for _p in (ROOT, os.path.join(ROOT, '01_werkzeugkette'), os.path.join(ROOT, '02_basis')):
    if _p not in sys.path: sys.path.insert(0, _p)
import project_config as PC
_CFG = PC.load_config()
Q = PC.resolve_path('project_root', _CFG)
R = os.path.join(PC.resolve_path('logs_dir', _CFG), 'adr_pruefung'); os.makedirs(R, exist_ok=True)
FLAT_BIN = PC.resolve_path('flat_bin', _CFG)
WDIS = PC.resolve_path('wdis', _CFG)
DATA = re.compile(r'0x(1[a-d][0-9a-f]{4})\b')
def orig_dump():
    p = os.path.join(R, 'target_objdump.txt')
    if not os.path.exists(p):
        with open(p, 'w') as f:
            subprocess.run(['objdump', '-D', '-b', 'binary', '-mi386', '-Mintel', '--no-show-raw-insn', '--adjust-vma=0x10000', FLAT_BIN], stdout=f, check=True)
    A, T = [], []
    for l in open(p, errors='replace'):
        m = re.match(r'\s*([0-9a-f]+):\t(.*)$', l)
        if m: A.append(int(m.group(1), 16)); T.append(m.group(2))
    return A, T
def gleich_fkt(u):
    p = os.path.join(PC.resolve_path('logs_dir', _CFG), 'live_fstand', u + '.fstand'); out = []
    if os.path.exists(p):
        for l in open(p, errors='replace'):
            m = re.match(r'([0-9A-F]{6})\s+(\d+)/(\d+)\s+' + ('' if os.environ.get('QUELLE') else 'GLEICH'), l)   # 06.11.: mit QUELLE alle Funktionen pruefen (W92: Zielfunktion war noch nicht GLEICH im live_fstand)
            if m: out.append((int(m.group(1), 16), int(m.group(2))))
    return out
def neu_folgen(src):
    from comp import comp
    obj = tempfile.mktemp(suffix='.obj')
    ok = comp(src, obj)[0]
    if not ok: return None
    w = subprocess.run([WDIS, '-a', obj], capture_output=True, text=True).stdout.splitlines(); os.remove(obj)
    fk, cur = {}, None
    for l in w:
        m = re.search(r'(?<![0-9A-Za-z_])f_([0-9a-f]{6})', l)
        ist_label = l.rstrip().endswith(':') or re.search(r'\bPROC\b', l)
        if m and ist_label and not re.match(r'^\s*(call|jmp|j[a-z]+|mov|push|lea)\b', l.strip()):
            cur = 'f_' + m.group(1); fk.setdefault(cur, []); continue
        if cur is None: continue
        if re.search(r'\bEND[PS]\b', l): cur = None; continue
        for d in re.finditer(r'(?<![0-9A-Za-z])d_(1[a-d][0-9a-f]{4})(_[A-Za-z0-9]+)?(?:\$[^`\s]*`|\$[^\s,+\[\]-]*)?([+-](0x)?[0-9a-fA-F]+H?(?![0-9A-Za-z_]))?', l):   # [ und Registernamen (+eax) nicht als Versatz   # C++: `W?d_xxxxxx$ni`+2H
            if d.group(2): fk[cur].append('UNBEKANNT'); continue   # Teilsymbol d_xxxxxx_k1: echte Adresse nicht aus dem Namen ablesbar
            roh = d.group(3) or '+0'; o = roh[1:].rstrip('H')
            o = int(o, 16) if (d.group(4) or roh.endswith('H') or not o.isdigit()) else int(o)   # 18H = hex!
            if roh.startswith('-'): o = -o
            fk[cur].append('%06x' % (int(d.group(1), 16) + o))
    return fk
def einheit(u):
    src = os.environ.get('QUELLE') or os.path.join(PC.resolve_path('src_p3_dir', _CFG), u + '_P1.CPP'); gf = gleich_fkt(u)   # 06.11.: QUELLE=Datei prueft eine Arbeitskopie/Kandidaten statt p3 (nur mit genau einer Einheit sinnvoll)
    if not gf or not os.path.exists(src): return []
    try: fk = neu_folgen(src)
    except Exception as e: return [(u, '-', 'FEHLER', 0, 0, str(e)[:80])]
    if fk is None: return [(u, '-', 'UEBERSETZFEHLER', 0, 0, '')]
    if os.environ.get('ZEIGEN'): print('\n'.join(sorted(fk)[:20]))
    res = []
    for a, size in gf:
        i = bisect.bisect_left(FS, a); j = bisect.bisect_left(FS, a + size)
        alt = ['%06x' % g for _, g in FIX[i:j]]   # nur echte Adressen laut Fixup-Tabelle (Konstanten wie 0x1d0000 zaehlen nicht)
        neu = fk.get('f_%06x' % a)
        if neu is None: res.append((u, 'f_%06x' % a, 'UNSICHER', len(alt), 0, 'Funktion im OBJ nicht gefunden')); continue
        if 'UNBEKANNT' in neu: st, d = 'UNSICHER', 'Teilsymbol d_..._kN (Adresse nicht ablesbar)'
        elif alt == neu: st, d = 'OK', ''
        elif len(alt) == len(neu):
            k = next(k for k in range(len(alt)) if alt[k] != neu[k]); st, d = 'ABWEICHUNG', 'Pos %d: orig %s neu %s' % (k, alt[k], neu[k])
        else: st, d = 'UNSICHER', 'Anzahl %d/%d orig %s neu %s' % (len(alt), len(neu), ','.join(alt[:4]), ','.join(neu[:4]))
        res.append((u, 'f_%06x' % a, st, len(alt), len(neu), d))
    return res
def orig_fixups():
    import le
    return sorted((s, g) for s, t, g in le.fixups if 0x1a0000 <= g < 0x1e0000)
FIX = orig_fixups(); FS = [x[0] for x in FIX]
A, T = orig_dump()
if __name__ == '__main__':
    teile = [l.split('\t')[1] for l in open(PC.resolve_path('units_tsv', _CFG)) if '\t' in l]
    liste = sys.argv[1:] or teile
    if os.environ.get('NUR_AUFFAELLIG'):
        liste = sorted({l.split('\t')[0] for l in open(os.path.join(R, 'ERGEBNIS.tsv')) if '\tABWEICHUNG\t' in l or '\tUNSICHER\t' in l})
    E = os.path.join(R, 'ERGEBNIS2.tsv' if os.environ.get('NUR_AUFFAELLIG') else ('ERGEBNIS.tsv' if not sys.argv[1:] else 'TEST_%s.tsv' % '_'.join(sys.argv[1:])[:80]))
    if not sys.argv[1:] and not os.environ.get('NUR_AUFFAELLIG') and os.environ.get('ALLE') != '1':
        sys.exit('Voller Lauf nur mit ALLE=1 (ueberschreibt ERGEBNIS.tsv). Einzeltest: Einheit(en) als Argument.')
    ZIEL = E; E = E + '.neu'   # erst am Ende atomar ersetzen - Abbruch zerstoert nichts
    with open(E, 'w') as f: f.write('einheit\tfkt\tstatus\tn_orig\tn_neu\terste_abweichung\n')
    with Pool(int(os.environ.get('N', 3))) as p:
        for res in p.imap_unordered(einheit, liste):
            with open(E, 'a') as f:
                for r in res:
                    f.write('\t'.join(map(str, r)) + '\n')
                    if r[2] != 'OK': print('\t'.join(map(str, r)), flush=True)
    os.replace(E, ZIEL); E = ZIEL
    s = [l.split('\t')[2] for l in open(E)][1:]
    print('FERTIG: %d Funktionen | OK %d | ABWEICHUNG %d | UNSICHER %d | Fehler %d -> %s' % (len(s), s.count('OK'), s.count('ABWEICHUNG'), s.count('UNSICHER'), len([x for x in s if 'FEHLER' in x]), E))
