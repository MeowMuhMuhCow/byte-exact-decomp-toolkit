"""Strikter Einheitsvergleich für zusammen.py; Import ist seiteneffektfrei."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

from native_ergebnis import parse_unit, target_better

SCHEMA = 'DECOMP-UEBERNAHMESCHUTZ-1'


class Stand(dict):
    """Numerische Sicht nur für bestehende Summen/Transplantat-Adresslisten.

    Entscheidungen und GLEICH-Anzahl verwenden immer den vollständigen Status.
    """
    def __init__(self, payload):
        self.payload = payload
        self.parsed = parse_unit(payload['text'], payload['returncode'])
        if payload.get('schema') != SCHEMA: raise ValueError('Schutzbeleg-Schema fehlt')
        if not self.parsed['valid']: raise ValueError(self.parsed['fehler'])
        p = payload.get('provenance', {})
        if not p.get('stable') or not p.get('context_sha256') or not p.get('obj_sha256') or not p.get('unit_lo'):
            raise ValueError('Messgrundlage fehlt oder wurde während der Messung verändert')
        self.extra_errors = payload.get('extra_errors', [])
        proofs = payload.get('extra_proofs', [])
        if not self.extra_errors:
            actual = Counter((x['name'], x['size'], x['offset']) for x in proofs)
            if actual != Counter(map(tuple, self.parsed['extra_rows'])):
                raise ValueError('EXTRA-Belege decken Richterzeilen nicht exakt ab')
            if any(not x.get('sha256') for x in proofs): raise ValueError('EXTRA-Hash fehlt')
        super().__init__((a.upper(), 999 if r['status'] == 'FEHLT' else r['rest'])
                         for a, r in self.parsed['by_address'].items())

    def gleich(self):
        return sum(r['status'] == 'GLEICH' for r in self.parsed['rows'])


def compare(before, after):
    """Kein kleinerer Rest kann eine unvollständige Messgrundlage überstimmen."""
    result = dict(allowed=False, better=[], worse=[], blockers=[], notes=[])
    if not isinstance(before, Stand) or not isinstance(after, Stand):
        result['blockers'].append('Vollständige statusgebundene Einheitsmessung fehlt'); return result
    bp, np = before.payload['provenance'], after.payload['provenance']
    if bp['context_sha256'] != np['context_sha256']:
        result['blockers'].append('Richter/Metadaten/Messprofil verschieden; beide Seiten frisch messen')
    if bp['unit_lo'] != np['unit_lo']:
        result['blockers'].append('Unterschiedliche Einheitszuordnung')
    b, n = before.parsed['by_address'], after.parsed['by_address']
    if set(b) != set(n): result['blockers'].append('Vollständige Funktionsidentitätsmenge verändert')
    for address in sorted(set(b) & set(n)):
        old, new = b[address], n[address]; reasons = []
        if old['status'] == 'GLEICH' and new['status'] != 'GLEICH': reasons.append('GLEICH verloren')
        if old['status'] != 'FEHLT' and new['status'] == 'FEHLT': reasons.append('jetzt FEHLT')
        if old['status'] == new['status'] == 'BEFEHLE' and new['rest'] > old['rest']: reasons.append('Rest größer')
        if old['original_bytes'] != new['original_bytes']:
            if new['status'] == 'GLEICH':
                result['notes'].append(address + ': berichtete Endgröße geändert, GLEICH und gleicher Metadatenkontext erforderlich')
            else: reasons.append('berichtete Originalgröße verändert')
        if (old['original_bytes'] == old['compiled_bytes'] and
                new['original_bytes'] != new['compiled_bytes'] and new['status'] != 'GLEICH'):
            # 07.11.2026 (maintainer "genau", Claude worker): Groessengleichheit verloren zaehlt nicht,
            # wenn sich der Rest mindestens halbiert (Blind-Neubau 48->16, 68->30 gingen sonst verloren).
            # 07.11.2026 (maintainer "dann klaer das"): bei altem Rest > 40 sagt zufaellige Groessengleichheit nichts
            # ueber den Aufbau - dort entscheidet allein der Rest.
            if (old['status'] == new['status'] == 'BEFEHLE' and isinstance(old.get('rest'), int)
                    and isinstance(new.get('rest'), int) and (2 * new['rest'] <= old['rest'] or old['rest'] > 40)):
                result['notes'].append(address + ': Größengleichheit verloren, aber Rest %d -> %d (halbiert oder alter Rest > 40) - zugelassen' % (old['rest'], new['rest']))
            else:
                reasons.append('Größengleichheit verloren')
        if reasons: result['worse'].append(address.upper())
        elif target_better(after.parsed, before.parsed, address): result['better'].append(address.upper())
    if before.extra_errors or after.extra_errors:
        result['blockers'].append('EXTRA-Körper nicht vollständig gebunden: ' + '; '.join(before.extra_errors + after.extra_errors))
    else:
        # Auch identische relative Sprungbytes können nach einer Verschiebung
        # auf andere außerhalb des Körpers liegende Ziele zeigen. Keine Lage-
        # normalisierung ohne separaten disassemblierten Referenzbeleg.
        key = lambda x: (x['name'], x['size'], x['offset'], x['sha256'])
        old_extra = Counter(key(x) for x in before.payload['extra_proofs'])
        new_extra = Counter(key(x) for x in after.payload['extra_proofs'])
        if new_extra - old_extra:
            result['blockers'].append('Zusätzlicher/geänderter/verschobener EXTRA-Körper einschließlich Relokationszielen')
        if old_extra - new_extra: result['notes'].append('EXTRA entfernt; dies allein zählt nicht als Funktionsgewinn')
    result['allowed'] = bool(result['better']) and not result['worse'] and not result['blockers']
    return result


def vergleich(before, after):
    """Alte Zwei-Listen-API; Sperrmarker sind absichtlich keine Funktionsadresse.

    Dadurch kann der alte Transplantatpfad bei Identitäts-/EXTRA-/Kontextfehlern
    nicht vermeintliche Funktionsblöcke austauschen.
    """
    check = compare(before, after)
    bad = check['worse'][:]
    if check['blockers']:
        bad.append('!MESSGRUNDLAGE:' + '|'.join(check['blockers']))
    return bad, check['better']


def measure(judge, obj, lo, source=None, workbench=None, timeout=120):
    cmd = [sys.executable, str(Path(__file__).with_name('schutz_messen.py')),
           '--judge', str(judge), '--obj', str(obj), '--lo', str(lo)]
    if source: cmd += ['--source', str(source)]
    if workbench: cmd += ['--workbench', str(workbench)]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if run.returncode: raise ValueError(run.stderr[-1000:] or run.stdout[-1000:])
        payload = json.loads(run.stdout); stand = Stand(payload)
        return stand, payload['text']
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        return None, 'ÜBERNAHMESCHUTZ: ' + str(error)


def still_current(stand, judge, workbench):
    """Vor der bestehenden p3-Sperre die verwendeten Messartefakte erneut binden."""
    from schutz_messen import context, sha
    try:
        p = stand.payload['provenance']
        return (context(Path(judge), Path(workbench))['sha256'] == p['context_sha256'] and
                sha(p['obj']) == p['obj_sha256'] and
                (not p.get('source') or sha(p['source']) == p['source_sha256']))
    except (ValueError, KeyError, OSError): return False
