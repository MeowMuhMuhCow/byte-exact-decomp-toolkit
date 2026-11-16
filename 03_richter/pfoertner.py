# pfoertner.py - Static Gatekeeper: rejects inline assembly, raw bytes, unauthorized #pragma aux clauses, and altered external prototypes.
# Usage: python3 pfoertner.py CANDIDATE.CPP [--gegen BASELINE.CPP]
import os, re, sys, shutil, time, datetime

HIER = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HIER, '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import project_config as PC
_CFG = PC.load_config()
WURZEL = PC.resolve_path('project_root', _CFG)
ERLAUBT_DATEI = PC.resolve_path('allowed_pragma_tsv', _CFG) or os.path.join(ROOT, 'meta', 'allowed_pragma.tsv')
REGEL_A = re.compile(
    r'__segname\(\s*"_TEXT"\s*\)|#pragma\s+aux\b[^\n]*"db\s|\b_emit\b|\b__asm\b|\b_asm\b')
PRAEGMA = re.compile(r'#pragma\s+aux\b')
SCHNITT = re.compile(
    r'\b(?:parm|value|modify|aborts|__parm|__value|__modify)\b', re.I)
LINK_SIG = re.compile(r'\$[a-zA-Z]*\(([^)]*)\)([a-zA-Z]+)\s*$')
MANGLED = re.compile(r'^(W\?|\?)')
DECL = re.compile(
    r'(?:^|[;{}])\s*'
    r'((?:extern|static|inline|virtual)\s+)*'
    r'((?:(?:const|volatile|unsigned|signed|struct|enum|long|short)\s+)*)'
    r'(void|int|char|short|long|float|double|signed|unsigned|[A-Za-z_]\w*)(?=\s|\*|&)'
    r'\s*((?:\*\s*|&\s*)*)'
    r'(?:[A-Za-z_]\w*::)*'
    r'([A-Za-z_]\w*)\s*'
    r'\(([^;{}]*)\)\s*'
    r'([;{])',
    re.M)
TYPWORTE = {
    'void', 'int', 'char', 'short', 'long', 'float', 'double',
    'signed', 'unsigned', 'struct', 'enum', 'const', 'volatile', 'register',
}
SELBST_XOR = re.compile(r'\b([A-Za-z_]\w*)\s*\^\s*\1\b')
OR_AND0 = re.compile(r'\b([A-Za-z_]\w*)\s*\|=\s*\1\s*&\s*0\b')
TERNARY_AND0 = re.compile(
    r'\(\s*([A-Za-z_]\w*)\s*&\s*0\s*\)\s*\?\s*0\s*:\s*\1\b')
BYTEOFFSET = re.compile(
    r'\*\s*\(\s*(?:(?:unsigned|signed|const|volatile)\s+)*(?:int|short|char|long|void)\s*\*+\s*\)'
    r'\s*\(\s*\(\s*(?:(?:const|volatile)\s+)*char\s*\*+\s*\)',
    re.I)
VOLATILE_ZEILE = re.compile(r'^.*\bvolatile\b.*$', re.M)


def lies(pfad):
    return open(pfad, encoding='latin1', errors='replace').read().replace('\r', '')


def ohne_kommentar(text):
    aus = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
            aus.append(' ')
        elif text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j
        elif text[i] in '"\'':
            q = text[i]
            j = i + 1
            while j < n and text[j] != q:
                j += 2 if text[j] == '\\' else 1
            j = min(n, j + 1)
            aus.append(text[i:j])
            i = j
        else:
            aus.append(text[i])
            i += 1
    return ''.join(aus)


def ohne_strings(text):
    return re.sub(r'"[^"]*"|\'[^\']*\'', ' ', text)


PROTO_DATEI = PC.resolve_path('allowed_prototype_tsv', _CFG) or os.path.join(ROOT, 'meta', 'allowed_prototype.tsv')


def proto_erlaubt():
    """Approved Typkorrekturen am EIGENEN Prototyp (ASM-belegt). Spalte 1: 'name alt -> neu' exakt wie in der Abweisung."""
    try:
        return {l.split('\t')[0].strip() for l in open(PROTO_DATEI, encoding='utf-8') if l.strip() and not l.startswith('#')}
    except OSError:
        return set()


