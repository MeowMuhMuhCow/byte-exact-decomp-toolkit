#!/usr/bin/env python3
"""zusammen2.py (worker, 15.11.2026): zusammen.py fuer mehrere Arbeiter gleichzeitig.
Unterschiede zu zusammen.py (sonst identisch):
  - ENTK_OUT=<ordner>  eigener Ausgabeordner (Fassungen, ERGEBNIS.tsv, UNENTFERNT.tsv, log.md, arbeit/)
  - ENTK_ID=<kennung>  WORKER_ID fuer probe_queue (z. B. K1, D23x)
  - --frisch           Kruecken direkt im AKTUELLEN p3 erkennen (muster.kruecken), nicht nur die alte worker-Liste
  - --zeilen A-B       Einheiten aus meta/units.tsv (Spalte 2), Zeilen A bis B
Beispiel: ENTK_OUT=logs/decrutch/W1 ENTK_ID=K1 python3 -u .../worker/zusammen2.py --frisch --budget 16 --zeilen 146-290 --ueberspringen-fertig
Ergebnis wird NICHT nach p3 geschrieben.
"""
"""zusammen.py — worker: alle Krücken einer Einheit zugleich entfernen und nativ messen.

Verfahren (aus worker übernommen, nicht neu erfunden):
  - Erkennung und Rückschreibung: worker/kruecken/muster.py (byte-gleiche Kopie in worker/muster.py)
  - Zuordnung der Zeilen zu den Krücken: worker/kruecken/LAUF.tsv enthält zu jeder einzeln
    gemessenen Variante den Quell-Hash (key = einheit:fkt:sha16). Damit wird jede Zeile
    exakt dem Vorkommen zugeordnet — wichtig, weil der Text `volatile` bei vielen
    Vorkommen gleich lautet. Wo der Hash nicht mehr passt (p3 inzwischen geändert),
    Fallback auf den Text aus KRUECKEN_GLEICH.tsv.
  - Messung: WORKER_ID=worker probe_queue.py EINHEIT DATEI (ohne FKT = Stand der ganzen
    Einheit) gegen live_fstand. Nie die Befehlszahl von fdiff.

Ablauf je Einheit:
  1. p3 lesen, Krücken erkennen, Zeilen der Liste exakt zuordnen (Hash, sonst Text).
  2. Basis nativ messen (p3 unverändert).
  3. Alle Entfernungen zugleich anwenden und nativ messen.
  4. Bleibt alles gleich -> OUT/EINHEIT_P1.CPP, ERGEBNIS.tsv OK.
  5. Kippt etwas (oder übersetzt nicht) -> halbieren (Chunks, größter zuerst),
     höchstens 8 Messungen je Einheit. Größte geprüft-gleiche Teilmenge liefern,
     Status TEIL, Rest in UNENTFERNT.tsv.

Aufruf:
  python3 zusammen.py --abgleich              # nur Zuordnung Liste<->p3, keine Messung
  python3 zusammen.py --kleinste 5            # die 5 Einheiten mit den wenigsten Zeilen
  python3 zusammen.py EINHEIT [EINHEIT ...]
  python3 zusammen.py --alle [--hoechstens N] [--ueberspringen-fertig]
"""
import csv
import hashlib
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent          # decrutch dir
ROOT = HERE.parents[4]                          # Projektwurzel
sys.path.insert(0, str(HERE))
import muster

# 15.11. worker: Wird eine ganze Anweisung entfernt, die alleiniger Koerper von if/else/while/for/do war,
# bleibt ein leeres ';' stehen (erzeugt keinen Code), sonst bricht die Syntax ("expecting while but found else").
_anwenden_orig = muster.anwenden
def _braucht_leer(text, s, e):
    if not text[s:e].rstrip().endswith(';'):
        return False
    vor = re.sub(r'//[^\n]*$', '', text[:s].rstrip(), flags=re.M).rstrip()
    if vor.endswith(')') or re.search(r'\b(else|do)$', vor):
        return True
    nach = re.sub(r'^\s*(//[^\n]*\n\s*)*', '', text[e:])
    return bool(re.match(r'else\b', nach))
def _anwenden(text, gewaehlt):
    spannen = []
    for k in gewaehlt:
        spannen.extend(k.spans)
    spannen.sort(key=lambda x: x[0], reverse=True)
    out = text
    for s0, e0, repl in spannen:
        if repl.strip() == '' and _braucht_leer(text, s0, e0):
            repl = repl + ';'
        out = out[:s0] + repl + out[e0:]
    return out
