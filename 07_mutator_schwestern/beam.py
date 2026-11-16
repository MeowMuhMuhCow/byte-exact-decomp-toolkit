#!/usr/bin/env python3
"""Mehrkandidatensuche fuer suche.py; gleicher Aufruf und gleiche Operatoren.

Aktivierung: SUCHE_BEAM=1 python3 suche.py NAME LO CTN VD [--test ...]
Direkt: python3 beam.py NAME LO CTN VD [--test ...]
SUCHE_BEAM_BREITE=8, SUCHE_BEAM_TIEFE=6, SUCHE_BEAM_BATCH=48,
SUCHE_BEAM_RUECKSCHRITT=4, SUCHE_BEAM_CODE_KOPIEN=2.
SUCHE_BEAM_BUDGET begrenzt Varianten der ganzen Einheit, OHNE Basislauf;
Standard MAXV*LAEUFE je Zielfunktion. Nicht verbrauchtes Budget wird vererbt.
KD_BEAM_ADAPTIV=1 startet je Funktion mit KD_BEAM_START Varianten und
erweitert nach grober Verbesserung um KD_BEAM_ZUSATZ bis zum alten Limit.
KD_GROESSENBRUECKE=1 behaelt hoechstens KD_GROESSENPLAETZE zusaetzliche
groessengleiche Zwischenzustaende bis KD_GROESSEN_RESTPLUS Restanstieg.

Neutrale/maessig schlechtere Zielfassungen sind nur Suchzustaende in VD.
Ablagen laufen ausschliesslich ueber suche.ablegen -> sperre.schreibe.
Vorher: bewerte/vertraeglich PLUS Einzel-Nachbarpruefung und feste Grenzen.
BEAM-Schluessel im bestehenden Register unterscheiden sich bewusst von alten
Einzelschritten: deren 'kein' schliesst einen nuetzlichen Zwischenschritt nicht aus.
--test bzw. SL_TEST=1 schreibt nie p3. SUCHE_REG darf im Test nicht auf das
Produktionsregister zeigen. Keine Zusatzpakete; kein eigener Compilerpfad.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import time
from dataclasses import dataclass, field


def _hash(text):
    return hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()


def nachbarn_sicher(ref, neu, ziel):
    """Die Summenpruefung von vertraeglich um jeden einzelnen Nachbarn ergaenzen.

Keine verschobenen Originalgrenzen, verlorenen Funktionen oder neuen Luecken.
Die bisher passende Groesse darf auch ohne GLEICH nicht verloren gehen.
"""
    if os.environ.get('SUCHE_RESTBREMSE')=='1':
        import a2wertung
        return a2wertung.neighbours_safe(ref,neu,ziel)
    if set(ref) != set(neu):
        return False
    for ad, alt in ref.items():
        neu_r = neu[ad]
        if neu_r['so'] != alt['so']:
            return False
        if ad == ziel:
            continue
        if alt['gl'] and not neu_r['gl']:
            return False
        if alt['status'] != 'FEHLT' and neu_r['status'] == 'FEHLT':
            return False
        if alt['nd'] is not None and (neu_r['nd'] is None or neu_r['nd'] > alt['nd']):
            return False
        if alt['so'] == alt['sn'] and neu_r['so'] != neu_r['sn']:
            return False
    return True


@dataclass
class Zustand:
    zeilen: list
    obj: str
    r: dict
    tiefe: int = 0
    weg: tuple = ()
    merkmale: frozenset = frozenset()
    bruecke: bool = False
    rows: dict = None
    extra: tuple = ()
    iterator: object = None
    fertig: bool = False
    plan_cursor: int = 0
    ident: str = field(init=False)
    code: str = field(init=False)

    def __post_init__(self):
        self.ident = _hash('\n'.join(self.zeilen))
        # Nur zur Vielfalt, NICHT zum Verwerfen gleicher Maschinenfassungen.
        self.code = _hash(str(self.r['sn']) + '\n' + '\n'.join(self.r.get('A', [])))


def auswahl(pool, breite, schluessel, code_kopien=2):
    """Haelfte nach Qualitaet, Rest nach unterschiedlichen Aenderungswegen.