NAMENTLICH_DATEI = PC.resolve_path('named_pragma_tsv', _CFG) or os.path.join(ROOT, 'meta', 'named_pragma.tsv')


def namentlich_liste(pfad=None):
    """Zeilen (einheit, funktion, pragma_name, norm_koerper). Fehlt die Datei, gibt es keine Ausnahme."""
    fund = []
    try:
        for roh in open(pfad or NAMENTLICH_DATEI, encoding='utf-8', errors='replace'):
            if not roh.strip() or roh.startswith('#') or roh.startswith(('einheit\t', 'unit\t')):
                continue
            teile = [x.strip() for x in roh.rstrip('\n').split('\t')]
            if len(teile) >= 4:
                fund.append((teile[0], teile[1], teile[2], ' '.join(teile[3].split()).lower()))
    except OSError:
        pass
    return fund


def _funktionskoerper(t, funktion):
    """(start, ende) des Koerpers der Definition von funktion auf Dateiebene im kommentarfreien Text, sonst None."""
    pos, depth = 0, 0
    for m in DECL.finditer(t):
        anfang = m.start() + (1 if m.start() < len(t) and t[m.start()] in ';{}' else 0)
        depth, pos = _tiefe_bis(t, anfang, pos, depth)
        if m.group(5) != funktion or m.group(7) != '{' or depth != 0:
            continue
        i, d = m.end(), 1
        while i < len(t) and d:
            c = t[i]
            if c == '"':
                i += 1
                while i < len(t) and t[i] != '"':
                    i += 2 if t[i] == '\\' else 1
            elif c == '{':
                d += 1
            elif c == '}':
                d -= 1
            i += 1
        return m.end(), i
    return None


def namentlich_erlaubt(text, name, koerper, einheit=None):
    """Code-Pragma name ist namentlich freigegeben, wenn Name und Koerper exakt in PRAGMA_NAMENTLICH.tsv stehen,
    die dort genannte Funktion in dieser Datei auf Dateiebene definiert ist und JEDE Verwendung des Pragma-Namens
    (ausser der eigenen Deklaration und der Pragma-Zeile) im Koerper dieser Funktion liegt. Gibt die Funktion zurueck oder None."""
    nk = norm_koerper(koerper)
    for e_einheit, funktion, pname, pkoerper in namentlich_liste():
        if pname != name or pkoerper != nk:
            continue
        if einheit is not None and e_einheit and einheit.lower() != e_einheit.lower():
            continue
        t = ohne_kommentar(text)
        span = _funktionskoerper(t, funktion)
        if span is None:
            continue
        ok = True
        for m in re.finditer(r'\b' + re.escape(name) + r'\b', t):
            if span[0] <= m.start() < span[1]:
                continue
            a = t.rfind('\n', 0, m.start()) + 1
            e = t.find('\n', m.start())
            zeile_ = t[a:e if e >= 0 else len(t)]
            if PRAEGMA.search(zeile_) or re.search(r'\b' + re.escape(name) + r'\s*\([^;{}]*\)\s*;', zeile_) and 'extern' in zeile_:
                continue
            ok = False
            break
        if ok:
            return funktion
    return None


def erlaubtliste(pfad=None):
    pfad = pfad or ERLAUBT_DATEI
    mnemonics, int_ops, bytes_ = set(), set(), set()
    for roh in open(pfad, encoding='utf-8', errors='replace'):
        zeile = roh.split('#', 1)[0].strip()
        if not zeile or zeile.startswith(('art\t', 'kind\t')):
            continue
        teile = zeile.split('\t')
        if len(teile) < 2:
            continue
        art, wert = teile[0].strip(), teile[1].strip().lower()
        if art == 'mnemonic':
            mnemonics.add(wert)
        elif art == 'int_operand':
            int_ops.add(wert)
        elif art == 'bytefolge':
            bytes_.add(re.sub(r'\s+', ' ', wert))
    return mnemonics, int_ops, bytes_


def pragma_bloecke(text):
    """Liste (erste_zeile_1basiert, text). Ein Pragma darf ueber Folgezeilen gehen, bis zum Semikolon."""
    zeilen = text.splitlines()
    i, fund = 0, []
    while i < len(zeilen):
        if PRAEGMA.search(zeilen[i]):
            start = i + 1
            buf = zeilen[i]
            while ';' not in buf and i + 1 < len(zeilen) and not PRAEGMA.search(zeilen[i + 1]):
                i += 1
                buf += ' ' + zeilen[i].strip()
            fund.append((start, buf.strip()))
        i += 1
    return fund


