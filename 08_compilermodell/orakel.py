#!/usr/bin/env python3
"""orakel.py EINHEIT FKT [QUELLE] [--stapel | --register] [--procs N] [--voll]   (worker, 05.11.2026)

Allgemeines Listen-Orakel fuer Watcom 10.6 (wpp386 UND wcc386) im Emulator. Verallgemeinert
Unified register & stack-frame oracle combining
slotdiag_ra.py and adr106.py. Read-only: source is never
modified in place. Uses fdiff2.py (same instruction diff count as fstand.py,
'N Befehle' je Funktion) auf dem Emulator-OBJ.

--stapel (Vorgabe, fuer Klasse 1 'nur Stapelplaetze'):
  1. Rohliste (vor der Groessensortierung, TempAllocVorliste) und sortierte Liste (TempAllocNach) ausgeben.
  2. Modellprobe: Shell-Sort-Nachbau (USED_AS_FD zuerst, dann Groesse aufsteigend) muss die echte Folge treffen.
  3. ZWANG: Folgen innerhalb gleicher Groesse umstellen, im Emulator erzwingen, messen -> beste Soll-Folge.
  4. RECHNUNG: Welche EINE Aenderung der Rohliste (Name weg, Name dazu, Name verschoben) ergibt im Modell
     genau die Soll-Folge? Das ist die Rechnung, die die Handfenster bisher je Funktion neu bauen.
--register (fuer Klasse 2 'nur Registerwahl'):
  Konflikt-Rohliste (SortConflictsVor). Fuer jede Einzelaenderung (Knoten weg, Dummy dazu, Nutzwert +-1/+-2)
  die Shell-Folge nach Nutzwert vorhersagen, erzwingen, messen. Vorgabe: weg + Nutzwert +-1; --voll: alles.

Laufumgebung: unicorn/capstone aus ~/.w106_pylib (wird automatisch eingehaengt). Eine Uebersetzung 2-4 s.
Vor einer Abgabe immer nativ mit probe.sh nachmessen (PROBE_CACHE=0).
"""
import sys, os, re, struct, argparse, subprocess, multiprocessing as mp

HIER = os.path.dirname(os.path.abspath(__file__))
TOOLKIT_ROOT = os.path.normpath(os.path.join(HIER, '..'))
for _p in (HIER, os.path.join(TOOLKIT_ROOT, '01_werkzeugkette'), TOOLKIT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import project_config as PC
_CFG = PC.load_config()
PROJ = PC.resolve_path('project_root', _CFG)
import w106cfg as C
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp
import adr106

FD = 0x200
O = adr106.OFF


def shell_sort(a, before):
    """Watcom SortList: Shell-Sort, nicht stabil (Listenlaenge bestimmt die Gleichstaende)."""
    a = list(a); n = len(a); gap = n; adjust = 1
    if n < 2:
        return a
    while True:
        adjust = 1 - adjust; gap = gap // 2 + adjust
        while True:
            swap = False
            for i in range(n - gap):
                if before(a[i + gap], a[i]):
                    a[i], a[i + gap] = a[i + gap], a[i]; swap = True
            if not swap:
                break
        if gap == 1:
            break
    return a


def _name(e, p):
    size = e.u32(p + O['name_size'])
    nid = struct.unpack('<H', e.rd(p + O['name_id'], 2))[0]
    fl = struct.unpack('<H', e.rd(p + O['name_flags'], 2))[0]
    sym = e.u32(p + O['name_sym'])
    txt = 't%d' % nid
    if sym >= BASE:
        try:
            txt = e.cstr(e.u32(e.u32(sym + O['sym_inner']) + O['sym_inner']), 40) or txt
        except Exception:
            pass
    return dict(p=p, txt=txt, size=size, id=nid, fl=fl, fd=1 if fl & FD else 0, cls=e.rd(p + O['name_class'], 1)[0])


def _kette(e, p, leser):
    L = []
    while p and len(L) < 5000:
        L.append(leser(e, p)); p = e.u32(p + O['conf_next'])
    return L


def _schluessel(L):
    """Eindeutiger Schluessel je Knoten: (txt, id, groesse, k-tes Vorkommen)."""
    z = {}; out = []
    for d in L:
        b = (d['txt'], d['id'], d['size']); z[b] = z.get(b, 0) + 1; out.append(b + (z[b],))
    return out


_LO = {}


def _lo(unit):
    if not _LO:
        for l in open(PC.resolve_path('units_tsv', _CFG), encoding='utf-8'):
            q = l.rstrip('\n').split('\t')
            if len(q) >= 3:
                _LO[q[1]] = q[2]
    return _LO[unit]


def _mess(unit, fkt, obj):
    """Distance of the function using the exact judge (03_richter/fstand.py)."""
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLKIT_ROOT, '03_richter', 'fstand.py'), obj, _lo(unit)], capture_output=True, text=True, timeout=120)
        m = re.search(r'^%s\s+\d+/\d+\s+(GLEICH|(\d+) Befehle)' % fkt[2:].upper(), r.stdout, re.M)
        if not m:
            return 9999
        return 0 if m.group(1) == 'GLEICH' else int(m.group(2))
    except Exception:
        return 9999


