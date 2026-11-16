"""Gemeinsame strikte Semantik für native Mutatormessungen. Kein Compileraufruf."""
from collections import Counter
import re

SCHEMA = 1
PROFILE = 'native_fstand_status_v1'
ROW = re.compile(r'^([0-9A-Fa-f]{6})\s+(\d+)\s*/\s*(\d+)\s+(GLEICH|FEHLT|\d+ Befehle)\s*$')
SUMMARY = re.compile(r'^(\d+)/(\d+) GLEICH, Bytes (\d+)/(\d+), Fast-Treffer\(<=10 Bef\) (\d+), EXTRA (\d+)\s*$')
EXTRA = re.compile(r'^EXTRA\s+(\S+)\s+(\d+) B @\+([0-9a-fA-F]+)\s*$')


def parse_unit(text, returncode):
    """R-Tupel bleiben kompatibel; GLEICH ist ausschließlich ein expliziter Status.

    FEHLT-Nachbarn bleiben im vollständigen Stand. FEHLT als Ziel ist ein Fehler.
    Ein vollständiger, konsistenter Einheitsabschluss ist zwingend erforderlich.
    """
    rows = []; summaries = []; extras = []; errors = []
    if returncode != 0: errors.append('Prüfaufruf endete mit Status %s' % returncode)
    for line_number, line in enumerate(text.splitlines(), 1):
        m = ROW.fullmatch(line)
        if m:
            label = m[4]; status = label if label in ('GLEICH', 'FEHLT') else 'BEFEHLE'
            rows.append(dict(address=m[1].lower(), original_bytes=int(m[2]), compiled_bytes=int(m[3]),
                             status=status, rest=0 if status == 'GLEICH' else None if status == 'FEHLT' else int(label.split()[0]),
                             line=line_number, text=line)); continue
        m = SUMMARY.fullmatch(line)
        if m: summaries.append(tuple(map(int, m.groups()))); continue
        m = EXTRA.fullmatch(line)
        if m: extras.append((m[1], int(m[2]), int(m[3], 16))); continue
        if re.match(r'^[0-9A-Fa-f]{6}\s+\d+\s*/', line): errors.append('Unlesbare Funktionszeile %d' % line_number)
        if line.startswith('EXTRA'): errors.append('Unlesbare EXTRA-Zeile %d' % line_number)
    duplicates = [a for a, n in Counter(r['address'] for r in rows).items() if n != 1]
    if duplicates: errors.append('Mehrdeutige Funktionszeilen: ' + ', '.join(duplicates))
    if len(summaries) != 1: errors.append('Genau ein Einheitsabschluss erwartet, gefunden %d' % len(summaries))
    extra_count = None
    if len(summaries) == 1:
        equal, total, eqbytes, allbytes, near, extra_count = summaries[0]
        expected = (sum(r['status'] == 'GLEICH' for r in rows), len(rows),
                    sum(r['original_bytes'] for r in rows if r['status'] == 'GLEICH'),
                    sum(r['original_bytes'] for r in rows), len(extras))
        # fstand zählt bei Fast-Treffer teils intern verziehene GLEICH-Differenzen.
        # Deren nd steht nicht in der Textzeile; nicht aus sichtbaren Resten erraten.
        visible_near = sum(r['status'] == 'BEFEHLE' and r['rest'] <= 10 for r in rows)
        if (equal, total, eqbytes, allbytes, extra_count) != expected or not visible_near <= near <= total:
            errors.append('Einheitsabschluss widerspricht Funktions-/EXTRA-Zeilen')
    # Kein letzter Regex-Treffer wird bei Mehrdeutigkeit zur maßgeblichen Zeile.
    by_address = {r['address']: r for r in rows if r['address'] not in duplicates}
    result = dict(schema_version=SCHEMA, profile=PROFILE, returncode=returncode,
                  rows=rows, by_address=by_address, target=None, extra=extra_count,
                  extra_rows=extras, summary=summaries[0] if len(summaries) == 1 else None,
                  R={a: (r['rest'], r['original_bytes'], r['compiled_bytes']) for a, r in by_address.items()},
                  valid=not errors, errors=errors)
    if errors: result['fehler'] = '; '.join(errors)
    return result


def parse(text, target, returncode):
    result = parse_unit(text, returncode)
    target = target.lower().removeprefix('f_'); result['target'] = target
    selected = [r for r in result['rows'] if r['address'] == target]
    if len(selected) != 1: result['errors'].append('Zielfunktion fehlt oder ist mehrdeutig')
    elif selected[0]['status'] == 'FEHLT': result['errors'].append('Zielfunktion ist FEHLT')
    result['valid'] = not result['errors']
    if result['errors']: result['fehler'] = '; '.join(result['errors'])
    return result


def is_equal(result, target):
    return bool(result and result.get('valid') is True
                and result.get('by_address', {}).get(target.lower().removeprefix('f_'), {}).get('status') == 'GLEICH')


def target_better(new, old, target):
    if not new or not old or not new.get('valid') or not old.get('valid'): return False
    target = target.lower().removeprefix('f_')
    n, b = new['by_address'].get(target), old['by_address'].get(target)
    if not n or not b or n['status'] == 'FEHLT': return False
    if b['status'] == 'FEHLT': return True
    if b['status'] == 'GLEICH': return False
    if n['status'] == 'GLEICH': return True
    return n['rest'] < b['rest']


def same_target(a, b, target):
    if not a or not b or not a.get('valid') or not b.get('valid'): return False
    target = target.lower().removeprefix('f_')
    x, y = a['by_address'].get(target), b['by_address'].get(target)
    return bool(x and y and all(x[k] == y[k] for k in ('status', 'rest', 'original_bytes', 'compiled_bytes')))


def regressions(new, old, target):
    """Alle Nachbarn, FEHLT, GLEICH-Status, Größen und zusätzliche Symbole prüfen."""
    if not new or not old or not new.get('valid') or not old.get('valid'):
        return ['Native Einheitsmessung ungültig']
    target = target.lower().removeprefix('f_'); bad = []
    before, after = old['by_address'], new['by_address']
    if set(before) != set(after): bad.append('Menge der Funktionszeilen verändert')
    for address, b in before.items():
        if address == target: continue
        n = after.get(address)
        if n is None: bad.append(address + ' fehlt vollständig'); continue
        if n['original_bytes'] != b['original_bytes']: bad.append(address + ' Originalgrenze verändert')
        if b['status'] == 'GLEICH' and n['status'] != 'GLEICH': bad.append(address + ' GLEICH-Status verloren')
        if b['status'] != 'FEHLT' and n['status'] == 'FEHLT': bad.append(address + ' jetzt FEHLT')
        if b['status'] == n['status'] == 'BEFEHLE' and n['rest'] > b['rest']: bad.append(address + ' Rest erhöht')
        if b['original_bytes'] == b['compiled_bytes'] and n['original_bytes'] != n['compiled_bytes']:
            bad.append(address + ' Größengleichheit verloren')
    if new['extra'] > old['extra']: bad.append('EXTRA erhöht')
    if Counter(map(tuple, new['extra_rows'])) - Counter(map(tuple, old['extra_rows'])): bad.append('Neue EXTRA-Symbole')
    return bad
