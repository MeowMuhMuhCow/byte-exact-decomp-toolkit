#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mischer worker (worker, 07.11.2026). Siehe mischer_lib_o14.py fuer das Verfahren.

  mischer_o14.py EINHEIT FKT [--zeit MIN] [--procs N<=3] [--abgeben] [--basen K] [--ab N]

Ablauf: Ernte (worker/ernte/<E>_<F>/LISTE.tsv, sonst frisch) -> ALLE Fassungen im Emulator messen (Cache) ->
Basen nach gemessenem Abstand (p3 + beste andere Familien) -> Tauschbloecke in Original-Koordinaten nach
erwartetem Gewinn (Haltemodell x Gewinn x Konsens) kreuzen, Ratsche -> gekoppelte Bloecke nachschieben ->
beste Ergebnisse nativ (Richter) -> Abgabe nur wenn nativ besser als p3 und kein Nachbar schlechter.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.environ.get('O14_LIB1358') or os.path.dirname(os.path.abspath(__file__)))   # D9: Kopie nutzt mischer_lib/mischer aus worker
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mischer_lib as M          # noqa: E402
import mischer as X              # noqa: E402
import mischer_lib_o14 as O      # noqa: E402

FEHLERKLASSEN = (
    ('doppelt', r"E042|E126|already been defined|already defined|redefinition"),
    ('nicht deklariert', r"E029|has not been declared"),
    ('Sprungmarke', r"E033|is not defined in function"),
    ('return fehlt', r"E003|missing return"),
    ('Typ/Signatur', r"E473|E341|E329|E191|E050|E1113|E1033|E040|do not match|incomplete type|conver"),
    ('Syntax', r"E006|E121|syntax error|E336|E241|E498"),
    ('timeout', r"timeout"),
)


def fehlerklasse(txt):
    for k, rx in FEHLERKLASSEN:
        if re.search(rx, txt or ''):
            return k
    return 'sonst'


def h12(text):
    return hashlib.sha1(re.sub(r'\s+', '', text).encode('latin1', 'replace')).hexdigest()[:12]


