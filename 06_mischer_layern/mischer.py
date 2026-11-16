#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mischer (worker).

  mischer.py --sammle EINHEIT FKT
  mischer.py EINHEIT FKT FASUNG1 FASUNG2 [...] [--basis DATEI] [--procs N] [--zeit MIN] [--abgeben] [--strahl N]
  mischer.py EINHEIT FKT --ernte [--abgeben]
  mischer.py --stamm EINHEIT FKT FASUNG
  mischer.py --empfehlung EINHEIT FKT
  mischer.py --eichung e0|e1|e2|e3|e4
  mischer.py --mini EINHEIT FKT DATEI
  mischer.py --nacht [--abgeben] [--procs N] [--zeit MIN] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import mischer_lib as M

HERE = M.HERE


def quelle_der_einheit(einheit):
    for st in ('p3', 'p2', 'p1'):
        p = os.path.join(M.ROOT, 'Quelle', 'cpp', st, f'{einheit}_P1.CPP')
        if os.path.isfile(p):
            return p
    raise SystemExit(f'keine Quelle fuer {einheit}')


def lauf_ordner(einheit, fkt):
    p = os.path.join(HERE, 'lauf', f'{einheit}_{fkt}')
    os.makedirs(p, exist_ok=True)
    return p


def _schreib(pfad, text):
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, 'w', encoding='latin1', errors='replace') as h:
        h.write(text)


def _anhang(pfad, text):
    with open(pfad, 'a', encoding='utf-8') as h:
        h.write(text)


def fassung_laden(pfad, fkt):
    text = open(pfad, encoding='latin1', errors='replace').read()
    fn = M.parse_funktion(text, fkt, pfad)
    if not fn:
        return None
    h = __import__('hashlib').sha1(re.sub(r'\s+', '', fn.text).encode('latin1', 'replace')).hexdigest()
    return {'hash': h, 'pfad': pfad, 'fn': fn, 'text': text, 'ghidra': 'ghidra' if 'ghidra' in pfad else '',
            'signatur': M.signatur_kern(fn.signatur)}


def _splice(basis_unit, fkt, fn_text, helfer):
    neu = M.setze_funktion(basis_unit, fkt, fn_text)
    if neu is None:
        return None
    if helfer:
        block = '\n\n'.join(helfer) + '\n\n'
        # vor die Funktion
        sp = M._function_span(neu, fkt)
        if sp:
            neu = neu[:sp[0]] + block + neu[sp[0]:]
    return neu


def _score_text(einheit, fkt, unit_text, tag, orig, ordner):
    src = os.path.join(ordner, tag + '.CPP')
    obj = os.path.join(ordner, tag + '.obj')
    _schreib(src, unit_text)
    # -d1 nur zur Zeilenzuordnung. E0: das CODE-Segment bleibt dasselbe, gemessen wird dieser Code.
    extra = ['-d1'] if M.d1_erlaubt() else None
    ok, out = M.emu_compile(src, obj, extra)
    if not ok:
        return {'ok': False, 'ausgabe': out[-400:], 'src': src}
    ins = M.obj_asm(obj, fkt)
    if not ins:
        return {'ok': False, 'ausgabe': 'kein ASM der Funktion', 'src': src}
    fn = M.parse_funktion(unit_text, fkt, src)
    if not fn:
        return {'ok': False, 'ausgabe': 'Funktion nach dem Einsetzen nicht lesbar', 'src': src}
    zeilen = M.zeilen_zuordnung(obj, fkt, unit_text, fn) if extra else None
    bew = M.bewerte(fn, orig, ins, zeilen)
    return {'ok': True, 'bew': bew, 'fn': fn, 'ins': ins, 'src': src, 'obj': obj, 'text': unit_text}


def bewerte_fassungen(einheit, fkt, fassungen, basis_unit, orig, ordner, procs, deadline):
    """Jede Fassung in die aktuelle Einheit setzen, im Emulator uebersetzen, Abschnitte bewerten."""
    os.makedirs(ordner, exist_ok=True)
    aufgaben = []
    for i, f in enumerate(fassungen):
        calls = []
        for sec in f['fn'].abschnitte:
            calls.extend(sec.calls)
        helfer = M.helfer_zeilen(f['text'], calls, basis_unit)
        if any(M.verbotener_code(h) for h in helfer):
            f['verworfen'] = 'helfer-verboten'
            continue
        text = _splice(basis_unit, fkt, f['fn'].text, helfer)
        if text is None:
            f['verworfen'] = 'nicht einsetzbar'
            continue
        if M.verbotener_code(f['fn'].text):
            f['verworfen'] = M.verbotener_code(f['fn'].text)
            continue
        aufgaben.append((i, f, text))
    erg = {}

    def eine(job):
        i, f, text = job
        if time.time() > deadline:
            return i, f, {'ok': False, 'ausgabe': 'zeit'}
        tag = f"v{i:03d}_{f['hash'][:6]}"
        sc = _score_text(einheit, fkt, text, tag, orig, ordner)
        if not sc.get('ok'):
            neu, nfix = M.repariere_fehlende(text, fkt, sc.get('ausgabe', ''), [text, basis_unit])
            if nfix and neu:
                sc = _score_text(einheit, fkt, neu, tag + 'r', orig, ordner)
                if not sc.get('ok'):
                    neu2, nfix2 = M.repariere_fehlende(neu, fkt, sc.get('ausgabe', ''), [neu, basis_unit])
                    if nfix2 and neu2:
                        sc = _score_text(einheit, fkt, neu2, tag + 'r2', orig, ordner)
        return i, f, sc

    workers = max(1, min(procs, M.MAX_PROCS, len(aufgaben) or 1))
    if workers == 1:
        for job in aufgaben:
            i, f, sc = eine(job)
            erg[f['hash']] = sc
            f['score'] = sc
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(eine, job) for job in aufgaben]
            for fu in as_completed(futs):
                i, f, sc = fu.result()
                erg[f['hash']] = sc
                f['score'] = sc
    return erg


def _ganz(sc):
    if not sc or not sc.get('ok'):
        return 10 ** 9
    return sc['bew'].get('_GANZ', {}).get('dist', 10 ** 9)


_ZEICHNER_CACHE = None


