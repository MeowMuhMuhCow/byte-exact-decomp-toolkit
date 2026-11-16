"""EXTRA-Körper streng binden, ohne Maschinenbefehle oder Gleichheit neu zu richten.

FIXUPP-Grundformen entsprechen omf.py/einbau.py; hier bleiben zusätzlich die
aufgelösten EXTDEF-/Segment-/Gruppenziele im Beleg. Unbekannt heißt ungeprüft.
Keine Optimierung, kein Linken, kein Compileraufruf.
"""
import hashlib
import json
from pathlib import Path
import struct

LOCSZ = {0: 1, 1: 2, 2: 2, 3: 4, 4: 1, 5: 2, 9: 4, 11: 6, 13: 4}
# Nur bekannte Formen dürfen ohne weitere Tabelleninterpretation passieren.
# Insbesondere COMDEF/LCOMDEF belegen ebenfalls EXTDEF-Indizes: Ignorieren
# würde alle folgenden Ziele verschieben. Unbekannte Alias-/Patchformen sind
# ebenso kein Beweis unveränderten EXTRA-Codes.
KNOWN_RECORDS = {0x80, 0x88, 0x8a, 0x8b, 0x8c, 0x8e, 0x90, 0x91, 0x94, 0x95,
                 0x96, 0x98, 0x99, 0x9a, 0x9c, 0x9d, 0xa0, 0xa1, 0xa2, 0xa3,
                 0xb4, 0xb6, 0xb7, 0xbc, 0xc2, 0xc3, 0xc4, 0xc5, 0xca, 0xcc}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def idx(data, pos):
    if pos >= len(data): raise ValueError('OMF-Index fehlt')
    if data[pos] & 128:
        if pos + 1 >= len(data): raise ValueError('OMF-Index abgeschnitten')
        return ((data[pos] & 127) << 8) | data[pos + 1], pos + 2
    return data[pos], pos + 1


def records(raw):
    pos = 0
    while pos < len(raw):
        if pos + 3 > len(raw): raise ValueError('OMF-Kopf abgeschnitten')
        typ, size = struct.unpack_from('<BH', raw, pos)
        end = pos + size + 3
        if not size or end > len(raw): raise ValueError('OMF-Satz abgeschnitten')
        rec = raw[pos:end]
        if rec[-1] and sum(rec) & 255: raise ValueError('OMF-Prüfsumme falsch')
        yield typ, rec[3:-1]
        pos = end