class Lauf:
    def __init__(self, einheit, fkt, args):
        self.e, self.f, self.a = einheit, fkt, args
        self.ordner = os.path.join(O.worker, 'lauf', f'{einheit}_{fkt}')
        os.makedirs(self.ordner, exist_ok=True)
        self.q = os.path.abspath(args.p3) if args.p3 else X.quelle_der_einheit(einheit)
        self.p3_unit = open(self.q, encoding='latin1', errors='replace').read()
        self.p3h = hashlib.sha1(self.p3_unit.encode('latin1', 'replace')).hexdigest()[:10]
        if args.p3:   # Runde 2: Messcache des echten p3 weiter nutzen (Einheit ausserhalb der Funktion gleich)
            echt = open(X.quelle_der_einheit(einheit), encoding='latin1', errors='replace').read()
            self.p3h = hashlib.sha1(echt.encode('latin1', 'replace')).hexdigest()[:10]
        # D8 12.11.: geeichte Abstaende (Richter auf Emu-OBJ) in eigenem Cache, nie mit alten mess3-Werten mischen
        self.mess_dir = os.path.join(self.ordner, ('mess4_' if O.EICHUNG else 'mess3_') + self.p3h)
        self.obj_dir = os.path.join(self.ordner, 'obj')
        _EIGEN_OBJ[0] = self.obj_dir
        os.makedirs(self.mess_dir, exist_ok=True)
        self.orig = M.orig_asm(einheit, fkt)
        self.verlauf = os.path.join(self.ordner, 'VERLAUF_O14.md')
        self.t0 = time.time()
        self.deadline = self.t0 + args.zeit * 60
        self.nr = 0
        import threading
        self._nr_lock = threading.Lock()
        self.stats = {'kreuz_versucht': 0, 'kreuz_uebersetzt': 0, 'kreuz_besser_emu': 0,
                      'ab_mit': [0, 0], 'ab_ohne': [0, 0], 'fehler': {}, 'folgen': {}, 'bloecke_gekoppelt': 0,
                      'bloecke_gekoppelt_besser': 0}
        self.modell = O.Haltemodell()

    def neue_nr(self):
        with self._nr_lock:
            self.nr += 1
            return self.nr

    def log(self, s):
        line = f'{time.strftime("%H:%M:%S")} {s}'
        print(line, flush=True)
        with open(self.verlauf, 'a', encoding='utf-8') as h:
            h.write(line + '\n')

    # ---------- Ernte ----------
    def ernte(self):
        liste = os.path.join(HERE, 'ernte', f'{self.e}_{self.f}', 'LISTE.tsv')
        pfade = []
        if os.path.isfile(liste):
            for l in open(liste, encoding='utf-8', errors='replace'):
                p = l.rstrip('\n').split('\t')
                if len(p) >= 4 and p[0] != 'hash':
                    pfade.append(p[3])
        if os.environ.get('O14_PFADLISTE'):   # D9: feste Pfadliste (A/B-Tests, gleicher Pool, ohne rg-Ernte)
            pfade = [l.strip() for l in open(os.environ['O14_PFADLISTE'], encoding='utf-8') if l.strip()]
        elif self.a.frisch or not pfade:
            funde = M.sammle(self.e, self.f)
            pfade = [x['pfad'] for x in funde]
        fass = []
        gesehen = set()
        for p in [self.q] + pfade:
            if not os.path.isfile(p):
                continue
            try:
                fa = X.fassung_laden(p, self.f)
            except Exception:
                fa = None
            if not fa or fa['hash'] in gesehen:
                continue
            gesehen.add(fa['hash'])
            fa['familie'], fa['quelle'] = O.herkunft(p)
            fass.append(fa)
        self.log(f'Ernte: {len(fass)} verschiedene Fassungen aus {len(pfade)} Pfaden')
        return fass

    # ---------- Messen ----------
    def messe_unit(self, unit, tag):
        return O.messe(self.e, self.f, unit, tag, self.orig, self.obj_dir)

    def _quelle_passt(self, fa, ra):
        """D8: Ist die gespeicherte Messquelle (ra['src']) genau die Einheit, die jetzt fuer fa gebaut wuerde?
        (obj-Ordner ist ueber p3-Staende hinweg geteilt; nur dann darf das alte OBJ nachgerichtet werden.)"""
        try:
            s = open(ra['src'], encoding='latin1', errors='replace').read()
            if ra.get('eigen'):
                return s == fa['text']
            if os.path.abspath(fa['pfad']) == os.path.abspath(self.q):
                return s == self.p3_unit
            calls = []
            for sec in fa['fn'].abschnitte:
                calls.extend(sec.calls)
            helfer = M.helfer_zeilen(fa['text'], calls, self.p3_unit)
            return s == X._splice(self.p3_unit, self.f, fa['fn'].text, helfer)
        except Exception:
            return False

    def messe_fassung(self, fa):
        cp = os.path.join(self.mess_dir, fa['hash'][:16] + '.json')
        if os.path.isfile(cp):
            try:
                return json.load(open(cp))
            except Exception:
                pass
        alt = os.path.join(self.ordner, 'mess_' + self.p3h, fa['hash'][:16] + '.json')
        if O.EICHUNG:   # D8: altes mess3 mit vorhandenem OBJ nur nachrichten (kein Neuuebersetzen), wenn das OBJ zur Quelle passt
            alt3 = os.path.join(self.ordner, 'mess3_' + self.p3h, fa['hash'][:16] + '.json')
            if os.path.isfile(alt3):
                alt = alt3
        if os.path.isfile(alt):
            try:
                ra = json.load(open(alt))
                obj = (ra.get('src') or '')[:-4] + '.obj'
                if (ra.get('ok') and os.path.isfile(obj) and os.path.isfile(ra['src'])
                        and os.path.getmtime(obj) >= os.path.getmtime(ra['src']) - 1
                        and self._quelle_passt(fa, ra)):
                    r = O.analysiere(open(ra['src'], encoding='latin1', errors='replace').read(), obj, ra['src'], self.f, self.orig,
                                     einheit=self.e)
                    if r.get('ok'):
                        for k in ('eigen', 'fehler_p3'):
                            if k in ra:
                                r[k] = ra[k]
                        r['unit_pfad'] = r['src']
                        json.dump(r, open(cp, 'w'))
                        return r
                elif not ra.get('ok'):
                    json.dump(ra, open(cp, 'w'))
                    return ra
            except Exception:
                pass
        if os.path.abspath(fa['pfad']) == os.path.abspath(self.q):
            unit = self.p3_unit
        else:
            calls = []
            for sec in fa['fn'].abschnitte:
                calls.extend(sec.calls)
            helfer = M.helfer_zeilen(fa['text'], calls, self.p3_unit)
            if any(M.verbotener_code(h) for h in helfer) or M.verbotener_code(fa['fn'].text):
                r = {'ok': False, 'fehler': 'verboten'}
                json.dump(r, open(cp, 'w'))
                return r
            unit = X._splice(self.p3_unit, self.f, fa['fn'].text, helfer)
            if unit is None:
                r = {'ok': False, 'fehler': 'nicht einsetzbar'}
                json.dump(r, open(cp, 'w'))
                return r
        tag = 'f_' + fa['hash'][:10]
        r = self.messe_unit(unit, tag)
        if not r['ok']:
            for k in range(2):
                neu, nfix = M.repariere_fehlende(unit, self.f, r.get('fehler', ''), [unit, fa['text'], self.p3_unit])
                if not (nfix and neu):
                    break
                unit = neu
                r = self.messe_unit(unit, tag + f'r{k}')
                if r['ok']:
                    break
        if not r['ok'] and os.path.abspath(fa['pfad']) != os.path.abspath(self.q):
            # Rueckfall: Fassung in ihrer EIGENEN Datei messen (Beobachtung + Spender, nicht Basis)
            fehler_p3 = r.get('fehler', '')
            r2 = self.messe_unit(fa['text'], tag + 'e')
            if r2['ok']:
                r2['eigen'] = True
                r2['fehler_p3'] = fehler_p3
                r = r2
            else:
                r['fehler_eigen'] = r2.get('fehler', '')[-200:]
        if r['ok']:
            r['unit_pfad'] = r['src']
        json.dump(r, open(cp, 'w'))
        return r

    def messe_alle(self, fass):
        offen = [fa for fa in fass]
        t = time.time()
        with ThreadPoolExecutor(max_workers=self.a.procs) as ex:
            for fa, r in zip(offen, ex.map(self.messe_fassung, offen)):
                fa['m'] = r
        ok = [fa for fa in fass if fa['m'].get('ok')]
        kl = {}
        for fa in fass:
            k = None
            if not fa['m'].get('ok'):
                k = fehlerklasse(fa['m'].get('fehler', ''))
            elif fa['m'].get('eigen'):
                k = 'in p3: ' + fehlerklasse(fa['m'].get('fehler_p3', ''))
            if k:
                kl[k] = kl.get(k, 0) + 1
        self.stats['fassung_fehler'] = kl
        self.log(f'gemessen {len(fass)} in {time.time() - t:.0f} s: uebersetzt {len(ok)}, nicht {len(fass) - len(ok)} {kl}')
        with open(os.path.join(self.ordner, 'FASSUNGEN.tsv'), 'w', encoding='utf-8') as h:
            h.write('hash\tfamilie\tquelle\tok\tdist\tdist_struct\ttreffer\tpfad\n')
            for fa in sorted(fass, key=lambda x: x['m'].get('dist', 10 ** 9)):
                m = fa['m']
                h.write(f"{fa['hash'][:12]}\t{fa['familie']}\t{fa['quelle']}\t{int(bool(m.get('ok')))}\t{m.get('dist', '')}\t"
                        f"{m.get('dist_struct', '')}\t{sum(m.get('cov') or [])}\t{fa['pfad']}\n")
        return ok

    # ---------- Kreuzen ----------
    def kandidaten(self, mb, spender, base_unit):
        """Heap-Eintraege fuer Basis mb aus allen Spendern."""
        kand = []
        konsens = {}
        roh = []
        for fa in spender:
            md = fa['m']
            if md is mb or not md.get('ok') or not md.get('fn_text'):
                continue
            if len(md['cov']) != len(mb['cov']):
                continue
            if sum(1 for i in range(len(mb['cov'])) if md['cov'][i] and not mb['cov'][i]) == 0:
                continue
            abb = O.namensabbildung(mb['fn_text'], md['fn_text'], self.f)
            for lv in range(O.MAXT + 1):
                for B, D, span in O.tauschbloecke(mb, md, lv):
                    g = O.block_gewinn(mb, md, span)
                    if g <= 0:
                        continue
                    (ab, eb), dtxt = O.block_texte(mb, md, B, D)
                    if M._brace_delta(dtxt) != 0:
                        continue
                    dtxt_r = O.umbenennen(dtxt, abb)
                    if re.sub(r'\s+', '', dtxt_r) == re.sub(r'\s+', '', mb['fn_text'][ab:eb]):
                        continue
                    key = re.sub(r'\s+', '', dtxt_r)
                    konsens.setdefault(key, set()).add(fa['familie'])
                    sim = O.aehnlichkeit(mb, md, span)
                    roh.append((g, sim, key, fa, abb, lv, B, D, span, ab, eb, dtxt, dtxt_r))
        gesehen = set()
        for g, sim, key, fa, abb, lv, B, D, span, ab, eb, dtxt, dtxt_r in roh:
            if (key, ab, eb) in gesehen:
                continue
            gesehen.add((key, ab, eb))
            bonus = 1 + 0.25 * (len(konsens[key]) - 1)
            prio = self.modell.ucb(sim) * g * bonus
            kand.append({'prio': prio, 'g': g, 'sim': sim, 'fa': fa, 'abb': abb, 'lv': lv, 'B': B, 'D': D,
                         'span': span, 'ab': ab, 'eb': eb, 'dtxt': dtxt, 'dtxt_r': dtxt_r,
                         'nfam': len(konsens[key]), 'art': 'einzel'})
        # Token-Hunks aus den naechsten Fassungen (Kontextnaehe ueber die ganze Funktion)
        if not self.a.ohne_hunks:
            nah = []
            for fa in spender:
                md = fa['m']
                if md is mb or not md.get('ok') or md.get('eigen') or not md.get('zeile') or len(md['cov']) != len(mb['cov']):
                    continue
                nah.append((O.aehnlichkeit(mb, md, []), fa))
            nah.sort(key=lambda x: -x[0])
            hk = {}
            hroh = []
            for sim, fa in nah[:self.a.hunk_spender]:
                md = fa['m']
                abb = O.namensabbildung(mb['fn_text'], md['fn_text'], self.f)
                dfn = O.umbenennen(md['fn_text'], abb)
                for a, b, text, da, db in O.hunks(mb['fn_text'], dfn):
                    la, lb = dfn[:da].count('\n'), dfn[:db].count('\n')
                    P = [i for i, z in enumerate(md['zeile']) if la <= z <= lb]
                    g = sum(md['cov'][i] - mb['cov'][i] for i in P)
                    if g < 0:
                        continue
                    if not P:
                        # Deklaration/Prolog ohne eigenen Code: globaler Hebel (Register/Stapel), schwacher Vorwert
                        g = 0.5 if md['dist'] <= mb['dist'] + 10 else 0.2
                    elif g == 0:
                        continue
                    key = (a, b, re.sub(r'\s+', '', text))
                    hk.setdefault(key, set()).add(fa['familie'])
                    hroh.append((key, g, sim, fa, abb, P, a, b, text))
            gesehen_h = set()
            for key, g, sim, fa, abb, P, a, b, text in hroh:
                if key in gesehen_h:
                    continue
                gesehen_h.add(key)
                bonus = 1 + 0.25 * (len(hk[key]) - 1)
                neu_fn = mb['fn_text'][:a] + text + mb['fn_text'][b:]
                kand.append({'prio': self.modell.ucb(sim) * g * bonus, 'g': g, 'sim': sim, 'fa': fa, 'abb': abb,
                             'lv': -1, 'B': [], 'D': [], 'span': P, 'ab': a, 'eb': b, 'dtxt': text, 'dtxt_r': text,
                             'nfam': len(hk[key]), 'art': 'hunk', 'neu_fn': neu_fn})
        kand.sort(key=lambda c: -c['prio'])
        return kand

    def baue(self, mb, base_unit, c, umbenannt=True):
        fa = c['fa']
        if c['art'] == 'hunk':
            if M.verbotener_code(c['dtxt']):
                return None
            helfer = M.helfer_zeilen(fa['text'], M._calls_of(c['dtxt']), base_unit)
            helfer += M.fehlende_defines(c['dtxt'], base_unit, [fa['text']])
            fn = c['neu_fn']
            if RUECKFALL:   # D9: auch Hunks bekommen fehlende Lokale des Spenders (wie Einzelbloecke)
                try:
                    sp_fn = O.umbenennen(fa['m']['fn_text'], c['abb']) if c['abb'] else fa['m']['fn_text']
                    decls = M.noetige_deklarationen(mb['fn_text'], sp_fn, c['dtxt'], [base_unit, fa['text']])
                    if decls:
                        fn = M.mit_deklarationen(fn, self.f, decls) or fn
                except Exception:
                    pass
            return X._splice(base_unit, self.f, fn, helfer)
        dtxt = c['dtxt_r'] if umbenannt else c['dtxt']
        sp_fn = O.umbenennen(fa['m']['fn_text'], c['abb']) if umbenannt else fa['m']['fn_text']
        fn = mb['fn_text'][:c['ab']] + dtxt + mb['fn_text'][c['eb']:]
        decls = M.noetige_deklarationen(mb['fn_text'], sp_fn, dtxt, [base_unit, fa['text']])
        if decls:
            fn = M.mit_deklarationen(fn, self.f, decls) or fn
        helfer = M.helfer_zeilen(fa['text'], M._calls_of(dtxt), base_unit)
        helfer += M.fehlende_defines(dtxt, base_unit, [fa['text']])
        if any(M.verbotener_code(h) for h in helfer) or M.verbotener_code(dtxt):
            return None
        return X._splice(base_unit, self.f, fn, helfer)

    def baue_mehrere(self, mb, base_unit, cs):
        """D9: mehrere Kreuzungen (c, umb) zugleich auf die Basis anwenden (Textbereiche muessen disjunkt sein)."""
        cs = sorted(cs, key=lambda x: -x[0]['ab'])
        for (c1, _), (c2, _) in zip(cs, cs[1:]):
            if c2['eb'] > c1['ab']:
                return None
        fn = mb['fn_text']
        decls, helfer = [], []
        for c, umb in cs:
            fa = c['fa']
            if c['art'] == 'hunk':
                t = c['dtxt']
            else:
                t = c['dtxt_r'] if (umb and c['abb']) else c['dtxt']
                sp_fn = O.umbenennen(fa['m']['fn_text'], c['abb']) if (umb and c['abb']) else fa['m']['fn_text']
                decls += M.noetige_deklarationen(mb['fn_text'], sp_fn, t, [base_unit, fa['text']]) or []
            if M.verbotener_code(t):
                return None
            fn = fn[:c['ab']] + t + fn[c['eb']:]
            helfer += M.helfer_zeilen(fa['text'], M._calls_of(t), base_unit)
            helfer += M.fehlende_defines(t, base_unit, [fa['text']])
        if decls:
            fn = M.mit_deklarationen(fn, self.f, decls) or fn
        hz, gs = [], set()
        for h in helfer:
            if h not in gs:
                gs.add(h)
                hz.append(h)
        if any(M.verbotener_code(h) for h in hz):
            return None
        return X._splice(base_unit, self.f, fn, hz)

    def paare(self, mb, base_unit, nah):
        """D9: Paare aus Beinahe-Kreuzungen (je fuer sich <= T schlechter) gemeinsam messen. Rueckgabe beste bessere Messung oder None."""
        nah = sorted(nah, key=lambda x: (x[0], -x[1]))[:60]
        paare = []
        for i in range(len(nah)):
            for j in range(i + 1, len(nah)):
                ci, cj = nah[i][2], nah[j][2]
                if ci['eb'] <= cj['ab'] or cj['eb'] <= ci['ab']:
                    paare.append((nah[i][0] + nah[j][0], i, j))
        paare.sort()
        paare = paare[:PAARE]
        units = []
        for _, i, j in paare:
            u = self.baue_mehrere(mb, base_unit, [(nah[i][2], nah[i][3]), (nah[j][2], nah[j][3])])
            if u:
                units.append((i, j, u))

        def eins(x):
            i, j, u = x
            nr = self.neue_nr()
            r = self.messe_unit(u, f'q{nr:05d}')
            return i, j, r
        with ThreadPoolExecutor(max_workers=self.a.procs) as ex:
            res = list(ex.map(eins, units))
        st = self.stats.setdefault('paare', {'versucht': 0, 'uebersetzt': 0, 'besser': 0, 'gleich': 0})
        bester = None
        for i, j, r in res:
            st['versucht'] += 1
            if not r['ok']:
                continue
            st['uebersetzt'] += 1
            if r['dist'] < mb['dist']:
                st['besser'] += 1
                if bester is None or r['dist'] < bester[2]['dist']:
                    bester = (i, j, r)
            elif r['dist'] == mb['dist']:
                st['gleich'] += 1
        self.log(f'  Paare: {len(nah)} Beinahe-Kreuzungen, {len(units)} Paare gemessen, besser {sum(1 for i, j, r in res if r["ok"] and r["dist"] < mb["dist"])}'
                 + (f' (bestes {bester[2]["dist"]} aus {nah[bester[0]][0]:+d}/{nah[bester[1]][0]:+d})' if bester else ''))
        return bester[2] if bester else None

    def pruefe(self, mb, base_unit, c, ab_test):
        """Baut und misst eine Kreuzung. ab_test: beide Varianten (mit/ohne Angleichung) messen."""
        ergebnisse = []
        varianten = [True, False] if (ab_test or (RUECKFALL and c['art'] != 'hunk')) else [True]
        if not c['abb']:
            varianten = [False] if not ab_test else [False]
        for umb in varianten:
            unit = self.baue(mb, base_unit, c, umb)
            if not unit:
                continue
            tag = f'x{self.neue_nr():05d}'
            r = self.messe_unit(unit, tag)
            if not r['ok']:
                neu, nfix = M.repariere_fehlende(unit, self.f, r.get('fehler', ''), [unit, c['fa']['text'], base_unit])
                if nfix and neu:
                    r = self.messe_unit(neu, tag + 'r')
            ergebnisse.append((umb, r))
            if not r['ok'] and os.environ.get('O14_FEHLERLOG'):   # D9: Fehlertexte zur Auswertung
                with open(os.environ['O14_FEHLERLOG'], 'a', encoding='utf-8') as h:
                    h.write(f"=== {tag} g={c['g']} art={c['art']} umb={umb} klasse={fehlerklasse(r.get('fehler', ''))}\n{(r.get('fehler') or '')[-400:]}\n")
            if r['ok'] and not ab_test:
                break
            if not ab_test and not r['ok'] and c['abb'] and umb:
                # Rueckfall: ohne Angleichung
                continue
        return ergebnisse

    def klettern(self, mb, base_unit, spender, name):
        """Ratsche ueber modellgeleitete Kreuzungen fuer eine Basis. Rueckgabe Liste verbesserter Messungen."""
        self.log(f'Basis {name}: Emulator-Abstand {mb["dist"]}, Treffer {sum(mb["cov"])}/{len(mb["cov"])}')
        kand = self.kandidaten(mb, spender, base_unit)
        self.log(f'  {len(kand)} Tauschbloecke mit vorhergesagtem Gewinn > 0 (Haltemodell {self.modell.tabelle()})')
        verbessert = []
        versucht = set()
        ab_rest = self.a.ab
        deadline = min(self.deadline, time.time() + self.a.basis_zeit * 60)
        nah = []                       # D9: Beinahe-Kreuzungen (delta, innen, c, umb)
        tabu = {h12(mb['fn_text'])}    # D9: besuchte Basen (Plateau)
        n_plateau = 0
        while time.time() < deadline:
            if not kand:
                if PAARE and len(nah) >= 2:
                    r = self.paare(mb, base_unit, nah)
                    nah = []
                    if r is not None:
                        self.log(f'  besser (Paar): Abstand {mb["dist"]} -> {r["dist"]}')
                        mb = r
                        mb['unit_pfad'] = r['src']
                        base_unit = open(r['src'], encoding='latin1', errors='replace').read()
                        verbessert.append(r)
                        tabu.add(h12(mb['fn_text']))
                        kand = self.kandidaten(mb, spender, base_unit)
                        versucht = set()
                        self.log(f'  neue Basis, {len(kand)} Tauschbloecke')
                        continue
                break
            charge = []
            while kand and len(charge) < self.a.procs:
                c = kand.pop(0)
                k = (h12(c['dtxt_r']), c['ab'], c['eb'])
                if k in versucht:
                    continue
                versucht.add(k)
                charge.append(c)
            if not charge:
                continue   # D9: kand ist leer -> oben Paarphase oder Ende
            ab_flags = []
            for c in charge:
                ab_flags.append(ab_rest > 0 and bool(c['abb']) and c['art'] != 'hunk')
                if ab_rest > 0 and c['abb'] and c['art'] != 'hunk':
                    ab_rest -= 1
            with ThreadPoolExecutor(max_workers=self.a.procs) as ex:
                res = list(ex.map(lambda x: self.pruefe(mb, base_unit, x[0], x[1]), zip(charge, ab_flags)))
            bester = None
            plateau = None
            for c, erg, abf in zip(charge, res, ab_flags):
                self.stats['kreuz_versucht'] += 1
                self.stats.setdefault('art', {}).setdefault(c['art'], [0, 0, 0])
                self.stats['art'][c['art']][0] += 1
                r_gut = None
                umb_gut = True
                for umb, r in erg:
                    if abf:
                        z = self.stats['ab_mit' if umb else 'ab_ohne']
                        z[0] += 1
                        z[1] += int(bool(r['ok']))
                    if r['ok'] and (r_gut is None or r['dist'] < r_gut['dist']):
                        r_gut = r
                        umb_gut = umb
                    if not r['ok']:
                        k = fehlerklasse(r.get('fehler', ''))
                        self.stats['fehler'][k] = self.stats['fehler'].get(k, 0) + 1
                if r_gut is None:
                    self.modell.lerne(c['sim'], False)
                    self.protokoll(name, mb, c, None, erg)
                    continue
                self.stats['kreuz_uebersetzt'] += 1
                if RUECKFALL and not abf and not umb_gut and c['abb']:   # D9: nur dank Rueckfall uebersetzt
                    self.stats['rueckfall_ok'] = self.stats.get('rueckfall_ok', 0) + 1
                    self.stats['rueckfall_besser'] = self.stats.get('rueckfall_besser', 0) + int(r_gut['dist'] < mb['dist'])
                span = set(c['span'])
                innen = sum(r_gut['cov'][i] - mb['cov'][i] for i in span)
                schaden = [i for i in range(len(mb['cov'])) if i not in span and mb['cov'][i] and not r_gut['cov'][i]]
                hielt = r_gut['dist'] < mb['dist']
                self.modell.lerne(c['sim'], hielt)
                folge = ('besser' if hielt else
                         ('Teil haelt nicht + Schaden aussen' if innen < c['g'] and schaden else
                          'Schaden aussen (Kopplung)' if schaden else
                          'Teil haelt nicht im neuen Kontext' if innen < c['g'] else 'gleich/anders'))
                self.stats['folgen'][folge] = self.stats['folgen'].get(folge, 0) + 1
                self.protokoll(name, mb, c, r_gut, erg, innen, len(schaden), folge)
                fa_key = c['art']
                self.stats.setdefault('art', {}).setdefault(fa_key, [0, 0, 0])
                self.stats['art'][fa_key][1] += 1
                self.stats['art'][fa_key][2] += int(hielt)
                if c['art'] == 'block':
                    self.stats['bloecke_gekoppelt'] += 1
                    self.stats['bloecke_gekoppelt_besser'] += int(hielt)
                if PAARE and not hielt and r_gut['dist'] - mb['dist'] <= PAARE_T and (innen > 0 or r_gut['cov'] != mb['cov']):
                    nah.append((r_gut['dist'] - mb['dist'], innen, c, umb_gut))
                if (PLATEAU and not hielt and n_plateau < PLATEAU and r_gut['dist'] == mb['dist'] and r_gut['cov'] != mb['cov']
                        and h12(r_gut.get('fn_text') or '') not in tabu and (plateau is None or innen > plateau[2])):
                    plateau = (c, r_gut, innen)
                if hielt:
                    self.stats['kreuz_besser_emu'] += 1
                    if bester is None or r_gut['dist'] < bester[1]['dist']:
                        bester = (c, r_gut)
                elif schaden and innen > 0 and c['art'] == 'einzel':
                    # gekoppelter Block: Bloecke desselben Spenders, die den Schaden enthalten, mitnehmen
                    md = c['fa']['m']
                    sch = set(schaden)
                    for B2, D2, span2 in O.tauschbloecke(mb, md, c['lv']):
                        if not (set(span2) & sch) or B2 == c['B']:
                            continue
                        B = list(range(min(c['B'] + B2), max(c['B'] + B2) + 1))
                        D = list(range(min(c['D'] + D2), max(c['D'] + D2) + 1))
                        sb = mb['segl'][c['lv']]
                        sd = md['segl'][c['lv']]
                        spanu = [i for i in range(len(sb)) if sb[i] in B or sd[i] in D]
                        g = O.block_gewinn(mb, md, spanu)
                        if g <= 0:
                            continue
                        (ab, eb), dtxt = O.block_texte(mb, md, B, D)
                        if M._brace_delta(dtxt) != 0:
                            continue
                        nc = dict(c, B=B, D=D, span=spanu, g=g, ab=ab, eb=eb, dtxt=dtxt,
                                  dtxt_r=O.umbenennen(dtxt, c['abb']), art='block',
                                  prio=self.modell.ucb(c['sim']) * g * 1.5)
                        kand.insert(0, nc)
                        break
            if not bester and plateau is not None:
                c, r, _ = plateau
                n_plateau += 1
                self.stats['plateau'] = self.stats.get('plateau', 0) + 1
                self.log(f'  Plateau {n_plateau}: {c["fa"]["familie"]}/{c["fa"]["quelle"]} {c["art"]} gleich {r["dist"]}, andere Treffer -> neue Basis')
                mb = r
                mb['unit_pfad'] = r['src']
                base_unit = open(r['src'], encoding='latin1', errors='replace').read()
                tabu.add(h12(mb['fn_text']))
                kand = self.kandidaten(mb, spender, base_unit)
                nah = []
                continue
            if bester:
                c, r = bester
                self.log(f'  besser: {c["fa"]["familie"]}/{c["fa"]["quelle"]} lv{c["lv"]} Bloecke B{c["B"]} D{c["D"]} '
                         f'g={c["g"]} sim={c["sim"]:.2f} nfam={c["nfam"]} {c["art"]}: Abstand {mb["dist"]} -> {r["dist"]}')
                mb = r
                mb['unit_pfad'] = r['src']
                base_unit = open(r['src'], encoding='latin1', errors='replace').read()
                verbessert.append(r)
                tabu.add(h12(mb['fn_text']))
                nah = []
                kand = self.kandidaten(mb, spender, base_unit)
                self.log(f'  neue Basis, {len(kand)} Tauschbloecke')
        return verbessert

    def protokoll(self, name, mb, c, r, erg, innen='', schaden='', folge='nicht uebersetzt'):
        pf = os.path.join(self.ordner, 'KREUZUNGEN.tsv')
        neu = not os.path.isfile(pf)
        with open(pf, 'a', encoding='utf-8') as h:
            if neu:
                h.write('zeit\tbasis\tart\tspender_fam\tspender_quelle\tlv\tg\tsim\tnfam\tdist_basis\tdist_neu\tinnen\tschaden\tfolge\tfehler\n')
            fehl = '' if r else '|'.join(fehlerklasse(x[1].get('fehler', '')) for x in erg)
            h.write(f"{time.strftime('%H:%M:%S')}\t{name}\t{c['art']}\t{c['fa']['familie']}\t{c['fa']['quelle']}\t{c['lv']}\t{c['g']}\t"
                    f"{c['sim']:.3f}\t{c['nfam']}\t{mb['dist']}\t{r['dist'] if r else ''}\t{innen}\t{schaden}\t{folge}\t{fehl}\n")

    # ---------- Merkmalsregression (ganze Population) ----------
    def regression(self, p3, ok):
        """Phase R: Hunks relativ zu p3 aus allen nahen Fassungen, gebuendelt, Ridge-Effekt je Merkmal geschaetzt;
        die besten Merkmale einzeln messen, gemessen gute exakt per Intervall-DP kombinieren und messen."""
        mb = p3['m']
        p3_fn = mb['fn_text']
        pool = [fa for fa in ok if fa is not p3 and not fa['m'].get('eigen') and fa['m'].get('fn_text')]
        zeilen, info = O.merkmale(p3_fn, pool, self.f, max_n=self.a.reg_max_hunks)
        zeilen, ginfo = O.buendeln(zeilen, info)
        beta = O.ridge(zeilen, mb['dist'], ginfo, lam=self.a.reg_lambda, min_n=1)
        self.log(f'Phase R: {len(zeilen)} nahe Fassungen (<= {self.a.reg_max_hunks} Hunks), {len(info)} Hunks, {len(ginfo)} Merkmale')
        top = sorted(beta.items(), key=lambda kv: (kv[1], -ginfo[kv[0]][3]))[:self.a.reg_top]
        # stellenweise Assoziation: je p3-Fehlstelle die bei treffenden Fassungen angereicherten Merkmale
        ass = O.assoziation(zeilen, ginfo, mb['cov'])
        schon = {gk for gk, _ in top}
        n_ass = 0
        for s, gk, i in ass:
            if gk in schon or s <= 0:
                continue
            schon.add(gk)
            top.append((gk, beta.get(gk, 0.0)))
            n_ass += 1
            if n_ass >= self.a.reg_top:
                break
        # Treffer-Konsensbuendel: je Fehlstelle alle bei den Treffern angereicherten Hunks gemeinsam
        n_kb = 0
        try:
            for s, bu, stellen in O.konsens_buendel(zeilen, ginfo, info, mb['cov']):
                if bu in schon:
                    continue
                schon.add(bu)
                top.append((bu, -s))
                n_kb += 1
                if n_kb >= self.a.reg_top:
                    break
        except Exception as ex:
            self.log(f'  Konsensbuendel Fehler {ex!r}')
        self.log(f'  Merkmale zum Einzeltest: {len(top) - n_ass - n_kb} nach Ridge-Effekt + {n_ass} nach Stellen-Assoziation + {n_kb} Treffer-Konsensbuendel')
        einzel = []
        units = []
        for gk, b in top:
            fn = O.wende_an(p3_fn, [(info[k][0], info[k][1], info[k][2]) for k in gk])
            u = X._splice(self.p3_unit, self.f, fn, [])
            if u:
                units.append((gk, b, u))

        def eins(x):
            gk, b, u = x
            nr = self.neue_nr()
            r = self.messe_unit(u, f'r{nr:05d}')
            if not r['ok']:
                neu, nfix = M.repariere_fehlende(u, self.f, r.get('fehler', ''), [u, self.p3_unit] + [fa['text'] for fa in pool[:30]])
                if nfix and neu:
                    r = self.messe_unit(neu, f'r{nr:05d}r')
            return gk, b, r
        with ThreadPoolExecutor(max_workers=self.a.procs) as ex:
            res = list(ex.map(eins, units))
        verb = []
        for gk, b, r in res:
            d = r['dist'] if r['ok'] else None
            self.stats.setdefault('reg', {'einzel': 0, 'uebersetzt': 0, 'besser': 0, 'neutral': 0, 'kombi': []})
            self.stats['reg']['einzel'] += 1
            if r['ok']:
                self.stats['reg']['uebersetzt'] += 1
                if d < mb['dist']:
                    self.stats['reg']['besser'] += 1
                    verb.append(r)
                elif d == mb['dist']:
                    self.stats['reg']['neutral'] += 1
                einzel.append((gk, b, d, r))
            gi = ginfo.get(gk)
            self.log(f'  R einzel beta {b:6.2f} n={gi[3] if gi else "KB"} fam={len(gi[4]) if gi else "-"} Hunks {len(gk)}: Abstand {d}')
        # Kombination: gemessene Einzelgewinne (neutral = 0.1) exakt per Intervall-DP, dann messen
        kandid = []
        for gk, b, d, r in einzel:
            w = (mb['dist'] - d) if d < mb['dist'] else (0.1 if d == mb['dist'] else 0)
            if w > 0:
                for k in gk:
                    kandid.append((info[k][0], info[k][1], w / len(gk), k))
        if kandid:
            wahl = O.beste_intervalle(kandid)
            # ganze Buendel nur vollstaendig
            gew = set(wahl)
            ganze = [gk for gk, b, d, r in einzel if all(k in gew for k in gk) and ((mb['dist'] - d) if d < mb['dist'] else 0.1) > 0]
            hs = [(info[k][0], info[k][1], info[k][2]) for gk in ganze for k in gk]
            if len(ganze) >= 2:
                fn = O.wende_an(p3_fn, hs)
                u = X._splice(self.p3_unit, self.f, fn, [])
                if u:
                    r = self.messe_unit(u, f'r{self.neue_nr():05d}k')
                    d = r['dist'] if r['ok'] else None
                    self.stats['reg']['kombi'].append([len(ganze), d])
                    self.log(f'  R Kombination aus {len(ganze)} Merkmalen (DP): Abstand {d} (p3 {mb["dist"]})')
                    if r['ok'] and d < mb['dist']:
                        verb.append(r)
        return verb

    # ---------- Pfad-Verknuepfung (Path Relinking) ----------
    def pfad(self, mb, base_unit, ziel, name):
        """Von Basis mb schrittweise zur Zielfassung: je Schritt den besten von hoechstens k Hunks anwenden,
        auch wenn der Zwischenstand schlechter ist; bester Zwischenstand wird gemerkt."""
        md = ziel['m']
        abb = O.namensabbildung(mb['fn_text'], md['fn_text'], self.f)
        zfn = O.umbenennen(md['fn_text'], abb)
        akt_fn, akt = mb['fn_text'], mb
        bester = []
        schritte = 0
        start_dist = mb['dist']
        helfer = None
        deadline = min(self.deadline, time.time() + self.a.pfad_zeit * 60)
        while time.time() < deadline:
            H = O.hunks(akt_fn, zfn, max_n=60)
            if not H:
                break
            # Reihenfolge: kleine Hunks zuerst (Satz: kleinste Aenderung, groesste Wahrscheinlichkeit zu halten)
            H.sort(key=lambda h: len(h[2]) + (h[1] - h[0]))
            H = H[:self.a.pfad_k]
            units = []
            for a, b, text, da, db in H:
                fn = akt_fn[:a] + text + akt_fn[b:]
                hz = M.helfer_zeilen(ziel['text'], M._calls_of(text), base_unit) if text else []
                u = X._splice(base_unit, self.f, fn, hz)
                if u:
                    units.append((fn, u))
            if not units:
                break

            def eins(x):
                fn, u = x
                nr = self.neue_nr()
                r = self.messe_unit(u, f'p{nr:05d}')
                if not r['ok']:
                    neu, nfix = M.repariere_fehlende(u, self.f, r.get('fehler', ''), [u, ziel['text'], base_unit])
                    if nfix and neu:
                        r = self.messe_unit(neu, f'p{nr:05d}r')
                return fn, r
            with ThreadPoolExecutor(max_workers=self.a.procs) as ex:
                res = list(ex.map(eins, units))
            ok = [(r['dist'], fn, r) for fn, r in res if r['ok']]
            self.stats['pfad_versucht'] = self.stats.get('pfad_versucht', 0) + len(res)
            self.stats['pfad_uebersetzt'] = self.stats.get('pfad_uebersetzt', 0) + len(ok)
            if not ok:
                break
            ok.sort(key=lambda x: x[0])
            d, fn, r = ok[0]
            schritte += 1
            akt_fn, akt = r['fn_text'] or fn, r
            if d < start_dist:
                bester.append(r)
                self.log(f'  Pfad {name} Schritt {schritte}: Abstand {d} (< Start {start_dist}) {os.path.basename(r["src"])}')
            if akt_fn and re.sub(r'\s+', '', akt_fn) == re.sub(r'\s+', '', zfn):
                break
        self.log(f'  Pfad {name}: {schritte} Schritte, bester Zwischenstand {min([x["dist"] for x in bester], default=None)} (Start {start_dist}, Ziel {md["dist"]})')
        return bester

    # ---------- nativ ----------
    def nativ(self, src):
        nv = M.nativ(self.e, src, self.f)
        return nv

    def run(self):
        self.log(f'# Mischer worker {self.e} {self.f} ({self.a.zeit} min, procs {self.a.procs}, Mess-ID {O.MESS_ID})')
        fass = self.ernte()
        # 08.11. spaet (target: "warum bei identischem Stand nochmal?"): p3 und alle Fassungen aelter als das letzte Ergebnis -> nichts Neues zu mischen
        _erg = os.path.join(self.ordner, 'ERGEBNIS_O14.json')
        if os.path.isfile(_erg) and not os.environ.get('MISCH_IMMER'):
            _t = os.path.getmtime(_erg)
            _neu = [fa['pfad'] for fa in fass if os.path.isfile(fa['pfad']) and os.path.getmtime(fa['pfad']) > _t]
            if os.path.isfile(self.q) and os.path.getmtime(self.q) > _t: _neu.append(self.q)
            if not _neu:
                self.log('UNVERAENDERT: p3 und alle %d Fassungen aelter als das letzte Ergebnis - uebersprungen (MISCH_IMMER=1 erzwingt)' % len(fass))
                return None
            self.log('neu seit letztem Lauf: %d Dateien' % len(_neu))
        if self.a.max_fassungen:
            fass = fass[:self.a.max_fassungen]
        ok = self.messe_alle(fass)
        if self.a.nur_messen:
            return None
        if not ok:
            self.log('keine Fassung uebersetzt')
            return None
        p3 = next((fa for fa in ok if os.path.abspath(fa['pfad']) == os.path.abspath(self.q)), None)
        fam = {}
        for fa in ok:
            fam.setdefault(fa['familie'], []).append(fa)
        self.log('Familien (uebersetzt): ' + ', '.join(f'{k} {len(v)} (bester Abstand {min(x["m"]["dist"] for x in v)})'
                                                     for k, v in sorted(fam.items(), key=lambda kv: -len(kv[1]))))
        # Spender: nach Komplementaritaet zur jeweiligen Basis; hier alle uebersetzten
        spender = ok
        basen = []
        if p3:
            basen.append(('p3', p3))
        n_eigen = sum(1 for fa in ok if fa['m'].get('eigen'))
        self.log(f'davon nur in eigener Datei uebersetzbar (Spender, keine Basis): {n_eigen}')
        if p3:   # D8: Lupe gegen den Richterstand von p3 abgleichen (logs/live_fstand/<unit>.fstand)
            try:
                _fs = M.parse_stand(open(self.q[:-4] + '.fstand', encoding='latin1', errors='replace').read())
                _rn = _fs.get(self.f.replace('f_', '').lower())
            except OSError:
                _rn = None
            self.log(f"Lupe {'GEEICHT (Richter auf Emu-OBJ)' if O.EICHUNG else 'ALT (align_dist)'}: p3 Emu {p3['m']['dist']} / p3.fstand {_rn}"
                     + (f" / alt {p3['m'].get('dist_alt')}" if p3['m'].get('dist_alt') is not None else ''))
        self.stats['eigen'] = n_eigen
        andere = sorted([fa for fa in ok if fa is not p3 and not fa['m'].get('eigen')], key=lambda x: x['m']['dist'])
        gfam = set()
        for fa in andere:
            if len(basen) >= self.a.basen:
                break
            if fa['familie'] in gfam:
                continue
            gfam.add(fa['familie'])
            basen.append((f"{fa['familie']}/{fa['quelle']}/{os.path.basename(fa['pfad'])}", fa))
        alle_verb = []
        if p3 and not self.a.ohne_reg:
            try:
                alle_verb.extend(self.regression(p3, ok))
            except Exception as ex:
                self.log(f'Phase R Fehler: {ex!r}')
        for name, fa in basen:
            if time.time() > self.deadline or self.a.nur_pfad or self.a.nur_reg:
                break
            mb = fa['m']
            base_unit = open(mb['unit_pfad'], encoding='latin1', errors='replace').read() if mb.get('unit_pfad') else self.p3_unit
            if name == 'p3':
                base_unit = self.p3_unit
                if R_BASIS and alle_verb:   # D9: auf dem Gewinn aus Phase R weiterklettern
                    rb = min(alle_verb, key=lambda r: r['dist'])
                    if rb['dist'] < mb['dist']:
                        self.log(f'  R-Basis: klettern ab Phase-R-Ergebnis {rb["dist"]} statt p3 {mb["dist"]}')
                        mb = rb
                        base_unit = open(rb['src'], encoding='latin1', errors='replace').read()
                        name = 'p3+R'
            v = self.klettern(mb, base_unit, spender, name)
            alle_verb.extend(v)
        # Phase 2: Pfad-Verknuepfung p3 -> beste Fremdfassungen (je Quelle eine), solange Zeit bleibt
        if p3 and not self.a.ohne_pfad and not self.a.nur_reg:
            ziele = []
            gq = set()
            for fa in andere:
                if fa['quelle'] in gq:
                    continue
                gq.add(fa['quelle'])
                ziele.append(fa)
                if len(ziele) >= self.a.pfad_ziele:
                    break
            mb0 = p3['m']
            if alle_verb:
                mb0 = min(alle_verb + [mb0], key=lambda r: r['dist'])
            bu0 = open(mb0['src'], encoding='latin1', errors='replace').read()
            for fa in ziele:
                if time.time() > self.deadline:
                    break
                alle_verb.extend(self.pfad(mb0, bu0, fa, f"{fa['familie']}/{fa['quelle']}/{os.path.basename(fa['pfad'])}"))
        # nativ: p3 als Boden, dann die besten Emulator-Ergebnisse
        self.log('nativ p3 (Boden)')
        boden = self.nativ(self.q)
        fk = self.f.replace('f_', '').lower()
        rest_p3 = (boden.get('stand') or {}).get(fk)
        self.log(f'  Rest p3 {rest_p3}')
        p3_dist = p3['m']['dist'] if p3 else 10 ** 9
        kandid = sorted(alle_verb, key=lambda r: r['dist'])
        # auch die besten Basen selbst
        for name, fa in basen[1:]:
            kandid.append(fa['m'])
        # D8: dieselbe Groessenregel wie M.nativ (p3 hat Originalgroesse -> Kandidat darf sie nicht verlieren) schon bei der
        # Auswahl beachten, sonst gehen die nativen Plaetze an Fassungen, die nativ ohnehin 'Rest None' bekommen
        _p3g = p3['m'].get('groesse') if (p3 and O.EICHUNG) else None

        def _gv(r):
            g = r.get('groesse')
            return bool(_p3g and g and ((_p3g[0] == _p3g[1] and g[0] != g[1]) or g[0] != _p3g[0]))
        kandid = sorted({r['src']: r for r in kandid}.values(), key=lambda r: (_gv(r), r['dist']))[:self.a.nativ_n]
        if _p3g:
            self.log(f'  Groessenregel: {sum(1 for r in kandid if _gv(r))} von {len(kandid)} nativen Kandidaten verlieren die Originalgroesse')
        bester = None
        for r in kandid:
            if time.time() > self.deadline + 600:
                break
            nv = self.nativ(r['src'])
            rest = nv.get('rest')
            nb = X._nachbarn(boden.get('stand') or {}, nv.get('stand') or {}, self.f)
            self.log(f'  nativ {os.path.basename(r["src"])} Emu {r["dist"]}: Rest {rest} Nachbarn {"ok" if nb else "schlechter"}')
            if rest is not None and nb and (bester is None or rest < bester[0]):
                bester = (rest, r)
        erg = {'einheit': self.e, 'fkt': self.f, 'fassungen': len(fass), 'uebersetzt': len(ok),
               'familien': {k: len(v) for k, v in fam.items()}, 'rest_p3': rest_p3, 'p3_emu': p3_dist,
               'rest_o14': bester[0] if bester else rest_p3, 'src': bester[1]['src'] if bester else '',
               'stats': self.stats, 'modell': self.modell.tabelle(), 'minuten': round((time.time() - self.t0) / 60, 1)}
        self.log('ERGEBNIS ' + json.dumps({k: v for k, v in erg.items() if k != 'stats'}, ensure_ascii=False))
        self.log('STATS ' + json.dumps(self.stats, ensure_ascii=False))
        json.dump(erg, open(os.path.join(self.ordner, 'ERGEBNIS_O14.json'), 'w'), ensure_ascii=False, indent=1)
        if bester and rest_p3 is not None and bester[0] < rest_p3:
            ziel = os.path.join(self.ordner, f'{self.e}_P1.CPP')
            open(ziel, 'w', encoding='latin1', errors='replace').write(open(bester[1]['src'], encoding='latin1').read())
            self.log(f'BESSER nativ {rest_p3} -> {bester[0]}: {ziel}')
            if self.a.abgeben:
                O.abgeben(self.e, self.f, ziel, rest_p3, bester[0], f'worker Mosaik {rest_p3}->{bester[0]}')
        return erg