def zerlege_pragma(zeile):
    m = re.search(r'#pragma\s+aux\s+(\w+)\s*(.*)$', zeile.strip(), re.I)
    if not m:
        return None
    name, rest = m.group(1), m.group(2).strip().rstrip(';').strip()
    if rest.startswith('='):
        koerper = SCHNITT.split(rest[1:].strip(), maxsplit=1)[0].strip()
        return 'code', name, koerper, ''
    mq = re.match(r'"([^"]*)"(.*)$', rest)
    if mq:
        return 'alias', name, mq.group(1), mq.group(2)
    return 'plain', name, rest, ''


def code_strings(koerper):
    return re.findall(r'"([^"]*)"', koerper)


def bytefolge(koerper):
    roh = koerper.strip()
    if not roh or roh.startswith('"'):
        return None
    teile = roh.split()
    if teile and all(re.fullmatch(r'0x[0-9a-fA-F]+', t) for t in teile):
        return ' '.join(t.lower() for t in teile)
    return None


def befehle(koerper):
    """Liste (mnemonic, operand) aus den Anfuehrungsstrings. Marken fallen weg."""
    fund = []
    for s in code_strings(koerper):
        s = s.strip()
        if not s or s.endswith(':'):
            continue
        teile = s.replace(',', ' ').split()
        if not teile:
            continue
        op = teile[0].lower()
        if op.endswith(':'):
            continue
        fund.append((op, teile[1].lower() if len(teile) > 1 else ''))
    return fund


def norm_koerper(koerper):
    folge = bytefolge(koerper)
    if folge:
        return 'bytes ' + folge
    strings = [' '.join(s.split()).lower() for s in code_strings(koerper) if s.strip()]
    return 'asm ' + ' | '.join(strings)


def parse_type(s, i):
    if i >= len(s):
        return 'unknown', i
    unsigned = False
    if s[i] == 'u' and i + 1 < len(s) and s[i + 1] in 'csilfd':
        unsigned = True
        i += 1
    ch = s[i]
    i += 1
    if ch == 'p':
        if s.startswith('n$', i):
            j = s.find('$$', i)
            return 'ptr', (len(s) if j < 0 else j + 2)
        if i < len(s) and (s[i] in 'vcsilfdp' or (
                s[i] == 'u' and i + 1 < len(s) and s[i + 1] in 'csilfd')):
            _, i = parse_type(s, i)
            return 'ptr', i
        return 'ptr', i
    namen = {'v': 'void', 'c': 'char', 's': 'short', 'i': 'int',
             'l': 'long', 'f': 'float', 'd': 'double'}
    if ch not in namen:
        return 'unknown', i
    t = namen[ch]
    if unsigned:
        t = 'unsigned ' + t
    return t, i


def parse_link(link):
    m = LINK_SIG.search(link.strip())
    if not m:
        return None
    args, ret = m.group(1), m.group(2)
    params, i = [], 0
    while i < len(args):
        t, i = parse_type(args, i)
        params.append(t)
    rt, j = parse_type(ret, 0)
    if j != len(ret):
        rt = 'unknown'
    return params, rt


def norm_param(roh):
    p = roh.strip()
    if not p or p == 'void':
        return ''
    if '(' in p:
        return 'fnptr'
    p = p.split('=')[0]
    p = re.sub(r'\b(const|volatile|register)\b', ' ', p)
    p = re.sub(r'\[[^\]]*\]', '*', p)
    sterne = p.count('*') + p.count('&')
    p = p.replace('*', ' ').replace('&', ' ')
    p = re.sub(r'\s+', ' ', p).strip()
    teile = p.split()
    while len(teile) >= 2 and teile[-1] not in TYPWORTE and teile[0] != 'struct':
        teile.pop()
        break
    if teile and teile[-1] not in TYPWORTE and len(teile) >= 2 and teile[0] != 'struct':
        teile = teile[:-1]
    basis = ' '.join(teile)
    basis = re.sub(r'\b(signed|unsigned|short|long)\s+\1\b', r'\1', basis)
    if basis in ('unsigned', 'unsigned int', 'signed int', 'signed'):
        basis = 'unsigned int' if basis.startswith('unsigned') else 'int'
    if basis in ('short int',):
        basis = 'short'
    if basis in ('long int',):
        basis = 'long'
    if basis in ('signed char',):
        basis = 'char'
    if not basis and sterne:
        return 'ptr'
    if sterne:
        return (basis or 'void') + '*' * sterne
    return basis