def fixups(raw):
    """Relokationen mit Eigentümer und konservativer kanonischer Zielidentität.

    Segmentinterne Addenden werden NICHT semantisch umgedeutet. Verschiebt sich
    ein solches Ziel, ist der EXTRA-Körper hier geändert/erneut zu prüfen.
    """
    ln = ['']; ext = [None]; segs = {}; groups = {}; result = []
    frames = {}; targets = {}; cds = {}; last = None
    recs = list(records(raw))
    if not recs or recs[0][0] != 0x80 or recs[-1][0] not in (0x8a, 0x8b):
        raise ValueError('Genau ein vollständiges OMF-Modul erwartet')
    if sum(t == 0x80 for t, _ in recs) != 1: raise ValueError('Mehrere OMF-Module')
    def word(data, pos, width):
        if pos + width > len(data): raise ValueError('OMF-Zahl abgeschnitten')
        return int.from_bytes(data[pos:pos + width], 'little'), pos + width
    def names(data):
        pos = 0
        while pos < len(data):
            size = data[pos]; pos += 1
            if pos + size > len(data): raise ValueError('OMF-Name abgeschnitten')
            yield data[pos:pos + size].decode('latin1'); pos += size
    for typ, data in recs:
        if typ in (0xb0, 0xb8):
            raise ValueError('%s (0x%02x) verändert EXTDEF-Indizes und wird für EXTRA nicht unterstützt' %
                             ('COMDEF' if typ == 0xb0 else 'LCOMDEF', typ))
        if typ not in KNOWN_RECORDS:
            raise ValueError('Nicht unterstützter OMF-Satz 0x%02x; Tabellen-/Alias-/Codewirkung ungeprüft' % typ)
        if typ in (0x96, 0xca): ln.extend(names(data))
        elif typ in (0x98, 0x99):
            pos = 1 + (3 if data[0] >> 5 == 0 else 0)
            _, pos = word(data, pos, 4 if typ & 1 else 2)
            name, pos = idx(data, pos); cls, pos = idx(data, pos); overlay, pos = idx(data, pos)
            segs[len(segs) + 1] = (ln[name], ln[cls], ln[overlay])
        elif typ == 0x9a:
            name, pos = idx(data, 0); members = []
            while pos < len(data):
                if data[pos] != 0xff: raise ValueError('Unbekannter GRPDEF-Eintrag')
                seg, pos = idx(data, pos + 1); members.append(seg)
            groups[len(groups) + 1] = (ln[name], members)
        elif typ in (0x8c, 0xb4):
            pos = 0
            while pos < len(data):
                size = data[pos]; pos += 1
                if pos + size > len(data): raise ValueError('EXTDEF abgeschnitten')
                ext.append(data[pos:pos + size].decode('latin1'))
                _, pos = idx(data, pos + size)
        elif typ == 0xbc:
            pos = 0
            while pos < len(data):
                ni, pos = idx(data, pos); ext.append(ln[ni]); _, pos = idx(data, pos)
        elif typ in (0xa0, 0xa1):
            seg, pos = idx(data, 0); off, pos = word(data, pos, 4 if typ & 1 else 2)
            last = (('seg', seg), off)
        elif typ in (0xa2, 0xa3):
            raise ValueError('LIDATA wird für EXTRA nicht geraten')
        elif typ in (0xc2, 0xc3):
            flags, attr = data[:2]
            if flags & 2: raise ValueError('Iterierter COMDAT ungeprüft')
            off, pos = word(data, 3, 4 if typ & 1 else 2); _, pos = idx(data, pos)
            if attr & 15 == 0:
                group, pos = idx(data, pos); seg, pos = idx(data, pos)
                if not group and not seg: _, pos = word(data, pos, 2)
            ni, pos = idx(data, pos); name = ln[ni]
            if not flags & 1: cds[name] = cds.get(name, 0) + 1
            if cds.get(name) != 1: raise ValueError('Mehrdeutiger COMDAT: ' + name)
            last = (('comdat', name), off)
        elif typ in (0x9c, 0x9d):
            pos = 0
            def datum(method):
                nonlocal pos
                if method < 3: value, pos = idx(data, pos); return value
                if method == 3: value, pos = word(data, pos, 2); return value
                if method in (4, 5): return None
                raise ValueError('Unbekannte FIXUPP-Methode')
            while pos < len(data):
                head = data[pos]; pos += 1
                if not head & 128:
                    method = (head >> 2) & (7 if head & 64 else 3)
                    value = datum(method)
                    (frames if head & 64 else targets)[head & 3] = (method, value)
                    continue
                loc = (head >> 2) & 15
                if loc not in LOCSZ: raise ValueError('Unbekannte FIXUPP-Breite')
                if pos + 2 > len(data): raise ValueError('FIXUPP abgeschnitten')
                offset = ((head & 3) << 8) | data[pos]; desc = data[pos + 1]; pos += 2
                if desc & 128: frame = frames[(desc >> 4) & 3]
                else:
                    method = (desc >> 4) & 7; frame = (method, datum(method))
                if desc & 8: target = targets[desc & 3]
                else:
                    method = desc & 3; target = (method, datum(method))
                disp = 0
                if not desc & 4: disp, pos = word(data, pos, 4 if typ & 1 else 2)
                if last is None: raise ValueError('FIXUPP ohne Dateneigentümer')
                result.append(dict(owner=last[0], offset=last[1] + offset,
                    width=LOCSZ[loc], location=loc, relative=not bool(head & 64),
                    frame=frame, target=target, displacement=disp))
    def segment(index):
        value = segs[index]
        if list(segs.values()).count(value) != 1: raise ValueError('Mehrdeutige SEGDEF-Identität')
        return value
    def canon(pair):
        method, value = pair
        if method == 0: return ('segment', segment(value))
        if method == 1:
            name, members = groups[value]
            return ('group', name, [segment(i) for i in members])
        if method == 2:
            if not value or value >= len(ext): raise ValueError('EXTDEF-Index fehlt')
            return ('external', ext[value])
        return ('absolute' if method == 3 else 'location' if method == 4 else 'target', value)
    for entry in result:
        entry['frame'] = canon(entry['frame']); entry['target'] = canon(entry['target'])
    return result