HERE = M.HERE

# D9 12.11.2026: Eigenprodukte nicht ernten. Die Ernte (rg over harvest pool) fand bisher die eigenen Mess-/Kreuzungsdateien
# (worker/lauf/*/obj/*.CPP, worker/lauf, Testlaeufe D*/lauf*) als 'Fassungen' wieder: unit_example 371 von 434, fz158128 391 von 880.
# Die kosten Ernte- und Messzeit bei jedem p3-Wechsel, bringen als Spender aber nichts Neues (ihre Bloecke stammen von anderen Spendern).
# Das abgegebene Ergebnis (lauf/<E>_<F>/<E>_P1.CPP) liegt nicht in obj/ und bleibt erntbar.
OHNE_EIGEN_MODUS = os.environ.get('O14_OHNE_EIGEN', 'fremd')   # '1' = alle Eigenprodukte weg, 'fremd' = nur obj-Ordner ANDERER Funktionen weg
OHNE_EIGEN = OHNE_EIGEN_MODUS in ('1', 'fremd')
_EIGEN_OBJ = ['']   # wird in Lauf.__init__ gesetzt (worker/lauf/<E>_<F>/obj)
if OHNE_EIGEN:
    _rg_alt = M._rg_dateien

    def _rg_ohne_eigen(muster, wurzeln):
        rg = M._rg_bin()
        if not rg:
            d = _rg_alt(muster, wurzeln)
        else:
            cmd = [rg, '-l', '-g', '*.CPP', '-g', '*.cpp', '-g', '*.c', '-g', '*.cc', '--glob', '!**/sicherung/**',
                   '--glob', '!**/__pycache__/**', '--glob', '!**/harvest/**',
                   '--glob', '!**/runs/*/obj/**', '--glob', '!**/runs/**',
                   '--glob', '!**/D[0-9]*/runs*/**', '-F', muster]
            d = []
            for w in wurzeln:
                if os.path.isdir(w):
                    r = subprocess.run(cmd + [w], capture_output=True, text=True)
                    d.extend(x for x in (r.stdout or '').splitlines() if x)
        d = [x for x in d if not re.search(r'/worker/runs/[^/]+/obj/|/worker/runs/|/wave/D\d+/runs', x.replace('\\', '/'))]
        if OHNE_EIGEN_MODUS == 'fremd' and _EIGEN_OBJ[0] and os.path.isdir(_EIGEN_OBJ[0]):
            # nur fremde obj-Ordner weglassen: die eigenen Kreuzungen DIESER Funktion bleiben Spender (Familie Mischer, 1/3 der Gewinne)
            r = subprocess.run([M._rg_bin() or 'rg', '-l', '-g', '*.CPP', '-F', muster, _EIGEN_OBJ[0]], capture_output=True, text=True)
            d.extend(x for x in (r.stdout or '').splitlines() if x)
        return d
    M._rg_dateien = _rg_ohne_eigen