muster.anwenden = _anwenden

TOOLKIT_ROOT = HERE.parent
if str(TOOLKIT_ROOT) not in sys.path: sys.path.insert(0, str(TOOLKIT_ROOT))
import project_config as PC
_CFG = PC.load_config()
ROOT = Path(PC.resolve_path('project_root', _CFG))
P3 = Path(PC.resolve_path('src_p3_dir', _CFG))
LOGS_DIR = Path(PC.resolve_path('logs_dir', _CFG, str(TOOLKIT_ROOT / 'logs')))
LISTE = LOGS_DIR / 'crutches_equal.tsv'
LAUF = LOGS_DIR / 'crutches_runs.tsv'
LIVE = LOGS_DIR / 'live_fstand'
PROBE = TOOLKIT_ROOT / '03_richter' / 'probe_queue.py'
OUT = (ROOT / os.environ['ENTK_OUT']) if os.environ.get('ENTK_OUT') else (LOGS_DIR / 'decrutched')
OUT.mkdir(parents=True, exist_ok=True)
ARBEIT = OUT / 'arbeit'
ERGEBNIS = OUT / 'ERGEBNIS.tsv'
UNENTFERNT = OUT / 'UNENTFERNT.tsv'
LOG = OUT / 'log.md'
STAND = OUT / 'STAND.md'
MAX_MESSUNGEN = 8   # Standard; --budget N (z. B. 16) erhöht das Budget je Einheit

# Überlappende Entfernungen: die natürlichere Form gewinnt.
PRIO = {
    'roundtrip': 0, 'kommentar': 1, 'vol_name': 2, 'addr_cast': 3, 'addr_direkt': 4,
    'and0': 5, 'or0': 5, 'maske16': 5, 'maske8': 5, 'void_addr': 5,
    'selbst': 6, 'und_selbst': 6, 'xor_selbst': 6, 'sub_selbst': 6, 'volatile': 9,
}


def jetzt():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def lese(pfad):
    return Path(pfad).read_text(encoding='latin1', errors='replace')


def sha16(text):
    return hashlib.sha256(text.encode('latin1', errors='replace')).hexdigest()[:16]


def norm(s):
    return ' '.join(s.split())


def log(zeile):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf8') as fh:
        fh.write(f'{jetzt()} {zeile}\n')


def parse_stand(text):
    """Richterausgabe: Adresszeilen `A  x/y  GLEICH|N Befehle`, EXTRA-Zeilen, EXTRA-Zahl."""
    rest, status, extra_zeilen, extra_zahl = {}, {}, [], None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r'^([0-9A-Fa-f]{6})\s+(\d+)/(\d+)\s+(.*)$', s)
        if m:
            addr = m.group(1).upper()
            st = m.group(4).strip()
            if st == 'GLEICH':
                rest[addr] = 0
            else:
                mm = re.match(r'(\d+) Befehle', st)
                rest[addr] = int(mm.group(1)) if mm else 10 ** 9
            status[addr] = s
            continue
        if s.startswith('EXTRA'):
            extra_zeilen.append(s)
            mm = re.search(r'EXTRA\s+(\d+)\s*$', s)
            if mm:
                extra_zahl = int(mm.group(1))
    return {'rest': rest, 'status': status,
            'extra_zeilen': sorted(extra_zeilen), 'extra': extra_zahl}


def messe(einheit, datei):
    """Ganze Einheit nativ über probe_queue.py messen (ohne FKT = Stand aller Funktionen)."""
    env = dict(os.environ)
    env['WORKER_ID'] = os.environ.get('ENTK_ID', 'worker')
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, str(PROBE), einheit, str(datei)],
                           cwd=str(ROOT), env=env, capture_output=True, text=True,
                           timeout=1800, errors='replace')
        txt = (p.stdout or '') + '\n' + (p.stderr or '')
        rc = p.returncode
    except subprocess.TimeoutExpired:
        return {'fehler': True, 'grund': 'Zeitüberschreitung', 'sek': round(time.time() - t0, 1),
                'rest': {}, 'extra': None, 'extra_zeilen': [], 'status': {}}
    st = parse_stand(txt)
    st['rc'] = rc
    st['sek'] = round(time.time() - t0, 1)
    st['auszug'] = txt[-700:]
    st['datei'] = str(datei)
    if not st['rest']:
        st['fehler'] = True
        st['grund'] = 'keine Richterzeilen (Compile-/Werkzeugfehler)'
        m = re.search(r'(NICHT UEBERSETZT:.*|Error!.*|E\d+:.*)', txt)
        if m:
            st['grund'] = m.group(1)[:200]
    return st