def funktionsfolge(src):
    """Alle Funktionsdefinitionen auf Dateiebene in Quellreihenfolge (fuer wcc386: dort gibt es keinen Namen am Symbol,
    die k-te uebersetzte Funktion ist die k-te Definition). Besser als die //@-Marken, die einzelnen Funktionen fehlen."""
    t = open(src, encoding='latin1', errors='replace').read()
    t = re.sub(r'/\*.*?\*/', ' ', t, flags=re.S); t = re.sub(r'//[^\n]*', '', t)
    t = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', t); t = re.sub(r"'(?:\\.|[^'\\\n])*'", "' '", t)
    namen = []; tiefe = 0; start = 0
    for i, c in enumerate(t):
        if c == '{':
            if tiefe == 0:
                kopf = t[start:i]
                m = re.search(r'\b([A-Za-z_]\w*)\s*\((?:[^()]|\([^()]*\))*\)\s*$', kopf)
                if m and '=' not in kopf and not re.search(r'\b(struct|union|enum|class)\b[^()]*$', kopf) and m.group(1) not in ('if', 'while', 'for', 'switch'):
                    namen.append(m.group(1).lower())
            tiefe += 1
        elif c == '}':
            tiefe = max(0, tiefe - 1)
            if tiefe == 0:
                start = i + 1
        elif c == ';' and tiefe == 0:
            start = i + 1
    return namen


def _spur(e, cc, src):
    return adr106.ProcTrack(e, cc, funktionsfolge(src) if cc == 'wcc386' else adr106.quellfunktionen(src))


# ---------------------------------------------------------------- Stapel
def stapel_lauf(src, unit, fkt, soll=None):
    """soll: Liste von Schluesseln = erzwungene Folge der sortierten Namensliste. Rueckgabe (rest, roh, sortiert)."""
    cc = adr106.compiler_aus_quelle(src); A = adr106.fuer(cc)
    st = {'vor': None, 'nach': None}

    def hook(e):
        track = _spur(e, cc, src)

        def hv(uc, a, s, _):
            if st['vor'] is None and fkt in track.name():
                st['vor'] = _kette(e, e.r(X.UC_X86_REG_EAX), _name)

        def hn(uc, a, s, _):
            if st['nach'] is not None or fkt not in track.name():
                return
            L = _kette(e, e.r(X.UC_X86_REG_EAX), _name)
            st['nach'] = L
            if soll:
                m = dict(zip(_schluessel(L), L))
                N = [m[k] for k in soll if k in m]
                if len(N) == len(L):
                    for i, d in enumerate(N):
                        uc.mem_write(d['p'] + O['conf_next'], struct.pack('<I', N[i + 1]['p'] if i + 1 < len(N) else 0))
                    e.w(X.UC_X86_REG_EAX, N[0]['p'])
                else:
                    st['fehler'] = 'Soll-Folge passt nicht zur Liste'
        e.uc.hook_add(U.UC_HOOK_CODE, hv, begin=BASE + A['TempAllocVorliste'], end=BASE + A['TempAllocVorliste'])
        e.uc.hook_add(U.UC_HOOK_CODE, hn, begin=BASE + A['TempAllocNach'], end=BASE + A['TempAllocNach'])
    obj = os.path.join(C.TMP, 'orakel_%d.obj' % os.getpid())
    ok, out, e = comp(src, obj, hook=hook)
    if not ok:
        return 9999, [], []
    if st.get('fehler'):
        return 9998, st['vor'] or [], st['nach'] or []
    return _mess(unit, fkt, obj), st['vor'] or [], st['nach'] or []


def _sjob(a):
    src, unit, fkt, soll = a
    return stapel_lauf(src, unit, fkt, soll)[0]


SKEY = lambda d: (0 if d['fd'] else 1, d['size'])
SBEF = lambda a, b: SKEY(a) < SKEY(b)


def _gruppen(L):
    g = {}
    for i, d in enumerate(L):
        g.setdefault(SKEY(d), []).append(i)
    return [v for v in g.values() if len(v) > 1]


def _gruppenplaetze(folge, L):
    key = dict(zip(_schluessel(L), [SKEY(d) for d in L]))
    gr = {}
    for i, k in enumerate(folge):
        gr.setdefault(key[k], []).append(i)
    return [v for v in gr.values() if len(v) > 1]


def _empfindlich(folge, L):
    """Je Name zwei Probefolgen: an den Anfang und ans Ende seiner Groessengruppe. Aendert sich der Rest, belegt der Name einen Stapelplatz."""
    out = []
    for plaetze in _gruppenplaetze(folge, L):
        for a in range(len(plaetze)):
            for ziel in (0, len(plaetze) - 1):
                if a == ziel:
                    continue
                teil = [folge[p] for p in plaetze]
                x = teil.pop(a); teil.insert(ziel, x)
                neu = list(folge)
                for p, k in zip(plaetze, teil):
                    neu[p] = k
                out.append((x, neu))
    return out


def _zuege(folge, L, rel):
    """Folgen aus EINEM Zug zwischen stapelrelevanten Namen derselben Groesse: zuerst Tausch zweier, dann Verschieben eines Namens."""
    gesehen = {tuple(folge)}; stufen = ([], [])
    def dazu(neu, stufe):
        if tuple(neu) not in gesehen:
            gesehen.add(tuple(neu)); stufen[stufe].append(neu)
    for plaetze in _gruppenplaetze(folge, L):
        rp = [p for p in plaetze if folge[p] in rel]
        for a in rp:
            for b in rp:
                if a < b:
                    neu = list(folge); neu[a], neu[b] = neu[b], neu[a]; dazu(neu, 0)
        for a in rp:                         # a auf den Platz von b, die relevanten dazwischen ruecken auf
            for b in rp:
                if a == b:
                    continue
                teil = [folge[p] for p in rp]
                ia, ib = rp.index(a), rp.index(b)
                x = teil.pop(ia); teil.insert(ib, x)
                neu = list(folge)
                for p, k in zip(rp, teil):
                    neu[p] = k
                dazu(neu, 1)
    return stufen[0] + stufen[1]


def stapel(src, unit, fkt, pool, maxzuege=240, runden=6):
    r0, roh, srt = stapel_lauf(src, unit, fkt)
    if r0 >= 9998 or not srt:
        print('Uebersetzung oder Hook fehlgeschlagen (Funktion %s nicht gefunden?)' % fkt); return
    cc = adr106.compiler_aus_quelle(src)
    kroh = _schluessel(roh); ksrt = _schluessel(srt)
    print('%s %s (%s): Rest %d (Richterzaehlung). Stapel-Namensliste: %d Namen.' % (unit, fkt, cc, r0, len(srt)))
    print('\nROHLISTE (Eingang der Groessensortierung; Platz = Ergebnis der Vorstufen: Nutzwert-Sortierung, Id):')
    if cc == 'wcc386':
        print('  (wcc386 kennt hier keine Quellnamen: tN mit kleiner id = Parameter und Lokale in Deklarationsfolge, grosse id = Compiler-Temporaere)')
    print('  nr  name              gr fd   id   flags')
    for i, d in enumerate(roh):
        print('  %3d %-16s %3d %2d %5d  0x%04x' % (i, d['txt'][:16], d['size'], d['fd'], d['id'], d['fl']))
    sim = shell_sort(list(range(len(roh))), lambda a, b: SBEF(roh[a], roh[b]))
    modell_ok = [kroh[i] for i in sim] == ksrt
    print('\nSORTIERT (hoechste Adresse zuerst vergeben): ' + ' '.join('%s/%d' % (d['txt'], d['size']) for d in srt))
    print('Modellprobe Shell-Sort (FD zuerst, Groesse aufsteigend): %s' % ('stimmt' if modell_ok else 'STIMMT NICHT - Rechnung unten nur als Hinweis'))
    if r0 == 0:
        print('Rest 0 - nichts zu tun.'); return
    # --- Empfindlichkeit: welche Namen belegen ueberhaupt einen Stapelplatz?
    E = _empfindlich(list(ksrt), srt)
    RE = pool.map(_sjob, [(src, unit, fkt, z) for _, z in E])
    rel = {x for (x, _), r in zip(E, RE) if r < 9998 and r != r0}
    print('\nSTAPELRELEVANT (Probe: Name an Anfang/Ende seiner Groessengruppe, %d Messungen): %d Namen' % (len(E), len(rel)))
    print('  ' + ' '.join('%s/%d(id %d)' % (k[0], k[2], k[1]) for k in ksrt if k in rel))
    if not rel:
        print('  Kein Name reagiert. KEIN Stapelfall in den Groessengruppen (Rahmen, Register oder Form pruefen).'); return
    # --- Zwang
    folge = list(ksrt); best = r0; verlauf = []
    j0 = min(range(len(E)), key=lambda i: RE[i])
    if RE[j0] < best:
        best, folge = RE[j0], E[j0][1]; verlauf.append((0, len(E), best))
    for runde in range(runden):
        if best == 0:
            break
        Z = _zuege(folge, srt, rel)[:maxzuege]
        if not Z:
            break
        gemessen = 0; fund = None
        for s in range(0, len(Z), 24):
            teil = Z[s:s + 24]
            R = pool.map(_sjob, [(src, unit, fkt, z) for z in teil]); gemessen += len(teil)
            j = min(range(len(teil)), key=lambda i: R[i])
            if R[j] < best:
                fund = (R[j], teil[j]); break
        verlauf.append((runde + 1, gemessen, fund[0] if fund else best))
        if not fund:
            break
        best, folge = fund
    print('\nZWANG (Namen nur innerhalb gleicher Groesse umgestellt, im Emulator erzwungen):')
    for r, n, b in verlauf:
        print('  %s: %d Folgen gemessen, beste %d' % ('Probe' if r == 0 else 'Runde %d' % r, n, b))
    if best >= r0:
        print('  Keine Umstellung senkt den Rest. Dann ist es KEIN reiner Stapelfall (Rahmen, Register oder Form pruefen).'); return
    d = dict(zip(ksrt, srt))
    print('  Rest %d -> %d mit der Soll-Folge:' % (r0, best))
    print('    ist  (nur relevante): ' + ' '.join('%s/%d' % (k[0], k[2]) for k in ksrt if k in rel))
    print('    soll (nur relevante): ' + ' '.join('%s/%d' % (k[0], k[2]) for k in folge if k in rel))
    anders = [(i, ksrt[i][0], folge[i][0]) for i in range(len(folge)) if ksrt[i] != folge[i]]
    print('    geaenderte Plaetze: ' + ', '.join('Platz %d %s->%s' % a for a in anders))
    if best:
        print('  Rest bleibt %d: der uebrige Rest liegt nicht an der Stapelfolge dieser Groessengruppen.' % best)
    # --- Rechnung
    if not modell_ok:
        return
    n = len(roh)
    wichtig = set(rel)
    def modell(liste):
        return [x['k'] for x in shell_sort(liste, SBEF) if x.get('k')]
    basis = [dict(k=kroh[i], fd=roh[i]['fd'], size=roh[i]['size']) for i in range(n)]
    zielw = [k for k in folge if k in wichtig]
    kand = {}
    def pruefe(m, art, text, fehlt=None):
        if fehlt is not None:                     # entfernter Name bleibt real in der Liste: ans Ende seiner Gruppe
            g = [i for i, k in enumerate(m) if (k[2], ) == (fehlt[2], )]
            m = m[:(g[-1] + 1 if g else len(m))] + [fehlt] + m[(g[-1] + 1 if g else len(m)):]
            if [k for k in m if k in wichtig and k != fehlt] != [k for k in zielw if k != fehlt]:
                return
        elif [k for k in m if k in wichtig] != zielw:
            return
        kand.setdefault(tuple(m), []).append((art, text))
    for i in range(n):
        pruefe(modell(basis[:i] + basis[i + 1:]), 'WEG', 'Name %s (Rohplatz %d, Groesse %d) steht nicht mehr in der Stapelliste' % (kroh[i][0], i, roh[i]['size']), fehlt=kroh[i])
    for fd, size in ((0, 4), (0, 2), (0, 1), (1, 4)):
        for p in range(n + 1):
            pruefe(modell(basis[:p] + [dict(k=None, fd=fd, size=size)] + basis[p:]), 'DAZU', 'ein zusaetzlicher Name Groesse %d%s an Rohplatz %d (vor %s)' % (size, ' USED_AS_FD' if fd else '', p, kroh[p][0] if p < n else 'Listenende'))
    for i in range(n):
        rest = basis[:i] + basis[i + 1:]
        for j in range(n):
            if j != i:
                pruefe(modell(rest[:j] + [basis[i]] + rest[j:]), 'SCHIEBEN', '%s von Rohplatz %d nach %d' % (kroh[i][0], i, j))
    K = list(kand.items())[:80]
    print('\nRECHNUNG: Einzelaenderungen der Rohliste, deren Modellfolge die Soll-Folge der wichtigen Namen trifft: %d verschiedene Folgen%s.' % (len(kand), ' (erste 80 gemessen)' if len(kand) > 80 else ''))
    print('  Soll-Folge der stapelrelevanten Namen: ' + ' '.join(k[0] for k in zielw))
    erg = []
    if K:
        R = pool.map(_sjob, [(src, unit, fkt, list(m)) for m, _ in K])
        erg = sorted(zip(R, K), key=lambda x: x[0])
        bester = erg[0][0]
        print('  Jede Folge erzwungen und gemessen. Bester Rest %d; Zuege mit diesem Rest je Art:' % bester)
        je = {}
        for r, (m, zs) in erg:
            if r == bester:
                for art, text in zs:
                    je.setdefault(art, []).append(text)
        for art in ('WEG', 'DAZU', 'SCHIEBEN'):
            if art in je:
                print('  %-8s %d Zuege, z. B.:' % (art, len(je[art])))
                for text in je[art][:6]:
                    print('             %s' % text)
        schlechter = sorted({r for r, _ in erg if r != bester})
        if schlechter:
            print('  (weitere gemessene Folgen mit Rest %s)' % ', '.join(map(str, schlechter[:8])))
        if erg[0][0] > best:
            print('  Keine Einzelaenderung erreicht den Zwangswert %d - dann sind zwei Aenderungen noetig oder Temporaere entscheiden mit.' % best)
    else:
        print('  Kein Einzelzug trifft die Soll-Folge der stapelrelevanten Namen.')
    if not K or erg[0][0] > best:
        # --- zwei Aenderungen (nur Modell, Zeitgrenze), Treffer danach erzwingen und messen
        import time
        t0 = time.time(); grenze = 150
        ein = [(kroh[i], (0 if roh[i]['fd'] else 1, roh[i]['size'])) for i in range(n)]
        def msort(l):
            return [k for k, _ in shell_sort(l, lambda a, b: a[1] < b[1]) if k]
        def zuege(l):
            m = len(l)
            for i in range(m):
                if l[i][0] in rel:
                    r_ = l[:i] + l[i + 1:]
                    for j in range(m):
                        if j != i:
                            yield ('SCHIEBEN %s Rohplatz %d->%d' % (l[i][0][0], i, j), r_[:j] + [l[i]] + r_[j:])
            for q in range(m + 1):
                yield ('DAZU 4-Byte-Name an Rohplatz %d' % q, l[:q] + [(None, (1, 4))] + l[q:])
            for i in range(m):
                if l[i][0] and l[i][0] not in rel:
                    yield ('WEG %s (Rohplatz %d)' % (l[i][0][0], i), l[:i] + l[i + 1:])
        paare = {}; geprueft = 0; voll = True
        for t1, l1 in zuege(ein):
            if time.time() - t0 > grenze or len(paare) >= 60:
                voll = False; break
            for t2, l2 in zuege(l1):
                geprueft += 1
                m = msort(l2)
                if [k for k in m if k in rel] == zielw:
                    fehl = [k for k in ksrt if k not in m]          # entfernte Namen real wieder anhaengen (hinter ihre Gruppe)
                    for k in fehl:
                        g = [i for i, x in enumerate(m) if x[2] == k[2]]
                        m = m[:(g[-1] + 1 if g else len(m))] + [k] + m[(g[-1] + 1 if g else len(m)):]
                    paare.setdefault(tuple(m), []).append(t1 + '  UND  ' + t2)
        print('  ZWEI Aenderungen (Modell, %d Paare gerechnet%s): %d verschiedene Folgen treffen die Soll-Folge.' % (geprueft, '' if voll else ', Zeit- oder Mengenbegrenzung erreicht', len(paare)))
        if paare:
            P2 = list(paare.items())[:60]
            R2 = pool.map(_sjob, [(src, unit, fkt, list(m)) for m, _ in P2])
            for r, (m, texte) in sorted(zip(R2, P2), key=lambda x: x[0])[:15]:
                print('  %4d  %s%s' % (r, texte[0], ' (+%d gleichwertige)' % (len(texte) - 1) if len(texte) > 1 else ''))
    print('\nQUELLHEBEL zu den Zugarten:')
    print('  WEG      Wert ins Register bringen oder Temp vermeiden (Ausdruck direkt ins Argument, kein benanntes Zwischenlager), Namen verschmelzen.')
    print('  DAZU     zusaetzlicher Stapelname: (void)&x an einem Lokal, benannte Kopie, eigenes Block-Lokal. Sein Rohplatz folgt aus Nutzwert und Id.')
    print('  SCHIEBEN Rohplatz = Vorstufe: Nutzwert (Referenzen, codefreier Umlauf { T t = x; x = t; } hebt ihn) und bei Gleichstand Id = Deklarationsfolge.')
    print('  Kette der Vorstufen nachrechnen: wcc386 patch/work/worker/kette.py, wpp386 wave/worker/werkzeug/savmodel4.py.')


# ---------------------------------------------------------------- Register
def _conf(e, p):
    d = _name(e, e.u32(p + O['conf_name'])); d['p'] = p; d['savings'] = e.u32(p + O['conf_savings']); return d


def reg_lauf(src, unit, fkt, ordner=None):
    """ordner(L) -> neue Folge der sortierten Konfliktliste (erster Vergabedurchgang der Funktion)."""
    cc = adr106.compiler_aus_quelle(src); A = adr106.fuer(cc)
    st = {'vor': None, 'nach': None}

    def hook(e):
        track = _spur(e, cc, src)

        def hv(uc, a, s, _):
            if st['vor'] is None and fkt in track.name():
                st['vor'] = _kette(e, e.r(X.UC_X86_REG_EAX), _conf)

        def hn(uc, a, s, _):
            if st['nach'] is not None or fkt not in track.name():
                return
            L = _kette(e, e.r(X.UC_X86_REG_EAX), _conf)
            st['nach'] = L
            if ordner:
                N = ordner(L)
                if N and len(N) == len(L):
                    for i, d in enumerate(N):
                        uc.mem_write(d['p'] + O['conf_next'], struct.pack('<I', N[i + 1]['p'] if i + 1 < len(N) else 0))
                    e.w(X.UC_X86_REG_EAX, N[0]['p'])
        e.uc.hook_add(U.UC_HOOK_CODE, hv, begin=BASE + A['SortConflictsVor'], end=BASE + A['SortConflictsVor'])
        e.uc.hook_add(U.UC_HOOK_CODE, hn, begin=BASE + A['SortConflictsNach'], end=BASE + A['SortConflictsNach'])
    obj = os.path.join(C.TMP, 'orakel_%d.obj' % os.getpid())
    ok, out, e = comp(src, obj, hook=hook)
    if not ok:
        return 9999, [], []
    return _mess(unit, fkt, obj), st['vor'] or [], st['nach'] or []


RBEF = lambda a, b: (a['savings'] & 0xffffffff) > (b['savings'] & 0xffffffff)
_RG = {}


def _rjob(a):
    art, i, s = a
    src, unit, fkt, kroh, roh = _RG['src'], _RG['unit'], _RG['fkt'], _RG['kroh'], _RG['roh']
    basis = [dict(k=kroh[j], savings=roh[j]['savings']) for j in range(len(roh))]
    weg = None
    if art == 'weg':
        weg = basis[i]; liste = basis[:i] + basis[i + 1:]
    elif art == 'dazu':
        liste = basis[:i] + [dict(k=None, savings=s)] + basis[i:]
    else:
        liste = [dict(x) for x in basis]; liste[i]['savings'] = max(0, liste[i]['savings'] + s)
    ziel = [x['k'] for x in shell_sort(liste, RBEF) if x['k']]

    def ordner(L):
        m = dict(zip(_schluessel(L), L))
        try:
            N = [m[k] for k in ziel]
        except KeyError:
            return None
        if weg is not None and weg['k'] in m:
            x = m[weg['k']]
            idx = max([j for j, y in enumerate(N) if y['savings'] == x['savings']] or [len(N) - 1])
            N.insert(idx + 1, x)
        return N
    try:
        return a, reg_lauf(src, unit, fkt, ordner)[0]
    except Exception as ex:
        return a, 9999


def register(src, unit, fkt, pool_n, voll=False):
    r0, roh, srt = reg_lauf(src, unit, fkt)
    if r0 >= 9998 or not roh:
        print('Uebersetzung oder Hook fehlgeschlagen (Funktion %s nicht gefunden?)' % fkt); return
    cc = adr106.compiler_aus_quelle(src)
    kroh = _schluessel(roh); ksrt = _schluessel(srt)
    print('%s %s (%s): Rest %d (Richterzaehlung). Konfliktliste (1. Vergabedurchgang): %d Knoten.' % (unit, fkt, cc, r0, len(roh)))
    sim = shell_sort(list(range(len(roh))), lambda a, b: RBEF(roh[a], roh[b]))
    ok = [kroh[i] for i in sim] == ksrt
    print('Modellprobe Shell-Sort nach Nutzwert: %s' % ('stimmt' if ok else 'STIMMT NICHT'))
    print('\nROHLISTE (vor der Sortierung):')
    for i, d in enumerate(roh):
        print('  %3d %-16s gr %d  Nutzwert %5d  id %d' % (i, d['txt'][:16], d['size'], d['savings'], d['id']))
    if r0 == 0:
        print('Rest 0 - nichts zu tun.'); return
    n = len(roh)
    jobs = [('weg', i, 0) for i in range(n)] + [('nutz', i, s) for i in range(n) for s in (1, -1)]
    if voll:
        jobs += [('nutz', i, s) for i in range(n) for s in (2, -2)] + [('dazu', p, s) for s in (0, 2, 3) for p in range(n + 1)]
    _RG.update(src=src, unit=unit, fkt=fkt, kroh=kroh, roh=roh)
    print('\nMesse %d Einzelaenderungen (vorhergesagte Folge erzwungen) ...' % len(jobs)); sys.stdout.flush()
    with mp.get_context('fork').Pool(pool_n, maxtasksperchild=40) as P:
        res = P.map(_rjob, jobs)
    res = [r for r in res if r[1] < 9998]; res.sort(key=lambda r: r[1])
    print('ERGEBNIS (beste zuerst; Basis %d):' % r0)
    for (art, i, s), r in res[:25]:
        if r >= r0 and res[0][1] < r0:
            break
        if art == 'weg':
            t = 'Knoten %d %s (Nutzwert %d) entfaellt' % (i, kroh[i][0], roh[i]['savings'])
        elif art == 'nutz':
            t = 'Knoten %d %s Nutzwert %d -> %d' % (i, kroh[i][0], roh[i]['savings'], roh[i]['savings'] + s)
        else:
            t = 'zusaetzlicher Knoten mit Nutzwert %d an Rohplatz %d (vor %s)' % (s, i, kroh[i][0] if i < n else 'Listenende')
        print('  %4d  %s' % (r, t))
    if res and res[0][1] >= r0:
        print('  Keine Einzelaenderung senkt den Rest (Paare noetig oder kein Listen-Gleichstand: zwang.py / regforce pruefen).')
    print('\nQUELLHEBEL: Nutzwert +2 je codefreiem Umlauf { T t = x; x = t; }, +1 je toter Lesung; Knoten weg = Wert direkt im Ausdruck;'
          '\n  zusaetzlicher Knoten = benannte Kopie/Halter (Nutzwert 1: j ^ j, worker); Rohplatz = erster Gebrauch im Code.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('einheit'); ap.add_argument('fkt'); ap.add_argument('quelle', nargs='?')
    ap.add_argument('--stapel', action='store_true'); ap.add_argument('--register', action='store_true')
    ap.add_argument('--procs', type=int, default=2); ap.add_argument('--voll', action='store_true')
    a = ap.parse_args()
    # 06.11. Claude: hoechstens ORAKEL_SLOTS (Standard 3) Orakel gleichzeitig auf dem Rechner, sonst warten (Fenster rechnen sonst alle parallel).
    import fcntl, time as _t
    _n = int(os.environ.get('ORAKEL_SLOTS', '3')); _slot = None; _gemeldet = False
    while _slot is None:
        for _i in range(_n):
            _fd = open('/tmp/orakel_slot_%d.lock' % _i, 'w')
            try:
                fcntl.flock(_fd, fcntl.LOCK_EX | fcntl.LOCK_NB); _slot = _fd; break
            except OSError:
                _fd.close()
        if _slot is None:
            if not _gemeldet: print('Orakel: alle %d Plaetze belegt, warte ...' % _n, flush=True); _gemeldet = True
            _t.sleep(10)
    fkt = a.fkt.lower() if a.fkt.lower().startswith('f_') else 'f_' + a.fkt.lower()
    src = a.quelle or os.path.join(PC.resolve_path('src_p3_dir', _CFG), a.einheit + '_P1.CPP')
    if not os.path.exists(src):
        sys.exit('Quelle fehlt: ' + src)
    if a.register:
        register(src, a.einheit, fkt, a.procs, a.voll)
    else:
        with mp.get_context('fork').Pool(a.procs, maxtasksperchild=40) as pool:
            stapel(src, a.einheit, fkt, pool)