def norm_typ(basis, sterne_roh):
    sterne = len(re.findall(r'\*', sterne_roh)) + len(re.findall(r'&', sterne_roh))
    basis = re.sub(r'\s+', ' ', (basis or '')).strip()
    if basis in ('unsigned', 'signed'):
        basis = 'unsigned int' if basis == 'unsigned' else 'int'
    if basis == 'signed int':
        basis = 'int'
    if basis == 'unsigned int':
        pass
    if sterne:
        return (basis or 'void') + '*' * sterne
    return basis


def _tiefe_bis(text, start, i0, d):
    """Klammtiefe bei start. Anführungszeichen zählen nicht."""
    i = i0
    while i < start:
        c = text[i]
        if c == '"':
            i += 1
            while i < start and text[i] != '"':
                if text[i] == '\\' and i + 1 < start:
                    i += 2
                    continue
                i += 1
            i += 1
            continue
        if c == '{':
            d += 1
        elif c == '}':
            d = max(0, d - 1)
        i += 1
    return d, start


def deklarationen(text):
    """name -> Liste (params, rueckgabe, definiert, dateiebene).
    Aufrufe von operator delete/new sind keine Prototypen.
    dateiebene: die Deklaration steht ausserhalb von Funktion und struct."""
    t = ohne_kommentar(text)
    fund = {}
    pos, depth = 0, 0
    for m in DECL.finditer(t):
        # Note: DECL beginnt am Trennzeichen (; { }). Die Tiefe muss dieses Zeichen einschliessen,
        # sonst gilt jede Definition hinter dem '}' der Vorgaengerfunktion als 'innen'.
        anfang = m.start() + (1 if m.start() < len(t) and t[m.start()] in ';{}' else 0)
        depth, pos = _tiefe_bis(t, anfang, pos, depth)
        # group2: Qualifier, group3: Kerntyp. `operator delete(p)` ist ein Aufruf.
        if (m.group(3) or '') == 'operator':
            continue
        qual = re.sub(r'\b(const|volatile|extern|static|inline|virtual)\b', ' ', m.group(2) or '')
        qual = re.sub(r'\s+', ' ', qual).strip()
        kern = m.group(3)
        if qual and kern not in ('unsigned', 'signed', 'short', 'long'):
            roh_basis = (qual + ' ' + kern).strip()
        elif qual and kern in ('int', 'char', 'short', 'long'):
            roh_basis = (qual + ' ' + kern).strip()
        else:
            roh_basis = (qual + ' ' + kern).strip() if qual else kern
        roh_basis = re.sub(r'\s+', ' ', roh_basis).strip()
        if roh_basis in ('unsigned',):
            roh_basis = 'unsigned int'
        if roh_basis in ('signed', 'signed int'):
            roh_basis = 'int'
        if roh_basis == 'short int':
            roh_basis = 'short'
        if roh_basis == 'long int':
            roh_basis = 'long'
        ret = norm_typ(roh_basis, m.group(4) or '')
        name = m.group(5)
        if name in ('if', 'for', 'while', 'switch', 'return', 'sizeof'):
            continue
        params = []
        roh_params = m.group(6).strip()
        if roh_params and roh_params != 'void':
            tiefe, cur = 0, []
            stueck = []
            for ch in roh_params:
                if ch in '([':
                    tiefe += 1
                elif ch in ')]':
                    tiefe = max(0, tiefe - 1)
                if ch == ',' and tiefe == 0:
                    stueck.append(''.join(cur))
                    cur = []
                else:
                    cur.append(ch)
            stueck.append(''.join(cur))
            params = [norm_param(s) for s in stueck if s.strip()]
        fund.setdefault(name, []).append((tuple(params), ret, m.group(7) == '{', depth == 0))
    return fund