def unterschiede(base, var):
    """Probleme, die einen Rest schlechter machen; Besserungen sind erlaubt."""
    probleme = []
    if var.get('fehler'):
        return ['Messung fehlgeschlagen: ' + var.get('grund', '')[:160]]
    for addr, r in base['rest'].items():
        if addr not in var['rest']:
            probleme.append(f'{addr} fehlt')
        elif var['rest'][addr] > r:
            probleme.append(f'{addr} {r}->{var["rest"][addr]}')
    for addr, r in var['rest'].items():
        if addr not in base['rest'] and r > 0:
            probleme.append(f'+{addr} {r}')
    if base['extra_zeilen'] != var['extra_zeilen']:
        probleme.append('EXTRA-Zeilen anders')
    if base['extra'] != var['extra']:
        probleme.append(f'EXTRA {base["extra"]}->{var["extra"]}')
    return probleme


def live_stand(einheit):
    pfad = LIVE / f'{einheit}.fstand'
    if not pfad.exists():
        return None
    st = parse_stand(lese(pfad))
    return st if st['rest'] else None


def lade_liste():
    pro = defaultdict(list)
    with open(LISTE, encoding='utf-8') as fh:
        for row in csv.DictReader(fh, delimiter='\t'):
            pro[row['einheit']].append(row)
    return pro


def _sauber(text, k):
    """15.11. worker: offensichtlich kaputte Erkennungen verwerfen (sonst kippt jede Sammelmessung):
    entfernter Text mit Steuerwoertern oder unausgeglichenen Klammern, oder Treffer mitten in a->b / a.b."""
    for s0, e0, repl in k.spans:
        weg = text[s0:e0]
        code = re.sub(r'//[^\n]*', '', weg)
        if re.search(r'\b(if|else|while|for|do|switch|case|return|goto|break|continue)\b', code):
            return False
        for a, b in ('()', '{}', '[]'):
            if code.count(a) - code.count(b) != repl.count(a) - repl.count(b):
                return False
        if s0 > 0 and (text[s0 - 1] == '.' or text[max(0, s0 - 2):s0] == '->'):
            return False
        nachher = (text[:s0] + repl).rstrip()
        if nachher.endswith('->') or nachher.endswith('.'):
            return False
    return True


def frisch_liste(einheit):
    """Alle Kruecken, die muster.py im aktuellen p3 erkennt, als Listeneintraege (mit exaktem Hash)."""
    src = P3 / f'{einheit}_P1.CPP'
    if not src.exists():
        return []
    text = lese(src)
    ks, _k = muster.kruecken(text)
    ks = [k for k in ks if _sauber(text, k)]
    return [{'einheit': einheit, 'fkt': k.fkt, 'art': k.kind, 'kruecke': k.text,
             'hash': sha16(muster.anwenden(text, [k]))} for k in ks]


def lade_lauf():
    """Alle einzeln gemessenen GLEICH-Varianten aus 1317s LAUF.tsv, mit Quell-Hash."""
    pro = defaultdict(list)
    with open(LAUF, encoding='utf-8', errors='replace') as fh:
        kopf = fh.readline().rstrip('\n').split('\t')
        for line in fh:
            x = line.rstrip('\n').split('\t')
            if len(x) < len(kopf):
                continue
            r = dict(zip(kopf, x))
            if (r['status'] == 'unveraendert' and r['art'].startswith('einzeln:')
                    and r['rest_alt'] == '0' and r['rest_neu'] == '0'):
                r['hash'] = r['key'].split(':')[-1]
                pro[r['einheit']].append(r)
    return pro


