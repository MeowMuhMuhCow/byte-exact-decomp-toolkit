#!/usr/bin/env python3
"""Krückenerkennung für worker.

Findet in einer p3-Quelle die Formen, die der Auftrag entfernen will, und
schreibt jede einzeln in die natürliche Form zurück. Kommentare und
Zeichenketten werden vorher durch Leerzeichen gleicher Länge ersetzt, damit
die Fundstellen auf den Originaltext zeigen.
"""
import re

SCHLUESSEL = {
    'if', 'for', 'while', 'switch', 'catch', 'return', 'sizeof', 'defined',
    'else', 'do', 'case', 'break', 'continue', 'goto', 'new', 'delete',
    'operator', 'this',
}
TYPWORTE = {
    'const', 'volatile', 'signed', 'unsigned', 'static', 'register', 'long',
    'short', 'int', 'char', 'bool', 'float', 'double', 'struct', 'class',
    'auto', 'extern', 'inline', 'void', 'enum', 'union', 'typedef',
}
EINFACH = r'[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*){0,3}'


class Kruecke:
    def __init__(self, kind, fkt, spans, text, global_wirkung):
        self.kind = kind
        self.fkt = fkt
        self.spans = tuple(spans)
        self.text = ' '.join(text.split())[:140]
        self.global_wirkung = bool(global_wirkung)

    def key(self):
        return (self.kind, self.fkt, self.spans)


def maske(text):
    """Kommentare und Zeichenketteninhalte durch Leerzeichen ersetzen."""
    zeichen = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ''
        if c == '/' and nxt == '/':
            j = text.find('\n', i)
            if j < 0:
                j = n
            for k in range(i, j):
                zeichen[k] = ' '
            i = j
            continue
        if c == '/' and nxt == '*':
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if text[k] != '\n':
                    zeichen[k] = ' '
            i = j
            continue
        if c in ('"', "'"):
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == '\\':
                    j += 2
                else:
                    j += 1
            j = min(n, j + 1)
            for k in range(i + 1, j - 1):
                if text[k] != '\n':
                    zeichen[k] = ' '
            i = j
            continue
        i += 1
    return ''.join(zeichen)


def klammer_zu(text, i, auf, zu):
    tiefe = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == auf:
            tiefe += 1
        elif c == zu:
            tiefe -= 1
            if tiefe == 0:
                return i + 1
        i += 1
    return -1


def funktionen(masked):
    """Alle Funktionskörper: Name, Anfang der geschweiften Klammer, Ende."""
    out = []
    i, n = 0, len(masked)
    while i < n:
        m = re.search(r'\b([A-Za-z_]\w*)\s*\(', masked[i:])
        if not m:
            break
        name = m.group(1)
        abs_par = i + m.end() - 1
        if name in SCHLUESSEL or masked[abs_par] != '(':
            i += m.end()
            continue
        ende_par = klammer_zu(masked, abs_par, '(', ')')
        if ende_par < 0:
            break
        j = ende_par
        while j < n and masked[j] in ' \t\r\n':
            j += 1
        if j < n and masked[j] == '{':
            ende = klammer_zu(masked, j, '{', '}')
            if ende > 0:
                out.append((name, j, ende))
                i = ende
                continue
        i += m.end()
    return out


def marker(text):
    return [(m.start(), m.group(1)) for m in re.finditer(r'(?m)^//@\s*(f_[0-9A-Fa-f]+)\b', text)]


def besitzer(pos, marks, koerper):
    for name, a, b in koerper:
        if a <= pos < b:
            return name
    vorher = ''
    for start, name in marks:
        if start <= pos:
            vorher = name
        else:
            break
    return vorher


