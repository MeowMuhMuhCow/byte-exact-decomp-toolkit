#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mischer worker - Bibliothek (worker, 07.11.2026).

Neu gegenueber mischer_lib.py (das unveraendert bleibt und hier nur benutzt wird):
  1. Messung in ORIGINAL-Koordinaten: jede Fassung wird im Emulator uebersetzt; fuer jeden Originalbefehl i
     steht fest, ob die Fassung ihn trifft (cov[i]) und welcher ihrer Quellabschnitte ihn erzeugt (seg[i]).
     Damit sind Abschnitte verschiedener Fassungen ueber das Original vergleichbar, auch wenn ihr Text,
     ihre Schluessel (Fingerabdruck) oder ihre Zerlegung verschieden sind.
  2. Tauschbloecke = Zusammenhangskomponenten des Ueberlappungsgraphen (Basis-Abschnitte x Spender-Abschnitte,
     verbunden, wenn sie denselben Originalbefehl erzeugen). Vorhergesagter Gewinn g = SUMME (covD - covB) im Block.
  3. Namensangleichung: Lokale/Parameter des Spenders werden ueber Tokenausrichtung der ganzen Funktion
     auf die Namen der Basis abgebildet, bevor getauscht wird (gegen 'already defined'/'not declared').
  4. Haltemodell: P(Tausch haelt | Kontextaehnlichkeit) als Beta-Posterior je Aehnlichkeitsklasse, aus den
     eigenen Kreuzungen online gelernt; Kopplung: beschaedigt ein Tausch Befehle ausserhalb seines Blocks,
     werden die betroffenen Bloecke desselben Spenders als gekoppelter Block nachgeschoben.
  5. Konsens: Spendertexte, die mehrere Familien unabhaengig treffen, bekommen Vorrang (Satz 5).
Keine Rueckwaertsrechnung, kein Loeser: nur gemessene Treffer anderer Fassungen werden kombiniert.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time

import mischer_lib as M

HERE = M.HERE
ROOT = M.ROOT
worker = os.path.join(PC.resolve_path('logs_dir', _CFG), 'mixer')
worker = os.environ.get('O14_ORDNER') or worker   # D9 12.11.: eigener Laufordner fuer Tests (Standard wie bisher)
MESS_ID = os.environ.get('O14_ID', 'worker')
M.WORKER_ID = MESS_ID          # eigene Mess-ID fuer probe_queue (nicht worker der Mischer-Nacht)


# ---------------- Eichung D8 (12.11.2026): Lupe = Richter auf dem Emulator-OBJ ----------------
# Befund D8/BEFUND.md: align_dist blendet Sprungziele ganz aus ('j X'), der Richter (fstand.py) vergleicht sie relativ
# zum Funktionsanfang (Sprungversatz zaehlt) und maskiert Globale ueber echte Relokationen. Daher lag die alte Lupe
# 25-90 Befehle unter dem nativen Rest. Mit O14_EICHUNG=1 (Standard) wird der Abstand 'dist' vom UNVERAENDERTEN
# Richter auf dem Emulator-OBJ berechnet (gleiche Bytes wie nativ); 'dist_alt' behaelt den alten Wert, cov/segl bleiben
# die alte Zuordnung (nur Kartierung der Abschnitte). O14_EICHUNG=0: alter Weg.
EICHUNG = os.environ.get('O14_EICHUNG', '1') != '0'
RICHTER = os.path.join(M.TOOLKIT_ROOT, '03_richter', 'fstand.py')
_TEILE = None


def _teile():
    global _TEILE
    if _TEILE is None:
        t = []
        for l in open(M.PC.resolve_path('units_tsv', M._CFG), encoding='utf-8', errors='replace'):
            c = l.rstrip('\n').split('\t')
            if len(c) > 3 and re.fullmatch(r'[0-9a-fA-F]{6}', c[2]) and re.fullmatch(r'[0-9a-fA-F]{6}', c[3]):
                t.append((c[1], c[2], int(c[2], 16), int(c[3], 16)))
        _TEILE = t
    return _TEILE