def zuordnen(text, eintraege):
    """Einträge (aus LAUF, mit Hash) exakt auf erkannte Krücken abbilden.

    Erst über den Quell-Hash (eindeutig), sonst über den Text. Gibt zusätzlich
    die Anzahl der Hash- bzw. Texttreffer zurück.
    """
    ks, _koerper = muster.kruecken(text)
    gruppe = defaultdict(list)
    for k in ks:
        gruppe[(k.fkt, k.kind)].append(k)
    hash_cache = {}

    def h(k):
        if id(k) not in hash_cache:
            hash_cache[id(k)] = sha16(muster.anwenden(text, [k]))
        return hash_cache[id(k)]

    used = set()
    zuordnung = []
    hash_treffer = text_treffer = 0

    def text_fallback(art_kind, fkt, text_wert, h_wert):
        kandidaten = gruppe.get((fkt, art_kind), [])
        passend = [k for k in kandidaten if h_wert and h(k) == h_wert]
        for k in passend:
            if id(k) not in used:
                return k, 'hash'
        if passend:
            return passend[0], 'dublette_hash'
        for k in kandidaten:
            if id(k) not in used and norm(k.text) == norm(text_wert):
                return k, 'text'
        for k in kandidaten:
            if id(k) in used and norm(k.text) == norm(text_wert):
                return k, 'dublette_text'
        return None, 'nicht_gefunden'

    for r in eintraege:
        kind = r['art'].split(':', 1)[1] if ':' in r['art'] else r['art']
        k, wie = text_fallback(kind, r['fkt'], r['kruecke'], r.get('hash', ''))
        if k is None:
            zuordnung.append({'eintrag': r, 'k': None, 'wie': 'nicht_gefunden'})
            continue
        if wie.startswith('dublette'):
            zuordnung.append({'eintrag': r, 'k': k, 'wie': 'dublette'})
            continue
        used.add(id(k))
        zuordnung.append({'eintrag': r, 'k': k, 'wie': 'applied'})
        if wie == 'hash':
            hash_treffer += 1
        else:
            text_treffer += 1
    return zuordnung, ks, hash_treffer, text_treffer


def auswahl(zuordnung):
    """Nicht überlappende Auswahl, natürliche Form zuerst.

    Gibt (gewaehlt, ueberdeckt, deckung) mit deckung[id(überdeckt)] = überdeckende Krücke.
    """
    einzig = {}
    for z in zuordnung:
        if z['wie'] == 'applied':
            einzig[id(z['k'])] = z['k']
    reihe = sorted(einzig.values(),
                   key=lambda k: (min(s[0] for s in k.spans), PRIO.get(k.kind, 7)))
    gewaehlt, ueberdeckt, deckung = [], [], {}
    for k in reihe:
        g = None
        for x in gewaehlt:
            if muster.ueberlappend(k, x):
                g = x
                break
        if g is None:
            gewaehlt.append(k)
        else:
            ueberdeckt.append(k)
            deckung[id(k)] = g
    return gewaehlt, ueberdeckt, deckung


def schreibe(pfad, text):
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(text.encode('latin1', errors='replace'))


class Messton:
    """Misst Textfassungen einer Einheit über probe_queue.py, zählt Messungen."""

    def __init__(self, einheit, basis):
        self.einheit = einheit
        self.basis = basis
        self.n = 0
        self.texte = {}
        self.ordner = ARBEIT / einheit

    def __call__(self, kruecken):
        text = muster.anwenden(_QUELLEN[self.einheit], kruecken)
        self.n += 1
        if text in self.texte:
            return self.texte[text]
        self.ordner.mkdir(parents=True, exist_ok=True)
        pfad = self.ordner / f'v{self.n:03d}.CPP'
        schreibe(pfad, text)
        st = messe(self.einheit, pfad)
        st['text_hash'] = sha16(text)
        self.texte[text] = st
        return st


_QUELLEN = {}


def suche_teil(ton, kandidaten, budget, start=()):
    """Halbierungssuche: größter geprüft-gleicher Teil der Kandidaten.

    Annahme: start + kandidaten ist bereits gemessen und NICHT gleich.
    Größten Chunk zuerst testen; kippt er, halbieren.
    Gibt (gewaehlt, ausgeschlossen, ungeprueft, verbrauchte Messungen).
    """
    gewaehlt = list(start)
    ausgeschlossen = []
    verbraucht = 0
    if not kandidaten:
        return gewaehlt, [], [], 0
    if len(kandidaten) == 1:
        if budget <= 0:
            return gewaehlt, [], list(kandidaten), 0
        st = ton(gewaehlt + kandidaten)
        verbraucht = 1
        if not unterschiede(ton.basis, st):
            gewaehlt.extend(kandidaten)
        else:
            ausgeschlossen.extend(kandidaten)
        return gewaehlt, ausgeschlossen, [], verbraucht
    h = len(kandidaten) // 2
    chunks = [list(kandidaten[:h]), list(kandidaten[h:])]
    while budget > 0 and chunks:
        chunks.sort(key=len, reverse=True)
        chunk = chunks.pop(0)
        st = ton(gewaehlt + chunk)
        budget -= 1
        verbraucht += 1
        if not unterschiede(ton.basis, st):
            gewaehlt.extend(chunk)
            continue
        if len(chunk) == 1:
            ausgeschlossen.extend(chunk)
            continue
        h = len(chunk) // 2
        chunks.append(chunk[:h])
        chunks.append(chunk[h:])
    ungeprueft = [k for c in chunks for k in c]
    return gewaehlt, ausgeschlossen, ungeprueft, verbraucht