def dateinamen(text, koerper):
    namen = set(re.findall(r'\b(d_[0-9A-Fa-f]{3,})\b', text))
    teil = []
    pos = 0
    for _name, a, b in koerper:
        teil.append(text[pos:a])
        pos = b
    teil.append(text[pos:])
    scope = '\n'.join(teil)
    for m in re.finditer(r'#pragma\s+aux\s+([A-Za-z_]\w*)', scope):
        namen.add(m.group(1))
    for zeile in scope.splitlines():
        if not re.search(r'\b(int|char|short|long|struct|unsigned|signed|extern|static|volatile|const|bool|float|double)\b', zeile):
            continue
        if '(' in zeile and 'extern' not in zeile:
            continue
        for wort in re.findall(r'\b([A-Za-z_]\w*)\b', zeile):
            if wort not in TYPWORTE and wort not in SCHLUESSEL:
                namen.add(wort)
    return namen


def im_koerper(pos, koerper):
    for name, a, b in koerper:
        if a <= pos < b:
            return name
    return ''


def global_volatile(text, pos, koerper, globale):
    """volatile wirkt symbolweit. Auf eine Globale bezogen, oder außerhalb jedes Körpers."""
    if not im_koerper(pos, koerper):
        return True
    fenster = text[pos:pos + 160]
    ziel = None
    m = re.search(r'&\s*([A-Za-z_]\w*)', fenster)
    if m:
        ziel = m.group(1)
    else:
        m = re.search(r'\)\s*\*?\s*([A-Za-z_]\w*)', fenster)
        if m:
            ziel = m.group(1)
    return bool(ziel and (ziel in globale or ziel.startswith('d_')))


def anweisung_bis(text, start, ende, ersatz):
    """Wenn der Ersatz die Anweisung zur Selbstzuweisung macht, die ganze Anweisung nehmen."""
    j = start
    while j > 0 and text[j - 1] in ' \t':
        j -= 1
    lhs = None
    lhs_s = start
    if j > 0 and text[j - 1] == '=':
        j -= 1
        while j > 0 and text[j - 1] in ' \t':
            j -= 1
        k = j
        while k > 0 and (text[k - 1].isalnum() or text[k - 1] in '_.'):
            k -= 1
        lhs = text[k:j]
        lhs_s = k
    semi = text.find(';', ende)
    if semi < 0 or semi - ende > 40:
        return start, ende, ersatz
    if lhs is not None and lhs.replace(' ', '') == ersatz.replace(' ', ''):
        return lhs_s, semi + 1, ''
    return start, ende, ersatz


def zeilenspanne(text, s, e):
    if not text[s:e].strip() and e == s:
        return s, e
    return s, e


def fund(text, masked, kind, fkt, s, e, repl, globale_wirkung, sammeln):
    if s < 0 or e <= s or e > len(text):
        return
    zeile = text.rfind('\n', 0, s) + 1
    kopf = text[zeile:text.find('\n', zeile)]
    if kopf.lstrip().startswith('//@'):
        return
    alt = text[s:e]
    if not alt.strip():
        return
    if '\n' in alt and kind not in ('roundtrip', 'kommentar'):
        # Mehrzeilige Treffer nur, wo die Spanne absichtlich eine Anweisung ist.
        if alt.count('\n') > 2:
            return
    sammeln.append(Kruecke(kind, fkt, ((s, e, repl),), alt, globale_wirkung))


def _einfach_gleich(stueck):
    return re.fullmatch(EINFACH, stueck.strip()) is not None