def einheit_lo(einheit=None, fkt=None):
    """Anfangsadresse (Text, wie probe.sh lo_von) der Einheit; ohne Einheit ueber die Funktionsadresse."""
    if einheit:
        for e, lo, a, b in _teile():
            if e == einheit:
                return lo
    if fkt:
        ad = int(fkt.replace('f_', ''), 16)
        tr = [(b - a, lo) for e, lo, a, b in _teile() if a <= ad < b]
        if tr:
            return min(tr)[1]
    return None


def richter_rest(obj, einheit, fkt, timeout=120):
    """Richter (fstand.py, unveraendert) auf ein OBJ. Rueckgabe dict: rest (0 = GLEICH, sonst Befehle, mind. 1),
    gleich, groesse (orig, neu), fehlt, fehler."""
    lo = einheit_lo(einheit, fkt)
    if not lo:
        return {'rest': None, 'fehler': f'Einheit {einheit} unbekannt'}
    env = os.environ.copy()
    pass
    try:
        r = subprocess.run(['python3', RICHTER, obj, lo], capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {'rest': None, 'fehler': 'Richter timeout'}
    key = fkt.replace('f_', '').upper()
    for line in (r.stdout or '').splitlines():
        m = re.match(r'^([0-9A-Fa-f]{4,8})\s+(\d+)/(\d+)\s+(GLEICH|(\d+) Befehle|FEHLT|AUSSERHALB)', line)
        if not m or m.group(1).upper().lstrip('0') != key.lstrip('0'):
            continue
        g = (int(m.group(2)), int(m.group(3)))
        if m.group(4) == 'GLEICH':
            return {'rest': 0, 'gleich': True, 'groesse': g}
        if m.group(5) is not None:
            return {'rest': max(1, int(m.group(5))), 'gleich': False, 'groesse': g, 'roh': int(m.group(5))}
        return {'rest': None, 'fehlt': True, 'fehler': 'Richter: ' + m.group(4)}
    return {'rest': None, 'fehler': 'Richter ohne Zeile: ' + ((r.stderr or '')[-300:] or (r.stdout or '')[-300:])}


# ---------------- Herkunft / Familie ----------------

FAM_PREFIX = (('S', 'Gemini'), ('B', 'Gemini'), ('V', 'Gemini'), ('O', 'ModelO'), ('K', 'ModelK'),
              ('Z', 'ModelZ'), ('L', 'Loeser'), ('W', 'Flick-W'), ('G', 'Flick-G'))


def herkunft(pfad):
    """(familie, quelle). quelle = je Lauf eigene ID (Ordnername), familie = Modellfamilie."""
    p = (pfad or '').replace('\\', '/')
    m = re.search(r'/src/(p[123])/', p)
    if m:
        return m.group(1), m.group(1)
    if '/ghidra' in p.lower():
        return 'Ghidra', 'ghidra'
    if '/F12/' in p or '/loeser' in p.lower():
        return 'Loeser', 'F12'
    m = re.search(r'/(Blind|Flick)/arbeit/([^/]+)/', p)
    if m:
        lid = m.group(2)
        if re.fullmatch(r'\d+', lid):
            import mischer as X
            fam = X.zeichner_nach_id().get(lid, '') or 'Blind-num'
            return fam, lid
        for pre, fam in FAM_PREFIX:
            if lid.upper().startswith(pre):
                return fam, lid
        if lid.upper().startswith('O3'):
            return 'ModelO', lid
        return 'sonst', lid
    m = re.search(r'/wave/([^/]+)/', p)
    if m:
        if m.group(1) in ('worker', 'worker', 'F14'):
            return 'Mischer', m.group(1)
        return 'Wave', m.group(1)
    if '/kandidaten/' in p:
        return 'kandidat', 'kandidat'
    for name in ('model_a', 'model_b', 'model_c', 'model_d', 'model_e', 'model_f'):
        if re.search(name, p, re.I):
            return name, name
    return 'sonst', os.path.dirname(p)[-24:]


# ---------------- Zerlegung in Abschnitte (Textspannen) ----------------

MAXT = 3


def segmente(func):
    """Liste von Abschnitten (a, b, tiefe, eltern) in func (Funktionstext). Deklarationen ausgenommen.
    Jede Anweisung ist ein Abschnitt ihrer Tiefe; Rumpf-Bloecke von for/while/do/if/else werden rekursiv
    (bis Tiefe MAXT) als eigene, tiefere Abschnitte zerlegt. switch: jeder Fall ein Abschnitt."""
    br = M._body_brace(func)
    if br is None:
        return []
    e = len(func) - 1
    while e > br and func[e] != '}':
        e -= 1
    out = []

    def rumpf(p, tiefe, eltern):
        """p zeigt auf eine Anweisung (Rumpf). Block -> innen zerlegen; if -> als Anweisung tiefer."""
        p = M._skip(func, p)
        if p < len(func) and func[p] == '{':
            bend = M._balanced(func, p, '{', '}')
            walk(p + 1, bend - 1, tiefe, eltern)
            return bend
        k, _ = M._ident_at(func, p)
        ende = M.end_of_stmt(func, p)
        if k in ('if', 'for', 'while', 'do', 'switch'):
            walk(p, ende, tiefe, eltern)
        return ende

    def walk(i, end, tiefe, eltern):
        while True:
            i = M._skip(func, i)
            if i >= end or func[i] == '}':
                return
            st = i
            k, j = M._ident_at(func, i)
            if k == 'switch':
                p = M._skip(func, j)
                if p < len(func) and func[p] == '(':
                    p = M._balanced(func, p, '(', ')')
                b = M._skip(func, p)
                if b < len(func) and func[b] == '{':
                    bend = M._balanced(func, b, '{', '}') - 1
                    for labels, a, c in M._split_cases(func, b + 1, bend):
                        if labels and c > a:
                            out.append((a, c, tiefe, f'sw{st}'))
                    i = bend + 1
                    continue
            ende = M.end_of_stmt(func, i)
            if ende <= st:
                return
            chunk = func[st:ende]
            if not M._is_decl(chunk):
                out.append((st, ende, tiefe, eltern))
            if tiefe < MAXT and k in ('for', 'while', 'if', 'do'):
                try:
                    p = M._skip(func, j)
                    if k == 'do':
                        rumpf(p, tiefe + 1, f'{k}{st}')
                    elif p < len(func) and func[p] == '(':
                        p = M._balanced(func, p, '(', ')')
                        then_e = rumpf(p, tiefe + 1, f'{k}{st}')
                        if k == 'if':
                            q = M._skip(func, then_e)
                            k2, j2 = M._ident_at(func, q)
                            if k2 == 'else' and j2 <= ende:
                                rumpf(j2, tiefe + 1, f'{k}{st}')
                except Exception:
                    pass
            i = ende

    walk(br + 1, e, 0, 'top')
    out = sorted(set(out))
    return out


# ---------------- Messen ----------------

def _orig_zu_neu(opcodes, n_orig, n_neu):
    m = [-1] * n_orig
    eq = [0] * n_orig
    for op, i1, i2, j1, j2 in opcodes:
        for i in range(i1, i2):
            if op == 'equal':
                m[i] = j1 + (i - i1)
                eq[i] = 1
            elif op == 'replace':
                m[i] = min(j2 - 1, j1 + (i - i1) * max(1, (j2 - j1)) // max(1, (i2 - i1)))
            elif op == 'delete':
                m[i] = min(max(0, j1), n_neu - 1) if n_neu else -1
    return m, eq


def messe(einheit, fkt, unit_text, tag, orig, ordner, timeout=150):
    """Emulator mit -d1. Rueckgabe dict: ok, dist, dist_struct, cov, seg0, seg1 (Orig-Index -> Abschnittsnr.),
    segs (Liste a,b,tiefe,eltern im Funktionstext), fn_text, src, fehler."""
    src = os.path.join(ordner, tag + '.CPP')
    obj = os.path.join(ordner, tag + '.obj')
    os.makedirs(ordner, exist_ok=True)
    with open(src, 'w', encoding='latin1', errors='replace') as h:
        h.write(unit_text)
    ok, out = M.emu_compile(src, obj, ['-d1'], timeout=timeout)
    if not ok:
        return {'ok': False, 'fehler': out[-600:], 'src': src}
    try:
        return analysiere(unit_text, obj, src, fkt, orig, einheit=einheit)
    except Exception as ex:
        return {'ok': False, 'fehler': f'Analyse: {ex!r}', 'src': src}


def analysiere(unit_text, obj, src, fkt, orig, einheit=None):
    ins = M.obj_asm(obj, fkt)
    if not ins:
        return {'ok': False, 'fehler': 'kein ASM der Funktion', 'src': src}
    rr = richter_rest(obj, einheit, fkt) if EICHUNG else None
    if rr is not None and rr.get('fehlt'):
        return {'ok': False, 'fehler': rr['fehler'], 'src': src}
    ga = M.align_dist(orig, ins)
    m, eq = _orig_zu_neu(ga['opcodes'], len(orig), len(ins))
    sp = M._function_span(unit_text, fkt)
    fn_text = unit_text[sp[0]:sp[1]] if sp else ''
    segs = segmente(fn_text) if fn_text else []
    segl = [[-1] * len(orig) for _ in range(MAXT + 1)]
    zeile_rel = [-1] * len(orig)
    start, end, _ = M._funktions_grenzen(obj, fkt)
    if sp and start is not None:
        rel = sorted((off - start, line) for line, off in M.linnum_pairs(obj) if start <= off < end)
        base = unit_text[:sp[0]].count('\n') + 1
        zeilen = []
        for idx, (a, b, t, e) in enumerate(segs):
            zeilen.append((base + fn_text[:a].count('\n'), base + fn_text[:b].count('\n'), idx, t))
        offs = [o for o, _ in rel]
        import bisect
        for i in range(len(orig)):
            j = m[i]
            if j < 0 or j >= len(ins):
                continue
            k = bisect.bisect_right(offs, ins[j][0] - ins[0][0]) - 1
            if k < 0:
                continue
            ln = rel[k][1]
            zeile_rel[i] = ln - base
            beste = [None] * (MAXT + 1)
            for a, b, idx, t in zeilen:
                if a <= ln <= b:
                    for lv in range(t, MAXT + 1):
                        if beste[lv] is None or t > beste[lv][0] or (t == beste[lv][0] and (b - a) < beste[lv][1]):
                            beste[lv] = (t, b - a, idx)
            for lv in range(MAXT + 1):
                if beste[lv]:
                    segl[lv][i] = beste[lv][2]
    out = {'ok': True, 'dist': ga['dist'], 'dist_struct': ga['dist_struct'], 'cov': eq, 'segl': segl, 'zeile': zeile_rel,
           'segs': segs, 'fn_text': fn_text, 'src': src, 'n_neu': len(ins)}
    if rr is not None:
        out['dist_alt'] = ga['dist']
        if rr.get('rest') is not None:     # Lupe = Richter (D8)
            out['dist'] = rr['rest']
            out['eich'] = 1
            out['groesse'] = rr.get('groesse')
        else:   # Richter versagt: NICHT auf den alten Wert zurueckfallen (der liegt systematisch zu tief und wuerde bevorzugt)
            return {'ok': False, 'fehler': 'Eichung: ' + (rr.get('fehler') or '?')[-300:], 'src': src}
    return out


# ---------------- Namensangleichung ----------------

TOK = re.compile(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|->|\+\+|--|<<|>>|[<>=!]=|&&|\|\||\S')


def lokale_und_parameter(fn_text, fkt):
    fn = M.parse_funktion(fn_text, fkt) or M.parse_funktion('//@ ' + fkt + '\n' + fn_text, fkt)
    if not fn:
        return set(), {}
    typen = {n: t for t, n in fn.lokale}
    idx = M.deklarations_index(fn.text)
    namen = set(typen) | set(M._parameter_namen(fn.signatur)) | {n for n in idx if n not in M.TYPE_KW}
    namen = {n for n in namen if not n.startswith('f_')}
    return namen, typen


def namensabbildung(basis_text, spender_text, fkt):
    """Spender-Lokalname -> Basis-Lokalname aus der Tokenausrichtung beider Funktionen."""
    lb, _ = lokale_und_parameter(basis_text, fkt)
    ld, _ = lokale_und_parameter(spender_text, fkt)
    if not lb or not ld:
        return {}
    tb = TOK.findall(basis_text)
    td = TOK.findall(spender_text)
    fb = ['V' if t in lb else t for t in tb]
    fd = ['V' if t in ld else t for t in td]
    sm = difflib.SequenceMatcher(None, fd, fb, autojunk=False)
    stimmen = {}
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != 'equal':
            continue
        for k in range(i2 - i1):
            a, b = td[i1 + k], tb[j1 + k]
            if a in ld and b in lb:
                stimmen[(a, b)] = stimmen.get((a, b), 0) + 1
    abb = {}
    belegt = set()
    for (a, b), v in sorted(stimmen.items(), key=lambda x: -x[1]):
        if a in abb or b in belegt:
            continue
        abb[a] = b
        belegt.add(b)
    return {a: b for a, b in abb.items() if a != b}


def umbenennen(text, abb):
    if not abb:
        return text
    return re.sub(r'\b[A-Za-z_]\w*\b', lambda m: abb.get(m.group(0), m.group(0)), text)


# ---------------- Tauschbloecke ----------------

def tauschbloecke(mb, md, lv):
    """Bloecke (Basis-Abschnitte, Spender-Abschnitte, Orig-Indizes) fuer Ebene lv (0/1)."""
    sb = mb['segl'][lv]
    sd = md['segl'][lv]
    n = len(sb)
    eltern = {}
    for idx, s in enumerate(mb['segs']):
        eltern[('B', idx)] = (s[2], s[3])
    for idx, s in enumerate(md['segs']):
        eltern[('D', idx)] = (s[2], s[3])
    par = {}

    def find(x):
        while par.setdefault(x, x) != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb

    for i in range(n):
        if sb[i] >= 0:
            find(('B', sb[i]))
        if sd[i] >= 0:
            find(('D', sd[i]))
        if sb[i] >= 0 and sd[i] >= 0:
            union(('B', sb[i]), ('D', sd[i]))
    # Zusammenhaengend machen: Luecken in der Abschnittsreihenfolge schliessen
    for _ in range(6):
        comps = {}
        for x in list(par):
            comps.setdefault(find(x), []).append(x)
        geaendert = False
        for c in comps.values():
            for seite in ('B', 'D'):
                ids = sorted(x[1] for x in c if x[0] == seite)
                if len(ids) >= 2:
                    for k in range(ids[0], ids[-1] + 1):
                        if (seite, k) in par and find((seite, k)) != find(c[0]):
                            union((seite, k), c[0])
                            geaendert = True
        if not geaendert:
            break
    comps = {}
    for x in list(par):
        comps.setdefault(find(x), []).append(x)
    bloecke = []
    for c in comps.values():
        B = sorted(x[1] for x in c if x[0] == 'B')
        D = sorted(x[1] for x in c if x[0] == 'D')
        if not B or not D:
            continue
        # gleiche Ebene/Eltern-Art je Seite
        tb = {eltern[('B', k)][0] for k in B}
        td = {eltern[('D', k)][0] for k in D}
        if len(tb) != 1 or tb != td:
            continue
        sB, sD = set(B), set(D)
        span = [i for i in range(n) if sb[i] in sB or sd[i] in sD]
        bloecke.append((B, D, span))
    return bloecke


def block_gewinn(mb, md, span):
    return sum(md['cov'][i] - mb['cov'][i] for i in span)


def block_texte(mb, md, B, D):
    ab = mb['segs'][B[0]][0]
    eb = mb['segs'][B[-1]][1]
    ad = md['segs'][D[0]][0]
    ed = md['segs'][D[-1]][1]
    return (ab, eb), md['fn_text'][ad:ed]


def aehnlichkeit(mb, md, span):
    """Jaccard der getroffenen Originalbefehle ausserhalb des Blocks (Kontextnaehe)."""
    s = set(span)
    a = b = 0
    for i in range(len(mb['cov'])):
        if i in s:
            continue
        x, y = mb['cov'][i], md['cov'][i]
        if x or y:
            b += 1
            if x and y:
                a += 1
    return a / b if b else 0.0


# ---------------- Haltemodell (Beta je Aehnlichkeitsklasse) ----------------

class Haltemodell:
    KLASSEN = (0.0, 0.6, 0.8, 0.9, 0.95, 1.01)

    def __init__(self, vorwert=(1.0, 3.0)):
        self.ab = {k: list(vorwert) for k in range(len(self.KLASSEN) - 1)}

    def klasse(self, sim):
        for k in range(len(self.KLASSEN) - 1):
            if self.KLASSEN[k] <= sim < self.KLASSEN[k + 1]:
                return k
        return len(self.KLASSEN) - 2

    def p(self, sim):
        a, b = self.ab[self.klasse(sim)]
        return a / (a + b)

    def ucb(self, sim):
        a, b = self.ab[self.klasse(sim)]
        n = a + b
        return a / n + math.sqrt(a * b / (n * n * (n + 1)))

    def lerne(self, sim, hielt):
        k = self.klasse(sim)
        if hielt:
            self.ab[k][0] += 1
        else:
            self.ab[k][1] += 1

    def tabelle(self):
        z = []
        for k in range(len(self.KLASSEN) - 1):
            a, b = self.ab[k]
            z.append(f'{self.KLASSEN[k]:.2f}-{min(1, self.KLASSEN[k + 1]):.2f}: p={a / (a + b):.2f} (n={a + b - 4:.0f})')
        return '; '.join(z)


# ---------------- Abgabe ----------------

def abgeben(einheit, fkt, datei, rest_vorher, rest_nachher, grund):
    if M.gesperrt(einheit):
        M.log(f'nicht abgeben: {einheit} gesperrt')
        return False
    if rest_nachher is None or rest_vorher is None or rest_nachher >= rest_vorher:
        M.log('nicht abgeben: nicht besser')
        return False
    ziel = os.path.join(M.KAND, f'{einheit}_P1.CPP')
    # Regel worker/F14: juenger als 10 min -> warten
    for _ in range(25):
        if os.path.exists(ziel) and time.time() - os.path.getmtime(ziel) < 600:
            M.log(f'{ziel} juenger als 10 min, warte')
            time.sleep(30)
            continue
        break
    shutil.copyfile(datei, ziel)
    import datetime
    status = 'GLEICH' if rest_nachher == 0 else 'besser'
    zeile = '\t'.join([datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                       einheit, fkt, str(rest_vorher), str(rest_nachher), status, '', 'mischerO14 ' + grund])
    with open(M.ERGEBNISSE, 'a', encoding='utf-8') as h:
        h.write(zeile + '\n')
    M.log(f'abgegeben {ziel} ({status} {rest_vorher}->{rest_nachher})')
    return True


# ---------------- Token-Hunks (kleinste Textunterschiede zu nahen Fassungen) ----------------

def hunks(base_fn, donor_fn, max_n=40):
    """Unterschiede Basis -> Spender auf Tokenebene, benachbarte zusammengefasst.
    Rueckgabe Liste (a, b, text, da, db): Basistext[a:b] wird durch text (= Spender[da:db]) ersetzt."""
    br_b = M._body_brace(base_fn)
    br_d = M._body_brace(donor_fn)
    if br_b is None or br_d is None:
        return []
    tb = [(m.group(0), m.start(), m.end()) for m in TOK.finditer(base_fn) if m.start() > br_b]
    td = [(m.group(0), m.start(), m.end()) for m in TOK.finditer(donor_fn) if m.start() > br_d]
    sm = difflib.SequenceMatcher(None, [x[0] for x in tb], [x[0] for x in td], autojunk=False)
    ops = [list(o[1:]) for o in sm.get_opcodes() if o[0] != 'equal']
    if not ops:
        return []
    zus = [ops[0]]
    for o in ops[1:]:
        if o[0] - zus[-1][1] <= 1 and o[2] - zus[-1][3] <= 1:
            zus[-1][1], zus[-1][3] = o[1], o[3]
        else:
            zus.append(o)
    if len(zus) > max_n:
        return []
    out = []
    for i1, i2, j1, j2 in zus:
        if i1 < len(tb):
            a = tb[i1][1]
        else:
            a = tb[-1][2]
        b = tb[i2 - 1][2] if i2 > i1 else a
        if j2 > j1:
            da, db = td[j1][1], td[j2 - 1][2]
            text = donor_fn[da:db]
            if i2 == i1:
                text = text + ' '
        else:
            da = db = td[j1][1] if j1 < len(td) else len(donor_fn)
            text = ''
        if M._brace_delta(base_fn[a:b]) != M._brace_delta(text.strip()) or M._brace_delta(text.strip()) != 0:
            continue
        if base_fn[a:b].count('"') % 2 or text.count('"') % 2:
            continue
        out.append((a, b, text, da, db))
    return out


# ---------------- Merkmalsregression ueber die ganze Population ----------------

def merkmale(p3_fn, fassungen, fkt, max_n=30):
    """Jede Fassung als Menge von Hunks relativ zu p3 (nach Namensangleichung).
    Rueckgabe (zeilen, merkmal_info): zeilen = [(dist, [schluessel...])], info[schluessel] = (a, b, text, anzahl, familien)."""
    zeilen = []
    info = {}
    for fa in fassungen:
        m = fa['m']
        abb = namensabbildung(p3_fn, m['fn_text'], fkt)
        dfn = umbenennen(m['fn_text'], abb)
        H = hunks(p3_fn, dfn, max_n=max_n)
        if not H and re.sub(r'\s+', '', dfn) != re.sub(r'\s+', '', p3_fn):
            continue
        keys = []
        for a, b, text, da, db in H:
            k = (a, b, re.sub(r'\s+', ' ', text).strip())
            keys.append(k)
            if k not in info:
                info[k] = [a, b, text, 0, set()]
            info[k][3] += 1
            info[k][4].add(fa['familie'])
        zeilen.append((m['dist'], keys, m['cov']))
    return zeilen, info


def ridge(zeilen, y0, info, lam=1.0, min_n=2, iters=60):
    """y_j = y0 + SUMME beta_k x_jk (+ Rauschen), Koordinatenabstieg, nur Merkmale mit >= min_n Vorkommen."""
    ks = [k for k, v in info.items() if v[3] >= min_n]
    idx = {k: i for i, k in enumerate(ks)}
    X = [[idx[k] for k in z[1] if k in idx] for z in zeilen]
    r = [z[0] - y0 for z in zeilen]
    beta = [0.0] * len(ks)
    spalten = [[] for _ in ks]
    for j, xs in enumerate(X):
        for i in xs:
            spalten[i].append(j)
    for _ in range(iters):
        for i in range(len(ks)):
            col = spalten[i]
            if not col:
                continue
            s = sum(r[j] + beta[i] for j in col)
            neu = s / (len(col) + lam)
            d = neu - beta[i]
            if d:
                for j in col:
                    r[j] -= d
                beta[i] = neu
    return {k: beta[idx[k]] for k in ks}


def beste_intervalle(kand):
    """Gewichtete Intervallplanung (exakt, DP): kand = [(a, b, gewicht, k)], Intervalle [a,b) duerfen sich nicht
    ueberlappen (Einfuegungen a==b belegen [a,a+1)). Rueckgabe Liste k mit maximaler Gewichtssumme."""
    iv = sorted([(a, max(b, a + 1), w, k) for a, b, w, k in kand if w > 0], key=lambda x: x[1])
    import bisect
    ends = [x[1] for x in iv]
    best = [0.0] * (len(iv) + 1)
    wahl = [None] * (len(iv) + 1)
    for i, (a, b, w, k) in enumerate(iv, 1):
        p = bisect.bisect_right(ends, a, 0, i - 1)
        mit = best[p] + w
        if mit > best[i - 1]:
            best[i] = mit
            wahl[i] = ('mit', p)
        else:
            best[i] = best[i - 1]
            wahl[i] = ('ohne', i - 1)
    out = []
    i = len(iv)
    while i > 0:
        art, p = wahl[i]
        if art == 'mit':
            out.append(iv[i - 1][3])
            i = p
        else:
            i = p
    return out[::-1]


def wende_an(fn_text, hunks_liste):
    """hunks_liste: [(a, b, text)] in Koordinaten von fn_text, nicht ueberlappend."""
    for a, b, text in sorted(hunks_liste, key=lambda h: -h[0]):
        fn_text = fn_text[:a] + text + fn_text[b:]
    return fn_text


def buendeln(zeilen, info):
    """Hunks mit identischem Vorkommensmuster (gleiche Fassungsmenge) zu einem Merkmal zusammenfassen."""
    vork = {}
    for j, z in enumerate(zeilen):
        for k in z[1]:
            vork.setdefault(k, set()).add(j)
    gruppen = {}
    for k, js in vork.items():
        gruppen.setdefault(frozenset(js), []).append(k)
    g_info = {}
    neu_zeilen = [(z[0], [], z[2]) for z in zeilen]
    for js, ks in gruppen.items():
        gk = tuple(sorted(ks))
        fam = set()
        for k in ks:
            fam |= info[k][4]
        g_info[gk] = [min(info[k][0] for k in ks), max(info[k][1] for k in ks), None, len(js), fam]
        for j in js:
            neu_zeilen[j][1].append(gk)
    return neu_zeilen, g_info


def assoziation(zeilen, ginfo, cov_basis, je_stelle=2, min_a=2):
    """Je Fehlstelle i der Basis: Merkmale, die bei Fassungen mit Treffer an i angereichert sind (Log-Odds, +0.5).
    Rueckgabe [(score, merkmal, stelle)] absteigend."""
    import math as _m
    n = len(zeilen)
    out = []
    for i, c in enumerate(cov_basis):
        if c:
            continue
        hit = [j for j in range(n) if zeilen[j][2][i]]
        if not hit or len(hit) == n:
            continue
        hs = set(hit)
        zaehl = {}
        for j in range(n):
            for gk in zeilen[j][1]:
                z = zaehl.setdefault(gk, [0, 0])
                z[0 if j in hs else 1] += 1
        nh, nn = len(hit), n - len(hit)
        best = []
        for gk, (a, c2) in zaehl.items():
            if a < min_a:
                continue
            b, d = nh - a, nn - c2
            lo = _m.log((a + .5) / (b + .5)) - _m.log((c2 + .5) / (d + .5))
            best.append((lo * _m.sqrt(a), gk))
        best.sort(key=lambda x: -x[0])
        for s, gk in best[:je_stelle]:
            out.append((s, gk, i))
    out.sort(key=lambda x: -x[0])
    return out


def konsens_buendel(zeilen, ginfo, info, cov_basis, lo_min=1.5, anteil=0.0):
    """Je Fehlstelle der Basis: ALLE Hunks, die bei den treffenden Fassungen angereichert sind (Log-Odds >= lo_min)
    und bei mindestens `anteil` der Treffer vorkommen, als EIN Buendel. Ueberlappende Hunks: exakte Intervall-DP nach
    Haeufigkeit unter den Treffern. Gleiche Buendel verschiedener Stellen werden zusammengelegt.
    Rueckgabe [(score, buendel_tuple_of_hunk_keys, stellen)]."""
    import math as _m
    n = len(zeilen)
    buendel = {}
    for i, c in enumerate(cov_basis):
        if c:
            continue
        hs = {j for j in range(n) if zeilen[j][2][i]}
        nh, nn = len(hs), n - len(hs)
        if nh < 2 or nn < 1:
            continue
        zaehl = {}
        for j in range(n):
            for gk in zeilen[j][1]:
                z = zaehl.setdefault(gk, [0, 0])
                z[0 if j in hs else 1] += 1
        kand = []
        score = 0.0
        for gk, (a, c2) in zaehl.items():
            if a < max(3, anteil * nh):
                continue
            b, d = nh - a, nn - c2
            lo = _m.log((a + .5) / (b + .5)) - _m.log((c2 + .5) / (d + .5))
            if lo < lo_min:
                continue
            for k in gk:
                kand.append((info[k][0], info[k][1], a + lo, k))
            score += lo
        if not kand:
            continue
        wahl = tuple(sorted(beste_intervalle(kand)))
        if wahl:
            e = buendel.setdefault(wahl, [0.0, []])
            e[0] = max(e[0], score)
            e[1].append(i)
    return sorted(((s, b, st) for b, (s, st) in buendel.items()), key=lambda x: -x[0])