def funktionen_aus_problemen(probleme):
    """Aus `ADDR alt->neu` die betroffenen Funktionen f_ADDR ziehen."""
    fkts = set()
    for p in probleme:
        m = re.match(r'^\+?([0-9A-Fa-f]{6})\b', p)
        if m:
            fkts.add('f_' + m.group(1).lower())
    return fkts


def tsv_setzen(pfad, kopf, einheit, zeilen):
    """Zeilen einer Einheit in einer TSV ersetzen (Wiederholungsläufe ohne Dubletten)."""
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    alt = {}
    reihenfolge = []
    if pfad.exists():
        with pfad.open(encoding='utf8') as fh:
            fh.readline()
            for line in fh:
                x = line.rstrip('\n').split('\t')
                if len(x) < len(kopf) or not x[0]:
                    continue
                if x[0] not in alt:
                    reihenfolge.append(x[0])
                alt.setdefault(x[0], []).append(x)
    if einheit in alt:
        reihenfolge = [e for e in reihenfolge if e != einheit]
    reihenfolge.append(einheit)
    alt[einheit] = [list(map(str, z)) for z in zeilen]
    tmp = pfad.with_suffix(pfad.suffix + '.tmp')
    with tmp.open('w', encoding='utf8') as fh:
        fh.write('\t'.join(kopf) + '\n')
        for e in reihenfolge:
            for z in alt.get(e, []):
                fh.write('\t'.join(z) + '\n')
    os.replace(tmp, pfad)


def unentfernt_alle(einheit, rows, grund):
    tsv_setzen(UNENTFERNT, ['einheit', 'fkt', 'art', 'kruecke', 'grund'], einheit,
               [[einheit, r.get('fkt', ''), r.get('art', ''), r.get('kruecke', ''), grund]
                for r in rows])