def suche_muster(text, masked, marks, koerper, globale, sammeln):
    def fkt_bei(pos):
        name = im_koerper(pos, koerper)
        if name:
            return name
        return besitzer(pos, marks, koerper)

    # volatile-Wort, eines je Vorkommen.
    for m in re.finditer(r'\bvolatile\b', masked):
        s, e = m.start(), m.end()
        if e < len(masked) and masked[e] == ' ':
            e += 1
        elif s > 0 and masked[s - 1] == ' ':
            s -= 1
        fund(text, masked, 'volatile', fkt_bei(m.start()), s, e, '',
             global_volatile(text, m.start(), koerper, globale), sammeln)

    # *(T *)&lokal  ->  (T)lokal    und    -> lokal
    addr = re.compile(
        r'\*\s*\(\s*((?:const\s+|volatile\s+|signed\s+|unsigned\s+|long\s+|short\s+)*)'
        r'(char|short|int|long)\s*\*\s*\)\s*&\s*([A-Za-z_]\w*)',
        re.I)
    for m in addr.finditer(masked):
        name = m.group(3)
        if name in globale or name.startswith('d_') or name in SCHLUESSEL:
            continue
        if not im_koerper(m.start(), koerper):
            continue
        typ = (m.group(1) + m.group(2)).replace('volatile', ' ')
        typ = re.sub(r'\s+', ' ', typ).strip()
        fkt = fkt_bei(m.start())
        # (T)name ist ein rvalue. Steht der Cast links von =, wird daraus kein C.
        # Die Form -> name bleibt und deckt die Zuweisung ab.
        if not re.match(r'\s*=(?!=)', masked[m.end():m.end() + 12]):
            fund(text, masked, 'addr_cast', fkt, m.start(), m.end(), f'({typ}){name}', False, sammeln)
        fund(text, masked, 'addr_direkt', fkt, m.start(), m.end(), name, False, sammeln)

    # *(volatile T *)&name  ->  name. Nur die Adressform, nicht *(volatile T *)zeiger.
    volname = re.compile(
        r'\*\s*\(\s*volatile\s+(?:const\s+|signed\s+|unsigned\s+|long\s+|short\s+)*'
        r'(?:char|short|int|long)\s*\*\s*\)\s*&\s*([A-Za-z_]\w*)',
        re.I)
    for m in volname.finditer(masked):
        name = m.group(1)
        fund(text, masked, 'vol_name', fkt_bei(m.start()), m.start(), m.end(), name,
             name in globale or name.startswith('d_'), sammeln)

    # (E & 0) ? 0 : R  ist immer R, auch wenn E selbst ein Cast ist.
    for anfang, ende, rechts in finde_and0(masked):
        s, e, repl = anweisung_bis(text, anfang, ende, rechts)
        fund(text, masked, 'and0', fkt_bei(anfang), s, e, repl, not im_koerper(anfang, koerper), sammeln)

    # lhs |= etwas & 0;
    or0 = re.compile(
        r'(' + EINFACH + r')\s*\|=\s*\(?\s*[^;=]{0,80}?&\s*0(?![0-9A-Fa-fxX])\s*\)?\s*;')
    for m in or0.finditer(masked):
        fund(text, masked, 'or0', fkt_bei(m.start()), m.start(), m.end(), '',
             not im_koerper(m.start(), koerper), sammeln)

    # x = x | (etwas & 0);
    or0b = re.compile(
        r'(' + EINFACH + r')\s*=\s*\1\s*\|\s*\(?\s*[^;=]{0,60}?&\s*0(?![0-9A-Fa-fxX])\s*\)?\s*;')
    for m in or0b.finditer(masked):
        fund(text, masked, 'or0', fkt_bei(m.start()), m.start(), m.end(), '',
             not im_koerper(m.start(), koerper), sammeln)

    # x&x, x^x, x-x. Beide Seiten derselbe einfache Ausdruck.
    selbst = re.compile(
        r'(?<![&|^.\w])(' + EINFACH + r')\s*([&|^-])\s*\1(?![\w])')
    for m in selbst.finditer(masked):
        op = m.group(2)
        nach = m.end(2)
        while nach < len(masked) and masked[nach] in ' \t':
            nach += 1
        if nach < len(masked) and masked[nach] in '=&|':
            continue
        if op == '&' and nach < len(masked) and masked[nach] == '&':
            continue
        kind = {'&': 'und_selbst', '^': 'xor_selbst', '-': 'sub_selbst'}[op]
        repl = m.group(1).strip() if op == '&' else '0'
        s, e, repl = anweisung_bis(text, m.start(), m.end(), repl)
        fund(text, masked, kind, fkt_bei(m.start()), s, e, repl,
             not im_koerper(m.start(), koerper), sammeln)

    # & 0xffff und & 0xff, nicht als Vorsilbe einer längeren Hexzahl.
    maske_re = re.compile(
        r'(?<![&])(' + EINFACH + r'|\([^;()]{1,80}\))\s*&\s*0x(ffff|ff)(?![0-9A-Fa-f_])',
        re.I)
    for m in maske_re.finditer(masked):
        breite = m.group(2).lower()
        kind = 'maske16' if breite == 'ffff' else 'maske8'
        fund(text, masked, kind, fkt_bei(m.start()), m.start(), m.end(), m.group(1).strip(),
             not im_koerper(m.start(), koerper), sammeln)

    # (void)&name;  und  (void)&a.b;
    void_re = re.compile(r'\(\s*void\s*\)\s*&\s*' + EINFACH + r'\s*;')
    for m in void_re.finditer(masked):
        fund(text, masked, 'void_addr', fkt_bei(m.start()), m.start(), m.end(), '',
             not im_koerper(m.start(), koerper), sammeln)

    # x = x;
    selbstzu = re.compile(r'(?<![\w.])(' + EINFACH + r')\s*=\s*\1\s*;')
    for m in selbstzu.finditer(masked):
        fund(text, masked, 'selbst', fkt_bei(m.start()), m.start(), m.end(), '',
             not im_koerper(m.start(), koerper), sammeln)

    # T name = expr; ... expr = name;   name sonst unbenutzt.
    defin = re.compile(
        r'\b((?:const|volatile|signed|unsigned|static|register|long|short|int|char|bool|'
        r'float|double|struct|class|auto)(?:\s+[A-Za-z_]\w*)*)\s+(\**)\s*([A-Za-z_]\w*)\s*=\s*([^;]+?)\s*;')
    for m in defin.finditer(masked):
        name, ausdruck = m.group(3), m.group(4).strip()
        if not re.fullmatch(EINFACH, ausdruck):
            continue
        if name in TYPWORTE or name in SCHLUESSEL:
            continue
        fkt = fkt_bei(m.start())
        bereich = None
        for fname, a, b in koerper:
            if a <= m.start() < b:
                bereich = (a, b)
                break
        if bereich is None:
            continue
        ko = masked[bereich[0]:bereich[1]]
        if len(re.findall(r'\b' + re.escape(name) + r'\b', ko)) != 2:
            continue
        rueck = re.compile(re.escape(ausdruck) + r'\s*=\s*' + re.escape(name) + r'\s*;')
        m2 = rueck.search(masked, m.end(), bereich[1])
        if not m2:
            continue
        # Nur die beiden Anweisungen. Code dazwischen bleibt, sonst verschwinden echte Zeilen.
        zwischen = masked[m.end():m2.start()]
        if zwischen.strip() == '':
            s, e = umgebende_klammer(masked, m.start(), m2.end())
            spannen = ((s, e, ''),)
            anzeige = text[s:e]
        else:
            spannen = ((m.start(), m.end(), ''), (m2.start(), m2.end(), ''))
            anzeige = text[m.start():m.end()] + ' … ' + text[m2.start():m2.end()]
        sammeln.append(Kruecke('roundtrip', fkt, spannen, anzeige, False))