def erste_signatur(varianten):
    """Datei-Prototyp vor innerer Deklaration. Leere Parameterliste weicht einem spaeteren Prototyp."""
    datei = [v for v in varianten if v[3]] or varianten
    gewaehlt = None
    definiert = False
    for params, ret, ist_def, _ebene in datei:
        definiert = definiert or ist_def
        if ist_def:
            if gewaehlt is None:
                gewaehlt = (params, ret)
            continue
        if gewaehlt is None or (gewaehlt[0] == tuple() and params):
            gewaehlt = (params, ret)
    return gewaehlt[0], gewaehlt[1], definiert


def typ_gleich(decl, link):
    if decl == link:
        return True
    if link == 'ptr' and isinstance(decl, str) and '*' in decl:
        return True
    if decl == 'ptr' and isinstance(link, str) and link == 'ptr':
        return True
    return False


def sig_text(params, ret):
    innen = ','.join(params) if params else ''
    return '(' + innen + ')->' + (ret or '?')


def standard_register(ret):
    if ret == 'void':
        return None
    if ret in ('short', 'unsigned short', 'short*'):
        return 'ax' if not str(ret).endswith('*') else 'eax'
    if ret in ('char', 'unsigned char', 'signed char'):
        return 'al'
    return 'eax'


def kruecken(text, gegen=None):
    nackt = ohne_strings(ohne_kommentar(text))
    warn = []
    for name in SELBST_XOR.findall(nackt):
        warn.append('self_xor:' + name)
    for name in OR_AND0.findall(nackt):
        warn.append('or_and0:' + name)
    for name in TERNARY_AND0.findall(nackt):
        warn.append('ternary_and0:' + name)
    if BYTEOFFSET.search(nackt):
        warn.append('byteoffset')
    if gegen is not None:
        alt = set(re.sub(r'\s+', ' ', z.strip()) for z in VOLATILE_ZEILE.findall(ohne_kommentar(gegen)))
        for z in VOLATILE_ZEILE.findall(ohne_kommentar(text)):
            nz = re.sub(r'\s+', ' ', z.strip())
            if nz and nz not in alt:
                warn.append('volatile_neu')
                break
    return warn


def code_koerper_satz(text):
    satz = set()
    for _zeile, block in pragma_bloecke(text):
        teil = zerlege_pragma(block)
        if not teil or teil[0] != 'code':
            continue
        koerper = teil[2]
        if koerper.strip() in ('""', "''"):
            continue
        satz.add(norm_koerper(koerper))
    return satz