def bearbeite(einheit, zeilen, lauf_zeilen, alt=None):
    t0 = time.time()
    src = P3 / f'{einheit}_P1.CPP'
    if not src.exists():
        unentfernt_alle(einheit, zeilen, 'keine_p3_quelle')
        return {'status': 'FEHLER', 'grund': 'keine p3-Quelle', 'entfernt': 0}
    try:
        text = lese(src)
    except OSError as exc:
        unentfernt_alle(einheit, zeilen, 'p3_nicht_lesbar')
        return {'status': 'FEHLER', 'grund': f'p3 nicht lesbar: {exc}', 'entfernt': 0}
    _QUELLEN[einheit] = text
    quel_hash = sha16(text)
    if lauf_zeilen and len(lauf_zeilen) == len(zeilen):
        eintraege = lauf_zeilen
    else:
        eintraege = [{'fkt': r['fkt'], 'art': r['art'], 'kruecke': r['kruecke'], 'hash': ''}
                     for r in zeilen]
    zuordnung, _ks, hash_treffer, text_treffer = zuordnen(text, eintraege)
    nicht_gefunden = [z for z in zuordnung if z['wie'] == 'nicht_gefunden']
    if len(nicht_gefunden) == len(zuordnung):
        unentfernt_alle(einheit, eintraege, 'nicht_im_p3')
        return {'status': 'FEHLER', 'grund': 'keine Zeile der Liste im p3 gefunden', 'entfernt': 0}
    gewaehlt, ueberdeckt, deckung = auswahl(zuordnung)
    if not gewaehlt:
        unentfernt_alle(einheit, eintraege, 'keine_anwendbare_kruecke')
        return {'status': 'FEHLER', 'grund': 'keine anwendbare Krücke', 'entfernt': 0}

    # 1. Basis nativ messen (p3 unverändert).
    basis = messe(einheit, src)
    messungen = 1
    if basis.get('fehler'):
        unentfernt_alle(einheit, eintraege, 'basis_nicht_messbar')
        return {'status': 'FEHLER', 'grund': 'Basis nicht messbar: ' + basis.get('grund', ''),
                'entfernt': 0, 'messungen': messungen}
    live = live_stand(einheit)
    basis_live = unterschiede(live, basis) if live is not None else ['kein live_fstand']
    ton = Messton(einheit, basis)

    # 2. Alle Entfernungen zugleich.
    voll = ton(gewaehlt)
    messungen = 1 + ton.n
    voll_probleme = unterschiede(basis, voll)
    if not voll_probleme:
        gewaehlt_final = list(gewaehlt)
        ausgeschlossen, ungeprueft = [], []
    else:
        # Fehlersignal nutzen: nur Krücken der schlechter gewordenen Funktionen
        # gelten als Verdacht; der Rest wird zuerst geprüft, dann der Verdacht
        # in Halbierungsschritten wieder aufgenommen.
        problem_fkts = funktionen_aus_problemen(voll_probleme)
        verdacht = [k for k in gewaehlt if k.fkt in problem_fkts] if problem_fkts else []
        rest = [k for k in gewaehlt if k not in verdacht]
        if verdacht and rest and (MAX_MESSUNGEN - messungen) > 0:
            st = ton(rest)
            if not unterschiede(basis, st):
                budget = max(0, MAX_MESSUNGEN - (1 + ton.n))
                gewaehlt_final, ausgeschlossen, ungeprueft, _ver = suche_teil(
                    ton, verdacht, budget, start=rest)
            else:
                budget = max(0, MAX_MESSUNGEN - (1 + ton.n))
                gewaehlt_final, ausgeschlossen, ungeprueft, _ver = suche_teil(
                    ton, gewaehlt, budget)
        else:
            budget = max(0, MAX_MESSUNGEN - (1 + ton.n))
            gewaehlt_final, ausgeschlossen, ungeprueft, _ver = suche_teil(
                ton, gewaehlt, budget)
        messungen = 1 + ton.n

    # 2b. Restbudget: ausgeschlossene Einzelkrücken gegen den Endstand erneut prüfen.
    # Der Kontext hat sich durch später aufgenommene Krücken geändert; eine, die
    # vorher kippte, kann jetzt passen.
    if ausgeschlossen:
        restbudget = max(0, MAX_MESSUNGEN - (1 + ton.n))
        weiter = []
        for k in ausgeschlossen:
            if restbudget <= 0:
                weiter.append(k)
                continue
            st = ton(gewaehlt_final + [k])
            restbudget -= 1
            if not unterschiede(basis, st):
                gewaehlt_final = gewaehlt_final + [k]
            else:
                weiter.append(k)
        ausgeschlossen = weiter
        messungen = 1 + ton.n

    # 3. Endfassung genau so messen, wie sie abgelegt wird.
    end_stand = None
    if gewaehlt_final:
        end_text = muster.anwenden(text, gewaehlt_final)
        if end_text in ton.texte:
            end_stand = ton.texte[end_text]
        else:
            end_stand = ton(gewaehlt_final)
            messungen = 1 + ton.n
        if unterschiede(basis, end_stand):
            # Sollte nicht vorkommen; im Zweifel nichts liefern.
            ausgeschlossen = list(gewaehlt)
            gewaehlt_final = []
            end_stand = None

    # 4. Bilanz je Listeneintrag.
    gew_ids = {id(k) for k in gewaehlt_final}
    ausg_ids = {id(k) for k in ausgeschlossen}
    unge_ids = {id(k) for k in ungeprueft}

    def nicht_entfernt_grund(k):
        if id(k) in ausg_ids:
            return 'ausgeschlossen'
        if id(k) in unge_ids:
            return 'ungeprueft'
        g = deckung.get(id(k))
        if g is not None:
            if id(g) in ausg_ids:
                return 'ausgeschlossen'
            if id(g) in unge_ids:
                return 'ungeprueft'
        return 'ungeprueft'

    def ist_entfernt(k):
        if id(k) in gew_ids:
            return True
        g = deckung.get(id(k))
        return g is not None and id(g) in gew_ids

    entfernt, ausg_rows, unge_rows = 0, [], []
    for z in zuordnung:
        k = z['k']
        if k is None:
            continue
        if ist_entfernt(k):
            entfernt += 1
        else:
            grund = nicht_entfernt_grund(k)
            (ausg_rows if grund == 'ausgeschlossen' else unge_rows).append((z, grund))

    # Die Basis hat gemessen: alles Weitere ist höchstens ein Teil-Erfolg, kein Fehler.
    status = 'OK' if (end_stand is not None and entfernt
                      and not ausg_rows and not unge_rows) else 'TEIL'

    sek = round(time.time() - t0, 1)
    if alt and entfernt < alt[1]:
        # Nie einen besseren vorhandenen Stand durch einen schlechteren ersetzen.
        log(f'{einheit} behalten: neuer Lauf entfernt={entfernt} < alt={alt[1]} '
            f'(status bleibt {alt[2]})')
        return {'status': alt[2], 'entfernt': alt[1], 'vorher': len(eintraege),
                'messungen': messungen, 'sek': sek, 'liefer': '', 'behalten': True,
                'ausgeschlossen': 0, 'ungeprueft': 0, 'nicht_gefunden': len(nicht_gefunden),
                'basis_live': 'gleich' if not basis_live else 'abweichung'}

    ziel = OUT / f'{einheit}_P1.CPP'
    liefer = ''
    if end_stand is not None and entfernt:
        schreibe(ziel, end_text)
        liefer = str(ziel.relative_to(ROOT))
    log(f'{einheit} rows={len(eintraege)} hash={hash_treffer} text={text_treffer} '
        f'entfernt={entfernt} status={status} messungen={messungen} sek={sek} '
        f'p3sha={quel_hash} liefer={liefer or "-"} '
        f'{("gruende=" + "|".join(voll_probleme[:4])) if voll_probleme else ""}')
    if nicht_gefunden:
        log(f'{einheit} nicht_gefunden={len(nicht_gefunden)}: ' +
            '; '.join(f'{z["eintrag"]["fkt"]} {z["eintrag"]["art"]} '
                      f'{z["eintrag"]["kruecke"][:50]}' for z in nicht_gefunden[:10]))
    if basis_live and live is not None:
        log(f'{einheit} HINWEIS Basis weicht von live_fstand ab: ' + ', '.join(basis_live[:8]))
    un_zeilen = []
    for z, grund in ausg_rows + unge_rows:
        un_zeilen.append([einheit, z['eintrag']['fkt'], z['eintrag']['art'],
                          z['eintrag']['kruecke'], grund])
    for z in nicht_gefunden:
        un_zeilen.append([einheit, z['eintrag']['fkt'], z['eintrag']['art'],
                          z['eintrag']['kruecke'], 'nicht_im_p3'])
    tsv_setzen(UNENTFERNT, ['einheit', 'fkt', 'art', 'kruecke', 'grund'],
               einheit, un_zeilen)

    return {'status': status, 'entfernt': entfernt, 'vorher': len(eintraege),
            'messungen': messungen, 'sek': sek, 'liefer': liefer,
            'ausgeschlossen': len(ausg_rows), 'ungeprueft': len(unge_rows),
            'nicht_gefunden': len(nicht_gefunden),
            'basis_live': 'gleich' if not basis_live else 'abweichung'}