def finde_and0(masked):
    """Spannen von `(E & 0) ? 0 : R` und `E & 0 ? 0 : R`. Ergebnis ist immer R."""
    treffer = []
    for m in re.finditer(r'&\s*0(?![0-9A-Fa-fxX])', masked):
        r = m.end()
        while r < len(masked) and masked[r] in ' \t':
            r += 1
        anfang = None
        if r < len(masked) and masked[r] == ')':
            tiefe = 0
            k = r
            while k >= 0:
                if masked[k] == ')':
                    tiefe += 1
                elif masked[k] == '(':
                    tiefe -= 1
                    if tiefe == 0:
                        anfang = k
                        break
                k -= 1
            r += 1
            while r < len(masked) and masked[r] in ' \t':
                r += 1
        else:
            links = re.search(r'(' + EINFACH + r')\s*$', masked[:m.start()])
            if not links:
                continue
            anfang = links.start(1)
        if anfang is None or r >= len(masked) or masked[r] != '?':
            continue
        r += 1
        while r < len(masked) and masked[r] in ' \t':
            r += 1
        if r >= len(masked) or masked[r] != '0':
            continue
        if r + 1 < len(masked) and masked[r + 1] in '0123456789abcdefABCDEFxX':
            continue
        r += 1
        while r < len(masked) and masked[r] in ' \t':
            r += 1
        if r >= len(masked) or masked[r] != ':':
            continue
        r += 1
        while r < len(masked) and masked[r] in ' \t':
            r += 1
        rechts = re.match(EINFACH, masked[r:])
        if not rechts:
            continue
        treffer.append((anfang, r + rechts.end(), re.sub(r'\s+', '', rechts.group(0))))
    return treffer