def pruefen(text, gegen=None, bestand=False, erlaubt=None, einheit=None):
    """bestand=True: die Datei IST p3. Signatur-Abweichungen werden Befunde, kein ABGEWIESEN.
    gegen: Text der p3-Datei derselben Einheit. Gleiche Abweichung wie dort ist geerbt."""
    if erlaubt is None:
        erlaubt = erlaubtliste()
    mnemonics, int_ops, byte_ok = erlaubt
    ab, warn, befunde = [], [], []
    roh_a = REGEL_A.search(text)
    if roh_a:
        treffer = roh_a.group(0)
        if '__segname' in treffer:
            ab.append('a:__segname(_TEXT)')
        elif 'db' in treffer:
            ab.append('a:db-im-pragma')
        elif treffer == '_emit' or '_emit' in treffer:
            ab.append('a:_emit')
        elif '__asm' in treffer:
            ab.append('a:__asm')
        else:
            ab.append('a:_asm')
    gegen_code = code_koerper_satz(gegen) if gegen else set()
    gegen_decl = deklarationen(gegen) if gegen else {}
    decl = deklarationen(text)
    gegen_alias = {}
    if gegen:
        for _zeile, block in pragma_bloecke(gegen):
            teil = zerlege_pragma(block)
            if teil and teil[0] == 'alias':
                gegen_alias[teil[1]] = teil[2]
    for zeile_nr, block in pragma_bloecke(text):
        teil = zerlege_pragma(block)
        if not teil:
            continue
        art, name, koerper, rest = teil
        if art == 'code':
            if koerper.strip() in ('""', "''"):
                warn.append('leer:' + name + ':' + str(zeile_nr))
                continue
            _nf = namentlich_erlaubt(text, name, koerper, einheit)   # Note: nur diese eine Funktion
            if _nf:
                warn.append('namentlich erlaubt (PRAGMA_NAMENTLICH.tsv): ' + name + ' nur in ' + _nf)
                continue
            folge = bytefolge(koerper)
            if folge is not None:
                if folge not in byte_ok:
                    ab.append('b:bytefolge ' + name)
                elif gegen is not None and norm_koerper(koerper) not in gegen_code:
                    warn.append('code_neu:' + name)
                continue
            for op, operand in befehle(koerper):
                if op not in mnemonics:
                    ab.append('b:' + op + ' ' + name)
                    break
                if op == 'int' and operand not in int_ops:
                    ab.append('b:int ' + (operand or '?') + ' ' + name)
                    break
            else:
                if gegen is not None and norm_koerper(koerper) not in gegen_code:
                    warn.append('code_neu:' + name)
        elif art == 'alias' and MANGLED.match(koerper):
            warn.append('alias:' + name + ':' + koerper + ':' + str(zeile_nr))
            link = parse_link(koerper)
            info = erste_signatur(decl[name]) if name in decl else None
            ginfo = erste_signatur(gegen_decl[name]) if name in gegen_decl else None
            geerbt = gegen_alias.get(name) == koerper and (
                info is None or (ginfo is not None and ginfo[:2] == info[:2]))
            if link and info:
                params, ret = link
                d_params, d_ret, _def = info
                if len(params) != len(d_params) or any(
                        not typ_gleich(a, b) for a, b in zip(d_params, params)) or not typ_gleich(d_ret, ret):
                    detail = 'c:link ' + name + ' decl=' + sig_text(d_params, d_ret) + ' link=' + sig_text(params, ret)
                    if bestand or geerbt:
                        befunde.append((name, 'signatur', detail))
                    else:
                        ab.append(detail)
                reg = standard_register(d_ret)
                vm = re.search(r'\bvalue\s*\[\s*([A-Za-z]+)', rest or '')
                if vm and reg and vm.group(1).lower() != reg:
                    detail = 'c:value ' + name + ' ' + vm.group(1).lower() + ' statt ' + reg
                    if bestand or geerbt:
                        befunde.append((name, 'value', detail))
                    else:
                        ab.append(detail)
            if re.search(r'\bmodify\b[^;\n]*\b(ebp|esp)\b', rest or '', re.I):
                befunde.append((name, 'modify', 'vereinbarung ' + name + ' modify nennt ebp/esp'))
    if gegen is not None and not bestand:
        # Auftrag Satz 2: nur Parameterzahl und Parametertypen auf Dateiebene.
        # Rueckgabetyp allein (int -> short) ist kein Grund. Methoden und Prototypen
        # innerhalb einer Funktion gehoeren nicht zum externen Aufrufvertrag.
        for name, varianten in decl.items():
            if name not in gegen_decl or any(v[2] and v[3] for v in varianten):
                continue
            eigene = [v for v in varianten if v[3] and not v[2]]
            fremd = [v for v in gegen_decl[name] if v[3] and not v[2]]
            if not eigene or not fremd:
                continue
            kand = {v[0] for v in eigene}
            for g_params, g_ret, _g_def, _g_ebene in fremd:
                if g_params in kand:
                    continue
                gezeigt = eigene[0]
                zeile = ('c:prototyp ' + name + ' ' + sig_text(g_params, g_ret)
                         + ' -> ' + sig_text(gezeigt[0], gezeigt[1]))
                if zeile[len('c:prototyp '):] in proto_erlaubt():
                    warn.append('erlaubt (PROTOTYP_ERLAUBT.tsv): ' + zeile)
                else:
                    ab.append(zeile)
                break
    warn.extend(kruecken(text, gegen if not bestand else None))
    # Doppelte Zeilen gleichen Wortlauts einmal.
    def uniq(xs):
        gesehen, aus = set(), []
        for x in xs:
            if x not in gesehen:
                gesehen.add(x)
                aus.append(x)
        return aus
    ab, warn = uniq(ab), uniq(warn)
    if ab:
        status = 'ABGEWIESEN'
    elif warn:
        status = 'WARNUNG'
    else:
        status = 'OK'
    return {'status': status, 'ab': ab, 'warn': warn, 'befunde': befunde}


def zeile(ergebnis):
    if ergebnis['status'] == 'OK':
        return 'OK'
    gruende = ergebnis['ab'] if ergebnis['status'] == 'ABGEWIESEN' else ergebnis['warn']
    return ergebnis['status'] + ' ' + '; '.join(gruende)