def fertige_einheiten():
    fertig = set()
    if ERGEBNIS.exists():
        with ERGEBNIS.open(encoding='utf8') as fh:
            fh.readline()
            for line in fh:
                x = line.rstrip('\n').split('\t')
                if x and x[0]:
                    fertig.add(x[0])
    return fertig


def abgleich(pro, lauf):
    """Nur Zuordnung Liste <-> aktuelles p3, ohne Messung."""
    gesamt = hash_ok = text_ok = dub = 0
    fehlt = []
    for einheit in sorted(pro):
        text = lese(P3 / f'{einheit}_P1.CPP')
        eintraege = lauf.get(einheit, [])
        if not eintraege or len(eintraege) != len(pro[einheit]):
            eintraege = [{'fkt': r['fkt'], 'art': r['art'], 'kruecke': r['kruecke'], 'hash': ''}
                         for r in pro[einheit]]
        zuordnung, _ks, hh, tt = zuordnen(text, eintraege)
        hash_ok += hh
        text_ok += tt
        for z in zuordnung:
            gesamt += 1
            if z['wie'] == 'dublette':
                dub += 1
            elif z['wie'] == 'nicht_gefunden':
                fehlt.append((einheit, z['eintrag']['fkt'], z['eintrag']['art'],
                              z['eintrag']['kruecke'][:60]))
    print(f'Einträge {gesamt}: Hash-Treffer {hash_ok}, Text-Fallback {text_ok}, '
          f'Dubletten {dub}, nicht gefunden {len(fehlt)}')
    for f in fehlt:
        print('  FEHLT', *f)