def umgebende_klammer(text, a, b):
    i = a
    while i > 0 and text[i - 1] in ' \t\r\n':
        i -= 1
    j = b
    while j < len(text) and text[j] in ' \t\r\n':
        j += 1
    if i > 0 and text[i - 1] == '{' and j < len(text) and text[j] == '}':
        return i - 1, j + 1
    return a, b


def suche_kommentar(text, koerper, sammeln):
    """// KRUECKE: die Anweisung davor entfernen, wenn kein benutzter Name hängen bleibt."""
    for m in re.finditer(r'(?m)^([^\n]*?)(//\s*KRUECKE\b[^\n]*)$', text, re.I):
        code = m.group(1)
        if not code.strip():
            continue
        s = m.start(1)
        e = m.end(1)
        while e > s and text[e - 1] in ' \t':
            e -= 1
        if e <= s:
            continue
        fkt = im_koerper(s, koerper) or ''
        if not fkt:
            # Marker-Abschnitt: der nächste Körper, der die Zeile nicht enthält, bleibt leer.
            for name, a, b in koerper:
                if s < a and a - s < 4000:
                    fkt = name
                    break
        namen = []
        for wort in re.findall(
                r'\b(?:int|char|short|long|bool|float|double|struct|unsigned|signed|const|volatile|static|register|auto)\b'
                r'(?:[^;=]{0,40}?)\b([A-Za-z_]\w*)\s*=',
                code):
            if wort not in TYPWORTE and wort not in SCHLUESSEL:
                namen.append(wort)
        # Deklarationsnamen stehen vor '=' . Benutzt heißt: das Wort steht noch im Körper außerhalb der Zeile.
        benutzt = False
        if fkt and namen:
            ko = ''
            for fname, a, b in koerper:
                if fname == fkt and a <= s < b:
                    ko = text[a:s] + text[e:b]
                    break
            for wort in namen:
                if re.search(r'\b' + re.escape(wort) + r'\b', ko):
                    benutzt = True
                    break
        if benutzt:
            continue
        alt = text[s:e]
        sammeln.append(Kruecke('kommentar', fkt, ((s, e, ''),), alt, False))


def dedupe(liste):
    gesehen = set()
    out = []
    for k in liste:
        schluessel = k.key()
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        out.append(k)
    return out


def kruecken(text):
    masked = maske(text)
    koerper = funktionen(masked)
    marks = marker(text)
    globale = dateinamen(text, koerper)
    sammeln = []
    suche_muster(text, masked, marks, koerper, globale, sammeln)
    suche_kommentar(text, koerper, sammeln)
    return dedupe(sammeln), koerper


def ueberlappend(a, b):
    sa = sorted(a.spans)
    sb = sorted(b.spans)
    i = j = 0
    while i < len(sa) and j < len(sb):
        if sa[i][1] <= sb[j][0]:
            i += 1
        elif sb[j][1] <= sa[i][0]:
            j += 1
        else:
            return True
    return False


def anwenden(text, gewaehlt):
    spannen = []
    for k in gewaehlt:
        spannen.extend(k.spans)
    spannen.sort(key=lambda s: s[0], reverse=True)
    out = text
    for s, e, repl in spannen:
        out = out[:s] + repl + out[e:]
    return out


def paare(liste, grenze=8):
    """Paare der ersten `grenze` Krücken, ohne überlappende Spannen."""
    kern = liste[:grenze]
    out = []
    for i in range(len(kern)):
        for j in range(i + 1, len(kern)):
            if not ueberlappend(kern[i], kern[j]):
                out.append((kern[i], kern[j]))
    return out