Gleicher Maschinencode darf mehrere unterschiedliche Quellfassungen behalten.
Die beste Fassung bleibt erhalten; neutrale und schlechtere Bruecken haben
eigene Plaetze, statt beim ersten gleichwertigen Einzelkandidaten zu verschwinden.
"""
    pool = list({n.ident: n for n in pool if not n.fertig}.values())
    pool.sort(key=lambda n: (schluessel(n.r), n.tiefe, n.ident))
    genommen, codes = [], {}

    def add(n):
        genommen.append(n)
        codes[n.code] = codes.get(n.code, 0) + 1
        pool.remove(n)

    for n in list(pool):
        if len(genommen) >= max(1, breite // 2):
            break
        if codes.get(n.code, 0) < code_kopien:
            add(n)
    while pool and len(genommen) < breite:
        erlaubt = [n for n in pool if codes.get(n.code, 0) < code_kopien]
        if not erlaubt:
            break

        def vielfalt(n):
            dist = min((len(n.merkmale ^ x.merkmale) /
                        max(1, len(n.merkmale | x.merkmale)) for x in genommen), default=1)
            return (-dist, schluessel(n.r), n.tiefe, n.ident)

        add(min(erlaubt, key=vielfalt))
    return genommen


def _positiv(name, default):
    n = int(os.environ.get(name, default))
    if n < 1:
        raise ValueError(name + ' muss positiv sein')
    return n


def groessen_bruecke(ref_r, candidate, enabled, restplus):
    """Nur begrenzte, groessengleiche Zwischenzustaende; kein Ablagekriterium."""
    return (enabled and ref_r['so'] != ref_r['sn'] and
            candidate['so'] == candidate['sn'] and candidate['nd'] is not None and
            candidate['nd'] <= ref_r['nd'] + restplus)


def _plaene(g, n, ziel):
    op = g['op']
    blocks = op.bloecke(n.zeilen)
    if ziel not in blocks:
        return
    unit = op.einheit_info(n.zeilen)
    tags, pos, ho, ha = g['signatur'](g['fsmod'].hunks(n.r))
    tags |= g['OPTSIG'].get(ziel, set())
    if tags & {'OPT_ohne_e', 'OPT_inl0'}:
        tags.add('INLINE')
    oo = [g['fsmod'].norm(x) for x in n.r['O']]
    aa = [g['fsmod'].norm(x) for x in n.r['A']]
    ev = op.typ_evidenz(ho, ha) if ho else op.typ_evidenz(oo, aa)
    if not (ev['w16'] or ev['b8']):
        ev = op.typ_evidenz(oo, aa)
    if 'OPT_j' in tags:
        ev['b8'] = True
    info = dict(O=oo, A=aa, ev=ev, unit=unit, tags=tags,
                first_mark=min(b['mark'] for b in blocks.values()))
    if g.get('PROTO_ENABLED'): info.update(g['proto_info'](n.zeilen,n.obj,ziel))
    sites = op.stellen(n.zeilen, blocks[ziel], info)
    sites = g['filter_sites'](sites,n.zeilen,blocks[ziel],n.r,tags)
    sites.sort(key=lambda s: g['rang'](s, tags, pos, n.r['nd']))
    fh = g['fhash'](n.zeilen, blocks[ziel], unit)
    aus, _ = g['waehle'](sites, set())
    start, _ = g['varianten'](aus)
    einzel = ([(s, i)] for s in sites for i in range(1, len(s.alts)))
    seen = set()
    from itertools import chain
    for wahl in chain(start, einzel):
        ak = '|'.join(sorted(s.op + ':' + g['akey'](s, i) for s, i in wahl))
        if not ak or ak in seen:
            continue
        seen.add(ak)
        # Kompletter Quellzustand verhindert Kollisionen bei geaenderten Klassen,
        # Inline-Helfern oder Nachbarn, die fhash allein nicht beruecksichtigt.
        key = f'{fh}:{g["SEED"]}:BEAM:{_hash(n.ident + ak)[:32]}'
        if key in g['REG']:
            continue
        zeilen = op.render(n.zeilen, [s.alts[i] for s, i in wahl])
        features = frozenset(s.op + ':' + str(s.info or '') for s, i in wahl)
        yield zeilen, wahl, key, features


def suchen(g):
    """BF1 optional; vorhandener Such-/Abgabepfad bleibt erhalten."""
    g['TEST'] = g['TEST'] or os.environ.get('SL_TEST') == '1'
    if os.environ.get('SUCHE_BEAM_FORTSETZEN', '0') != '1':
        return _suchen(g)
    import importlib.util
    import sys
    module_file = Path(__file__).with_name('beam_fortsetzung.py')
    spec = importlib.util.spec_from_file_location('target_beam_fortsetzung', module_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profile = {key: value for key, value in os.environ.items()
               if key.startswith(('SUCHE_BEAM_', 'KD_GROESSEN', 'KD_BEAM_', 'KD_DIFFKLASSE'))
               and key not in {'SUCHE_BEAM_BUDGET', 'SUCHE_BEAM_STATE', 'KD_BEAM_DATEI'}}
    profile.update(MAXV=g['MAXV'], LAEUFE=g['LAEUFE'], FEIN=g.get('FEIN', False))
    manager = module.Manager(g, __file__, profile)
    try:
        return _suchen(g, manager)
    finally:
        manager.close()


def _suchen(g, _bf=None):
    """Gemeinsamen Treiberzustand benutzen; dessen Abschluss bleibt unveraendert."""
    g['TEST'] = g['TEST'] or os.environ.get('SL_TEST') == '1'
    if g['TEST'] and os.environ.get('SUCHE_REG') and Path(g['REGF']).resolve() == (
            Path(PC.resolve_path('attempts_tsv', _CFG))).resolve():
        raise ValueError('Beam-Test braucht eine eigene SUCHE_REG-Datei')
    breite = _positiv('SUCHE_BEAM_BREITE', 8)
    tiefe = _positiv('SUCHE_BEAM_TIEFE', max(2, g['LAEUFE']))
    batch = min(g['MAXV'], _positiv('SUCHE_BEAM_BATCH', 48))
    kopien = _positiv('SUCHE_BEAM_CODE_KOPIEN', 2)
    rueck = _positiv('SUCHE_BEAM_RUECKSCHRITT', 4)
    budget = _positiv('SUCHE_BEAM_BUDGET',
                      g['MAXV'] * g['LAEUFE'] * max(1, len(g['arbeit'])))
    adaptiv = os.environ.get('KD_BEAM_ADAPTIV','0') == '1'
    startbudget = _positiv('KD_BEAM_START', 384)
    zusatzbudget = _positiv('KD_BEAM_ZUSATZ', 512)
    groessenbruecke = os.environ.get('KD_GROESSENBRUECKE','0') == '1'
    groessenplaetze = _positiv('KD_GROESSENPLAETZE', 1)
    groessenrest = _positiv('KD_GROESSEN_RESTPLUS', 24)
    used = 0
    log = g['log']
    score = g['schluessel']
    fs = g['fsmod']
    vd = Path(g['VD'])
    trace_path = vd / (g['NAME'] + '_beam.jsonl')
    log(f'BEAM Breite={breite} Tiefe={tiefe} Budget={budget} Batch={batch}')
    counters = dict(varianten=0, neutral_behalten=0, schlechter_behalten=0,
                    tiefe_max=0, brueckengewinne=0, nachbar_abgelehnt=0,
                    budget_erweitert=0, groessenbruecken=0, zwischen_nicht_abgelegt=0)

    def ende():
        return (g['GESPERRT'] or g['zeit_um']() or
                time.time() - g['T0'] > float(g['flag']('--zeit', 1e9)))

    with trace_path.open('a', encoding='utf-8') as trace:
        for index, (_, _, ziel) in enumerate(g['arbeit']):
            if ende() or used >= budget:
                break
            if ziel not in g['REF'] or g['REF'][ziel]['gl']:
                continue
            hard_limit = max(1, (budget - used) // (len(g['arbeit']) - index))
            limit = min(hard_limit,startbudget) if adaptiv else hard_limit
            local_used = 0
            # Zwischenzustaende sind nur waehrend dieser Funktion noetig.
            # Trace, Register und angenommene Gewinne bleiben weiterhin in VD/p3.
            scratch = tempfile.TemporaryDirectory(prefix='target_beam_',dir='/tmp')
            work = Path(scratch.name)
            root_e = fs.Einheit(g['OBJ_AKT'], g['LO'])
            ref = root_e.stand()
            extra0 = tuple(root_e.extra)
            root_obj = work / (g['NAME'] + '_beam_root_' + _hash('\n'.join(g['AKT']))[:24] + '.OBJ')
            shutil.copyfile(g['OBJ_AKT'], root_obj)
            root = Zustand(list(g['AKT']), str(root_obj), ref[ziel],
                           rows=ref, extra=extra0)
            _session = None
            if _bf is not None:
                try:
                    _session = _bf.open(ziel, root)
                    if _session is None:
                        log('BF1: Funktion bereits durch Fortsetzung belegt')
                        scratch.cleanup()
                        continue
                    frontier = _session.restore(root, work, Zustand, nachbarn_sicher)
                except Exception as exc:
                    log('BF1: Wiederaufnahme abgewiesen:', exc)
                    scratch.cleanup()
                    continue
            else:
                frontier = [root]
            seen_sources = {root.ident}
            seen_keys = set()
            log(f'BEAM f_{ziel:06x}: {ref[ziel]["status"]}, Teilbudget {limit}')
            while frontier and local_used < limit and not ende() and not ref[ziel]['gl']:
                todo = []
                _cursor_before = [(n, n.plan_cursor) for n in frontier]
                pending = list(frontier)
                # Reihum expandieren: ein Elternkandidat kann nicht das ganze
                # naechste Batch beanspruchen. Iteratoren ueber Runden behalten.
                while pending and len(todo) < min(batch, limit - local_used, budget - used):
                    for parent in list(pending):
                        if parent.fertig or parent.tiefe >= tiefe:
                            parent.fertig = True
                            pending.remove(parent)
                            continue
                        if parent.iterator is None:
                            parent.iterator = iter(_session.plans(_plaene, g, parent, ziel)
                                                   if _session else _plaene(g, parent, ziel))
                        for zeilen, wahl, key, features in parent.iterator:
                            sid = _hash('\n'.join(zeilen))
                            if sid in seen_sources or key in seen_keys:
                                continue
                            seen_sources.add(sid)
                            seen_keys.add(key)
                            todo.append((parent, zeilen, wahl, key, features))
                            break
                        else:
                            parent.fertig = True
                            pending.remove(parent)
                        if len(todo) >= min(batch, limit - local_used, budget - used):
                            break
                if not todo:
                    break
                objs, errors = g['uebersetze'](['\n'.join(x[1]) for x in todo],[x[2] for x in todo])
                if _session and not g.get('A1_FERTIG', True):
                    for _node, _cursor in _cursor_before:
                        _node.plan_cursor = _cursor
                        _node.iterator = None
                    log('BF1: unvollstaendiger Bau, Cursor bleibt vor dem Batch')
                    break
                local_used += len(todo)
                used += len(todo)
                counters['varianten'] += len(todo)
                nodes, entries = {}, []
                for k, (parent, zeilen, wahl, key, features) in enumerate(todo):
                    for s, i in wahl:
                        g['STAT'][(s.op, 'versuche')] += 1
                    status, rn = 'fehler', parent.r['nd']
                    if objs[k]:
                        try:
                            e = fs.Einheit(objs[k], g['LO'])
                            rr = e.funktion(ziel)
                            if rr['nd'] is not None and rr['so'] == ref[ziel]['so']:
                                rn = rr['nd']
                                status = ('GLEICH' if rr['gl'] else 'besser' if score(rr) < score(parent.r)
                                          else 'neutral' if score(rr) == score(parent.r) else 'schlechter')
                                n = Zustand(zeilen, objs[k], rr, parent.tiefe + 1,
                                            parent.weg + tuple(s.op for s, i in wahl),
                                            parent.merkmale | features,
                                            bruecke=parent.bruecke or score(rr) >= score(parent.r),
                                            extra=tuple(e.extra))
                                nodes[k] = (n, e)
                                counters['tiefe_max'] = max(counters['tiefe_max'], n.tiefe)
                        except Exception as ex:
                            log(f'  BEAM V{k}: OBJ nicht bewertbar: {ex}')
                    else:
                        for s, i in wahl:
                            g['STAT'][(s.op, 'fehler')] += 1
                    ops = '+'.join(s.op for s, i in wahl)
                    entries.append((key, ziel, 'BEAM:' + ops,
                                    'Zielbewertung; parent=' + parent.ident[:16], parent.r['nd'], rn, status))
                    trace.write(json.dumps(dict(fkt=f'{ziel:06x}', parent=parent.ident,
                                               quelle=_hash('\n'.join(zeilen)), tiefe=parent.tiefe + 1,
                                               ops=ops, status=status, rest=rn), ensure_ascii=False) + '\n')
                g['registriere'](entries)
                g['REG'].update(x[0] for x in entries)

                def sicher(k):
                    n, e = nodes[k]
                    if n.rows is None:
                        n.rows = e.stand()
                    # Zusatzsymbole duerfen weder entstehen noch verschwinden.
                    extras = {(name, size) for off, name, size in n.extra}
                    old_extras = {(name, size) for off, name, size in extra0}
                    return (extras == old_extras and g['vertraeglich'](ref, n.rows, ziel)
                            and nachbarn_sicher(ref, n.rows, ziel)
                            and (not g.get('PROTO_ENABLED') or g['proto_allowed'](ref[ziel],n.r,n.weg)))

                # Bewerte bestimmt den Gewinner. Bei einer durch die alte
                # Summenregel erlaubten Einzelregression weitere Kandidaten pruefen.
                allowed_objs = [o if k in nodes else None for k, o in enumerate(objs)]
                while any(allowed_objs):
                    w, k, nr, kz, _ = g['bewerte'](allowed_objs, [x[2] for x in todo], ziel, ref)
                    if w is None:
                        break
                    if (groessenbruecke and not nodes[k][0].r['gl'] and
                            nodes[k][0].r['nd'] > ref[ziel]['nd']):
                        allowed_objs[k] = None
                        counters['zwischen_nicht_abgelegt'] += 1
                        continue
                    if not sicher(k):
                        allowed_objs[k] = None
                        counters['nachbar_abgelehnt'] += 1
                        continue
                    winner = nodes[k][0]
                    before = ref[ziel]['nd']
                    alter_grobstand = g['a1'].coarse_key(ref[ziel])
                    detail = ' -> '.join(winner.weg)
                    # Ausschliesslicher Commitpfad; im Echtmodus ist sperre.py
                    # innerhalb von ablegen fuer jede Ablage zustaendig.
                    g['ablegen'](winner.zeilen, winner.obj, winner.rows)
                    g['AKT'] = list(winner.zeilen)
                    g['REF'] = ref = winner.rows
                    g['B'] = g['op'].bloecke(g['AKT'])
                    g['U'] = g['op'].einheit_info(g['AKT'])
                    g['GEWINNE'].append((ziel, 'BEAM', before, ref[ziel]['nd'], ref[ziel]['gl'], detail))
                    for op_name in set(winner.weg):
                        g['STAT'][('BEAM_' + op_name, 'treffer')] += 1
                        if ref[ziel]['gl']:
                            g['STAT'][('BEAM_' + op_name, 'gleich')] += 1
                    counters['brueckengewinne'] += winner.bruecke
                    log(f'  GEWINN BEAM Tiefe {winner.tiefe}: {before} -> {ref[ziel]["status"]} {detail}')
                    if adaptiv and limit<hard_limit and g['a1'].coarse_key(ref[ziel])<alter_grobstand:
                        limit=min(hard_limit,limit+zusatzbudget)
                        counters['budget_erweitert']+=1
                        log(f'  BEAM Fortschritt: Teilbudget auf {limit} erweitert')
                    break
                if _session:
                    _session.completed(nodes)
                if ref[ziel]['gl'] or (ende() and _session is None):
                    if _session:
                        _session.checkpoint([])
                    break
                # Begrenzte Rueckschritte am Ziel. Neutrale Fassungen bleiben
                # erlaubt; Nachbarn und Funktionsgrenzen bleiben unverhandelbar.
                max_rest = ref[ziel]['nd'] + max(rueck, math.ceil(ref[ziel]['nd'] * 0.25))
                max_size = max(32, abs(ref[ziel]['so'] - ref[ziel]['sn']) + 16)
                def normale_grenze(n):
                    return n.r['nd'] is not None and n.r['nd']<=max_rest and abs(n.r['so']-n.r['sn'])<=max_size
                def groessen_grenze(n):
                    return groessen_bruecke(ref[ziel],n.r,groessenbruecke,groessenrest)
                pool = [n for n in frontier if not n.fertig and n.tiefe < tiefe
                        and (normale_grenze(n) or groessen_grenze(n))
                        and nachbarn_sicher(ref, n.rows, ziel)]
                new_nodes = {}
                for k, (n, e) in nodes.items():
                    if n.tiefe < tiefe and (normale_grenze(n) or groessen_grenze(n)):
                        pool.append(n)
                        new_nodes[n.ident] = k
                # Erst vielversprechende/diverse Zustaende vollstaendig messen,
                # nicht alle Varianten in jeder grossen Einheit disassemblieren.
                checked = []
                while pool and len(checked) < breite:
                    proposed = auswahl(pool, breite - len(checked), score, kopien)
                    if not proposed:
                        break
                    for n in proposed:
                        pool.remove(n)
                        k = new_nodes.get(n.ident)
                        if k is not None and not sicher(k):
                            counters['nachbar_abgelehnt'] += 1
                            continue
                        checked.append(n)
                frontier = auswahl(checked, breite, score, kopien)
                if groessenbruecke and ref[ziel]['so']!=ref[ziel]['sn']:
                    extra=[n for n in pool if groessen_grenze(n) and n.ident not in {x.ident for x in frontier}]
                    for n in auswahl(extra,groessenplaetze,score,kopien):
                        k=new_nodes.get(n.ident)
                        if k is not None and not sicher(k):
                            counters['nachbar_abgelehnt']+=1
                            continue
                        frontier.append(n)
                        counters['groessenbruecken']+=1
                for n in frontier:
                    if n.ident in new_nodes:
                        dst = work / (g['NAME'] + '_beam_' + n.ident[:24])
                        shutil.copyfile(n.obj, str(dst) + '.OBJ')
                        # Die Quelle steckt bereits in n.zeilen.
                        n.obj = str(dst) + '.OBJ'
                    counters['neutral_behalten'] += score(n.r) == score(ref[ziel])
                    counters['schlechter_behalten'] += score(n.r) > score(ref[ziel])
                    counters['tiefe_max'] = max(counters['tiefe_max'], n.tiefe)
                if _session:
                    _session.checkpoint(frontier)
                trace.flush()
                log(f'  BEAM {local_used}/{limit} Varianten, {len(frontier)} Eltern, '
                    f'Tiefen {[n.tiefe for n in frontier]}')
            if _session:
                if g.get('A1_FERTIG', True) and not g.get('A1_INFRA', 0):
                    _session.checkpoint(frontier)
                log('BF1 ENDE ' + json.dumps(_session.stats, sort_keys=True))
                _session.close()
            scratch.cleanup()
    g['BEAM_STATS'] = counters
    (vd / (g['NAME'] + '_beam_stat.json')).write_text(json.dumps(counters, indent=2) + '\n')
    log('BEAM ENDE ' + json.dumps(counters, sort_keys=True))


def main():
    import sys
    os.environ['SUCHE_BEAM'] = '1'
    if os.environ.get('SL_TEST') == '1' and '--test' not in sys.argv:
        sys.argv.append('--test')
    runpy.run_path(str(Path(__file__).with_name('suche.py')), run_name='__main__')


if __name__ == '__main__':
    main()