def zeichner_nach_id():
    """Blind-ID -> Zeichnerfamilie aus den Nachtstart-Skripten."""
    global _ZEICHNER_CACHE
    if _ZEICHNER_CACHE is not None:
        return _ZEICHNER_CACHE
    zu = {}
    ordner = os.path.join(HERE, 'nachtstart')
    if os.path.isdir(ordner):
        for fn in os.listdir(ordner):
            m = re.fullmatch(r'blind_(\d+)\.sh', fn)
            if not m:
                continue
            try:
                t = open(os.path.join(ordner, fn), encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            for name in ('model_a', 'model_b', 'model_c', 'model_d', 'model_e', 'model_f'):
                if re.search(name, t, re.I):
                    zu[m.group(1)] = name
                    break
    _ZEICHNER_CACHE = zu
    return zu


def herkunft(pfad):
    """(familie, id). Familie ist p1/p2/p3, ein Zeichner oder die konkrete Arbeits-ID."""
    p = (pfad or '').replace('\\', '/')
    m = re.search(r'/src/(p[123])/', p)
    if m:
        return m.group(1), ''
    if '/ghidra' in p.lower():
        return 'Ghidra', ''
    for muster, art in ((r'/blind/work/(\d+)/', 'blind'), (r'/wave/(\d+)/', 'worker'),
                        (r'/worker/arbeit/', 'worker'), (r'/kandidaten/', 'kandidat')):
        m = re.search(muster, p)
        if not m:
            continue
        if art in ('worker', 'kandidat'):
            return art, ''
        id_ = m.group(1)
        fam = zeichner_nach_id().get(id_, '')
        if not fam:
            for name in ('model_a', 'model_b', 'model_c', 'model_d', 'model_e'):
                if re.search(name, p, re.I):
                    fam = name
                    break
        return (fam or f'{art}-{id_}'), id_
    for name in ('model_a', 'model_b', 'model_c', 'model_d', 'model_e'):
        if re.search(name, p, re.I):
            return name, ''
    return 'sonst', ''


def bekannte_reste(einheit, fkt):
    """id -> (rest, dateiname oder ''). Kleinste gemeldete Reste aus den Ergebnislisten."""
    by_id = {}

    def merke(id_, rest, datei):
        if not id_:
            return
        schluessel = [str(id_)]
        m = re.search(r'(\d{3,4})$', str(id_))
        if m and m.group(1) not in schluessel:
            schluessel.append(m.group(1))
        for s in schluessel:
            alt = by_id.get(s)
            if alt is None or rest < alt[0]:
                by_id[s] = (rest, datei or '')

    blind = os.path.join(M.ROOT, 'Blind', 'ERGEBNISSE.tsv')
    if os.path.isfile(blind):
        for line in open(blind, encoding='utf-8', errors='replace'):
            p = line.rstrip('\n').split('\t')
            if len(p) < 6 or p[2] != einheit or p[3] != fkt:
                continue
            try:
                rest = int(p[5])
            except ValueError:
                continue
            note = p[6] if len(p) > 6 else ''
            mf = re.search(r'([\w.-]+\.(?:CPP|cpp|c))\b', note)
            merke(p[1], rest, mf.group(1) if mf else '')
    if os.path.isfile(M.ERGEBNISSE):
        for line in open(M.ERGEBNISSE, encoding='utf-8', errors='replace'):
            p = line.rstrip('\n').split('\t')
            if len(p) < 5 or p[1] != einheit or p[2] != fkt:
                continue
            try:
                rest = int(p[4])
            except ValueError:
                continue
            note = p[7] if len(p) > 7 else ''
            mf = re.search(r'([\w.-]+\.(?:CPP|cpp|c))\b', note)
            mid = re.search(r'(?:model_a|model_b|model_c|model_d|model_e|model_f)(\d{3,4})', note)
            if not mid:
                mid = re.search(r'\b(\d{3,4})\b', note)
            merke(mid.group(1) if mid else '', rest, mf.group(1) if mf else '')
    return by_id


def _rest_aus_namen(name):
    m = re.search(r'(?:^|[_-])(?:rest|best|r)(\d{1,5})(?:\D|$)', name, re.I)
    if m:
        return int(m.group(1))
    return None


def waehle_ernte(einheit, fkt, zeilen, max_n=16):
    """Pfade nach Naehe (bekannter Rest) und Herkunft. p3 und die beste Nachtfassung sind dabei."""
    by_id = bekannte_reste(einheit, fkt)
    try:
        q = os.path.abspath(quelle_der_einheit(einheit))
    except SystemExit:
        q = ''
    eintraege = []
    gesehen = set()
    for z in zeilen:
        pf = z.get('pfad') or ''
        if not pf or not os.path.isfile(pf):
            continue
        ap = os.path.abspath(pf)
        if ap in gesehen:
            continue
        gesehen.add(ap)
        fam, id_ = herkunft(ap)
        rest = _rest_aus_namen(os.path.basename(ap))
        if rest is None and id_ and id_ in by_id:
            rest_id, datei = by_id[id_]
            bn = os.path.basename(ap).lower()
            if (datei and bn == datei.lower()) or bn == f'{einheit}_p1.cpp'.lower():
                rest = rest_id
        eintraege.append({
            'pfad': ap, 'signatur': z.get('signatur') or '', 'abschnitte': z.get('abschnitte') or 0,
            'familie': fam, 'id': id_, 'rest': rest,
        })
    if q and q not in gesehen and os.path.isfile(q):
        eintraege.append({'pfad': q, 'signatur': '', 'abschnitte': 0, 'familie': 'p3', 'id': '', 'rest': None})

    gewaehlt = []
    pfade = set()

    def nimm(e):
        if e['pfad'] in pfade or len(gewaehlt) >= max_n:
            return False
        gewaehlt.append(e)
        pfade.add(e['pfad'])
        return True

    for fam in ('p3', 'p2', 'p1'):
        for e in eintraege:
            if e['familie'] == fam:
                nimm(e)
                break
    # Beste bekannte Nachtfassung: die ID mit dem kleinsten Rest, plus Geschwister.
    mit_id = [(by_id[e['id']][0], e) for e in eintraege if e['id'] and e['id'] in by_id]
    if mit_id:
        mit_id.sort(key=lambda x: x[0])
        beste_id = mit_id[0][1]['id']
        geschwister = [e for e in eintraege if e['id'] == beste_id]
        geschwister.sort(key=lambda e: (e['rest'] is None, e['rest'] if e['rest'] is not None else 10 ** 9,
                                        e['pfad']))
        for e in geschwister[:5]:
            nimm(e)
    # Je Herkunft mindestens eine, bei bekanntem Rest die naechste, sonst eine andere Abschnittszahl.
    familien = {}
    for e in eintraege:
        familien.setdefault(e['familie'], []).append(e)
    for fam in sorted(familien, key=lambda f: min((e['rest'] if e['rest'] is not None else 10 ** 9)
                                                   for e in familien[f])):
        gruppe = sorted(familien[fam], key=lambda e: (e['rest'] is None,
                                                      e['rest'] if e['rest'] is not None else 10 ** 9))
        nimm(gruppe[0])
        if len(gewaehlt) >= max_n:
            break
        haben = {gruppe[0]['abschnitte']}
        for e in gruppe[1:]:
            if e['abschnitte'] not in haben:
                if nimm(e):
                    break
    # Auffuellen mit den naechsten bekannten Resten, hoechstens drei je Herkunft.
    restliche = sorted(eintraege, key=lambda e: (e['rest'] is None, e['rest'] if e['rest'] is not None else 10 ** 9))
    zaehl = {}
    for e in gewaehlt:
        zaehl[e['familie']] = zaehl.get(e['familie'], 0) + 1
    for e in restliche:
        if e['rest'] is None or len(gewaehlt) >= max_n:
            break
        if zaehl.get(e['familie'], 0) >= 3:
            continue
        if nimm(e):
            zaehl[e['familie']] = zaehl.get(e['familie'], 0) + 1
    haben_sig = {e['signatur'] for e in gewaehlt if e['signatur']}
    for e in eintraege:
        if len(gewaehlt) >= max_n:
            break
        if e['signatur'] and e['signatur'] not in haben_sig:
            if nimm(e):
                haben_sig.add(e['signatur'])
    return gewaehlt


def _tausch_unit(basis_f, paare, basis_unit, fkt):
    """Abschnittstexte einsetzen und die dazu noetigen Deklarationen und Defines mitnehmen."""
    ersatz = {}
    decls = []
    defines = []
    for key, sp in paare:
        fremd = next((s for s in sp['fn'].abschnitte if s.key == key), None)
        if fremd is None or fremd.verboten or not fremd.balanced:
            return None
        ersatz[key] = fremd.text
        decls.extend(M.noetige_deklarationen(
            basis_f['fn'].text, sp['fn'].text, fremd.text,
            [basis_unit, sp.get('text') or '', basis_f.get('text') or '']))
        defines.extend(M.fehlende_defines(fremd.text, basis_unit, [sp.get('text') or '']))
    text = M.baue(basis_f['fn'], ersatz)
    if not text:
        return None
    quellen = [basis_f['fn'].text] + [sp['fn'].text for _, sp in paare]
    text = M.gleiche_struct_decls(text, quellen) or text
    decls.extend(M.deklarationen_fuer_text(
        text, fkt, quellen,
        [basis_unit] + [sp.get('text') or '' for _, sp in paare] + [basis_f.get('text') or '']))
    if decls:
        gesehen = set()
        rein = []
        for d in decls:
            k = re.sub(r'\s+', '', d)
            if k in gesehen:
                continue
            gesehen.add(k)
            rein.append(d)
        text = M.mit_deklarationen(text, fkt, rein) or text
    text = M.gleiche_struct_decls(text, quellen) or text
    return _splice(basis_unit, fkt, text, defines)


def kreuze(einheit, fkt, brauchbar, scores, basis_unit, q, orig, objdir, verlauf, deadline, strahl, stats):
    """Kreuzt bis die Zeit um ist oder eine Fassung Rest 0 erreicht.

    Der Emulator sortiert vor. Nativ gemessen werden p3, die Emulator-Spitze und
    jede Runde der Lexicase-Strahl. p3 ist der Boden: schlechter wird nicht Sieger.
    """
    fk = fkt.replace('f_', '').lower()
    gruppen = []
    pool_scores = {}
    gemessen = {}
    nativ_cache = {}
    lauf_nr = [0]
    bester = None
    boden_stand = None
    boden_rest = None
    texte_reparatur = [basis_unit] + [f.get('text') or '' for f in brauchbar]
    qabs = os.path.abspath(q)

    def log_stand():
        _anhang(verlauf,
                'Kreuzungen: versucht {versucht}, uebersetzt {uebersetzt}, nativ {nativ}, besser {besser}\n'.format(**stats))

    def emu(name, unit):
        if not unit or time.time() > deadline:
            return None
        stats['versucht'] += 1
        lauf_nr[0] += 1
        sc = _score_text(einheit, fkt, unit, f'mix{lauf_nr[0]:04d}', orig, objdir)
        if not sc.get('ok'):
            neu, nfix = M.repariere_fehlende(unit, fkt, sc.get('ausgabe', ''), texte_reparatur)
            if nfix and neu:
                lauf_nr[0] += 1
                sc = _score_text(einheit, fkt, neu, f'mix{lauf_nr[0]:04d}', orig, objdir)
                if not sc.get('ok'):
                    neu2, nfix2 = M.repariere_fehlende(neu, fkt, sc.get('ausgabe', ''), texte_reparatur)
                    if nfix2 and neu2:
                        lauf_nr[0] += 1
                        sc = _score_text(einheit, fkt, neu2, f'mix{lauf_nr[0]:04d}', orig, objdir)
        if not sc.get('ok'):
            _anhang(verlauf, f'{name} nicht uebersetzt: {(sc.get("ausgabe") or "")[:160]}\n')
            return None
        stats['uebersetzt'] += 1
        pool_scores[name] = sc['bew']
        gemessen[name] = (name, sc.get('text') or unit, sc)
        return sc

    def nativ_von(name, src, sc):
        nonlocal bester
        if not src or time.time() > deadline:
            return None
        if src in nativ_cache:
            nv = nativ_cache[src]
        else:
            _anhang(verlauf, f'nativ {name}\n')
            nv = M.nativ(einheit, src, fkt)
            nativ_cache[src] = nv
            stats['nativ'] += 1
        rest = (nv.get('stand') or {}).get(fk)
        ok_n = _nachbarn(boden_stand, nv.get('stand'), fkt) if boden_stand else False
        _anhang(verlauf, f'  rest {rest} nachbarn {"ok" if ok_n else "schlechter"}\n')
        if rest is None or not ok_n:
            return rest
        if boden_rest is not None and rest > boden_rest:
            return rest
        if bester is None or rest < bester['rest']:
            if boden_rest is not None and rest < boden_rest:
                stats['besser'] += 1
                _anhang(verlauf, f'besser als p3: {name} Rest {rest} (Boden {boden_rest})\n')
            bester = {'name': name, 'rest': rest, 'src': src,
                      'text': (sc or {}).get('text'), 'nativ': nv,
                      'bew': (sc or {}).get('bew') or {}}
        return rest

    _anhang(verlauf, 'native Basis p3\n')
    boden_nv = M.nativ(einheit, q, fkt)
    stats['nativ'] += 1
    boden_stand = boden_nv.get('stand') or {}
    boden_rest = boden_stand.get(fk)
    nativ_cache[qabs] = boden_nv
    _anhang(verlauf, f'  rest {boden_rest} (Boden)\n')
    _schreib(os.path.join(os.path.dirname(verlauf), 'basis_nativ.txt'), boden_nv.get('text') or '')

    reihe = sorted(brauchbar, key=lambda f: _ganz(scores.get(f['hash'])))
    stich = []
    for f in reihe:
        if os.path.abspath(f['pfad']) == qabs:
            stich.append(f)
            break
    for f in reihe:
        if f not in stich:
            stich.append(f)
        if len(stich) >= 5:
            break
    native_rest = {}
    for f in stich:
        if time.time() > deadline:
            break
        if os.path.abspath(f['pfad']) == qabs:
            native_rest[f['hash']] = boden_rest
            scb = scores.get(f['hash']) or {}
            if boden_rest is not None and (bester is None or boden_rest < bester['rest']):
                bester = {'name': 'p3', 'rest': boden_rest, 'src': q,
                          'text': open(q, encoding='latin1', errors='replace').read(),
                          'nativ': boden_nv, 'bew': scb.get('bew') or {}}
            continue
        src = (scores.get(f['hash']) or {}).get('src')
        nativ_von(os.path.basename(f['pfad']), src, scores.get(f['hash']) or {})
        nv = nativ_cache.get(src)
        if nv:
            native_rest[f['hash']] = (nv.get('stand') or {}).get(fk)

    def prio(f):
        r = native_rest.get(f['hash'])
        return (r is None, r if r is not None else 10 ** 9, _ganz(scores.get(f['hash'])))

    skelette = sorted(brauchbar, key=prio)
    singles_offen = {}
    for basis in skelette:
        liste = []
        bew_b = (scores.get(basis['hash']) or {}).get('bew') or {}
        for sec in basis['fn'].abschnitte:
            b0 = bew_b.get(sec.key) or {}
            for f in brauchbar:
                if f['hash'] == basis['hash']:
                    continue
                fremd = next((s for s in f['fn'].abschnitte if s.key == sec.key), None)
                if fremd is None or fremd.verboten or not fremd.balanced:
                    continue
                if re.sub(r'\s+', '', fremd.text) == re.sub(r'\s+', '', sec.text):
                    continue
                bf = ((scores.get(f['hash']) or {}).get('bew') or {}).get(sec.key) or {}
                gew = b0.get('dist_struct', 0) - bf.get('dist_struct', 0)
                liste.append((gew, sec.key, f))
        liste.sort(key=lambda x: -x[0])
        singles_offen[basis['hash']] = liste

    benutzte_papier = set()
    runde = 0
    strahl_jetzt = max(1, strahl)
    while time.time() < deadline:
        basis = None
        for f in skelette:
            if singles_offen.get(f['hash']):
                basis = f
                break
        if basis is None:
            break
        runde += 1
        _anhang(verlauf, f"Runde {runde} Basis {os.path.basename(basis['pfad'])} "
                f"Ganz-Distanz {_ganz(scores.get(basis['hash']))} Strahl {strahl_jetzt}\n")
        if basis['hash'] not in benutzte_papier:
            benutzte_papier.add(basis['hash'])
            wahl = {}
            bew_b = (scores.get(basis['hash']) or {}).get('bew') or {}
            for sec in basis['fn'].abschnitte:
                best, bestv = basis, (10 ** 9, 10 ** 9)
                b0 = bew_b.get(sec.key)
                if b0:
                    bestv = (b0.get('dist_struct', 10 ** 9), b0.get('dist', 10 ** 9))
                for f in brauchbar:
                    b = ((scores.get(f['hash']) or {}).get('bew') or {}).get(sec.key)
                    if not b:
                        continue
                    v = (b.get('dist_struct', 10 ** 9), b.get('dist', 10 ** 9))
                    if v < bestv:
                        bestv, best = v, f
                wahl[sec.key] = best
            text, notizen, verworfen, extras = M.misch_quelltext(basis, brauchbar, wahl, basis_unit)
            if runde == 1:
                _anhang(verlauf, f'verworfene Abschnitte: {verworfen}\n')
                _anhang(verlauf, f'Notizen: {[(n[0], "decls" if isinstance(n[1], list) else n[1]) for n in notizen]}\n')
            if text:
                unit = _splice(basis_unit, fkt, text, extras)
                basis_text = (scores.get(basis['hash']) or {}).get('text') or ''
                if unit and re.sub(r'\s+', '', unit) != re.sub(r'\s+', '', basis_text):
                    sc = emu(f'papier_r{runde}', unit)
                    if sc and _ganz(sc) < _ganz(scores.get(basis['hash'])):
                        _anhang(verlauf, f'Papier verbessert die Ganz-Distanz auf {_ganz(sc)}\n')
                decls = []
                for n in notizen:
                    if isinstance(n[1], list):
                        decls.extend(n[1])
                if decls and time.time() < deadline:
                    fnp = M.parse_funktion(text, fkt)
                    if fnp:
                        for label, pos in (('anfang', 'anfang'), ('pos0', 0)):
                            if time.time() > deadline:
                                break
                            alt = M.prolog_mit(fnp, decls, pos)
                            if alt:
                                emu(f'decl_{label}_r{runde}', _splice(basis_unit, fkt, alt, extras))
        paket = singles_offen[basis['hash']][:12]
        singles_offen[basis['hash']] = singles_offen[basis['hash']][12:]
        verbesserte = []
        for gew, key, sp in paket:
            if time.time() > deadline:
                break
            unit = _tausch_unit(basis, [(key, sp)], basis_unit, fkt)
            name = 't_' + re.sub(r'[^0-9A-Za-z]+', '_', key)[:32]
            sc = emu(f'{name}_r{runde}', unit)
            if not sc:
                continue
            grp = M.gruppen_aus_tausch((scores.get(basis['hash']) or {}).get('bew') or {}, sc['bew'])
            if len(grp) > 1:
                gruppen.append(grp)
                _anhang(verlauf, f'Koppelgruppe {grp}\n')
            if gew > 0 or _ganz(sc) <= _ganz(scores.get(basis['hash'])):
                verbesserte.append((key, sp, sc))
            if _ganz(sc) < _ganz(scores.get(basis['hash'])):
                _anhang(verlauf, f'Tausch {key} Ganz-Distanz {_ganz(sc)}\n')
        quelle = verbesserte
        paare = []
        for i in range(len(quelle)):
            for j in range(i + 1, len(quelle)):
                paare.append((quelle[i], quelle[j]))
                if len(paare) >= 6:
                    break
            if len(paare) >= 6:
                break
        for pi, (a, b) in enumerate(paare):
            if time.time() > deadline:
                break
            unit = _tausch_unit(basis, [(a[0], a[1]), (b[0], b[1])], basis_unit, fkt)
            emu(f'paar_r{runde}_{pi}', unit)
        if len(quelle) >= 3 and time.time() < deadline:
            a, b, c = quelle[0], quelle[1], quelle[2]
            unit = _tausch_unit(basis, [(a[0], a[1]), (b[0], b[1]), (c[0], c[1])], basis_unit, fkt)
            emu(f'dreier_r{runde}', unit)
        if pool_scores:
            sieger = M.lexikase(list(pool_scores), pool_scores, strahl_jetzt)
            _anhang(verlauf, 'Lexicase-Strahl: ' + ', '.join(sieger) + '\n')
            for name in sieger:
                if name not in gemessen:
                    continue
                _n, _u, sc = gemessen[name]
                nativ_von(name, sc.get('src'), sc)
                if bester and bester['rest'] == 0:
                    break
        else:
            _anhang(verlauf, 'Lexicase-Strahl: basis\n')
        log_stand()
        if bester and bester['rest'] == 0:
            break
        strahl_jetzt = min(strahl_jetzt + 1, 8)
    if bester and bester.get('rest') and bester.get('text') and time.time() < deadline:
        _anhang(verlauf, 'Deklarationsstellung der besten Fassung\n')
        stellungen = M.prolog_stellungen(bester['text'], fkt)
        stell_scores = []
        for i, fn_text in enumerate(stellungen):
            if time.time() > deadline:
                break
            unit = M.setze_funktion(bester['text'], fkt, fn_text)
            if not unit:
                continue
            sc = emu(f'declstell_{i}', unit)
            if sc:
                stell_scores.append(sc)
        stell_scores.sort(key=_ganz)
        for sc in stell_scores[:3]:
            if time.time() > deadline or (bester and bester['rest'] == 0):
                break
            nativ_von('declstell', sc.get('src'), sc)
    for f in reihe:
        if time.time() > deadline - 15:
            break
        if bester and bester['rest'] == 0:
            break
        src = (scores.get(f['hash']) or {}).get('src')
        if not src or src in nativ_cache or os.path.abspath(f['pfad']) == qabs:
            continue
        nativ_von('rest_' + os.path.basename(f['pfad']), src, scores.get(f['hash']) or {})
    log_stand()
    return {'bester': bester, 'gruppen': gruppen, 'boden': boden_rest}


def mische(einheit, fkt, pfade, basis_pfad=None, procs=2, zeit_min=30, abgeben=False, strahl=3, notiz=''):
    t0 = time.time()
    deadline = t0 + zeit_min * 60
    ordner = lauf_ordner(einheit, fkt)
    verlauf = os.path.join(ordner, 'VERLAUF.md')
    _schreib(verlauf, f'# {einheit} {fkt}\n\nStart {time.strftime("%H:%M:%S")}\n\n')
    if M.asm_verbucht(fkt):
        _anhang(verlauf, 'ASM-verbucht, kein C++-Mischen.\n')
        M.ergebnis_anfuegen([time.strftime('%Y-%m-%dT%H:%M:%S'), einheit, fkt, 0, 0, '', '', 'asm', ordner])
        return {'status': 'asm'}
    q = quelle_der_einheit(einheit)
    basis_unit = open(q, encoding='latin1', errors='replace').read()
    orig = M.orig_asm(einheit, fkt)
    fassungen = []
    gesehen = set()
    for p in pfade:
        f = fassung_laden(p, fkt)
        if not f or f['hash'] in gesehen:
            continue
        gesehen.add(f['hash'])
        fassungen.append(f)
    if len(fassungen) < 1:
        _anhang(verlauf, 'keine lesbare Fassung\n')
        return {'status': 'leer'}
    _anhang(verlauf, f'{len(fassungen)} Fassungen, Emulator-Bewertung (procs {procs}).\n')
    _anhang(verlauf, 'Auswahl:\n')
    for f in fassungen:
        fam, _id = herkunft(f['pfad'])
        _anhang(verlauf, f"  {fam}\t{os.path.basename(f['pfad'])}\t{f['pfad']}\n")
    objdir = os.path.join(ordner, 'obj')
    scores = bewerte_fassungen(einheit, fkt, fassungen, basis_unit, orig, objdir, procs, deadline)
    brauchbar = [f for f in fassungen if scores.get(f['hash'], {}).get('ok')]
    _anhang(verlauf, f'uebersetzt {len(brauchbar)} von {len(fassungen)}, verworfen {len(fassungen) - len(brauchbar)}.\n')
    if not brauchbar:
        for f in fassungen:
            sc = scores.get(f['hash']) or {}
            _anhang(verlauf, f"- {os.path.basename(f['pfad'])}: {f.get('verworfen') or sc.get('ausgabe', '')[:180]}\n")
        M.ergebnis_anfuegen([time.strftime('%Y-%m-%dT%H:%M:%S'), einheit, fkt, len(fassungen), 0, '', '', 'nicht-uebersetzt', ordner])
        return {'status': 'nicht-uebersetzt'}
    # Matrix
    bew_liste = []
    for f in brauchbar:
        bew_liste.append((os.path.basename(f['pfad']), scores[f['hash']]['bew']))
    _schreib(os.path.join(ordner, 'MATRIX.tsv'), M.matrix_zeilen(bew_liste))
    # Vielfalt
    if len(brauchbar) >= 2:
        v = M.vielfalt_paar(brauchbar[0], brauchbar[1])
        _anhang(verlauf, f'Vielfalt der ersten beiden Fassungen (Textabweichung je Abschnitt): {v:.2f}\n')
    kons = M.konsens(brauchbar)
    _anhang(verlauf, f'Konsensabschnitte (>={max(2, (len(brauchbar)+1)//2)} gleiche Texte): {len(kons)}\n')
    if basis_pfad:
        vorgezogen = next((f for f in brauchbar if os.path.abspath(f['pfad']) == os.path.abspath(basis_pfad)
                           or f['pfad'].endswith(basis_pfad)), None)
        if vorgezogen:
            brauchbar = [vorgezogen] + [f for f in brauchbar if f is not vorgezogen]
    # Groesse der Emulator-Spitze (Fall 12). Das Skelett der Kreuzung waehlt kreuze nach nativem Boden.
    spitze = min(brauchbar, key=lambda f: _ganz(scores[f['hash']]))
    g = scores[spitze['hash']]['bew'].get('_GANZ', {})
    _anhang(verlauf, f"Emulator-Spitze {os.path.basename(spitze['pfad'])} Ganz-Distanz {_ganz(scores[spitze['hash']])}\n")
    _anhang(verlauf, f"Groesse Befehle orig/spitze {g.get('orig_befehle')}/{g.get('neu_befehle')}\n")
    stats = {'versucht': 0, 'uebersetzt': 0, 'nativ': 0, 'besser': 0}
    kreuz = kreuze(einheit, fkt, brauchbar, scores, basis_unit, q, orig, objdir, verlauf, deadline, strahl, stats)
    bester = kreuz['bester']
    gruppen = kreuz['gruppen']
    rest_basis = kreuz['boden']
    basis = spitze
    # Harte Abschnitte: niemand trifft strukturell
    keys = [s.key for s in basis['fn'].abschnitte]
    hart_bew = {}
    for k in keys:
        dists = []
        for f in brauchbar:
            b = scores[f['hash']]['bew'].get(k)
            if b:
                dists.append(b)
        if dists and all(b.get('status') == 'STRUKT' and b.get('dist_struct', 1) > 0 for b in dists):
            hart_bew[k] = min(dists, key=lambda b: b.get('dist_struct', 0))
    fn_basis = scores[basis['hash']]['fn']
    # nur die harten in die Liste geben: baue eine Scheinbewertung
    schein = {k: {'dist': 1, 'status': 'STRUKT', 'quelle': 'keine Fassung'} for k in hart_bew}
    for k in keys:
        if k not in hart_bew:
            schein[k] = {'dist': 0, 'status': 'OK', 'quelle': 'treffer'}
    md, n_hart = M.harte_markdown(fn_basis, orig, schein, einheit, fkt)
    _schreib(os.path.join(ordner, 'HARTE_ABSCHNITTE.md'), md)
    # Abdeckung
    getroffen = []
    for f in brauchbar:
        for k, b in scores[f['hash']]['bew'].items():
            if k.startswith('_'):
                continue
            if b.get('status') in ('OK', 'REG') or b.get('dist', 1) == 0:
                getroffen.append(k)
    getroffen = sorted(set(getroffen))
    ab_pfad = os.path.join(ordner, 'ABDECKUNG.tsv')
    if not os.path.isfile(ab_pfad):
        _schreib(ab_pfad, 'lauf\tneu\tgetroffen\tkonsens\n')
    bisher = set()
    for line in open(ab_pfad, encoding='utf-8'):
        if line.startswith('lauf'):
            continue
        p = line.rstrip('\n').split('\t')
        if len(p) > 2 and p[2]:
            bisher.update(p[2].split(','))
    neu_keys = [k for k in getroffen if k not in bisher]
    konsens_keys = [k for k, v in kons.items()]
    with open(ab_pfad, 'a', encoding='utf-8') as h:
        h.write(f'{time.strftime("%H:%M:%S")}\t{",".join(neu_keys)}\t{",".join(getroffen)}\t{",".join(konsens_keys)}\n')
    status = 'offen'
    rest = ''
    if bester and bester.get('text'):
        rest = bester['rest']
        _schreib(os.path.join(ordner, f'{einheit}_P1.CPP'), bester['text'])
        if rest == 0 and all(b.get('status') in ('OK', 'REG') or b.get('dist_struct', 1) == 0
                             for k, b in bester['bew'].items() if not k.startswith('_')):
            status = 'GLEICH'
        elif rest == 0:
            status = 'GLEICH'
        elif rest_basis is not None and rest < rest_basis:
            status = 'besser'
        else:
            status = 'gemessen'
        # Fall 11
        if status != 'GLEICH' and n_hart == 0 and rest and rest > 0:
            status = 'struktur-register'
            _anhang(verlauf, 'Struktur getroffen, Rest nur Register/Stapel -> Strom K\n')
        if abgeben and status in ('GLEICH', 'besser', 'struktur-register') and rest_basis is not None and rest < rest_basis:
            M.abgeben(einheit, fkt, bester['src'], rest_basis, rest, notiz or 'Mischer')
    else:
        _anhang(verlauf, 'kein nativer Sieger\n')
    sek = time.time() - t0
    _anhang(verlauf, f'Ende {time.strftime("%H:%M:%S")} Status {status} Rest {rest} Basis {rest_basis}\n')
    _anhang(verlauf, 'Gruppen: ' + repr(gruppen) + '\n')
    _anhang(verlauf, 'Kreuzungen: versucht {versucht}, uebersetzt {uebersetzt}, nativ {nativ}, besser {besser}\n'.format(**stats))
    _anhang(verlauf, f'Laufzeit {sek / 60:.1f} min von {zeit_min} min\n')
    if stats['versucht']:
        _anhang(verlauf, f'Uebersetzungsquote {stats["uebersetzt"]}/{stats["versucht"]}\n')
    M.ergebnis_anfuegen([time.strftime('%Y-%m-%dT%H:%M:%S'), einheit, fkt, len(fassungen), len(brauchbar),
                         '' if rest_basis is None else rest_basis, rest, status, ordner])
    return {'status': status, 'rest': rest, 'rest_basis': rest_basis, 'ordner': ordner, 'hart': n_hart,
            'fassungen': len(fassungen), 'mischbar': len(brauchbar), 'stats': stats, 'sekunden': sek}


def _nachbarn(basis, neu, fkt):
    if not basis or not neu:
        return False
    fk = fkt.replace('f_', '').lower()
    for k, v in basis.items():
        if k == fk:
            continue
        if neu.get(k, 10 ** 9) > v:
            return False
    return True


def cmd_sammle(einheit, fkt):
    t0 = time.time()
    funde = M.sammle(einheit, fkt)
    ordner = M.schreibe_ernte(einheit, fkt, funde)
    sigs = {}
    ghid = 0
    for f in funde:
        sigs[f['signatur']] = sigs.get(f['signatur'], 0) + 1
        if f['ghidra']:
            ghid += 1
    print(f'{len(funde)} verschiedene Fassungen in {ordner} ({time.time()-t0:.0f}s), davon Ghidra {ghid}')
    print(f'{len(sigs)} verschiedene Signaturen')
    for s, n in sorted(sigs.items(), key=lambda kv: -kv[1])[:8]:
        print(f'  {n:4d}  {s[:140]}')
    return funde


def cmd_ernte_mischen(einheit, fkt, args):
    ordner = os.path.join(HERE, 'ernte', f'{einheit}_{fkt}')
    liste = os.path.join(ordner, 'LISTE.tsv')
    if not os.path.isfile(liste):
        cmd_sammle(einheit, fkt)
    zeilen = []
    for line in open(liste, encoding='utf-8'):
        if line.startswith('hash'):
            continue
        p = line.rstrip('\n').split('\t')
        if len(p) >= 4 and os.path.isfile(p[3]):
            try:
                nabs = int(p[4]) if len(p) > 4 else 0
            except ValueError:
                nabs = 0
            zeilen.append({'pfad': p[3], 'signatur': p[1], 'abschnitte': nabs})
    max_n = 16
    gewaehlt = waehle_ernte(einheit, fkt, zeilen, max_n=max_n) if len(zeilen) > max_n else [
        {'pfad': os.path.abspath(z['pfad']), 'familie': herkunft(z['pfad'])[0], 'rest': _rest_aus_namen(os.path.basename(z['pfad']))}
        for z in zeilen
    ]
    if len(zeilen) <= max_n:
        # p3 und die beste bekannte Nachtfassung auch dann, wenn die Liste kurz ist.
        extra = waehle_ernte(einheit, fkt, zeilen, max_n=max_n)
        haben = {e['pfad'] for e in gewaehlt}
        for e in extra:
            if e['pfad'] not in haben:
                gewaehlt.append(e)
    print(f'Ernte {len(zeilen)} Fassungen, gewaehlt {len(gewaehlt)} (Naehe und Herkunft, p3 dabei)')
    for e in gewaehlt:
        print(f"  {e.get('familie', '?'):<12} rest {e.get('rest')}  {e['pfad']}")
    pfade = [e['pfad'] for e in gewaehlt]
    return mische(einheit, fkt, pfade, args.basis, min(args.procs, M.MAX_PROCS), args.zeit, args.abgeben, args.strahl, 'Ernte')


def cmd_stamm(einheit, fkt, fassung):
    f = fassung_laden(fassung, fkt)
    if not f:
        raise SystemExit('Funktion nicht in der Fassung')
    md, data = M.stamm_aus(f['fn'], einheit, fkt)
    ordner = os.path.join(HERE, 'stamm', f'{einheit}_{fkt}')
    os.makedirs(ordner, exist_ok=True)
    _schreib(os.path.join(ordner, 'STAMM.md'), md)
    with open(os.path.join(ordner, 'stamm.json'), 'w', encoding='utf-8') as h:
        json.dump(data, h, ensure_ascii=False, indent=1)
    _schreib(os.path.join(ordner, 'AUFTRAG_AST.txt'), M.auftrag_ast(data))
    for a in data['abschnitte']:
        _schreib(os.path.join(ordner, f"AUFTRAG_{a['kennung']}.txt"), M.auftrag_ast(data, a['kennung']))
    print(ordner)
    return ordner


def cmd_empfehlung(einheit, fkt):
    ordner = lauf_ordner(einheit, fkt)
    ab = os.path.join(ordner, 'ABDECKUNG.tsv')
    if not os.path.isfile(ab):
        print('keine ABDECKUNG.tsv, noch kein Lauf')
        return
    zeilen = []
    keys = []
    for line in open(ab, encoding='utf-8'):
        if line.startswith('lauf'):
            continue
        p = line.rstrip('\n').split('\t')
        getroffen = [x for x in (p[2].split(',') if len(p) > 2 else []) if x]
        zeilen.append((p[0], getroffen))
        for k in getroffen:
            if k not in keys:
                keys.append(k)
    # alle bekannten Schluessel aus der Matrix
    mx = os.path.join(ordner, 'MATRIX.tsv')
    if os.path.isfile(mx):
        for line in open(mx, encoding='utf-8'):
            if line.startswith('abschnitt'):
                continue
            k = line.split('\t', 1)[0]
            if k and k not in keys:
                keys.append(k)
    rest = None
    erg = os.path.join(HERE, 'ERGEBNIS.tsv')
    if os.path.isfile(erg):
        for line in open(erg, encoding='utf-8'):
            p = line.rstrip('\n').split('\t')
            if len(p) > 6 and p[1] == einheit and p[2] == fkt and p[6].isdigit():
                rest = int(p[6])
    text = M.empfehlung_text(zeilen, keys, rest)
    print(text)


def gleich_einheiten(limit_bytes=None):
    rows = []
    for fn in os.listdir(M.LIVE):
        if not fn.endswith('.fstand'):
            continue
        t = open(os.path.join(M.LIVE, fn), encoding='latin1', errors='replace').read().splitlines()
        if not t or 'GLEICH' not in t[-1]:
            continue
        bad = 0
        n = 0
        for l in t[:-1]:
            if not l.strip():
                continue
            n += 1
            if 'GLEICH' not in l:
                bad += 1
        if bad or n < 1:
            continue
        u = fn[:-7]
        p = os.path.join(M.P3, u + '_P1.CPP')
        if not os.path.isfile(p):
            continue
        sz = os.path.getsize(p)
        if limit_bytes and sz > limit_bytes:
            continue
        rows.append((sz, u, p))
    rows.sort()
    return rows


def e0():
    """Zehn GLEICHE Einheiten, CODE-Segment mit und ohne -d1."""
    ordner = os.path.join(HERE, 'eichung', 'e0')
    os.makedirs(ordner, exist_ok=True)
    ergebnisse = []
    for sz, u, p in gleich_einheiten():
        if len(ergebnisse) >= 10:
            break
        print(f'E0 {u} ({sz} B)', flush=True)
        d = os.path.join(ordner, u)
        os.makedirs(d, exist_ok=True)
        o1 = os.path.join(d, 'ohne.obj')
        o2 = os.path.join(d, 'mit.obj')
        ok1, a1 = M.emu_compile(p, o1)
        ok2, a2 = M.emu_compile(p, o2, ['-d1'])
        if not ok1 or not ok2:
            print('  nicht uebersetzt', flush=True)
            continue
        b1, b2 = M.code_segment(o1), M.code_segment(o2)
        gleich = b1 == b2
        ergebnisse.append({'einheit': u, 'bytes': sz, 'code_ohne': len(b1), 'code_mit': len(b2), 'gleich': gleich})
        print(f'  CODE {len(b1)} / {len(b2)} gleich={gleich}', flush=True)
    aendert = any(not r['gleich'] for r in ergebnisse)
    data = {'aendert_code': aendert, 'n': len(ergebnisse), 'einheiten': ergebnisse,
            'folge': 'Zeileninfo -d1 wird nicht zur Zuordnung benutzt' if aendert
            else 'Code unveraendert, Zeileninfo darf nur der Zuordnung dienen'}
    json.dump(data, open(os.path.join(HERE, 'eichung', 'e0.json'), 'w'), indent=1)
    print('E0 aendert_code', aendert, 'Einheiten', len(ergebnisse))
    return data


def _finde_e1():
    """Kleine GLEICHE switch-Funktion und if/else-Funktion."""
    switch = ifelse = None
    for sz, u, p in gleich_einheiten(80000):
        if switch and ifelse:
            break
        text = open(p, encoding='latin1', errors='replace').read()
        # Funktionen aus live, die GLEICH sind
        stand = open(os.path.join(M.LIVE, u + '.fstand'), encoding='latin1', errors='replace').read().splitlines()
        for line in stand:
            m = re.match(r'^([0-9A-Fa-f]{4,8})\s+\d+/\d+\s+GLEICH', line)
            if not m:
                continue
            fkt = 'f_' + m.group(1).lower()
            fn = M.parse_funktion(text, fkt, p)
            if not fn:
                continue
            cases = [s for s in fn.abschnitte if s.kind == 'case']
            if switch is None and len(cases) >= 2:
                # zwei Faelle mit je einer eigenen Konstante im Rumpf
                paare = []
                for s in cases:
                    labs = {hex(x) if isinstance(x, int) else str(x) for x in s.labels}
                    labs |= {str(x) for x in s.labels if isinstance(x, int)}
                    eigen = [c for c in s.consts if c not in labs and c not in ('0', '1', '0x0', '0x1')
                             and re.search(r'(?<![\w])' + re.escape(c) + r'(?![\w])', s.text)]
                    if eigen:
                        paare.append((s, eigen[0]))
                if len(paare) >= 2:
                    switch = (u, fkt, p, fn, paare[0], paare[1], sz)
            if ifelse is None:
                thens = [s for s in fn.abschnitte if s.kind == 'then']
                elses = [s for s in fn.abschnitte if s.kind == 'else']
                if thens and elses:
                    # gleiches Praefix IF:hash
                    for t in thens:
                        h = t.key.split(':')[1]
                        e = next((x for x in elses if f':{h}:' in x.key or x.key.startswith(f'IF:{h}:')), None)
                        if not e:
                            continue
                        ct = [c for c in t.consts if c not in ('0', '1', '0x0', '0x1')
                              and re.search(r'(?<![\w])' + re.escape(c) + r'(?![\w])', t.text)]
                        ce = [c for c in e.consts if c not in t.consts and c not in ('0', '1', '0x0', '0x1')
                              and re.search(r'(?<![\w])' + re.escape(c) + r'(?![\w])', e.text)]
                        if ct and ce:
                            ifelse = (u, fkt, p, fn, (t, ct[0]), (e, ce[0]), sz)
                            break
        if switch and sz > 20000 and ifelse:
            break
    return switch, ifelse


def _verderbe_const(text, alt):
    """Eine Konstante im Text um 1 erhoehen. Nur als ganzes Wort, Hex bleibt hex."""
    m = re.search(r'(?<![\w])' + re.escape(alt) + r'(?![\w])', text, re.I)
    if not m:
        return None, None
    alt = m.group(0)
    if alt.lower().startswith('0x'):
        neu = hex(int(alt, 16) + 1)
    else:
        neu = str(int(alt) + 1)
    return text[:m.start()] + neu + text[m.end():], neu


def e1():
    """Kuenstlich verdorbene Faelle / Zweige wieder zu GLEICH mischen."""
    print('E1 suche Kandidaten', flush=True)
    switch, ifelse = _finde_e1()
    ordner = os.path.join(HERE, 'eichung', 'e1')
    os.makedirs(ordner, exist_ok=True)
    bericht = []
    for art, fund in (('switch', switch), ('ifelse', ifelse)):
        if not fund:
            bericht.append({'art': art, 'status': 'kein Kandidat'})
            print('kein Kandidat', art, flush=True)
            continue
        u, fkt, p, fn, a, b, sz = fund
        print(f'E1 {art} {u} {fkt} ({sz} B) {a[0].key} / {b[0].key}', flush=True)
        ta, _ = _verderbe_const(a[0].text, a[1])
        tb, _ = _verderbe_const(b[0].text, b[1])
        if not ta or not tb:
            bericht.append({'art': art, 'einheit': u, 'fkt': fkt, 'status': 'konstante nicht ersetzbar'})
            continue
        text_a = M.baue(fn, {a[0].key: ta})
        text_b = M.baue(fn, {b[0].key: tb})
        unit = open(p, encoding='latin1', errors='replace').read()
        unit_a = M.setze_funktion(unit, fkt, text_a)
        unit_b = M.setze_funktion(unit, fkt, text_b)
        da = os.path.join(ordner, f'{art}_A.CPP')
        db = os.path.join(ordner, f'{art}_B.CPP')
        _schreib(da, unit_a)
        _schreib(db, unit_b)
        r = mische(u, fkt, [da, db], None, 2, 25, False, 3, 'E1 ' + art)
        bericht.append({'art': art, 'einheit': u, 'fkt': fkt, 'abschnitte': [a[0].key, b[0].key],
                        'konstanten': [a[1], b[1]], 'status': r.get('status'), 'rest': r.get('rest'),
                        'rest_basis': r.get('rest_basis')})
        print('E1', art, r.get('status'), r.get('rest'), flush=True)
    json.dump(bericht, open(os.path.join(ordner, 'e1.json'), 'w'), indent=1)
    return bericht


def e2():
    """Fuenf castle-Fassungen gegen fallvgl.py."""
    B = os.path.join(M.ROOT, 'Blind', 'arbeit', 'worker')
    orig = M.load_asm(os.path.join(B, 'orig.asm'))
    vals = [int(l.split()[0]) for l in open(os.path.join(B, 'casevals.txt'))]
    namen = [('t1.asm', 'fn_t1.cpp'), ('t12.asm', 'fn_t12.cpp'), ('t20.asm', 'fn_t20.cpp'),
             ('t29.asm', 'fn_t29.cpp'), ('v2.asm', 'v2.CPP')]
    zeilen = []
    fehler = 0
    for asm, cpp in namen:
        neu = M.load_asm(os.path.join(B, asm), 'f_400010') or M.load_asm(os.path.join(B, asm))
        rows = M.zaehl_faelle(orig, neu, vals, 'dx')
        haben = {v: d for v, st, d, ds in rows}
        import subprocess
        r = subprocess.run(['python3', 'fallvgl.py', asm, '--zaehl'], cwd=B, capture_output=True, text=True)
        last = [ln for ln in r.stdout.splitlines() if ':' in ln and not ln.startswith('abweichend')][-1]
        ref = {}
        for part in last.split():
            v, d = part.split(':')
            ref[int(v)] = int(d)
        diff = sum(1 for v, d in ref.items() if haben.get(v) != d)
        fehler += diff
        zeilen.append({'asm': asm, 'quelle': cpp, 'faelle': len(vals), 'abweichung_gegen_fallvgl': diff,
                       'faelle_mit_rest': sum(1 for v, st, d, ds in rows if d)})
        print(f'E2 {asm} Abweichung {diff}', flush=True)
    data = {'fehler': fehler, 'fassungen': zeilen}
    os.makedirs(os.path.join(HERE, 'eichung'), exist_ok=True)
    json.dump(data, open(os.path.join(HERE, 'eichung', 'e2.json'), 'w'), indent=1)
    return data


def e3():
    """demo_unit mischen, ohne Abgabe. ASM-Fallvergleich plus eine echte Mischung."""
    B = os.path.join(M.ROOT, 'Blind', 'arbeit', 'worker')
    orig = M.load_asm(os.path.join(B, 'orig.asm'))
    vals = [int(l.split()[0]) for l in open(os.path.join(B, 'casevals.txt'))]
    asms = [fn for fn in os.listdir(B) if fn.endswith('.asm') and fn != 'orig.asm']
    # nur die, die die Funktion enthalten und nicht riesige Duplikate: t*.asm v*.asm e*.asm
    asms = [a for a in asms if re.match(r'^[a-z]+\d*\.asm$', a)]
    print(f'E3 ASM-Fassungen {len(asms)}', flush=True)
    # je Fall die beste Distanz
    beste = {v: 10 ** 9 for v in vals}
    n_ok = 0
    for asm in asms:
        neu = M.load_asm(os.path.join(B, asm), 'f_400010') or M.load_asm(os.path.join(B, asm))
        if len(neu) < 50:
            continue
        try:
            rows = M.zaehl_faelle(orig, neu, vals, 'dx')
        except (ValueError, KeyError, IndexError):
            continue
        n_ok += 1
        for v, st, d, ds in rows:
            if d < beste[v]:
                beste[v] = d
    getroffen = sum(1 for v, d in beste.items() if d == 0)
    print(f'E3 Fallvergleich auf {n_ok} ASM, Faelle mit Distanz 0: {getroffen} von {len(vals)}', flush=True)
    # Quellmischung der ABGABE-Dateien und t*.CPP, die sich parsen lassen. Zeitlich eng: 6 Dateien.
    kandidaten = []
    for fn in ('ABGABE_rest486.CPP', 'ABGABE_rest450.CPP', 'ABGABE_rest466.CPP', 't1.CPP', 't12.CPP', 't29.CPP', 'v2.CPP'):
        p = os.path.join(B, fn)
        if os.path.isfile(p):
            kandidaten.append(p)
    r = mische('demo_unit', 'f_400010', kandidaten, os.path.join(B, 'ABGABE_rest486.CPP'), 2, 20, False, 3, 'E3')
    data = {'asm': n_ok, 'faelle': len(vals), 'faelle_distanz_0': getroffen, 'mischung': r}
    json.dump(data, open(os.path.join(HERE, 'eichung', 'e3.json'), 'w'), indent=1, default=str)
    return data


def e4():
    ziele = [('demo_unit', 'f_400010'), ('unit_example', 'f_400010'), ('unit_example', 'f_400010'),
             ('unit_example', 'f_400010'), ('demo_unit', 'f_400010')]
    bericht = []
    for u, f in ziele:
        if M.asm_verbucht(f):
            bericht.append({'einheit': u, 'fkt': f, 'status': 'asm'})
            print('E4 ASM', u, f, flush=True)
            continue
        print('E4 sammle', u, f, flush=True)
        funde = cmd_sammle(u, f)
        sig = {}
        for x in funde:
            sig[x['signatur']] = sig.get(x['signatur'], 0) + 1
        print('E4 mische', u, f, flush=True)
        r = cmd_ernte_mischen(u, f, argparse.Namespace(basis=None, procs=2, zeit=12, abgeben=False, strahl=2))
        bericht.append({'einheit': u, 'fkt': f, 'fassungen': len(funde), 'signaturen': len(sig),
                        'ghidra': sum(1 for x in funde if x['ghidra']),
                        'status': r.get('status'), 'rest': r.get('rest'), 'rest_basis': r.get('rest_basis'),
                        'mischbar': r.get('mischbar')})
        print('E4', u, f, r.get('status'), r.get('rest'), flush=True)
    json.dump(bericht, open(os.path.join(HERE, 'eichung', 'e4.json'), 'w'), indent=1, default=str)
    return bericht


def cmd_mini(einheit, fkt, datei):
    """Delta-Debugging: ueberfluessige Anweisungen entfernen, solange der Emulator-Abstand nicht steigt.
    Abschluss nativ."""
    ordner = lauf_ordner(einheit, fkt)
    orig = M.orig_asm(einheit, fkt)
    text = open(datei, encoding='latin1', errors='replace').read()
    fn = M.parse_funktion(text, fkt)
    if not fn:
        raise SystemExit('Funktion fehlt')
    # kuenstliche Kruecke, die der Minimierer wieder entfernen soll, wenn die Datei schon die Funktion enthaelt
    basis_sc = _score_text(einheit, fkt, text, 'mini_basis', orig, os.path.join(ordner, 'mini'))
    if not basis_sc.get('ok'):
        print('Basis nicht uebersetzt')
        return
    basis_dist = _ganz(basis_sc)
    aufrufe = set(M._calls_of(fn.text))
    inj = M.prolog_mit(fn, ['int mischer_tot = 0;'], 'ende')
    if not inj:
        print('Kruecke nicht eingesetzt')
        return
    unit = M.setze_funktion(text, fkt, inj)
    def testen(indizes):
        fn2 = M.parse_funktion(unit, fkt)
        if not fn2:
            return False
        neu = M.entferne(fn2.text, fkt, indizes)
        if neu is None or set(M._calls_of(neu)) < aufrufe:
            return False
        ganz = M.setze_funktion(text, fkt, neu)
        if not ganz:
            return False
        sc = _score_text(einheit, fkt, ganz, 'mini_' + str(abs(hash(tuple(indizes))) % 10**8), orig,
                         os.path.join(ordner, 'mini'))
        return bool(sc.get('ok') and _ganz(sc) <= basis_dist)
    # Die Kruecke ist eine Deklaration. indizes beziehen sich auf die injizierte Funktion.
    fn_inj = M.parse_funktion(unit, fkt)
    spans = M.anweisungs_spannen(fn_inj)
    # finde den Index der Kruecke
    ziel = None
    for i, (a, b, k) in enumerate(spans):
        if 'mischer_tot' in fn_inj.text[a:b]:
            ziel = i
            break
    if ziel is None:
        print('Kruecke nicht in den Anweisungen')
        return
    weg = M.ddmin(len(spans), testen)
    print('entfernt', weg, 'kruecke-index', ziel, 'kruecke-weg' , ziel in weg)
    if ziel in weg:
        neu = M.entferne(fn_inj.text, fkt, weg)
        ganz = M.setze_funktion(text, fkt, neu)
        pfad = os.path.join(ordner, 'mini_ergebnis.CPP')
        _schreib(pfad, ganz)
        nv = M.nativ(einheit, pfad, fkt)
        rest = (nv['stand'] or {}).get(fkt.replace('f_', '').lower())
        print('nativ nach Minimieren', rest, 'Kruecke noch drin', 'mischer_tot' in neu)
        json.dump({'weg': list(weg), 'kruecke_index': ziel, 'entfernt': ziel in weg, 'rest': rest,
                   'kruecke_weg': 'mischer_tot' not in neu},
                  open(os.path.join(ordner, 'mini.json'), 'w'), indent=1)
    else:
        print('Minimierer hat die Kruecke nicht entfernt')
        json.dump({'weg': list(weg), 'kruecke_index': ziel, 'entfernt': False},
                  open(os.path.join(ordner, 'mini.json'), 'w'), indent=1)


def cmd_nacht(args):
    import csv
    ziele = []
    for r in csv.DictReader(open(M.BYTEWERT, encoding='utf-8', errors='replace'), delimiter='\t'):
        try:
            rest = int(r['rest'])
        except ValueError:
            continue
        if rest <= 0:
            continue
        ziele.append((rest, int(r['bytes'] or 0), r['einheit'], r['fkt']))
    ziele.sort()
    logp = os.path.join(HERE, 'nacht', 'nacht.log')
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    n = 0
    for rest, byt, u, f in ziele:
        if args.limit and n >= args.limit:
            break
        if M.asm_verbucht(f) or M.gesperrt(u):
            _anhang(logp, f'{time.strftime("%H:%M:%S")} skip {u} {f} asm-oder-sperre\n')
            continue
        # Fall 13
        if byt < 500 and rest <= 25:
            _anhang(logp, f'{time.strftime("%H:%M:%S")} skip {u} {f} klein ({byt} B, Rest {rest}) -> Strom K\n')
            continue
        n += 1
        print(f'Nacht {n} {u} {f} Rest {rest} {byt} B', flush=True)
        _anhang(logp, f'{time.strftime("%H:%M:%S")} start {u} {f}\n')
        try:
            funde = M.sammle(u, f)
            M.schreibe_ernte(u, f, funde)
            if len(funde) < 2:
                _anhang(logp, f'  nur {len(funde)} Fassung(en)\n')
                continue
            r = cmd_ernte_mischen(u, f, argparse.Namespace(basis=None, procs=args.procs, zeit=args.zeit,
                                                           abgeben=args.abgeben, strahl=args.strahl))
            _anhang(logp, f'  {r.get("status")} rest {r.get("rest")} basis {r.get("rest_basis")}\n')
        except Exception as ex:
            _anhang(logp, f'  fehler {ex}\n')
    print(f'Nacht fertig, {n} Funktionen', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rest', nargs='*')
    ap.add_argument('--sammle', action='store_true')
    ap.add_argument('--ernte', action='store_true')
    ap.add_argument('--stamm', action='store_true')
    ap.add_argument('--empfehlung', action='store_true')
    ap.add_argument('--eichung', choices=['e0', 'e1', 'e2', 'e3', 'e4'])
    ap.add_argument('--mini', action='store_true')
    ap.add_argument('--nacht', action='store_true')
    ap.add_argument('--basis')
    ap.add_argument('--procs', type=int, default=2)
    ap.add_argument('--zeit', type=int, default=30)
    ap.add_argument('--abgeben', action='store_true')
    ap.add_argument('--strahl', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    a.procs = max(1, min(a.procs, M.MAX_PROCS))
    if a.eichung:
        {'e0': e0, 'e1': e1, 'e2': e2, 'e3': e3, 'e4': e4}[a.eichung]()
        return
    if a.nacht:
        cmd_nacht(a)
        return
    if a.mini:
        cmd_mini(a.rest[0], a.rest[1], a.rest[2])
        return
    if a.empfehlung:
        cmd_empfehlung(a.rest[0], a.rest[1])
        return
    if a.stamm:
        cmd_stamm(a.rest[0], a.rest[1], a.rest[2])
        return
    if a.sammle and len(a.rest) == 2 and not a.ernte:
        cmd_sammle(a.rest[0], a.rest[1])
        return
    if len(a.rest) >= 2 and (a.ernte or a.sammle):
        cmd_ernte_mischen(a.rest[0], a.rest[1], a)
        return
    if len(a.rest) >= 4:
        mische(a.rest[0], a.rest[1], a.rest[2:], a.basis, a.procs, a.zeit, a.abgeben, a.strahl, 'Aufruf')
        return
    ap.print_help()
    sys.exit(2)


if __name__ == '__main__':
    main()