# D9 12.11.2026: Such-Schalter (Standard AUS = altes Verhalten)
PAARE = int(os.environ.get('O14_PAARE', '0'))        # >0: Paare aus Beinahe-Kreuzungen (je Runde hoechstens so viele)
PAARE_T = int(os.environ.get('O14_PAARE_T', '3'))    # Beinahe = hoechstens T Befehle schlechter als die Basis
RUECKFALL = os.environ.get('O14_RUECKFALL', '0') == '1'   # 1: misslingt die Kreuzung mit Namensangleichung, ohne Angleichung nochmal (war als Kommentar gemeint, griff nie)
PLATEAU = int(os.environ.get('O14_PLATEAU', '0'))
R_BASIS = os.environ.get('O14_R_BASIS', '0') == '1'   # 1: klettern auf p3 startet beim besten Ergebnis aus Phase R statt bei p3    # >0: gleich gute, aber andere Fassung als neue Basis (hoechstens so oft je Basis)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('einheit')
    ap.add_argument('fkt')
    ap.add_argument('--zeit', type=float, default=30)
    ap.add_argument('--basis-zeit', type=float, default=12, dest='basis_zeit')
    ap.add_argument('--procs', type=int, default=3)
    ap.add_argument('--basen', type=int, default=3)
    ap.add_argument('--ab', type=int, default=30, help='A/B-Test Namensangleichung fuer die ersten N Kreuzungen')
    ap.add_argument('--nativ-n', type=int, default=int(os.environ.get('O14_NATIV_N', '4')), dest='nativ_n')   # 12.11.: Lupe nicht geeicht -> mehr Kandidaten nativ nachmessen
    ap.add_argument('--max-fassungen', type=int, default=0, dest='max_fassungen')
    ap.add_argument('--frisch', action='store_true')
    ap.add_argument('--ohne-hunks', action='store_true', dest='ohne_hunks')
    ap.add_argument('--ohne-pfad', action='store_true', dest='ohne_pfad')
    ap.add_argument('--nur-pfad', action='store_true', dest='nur_pfad')
    ap.add_argument('--ohne-reg', action='store_true', dest='ohne_reg')
    ap.add_argument('--nur-reg', action='store_true', dest='nur_reg')
    ap.add_argument('--p3', default='', help='andere Basisdatei statt p3 (z. B. eigener Kandidat fuer Runde 2)')
    ap.add_argument('--reg-top', type=int, default=24, dest='reg_top')
    ap.add_argument('--reg-lambda', type=float, default=3.0, dest='reg_lambda')
    ap.add_argument('--reg-max-hunks', type=int, default=30, dest='reg_max_hunks')
    ap.add_argument('--pfad-ziele', type=int, default=6, dest='pfad_ziele')
    ap.add_argument('--pfad-k', type=int, default=9, dest='pfad_k')
    ap.add_argument('--pfad-zeit', type=float, default=4, dest='pfad_zeit')
    ap.add_argument('--hunk-spender', type=int, default=40, dest='hunk_spender')
    ap.add_argument('--nur-messen', action='store_true', dest='nur_messen')
    ap.add_argument('--abgeben', action='store_true')
    a = ap.parse_args()
    a.procs = max(1, min(int(os.environ.get('O14_MAXPROCS', '3')), a.procs))   # 12.11. target: mehr Kerne, wenn sonst nichts laeuft (Std. weiter 3)
    Lauf(a.einheit, a.fkt, a).run()


if __name__ == '__main__':
    main()