def exit_code(status):
    return {'OK': 0, 'WARNUNG': 1, 'ABGEWIESEN': 2}[status]


def _eindeutig(pfad):
    if not os.path.exists(pfad):
        return pfad
    stamm, ext = os.path.splitext(pfad)
    return stamm + '.' + time.strftime('%Y%m%d_%H%M%S') + ext


def abweisen_datei(wurzel, pfad):
    """Kopie nach abgewiesen/, Originale nach _to_delete/ neben dem Fundort. Nichts wird geloescht."""
    wurzel = wurzel or WURZEL
    base = os.path.basename(pfad)
    ziele = []
    kandidat = os.path.join(PC.resolve_path('logs_dir', _CFG), 'candidates', base)
    r2 = os.path.join(PC.resolve_path('logs_dir', _CFG), 'r2', base)
    pfade = [pfad]
    norm = pfad.replace('\\', '/')
    if norm.endswith('/kandidaten/' + base) or norm.endswith('/r2/' + base):
        pfade.extend([kandidat, r2])
    gesehen = set()
    abw = os.path.join(PC.resolve_path('logs_dir', _CFG), 'rejected')
    os.makedirs(abw, exist_ok=True)
    for src in pfade:
        src = os.path.abspath(src)
        if src in gesehen or not os.path.isfile(src):
            continue
        gesehen.add(src)
        ziel = _eindeutig(os.path.join(abw, base))
        shutil.copy2(src, ziel)
        ziele.append(ziel)
        tod = os.path.join(os.path.dirname(src), '_to_delete')
        os.makedirs(tod, exist_ok=True)
        os.replace(src, _eindeutig(os.path.join(tod, base)))
    return ziele


def protokoll_abgewiesen(wurzel, einheit, pfad, grund):
    wurzel = wurzel or WURZEL
    jetzt = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()
    regel = os.path.join(PC.resolve_path('logs_dir', _CFG), 'RULE_VIOLATIONS.md')
    with open(regel, 'a', encoding='utf-8') as f:
        f.write(f'\n{jetzt} GATEKEEPER REJECTED {einheit} {pfad} {grund}\n')
    erg = os.path.join(PC.resolve_path('logs_dir', _CFG), 'RESULTS.tsv')
    with open(erg, 'a', encoding='utf-8') as f:
        f.write(f'{jetzt}\t{einheit}\t-\t-\t-\tABGEWIESEN\t-\tpfoertner: {grund}\n')


def nur_neue(warn, alt):
    """Warnungen, deren Art noch nicht im Bestand steht. Zeilennummern von leer/alias zaehlen nicht."""
    def schluessel(w):
        teile = w.split(':')
        if teile and teile[-1].isdigit() and teile[0] in ('leer', 'alias'):
            teile = teile[:-1]
        return ':'.join(teile)
    alt_keys = {schluessel(w) for w in alt}
    return [w for w in warn if schluessel(w) not in alt_keys]


def protokoll_kruecke(wurzel, einheit, datei, gruende):
    wurzel = wurzel or WURZEL
    pfad = os.path.join(HIER, 'KRUECKEN_NEU.tsv')
    neu = not os.path.exists(pfad)
    jetzt = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()
    with open(pfad, 'a', encoding='utf-8') as f:
        if neu:
            f.write('zeit\teinheit\tdatei\tgruende\n')
        f.write(f'{jetzt}\t{einheit}\t{datei}\t{"; ".join(gruende)}\n')


def main(argv):
    if len(argv) < 2:
        print('Aufruf: pfoertner.py DATEI [--gegen P3DATEI]', file=sys.stderr)
        return 2
    datei = argv[1]
    gegen_pfad = None
    if '--gegen' in argv:
        gegen_pfad = argv[argv.index('--gegen') + 1]
    text = lies(datei)
    gegen = lies(gegen_pfad) if gegen_pfad else None
    bestand = gegen is None and os.path.abspath(datei).replace('\\', '/').find('/p3/') >= 0
    erg = pruefen(text, gegen, bestand=bestand)
    print(zeile(erg))
    return exit_code(erg['status'])


if __name__ == '__main__':
    sys.exit(main(sys.argv))