def selbsttest():
    text = '''//@ f_400010
extern volatile int g_var_01;
int f_400010(int roll, int p2, int b, int scale, int w, int t, int x)
{
  int cv = *(signed char *)&roll;
  g_var_01 = (g_var_01 & 0) ? 0 : g_var_01;
  u=(u&0)?0:u;
  cursor |= b & 0;
  n = scale & scale;
  n = w ^ w;
  n = w - w;
  n = t & 0xffff;
  n = (t & 0xff);
  (void)&x;
  (void)&st.k;
  { int hold = g_var_01; g_var_01 = hold; } // KRUECKE namen
  int hold2 = g_var_01;
  int mitte = 3;
  g_var_01 = hold2;
  int low = (unsigned char)p2; // KRUECKE tot
  *(volatile int *)&g_var_01 = 1;
  int yp = ((int)roll & 0) ? 0 : roll;
}
'''
    # u und cursor und n und st sind hier ungebunden; der Finder soll die Formen trotzdem sehen.
    ks, koerper = kruecken(text)
    arten = {}
    for k in ks:
        arten.setdefault(k.kind, 0)
        arten[k.kind] += 1
    erwartet = ['volatile', 'addr_cast', 'addr_direkt', 'vol_name', 'and0', 'or0',
                'und_selbst', 'xor_selbst', 'sub_selbst', 'maske16', 'maske8',
                'void_addr', 'roundtrip', 'kommentar']
    fehlt = [a for a in erwartet if arten.get(a, 0) < 1]
    # and0 auf g_var_01 muss die ganze Zuweisung löschen.
    geloeschte = [k for k in ks if k.kind == 'and0' and k.spans[0][2] == '' and 'g_var_01' in k.text]
    # volatile auf der Datei-Globalen wirkt über die Funktion hinaus.
    vol_global = [k for k in ks if k.kind == 'volatile' and k.global_wirkung and 'extern' in text[k.spans[0][0]:k.spans[0][1] + 20]]
    fehler = []
    if fehlt:
        fehler.append('fehlt ' + ','.join(fehlt))
    if not geloeschte:
        fehler.append('and0 loescht die Selbstzuweisung nicht')
    if not any(k.global_wirkung and k.kind == 'volatile' for k in ks):
        fehler.append('kein globales volatile')
    if not koerper:
        fehler.append('kein Koerper')
    # Anwenden einer and0-Löschung darf die Zeile entfernen, ohne die Nachbarzeile zu fressen.
    if geloeschte:
        neu = anwenden(text, [geloeschte[0]])
        if 'g_var_01 = (g_var_01' in neu:
            fehler.append('and0 noch vorhanden')
        if 'u=(u&0)?0:u;' not in neu:
            fehler.append('and0 hat die Nachbarzeile mitgenommen')
    yp = [k for k in ks if k.kind == 'and0' and 'roll' in k.text and '0' in k.text]
    if not any(k.spans[0][2] == 'roll' and '((int)roll' not in anwenden(text, [k]) for k in yp):
        fehler.append('Cast-and0 wird nicht zu roll')
    uzeile = [k for k in ks if k.kind == 'and0' and 'u&0' in k.text.replace(' ', '')]
    if not uzeile or 'u=(u&0)?0:u;' in anwenden(text, [uzeile[0]]):
        fehler.append('u=(u&0)?0:u bleibt stehen')
    fern = [k for k in ks if k.kind == 'roundtrip' and 'hold2' in k.text]
    if not fern or 'int mitte = 3;' not in anwenden(text, [fern[0]]):
        fehler.append('Roundtrip frisst den Code dazwischen')
    if arten.get('kommentar', 0) < 2:
        fehler.append('KRUECKE-Zeilen %s' % arten.get('kommentar', 0))
    print('selbsttest', 'OK' if not fehler else 'FEHLER ' + '; '.join(fehler))
    print('arten', ' '.join(f'{a}:{arten[a]}' for a in sorted(arten)))
    return not fehler


if __name__ == '__main__':
    raise SystemExit(0 if selbsttest() else 1)