def main():
    global MAX_MESSUNGEN
    args = sys.argv[1:]
    pro = lade_liste()
    lauf = lade_lauf()
    if '--budget' in args:
        i = args.index('--budget')
        MAX_MESSUNGEN = int(args[i + 1])
        del args[i:i + 2]
    if '--abgleich' in args:
        abgleich(pro, lauf)
        return 0
    ueberspringen = '--ueberspringen-fertig' in args
    args = [a for a in args if a != '--ueberspringen-fertig']
    hoechstens = None
    if '--hoechstens' in args:
        i = args.index('--hoechstens')
        hoechstens = int(args[i + 1])
        del args[i:i + 2]
    frisch = '--frisch' in args
    args = [a for a in args if a != '--frisch']
    if '--zeilen' in args:
        i = args.index('--zeilen')
        a, b = (int(x) for x in args[i + 1].split('-'))
        del args[i:i + 2]
        tl = [l.rstrip('\n').split('\t') for l in open(Path(PC.resolve_path('units_tsv', _CFG)), encoding='utf-8', errors='replace') if l.strip()]
        args += [r[1] for r in tl[a - 1:b] if len(r) > 1]
    if '--alle' in args:
        args.remove('--alle')
        namen = sorted(pro)
    elif '--kleinste' in args:
        i = args.index('--kleinste')
        n = int(args[i + 1])
        del args[i:i + 2]
        namen = [e for e, z in sorted(pro.items(), key=lambda x: (len(x[1]), x[0]))][:n]
    else:
        namen = args
    if not namen:
        print(__doc__)
        return 2
    fertig = fertige_einheiten() if ueberspringen else set()
    alt_stand = {}
    if ERGEBNIS.exists():
        with ERGEBNIS.open(encoding='utf8') as fh:
            fh.readline()
            for line in fh:
                x = line.rstrip('\n').split('\t')
                if len(x) >= 4:
                    try:
                        alt_stand[x[0]] = (int(x[1]), int(x[2]), x[3])
                    except ValueError:
                        pass
    kopf = ['einheit', 'kruecken_vorher', 'entfernt', 'status']
    zaehler = defaultdict(int)
    gemacht = 0
    for einheit in namen:
        if einheit in fertig:
            continue
        if hoechstens is not None and gemacht >= hoechstens:
            break
        if frisch:
            pro[einheit] = frisch_liste(einheit)
            lauf[einheit] = pro[einheit]
            if not pro[einheit]:
                print(f'{einheit}: keine Kruecken erkannt', flush=True)
                continue
        if einheit not in pro:
            print(f'{einheit}: nicht in der Liste')
            continue
        gemacht += 1
        if os.environ.get('ENTK_ADAPTIV') == '1':
            # 15.11. worker: Budget je Einheit nach Kruecken-Zahl (Halbieren braucht ~2n), Geister-Riesen nur Sammelmessung
            nk = len(pro[einheit])
            MAX_MESSUNGEN = 2 if nk > int(os.environ.get('ENTK_GROSS', '300')) else min(int(os.environ.get('ENTK_MAX', '200')), max(12, 2 * nk + 4))
        r = bearbeite(einheit, pro[einheit], lauf.get(einheit, []),
                      alt_stand.get(einheit))
        zaehler[r['status']] += 1
        print(f"{r['status']:6} {einheit:34} vorher={r.get('vorher', len(pro[einheit])):3} "
              f"entfernt={r.get('entfernt', 0):3} messungen={r.get('messungen', 0)} "
              f"sek={r.get('sek', 0)} {r.get('grund', '')}"
              f"{'  -> ' + r['liefer'] if r.get('liefer') else ''}", flush=True)
        tsv_setzen(ERGEBNIS, kopf, einheit,
                   [[einheit, r.get('vorher', len(pro[einheit])),
                     r.get('entfernt', 0), r['status']]])
    print(dict(zaehler))
    return 0


if __name__ == '__main__':
    sys.exit(main())