def bind(scope):
    """Alle vom Richter sichtbaren EXTRA-Zeilen an genau dessen OBJ binden."""
    extras = scope['extra']
    if not extras: return []
    raw = Path(scope['obj']).read_bytes(); relocations = fixups(raw)
    model = scope['m']; selected = scope.get('_CODE_SEG')
    if selected is None:
        selected = next((i for i, v in model['segs'].items() if v is scope['sg']), None)
    if selected is None: raise ValueError('Kein eindeutiges ausgewähltes Segment')
    proofs = []
    for offset, name, size in extras:
        owner = ('seg', selected); body = model['segs'][selected]
        if name.startswith('SEGMENT_') and '::' in name:
            si = int(name.split('::')[0].removeprefix('SEGMENT_'))
            owner = ('seg', si); body = model['segs'][si]
        elif name.startswith('COMDAT_UNGEKLAERT::'):
            nm = name.split('::', 1)[1]
            options = [c for c in model['comdats'] if c['name'] == nm]
            if len(options) != 1: raise ValueError('EXTRA-COMDAT mehrdeutig')
            body = options[0]; owner = ('comdat', nm)
        end = offset + size
        if size <= 0 or offset < 0 or end > len(body['data']): raise ValueError('EXTRA-Bereich ungültig')
        # SEGDEF kann Nullfüllung reservieren, ohne dafür LEDATA zu senden.
        # Die Belegmaske wird mitgehasht; reserviert und emittiert bleiben getrennt.
        if any(not body['has'][i] and (body['data'][i] or body['mask'][i]) for i in range(offset,end)):
            raise ValueError('EXTRA enthält widersprüchliche unbelegte Bytes')
        refs = []
        covered = set()
        for relocation in relocations:
            if relocation['owner'] != owner: continue
            start = relocation['offset']; stop = start + relocation['width']
            if start < end and stop > offset:
                if start < offset or stop > end: raise ValueError('Fixup über EXTRA-Grenze')
                entry = {k: v for k, v in relocation.items() if k not in ('owner', 'offset')}
                entry['offset'] = start - offset; refs.append(entry)
                covered.update(range(start, stop))
        masked = {i for i in range(offset, end) if body['mask'][i]}
        if covered != masked: raise ValueError('EXTRA-Fixupabdeckung widerspricht Richtermaske')
        owner_identity = (body.get('name'), body.get('cls')) if owner[0]=='seg' else owner
        payload = dict(owner=owner_identity, bytes=bytes(body['data'][offset:end]).hex(), has=bytes(body['has'][offset:end]).hex(),
                       mask=bytes(body['mask'][offset:end]).hex(), fixups=refs)
        proofs.append(dict(name=name, size=size, offset=offset,
            sha256=sha(json.dumps(payload, sort_keys=True).encode()),
            code_sha256=sha(bytes(body['data'][offset:end])), fixups=refs,
            scope='exakter Körper einschließlich Segment, Belegmaske und Fixupzielen; Lage separat geschützt'))
    return proofs
