# -*- coding: latin-1 -*-
"""Mischer-Kern (worker).

Abschnittszerlegung, Fallvergleich nach worker/fallvgl.py, homologe
Ausrichtung, Kreuzen, Messung (Emulator zur Vorauswahl, nativ zur Entscheidung).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLKIT_ROOT = os.path.normpath(os.path.join(HERE, '..'))
import sys as _sys
if TOOLKIT_ROOT not in _sys.path: _sys.path.insert(0, TOOLKIT_ROOT)
import project_config as PC
_CFG = PC.load_config()
ROOT = PC.resolve_path('project_root', _CFG)
FLAT = PC.resolve_path('flat_bin', _CFG)
GW = os.path.join(TOOLKIT_ROOT, '03_richter')
EMU = os.path.join(TOOLKIT_ROOT, '01_werkzeugkette')
PYLIB = os.environ.get('W106_PYLIB', '')
PROBE_Q = os.path.join(TOOLKIT_ROOT, '03_richter', 'probe_queue.py')
LOGS_DIR = PC.resolve_path('logs_dir', _CFG, os.path.join(TOOLKIT_ROOT, 'logs'))
FSTAND = os.path.join(LOGS_DIR, 'zaehlen_fstand')
LIVE = os.path.join(LOGS_DIR, 'live_fstand')
P3 = PC.resolve_path('src_p3_dir', _CFG)
SPERREN = os.path.join(LOGS_DIR, 'funnel', 'LEASES.tsv')
ASM_VERBUCHT = os.path.join(LOGS_DIR, 'asm_anchors.tsv')
BYTEWERT = os.path.join(LOGS_DIR, 'live_status.tsv')
KAND = PC.resolve_path('src_p2_dir', _CFG)
ERGEBNISSE = os.path.join(LOGS_DIR, 'results.tsv')
VERTEILER = os.path.join(TOOLKIT_ROOT, '04_trichter', 'verteiler.py')
WORKER_ID = os.environ.get('MISCHER_ID', 'mixer_01')   # 04.11.: zweiter Mischer parallel mit eigener Mess-ID (MISCHER_ID=1359)
MAX_PROCS = 6

KW_STMT = {
    'if', 'for', 'while', 'do', 'switch', 'return', 'goto', 'break', 'continue',
    'else', 'case', 'default', 'try', 'catch', 'throw', 'delete', 'new', 'sizeof',
    'typedef',
}
TYPE_KW = {
    'void', 'int', 'short', 'long', 'char', 'float', 'double', 'signed', 'unsigned',
    'bool', 'const', 'volatile', 'static', 'register', 'struct', 'class', 'enum',
    'union', 'extern', 'auto', 'mutable', 'inline', 'typename', 'virtual', 'friend',
    'explicit', '__int64', 'size_t', 'int8_t', 'int16_t', 'int32_t', 'uint8_t',
    'uint16_t', 'uint32_t', 'wchar_t',
}


def log(msg):
    print(msg, flush=True)


# ---------- Assembler (fallvgl-kompatibel) ----------

def norm(t, regs=True):
    """Wie fallvgl.py:norm. Nicht aendern, E2 haengt daran."""
    t = re.sub(r'(call|j\w+)\s+0x[0-9a-f]+', r'\1 X', t)
    t = re.sub(r'\[ebp[+-]0x[0-9a-f]+\]', '[S]', t)
    t = re.sub(r'ds:0x[0-9a-f]+', 'ds:G', t)
    t = re.sub(r'0x1[a-c][0-9a-f]{4}\b', 'G', t)
    if t.startswith('mov ') and re.match(r'mov e[a-d]x,(0x0|G)$', t):
        t = re.sub(r',(0x0|G)$', ',G', t)
    if regs:
        t = re.sub(r'\b(e?[a-d]x|[a-d][lh]|e?si|e?di)\b', 'R', t)
        t = t.replace('DWORD PTR [S]', 'R')
    return t


def load_asm(fn, start_marker=None):
    """Wie tree.load. Akzeptiert objdump mit Rohbytes und 4-stellige Offsets."""
    ins = []
    on = start_marker is None
    with open(fn, encoding='latin1', errors='replace') as f:
        for l in f:
            if start_marker and start_marker in l:
                on = True
                continue
            if not on:
                continue
            m = re.match(r'\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} )+\s*(.*)$', l) or re.match(
                r'\s+([0-9a-f]{4,})\s+(.*)$', l)
            if not m:
                if start_marker and ins and re.match(r'^\S', l):
                    break
                continue
            ins.append((int(m.group(1), 16), re.sub(r'\s+', ' ', m.group(2).strip())))
    return ins


def load_objdump_text(text):
    ins = []
    for l in text.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s*(.*)$', l)
        if not m:
            continue
        rest = m.group(2).strip()
        rest = re.sub(r'^(?:[0-9a-f]{2} )+', '', rest)
        rest = re.sub(r'\s+', ' ', rest).strip()
        if not rest or rest.startswith('<'):
            continue
        ins.append((int(m.group(1), 16), rest))
    return ins


def fkt_groesse(einheit, fkt):
    a = fkt.replace('f_', '').upper()
    pfad = os.path.join(FSTAND, einheit + '.fstand')
    if not os.path.isfile(pfad):
        return None
    for l in open(pfad, encoding='latin1', errors='replace'):
        p = l.split()
        if p and p[0].upper() == a:
            return int(p[1].split('/')[0])
    return None


def orig_asm(einheit, fkt):
    n = fkt_groesse(einheit, fkt)
    if not n:
        raise RuntimeError(f'keine Groesse fuer {einheit} {fkt}')
    st = int(fkt.replace('f_', ''), 16)
    r = subprocess.run(
        ['objdump', '-D', '-b', 'binary', '-mi386', '-Mintel', '--adjust-vma=0x10000',
         '--start-address', str(st), '--stop-address', str(st + n), FLAT],
        capture_output=True, text=True)
    ins = load_objdump_text(r.stdout)
    if not ins:
        raise RuntimeError('objdump leer: ' + r.stderr[-200:])
    return ins


def _dispatch_reg(ins):
    """Haeufigstes cmp-Register in den ersten 80 Befehlen (Watcom-switch)."""
    cnt = {}
    for _, t in ins[:80]:
        m = re.match(r'cmp ([a-z][a-z0-9]*),0x[0-9a-f]+$', t)
        if m:
            cnt[m.group(1)] = cnt.get(m.group(1), 0) + 1
    if not cnt:
        return None
    return max(cnt, key=cnt.get)


def blocks(ins, reg='dx'):
    """Wie fallvgl.blocks, Register parametrierbar. Wirft ValueError ohne cmp-Kette."""
    idx = {a: i for i, (a, t) in enumerate(ins)}
    hits = [i for i, (a, t) in enumerate(ins) if t.startswith(f'cmp {reg},')]
    if not hits:
        raise ValueError('keine cmp-Kette')
    i0 = hits[0]

    def target(v):
        i = i0
        c = None
        guard = 0
        while guard < 100000:
            guard += 1
            if i >= len(ins) or i < 0:
                return i
            a, t = ins[i]
            m = re.match(rf'cmp {reg},0x([0-9a-f]+)$', t)
            if m:
                c = int(m.group(1), 16)
                i += 1
                continue
            m = re.match(r'(jb|jbe|je|ja|jae|jmp) 0x([0-9a-f]+)$', t)
            if m and c is not None or (m and m.group(1) == 'jmp'):
                j, tg = m.group(1), int(m.group(2), 16)
                if j == 'jmp':
                    i = idx.get(tg, i + 1)
                    continue
                ok = {'jb': v < c, 'jbe': v <= c, 'je': v == c, 'ja': v > c, 'jae': v >= c}[j]
                i = idx[tg] if ok and tg in idx else i + 1
                continue
            return i
        return i

    def trace(i):
        seen = set()
        out = []
        stack = [i]
        while stack:
            i = stack.pop()
            while i not in seen and 0 <= i < len(ins):
                seen.add(i)
                a, t = ins[i]
                out.append(t)
                if t == 'ret' or t.startswith('ret '):
                    break
                m = re.match(r'(j\w+) 0x([0-9a-f]+)$', t)
                if m:
                    tg = idx.get(int(m.group(2), 16))
                    if m.group(1) == 'jmp':
                        if tg is None:
                            break
                        i = tg
                        continue
                    if tg is not None:
                        stack.append(tg)
                i += 1
        return out

    return target, trace


def zaehl_faelle(orig, neu, values, reg=None):
    """Je Fall (status, dist_exakt, dist_struktur). status OK/REG/STRUKT wie fallvgl."""
    reg = reg or _dispatch_reg(orig) or 'dx'
    to, tro = blocks(orig, reg)
    tn, trn = blocks(neu, reg)
    rows = []
    for v in values:
        a = [norm(x) for x in tro(to(v))]
        b = [norm(x) for x in trn(tn(v))]
        a2 = [norm(x, False) for x in tro(to(v))]
        b2 = [norm(x, False) for x in trn(tn(v))]
        if a2 == b2:
            st = 'OK'
        elif a == b:
            st = 'REG'
        else:
            st = 'STRUKT'
        sm = difflib.SequenceMatcher(None, a2, b2, autojunk=False)
        d = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != 'equal')
        sm2 = difflib.SequenceMatcher(None, a, b, autojunk=False)
        ds = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm2.get_opcodes() if op != 'equal')
        rows.append((v, st, d, ds))
    return rows


def align_dist(orig, neu):
    """Editierabstand der normalisierten Befehlsfolge (exakt und struktur). Groesse extra."""
    A = [norm(t, False) for _, t in orig]
    B = [norm(t, False) for _, t in neu]
    As = [norm(t, True) for _, t in orig]
    Bs = [norm(t, True) for _, t in neu]
    def dist(x, y):
        sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
        return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != 'equal'), sm.get_opcodes()
    d, op = dist(A, B)
    ds, _ = dist(As, Bs)
    return {'dist': d, 'dist_struct': ds, 'orig_befehle': len(A), 'neu_befehle': len(B),
            'orig_bytes': (orig[-1][0] - orig[0][0] + 1) if orig else 0,
            'neu_bytes': (neu[-1][0] - neu[0][0] + 1) if neu else 0,
            'opcodes': op, 'A': A, 'B': B}


def fall_asm(orig, neu, v, reg=None):
    """Befehlsfolgen eines Falls, fuer HARTE_ABSCHNITTE."""
    reg = reg or _dispatch_reg(orig) or 'dx'
    to, tro = blocks(orig, reg)
    tn, trn = blocks(neu, reg)
    return [norm(x, False) for x in tro(to(v))], [norm(x, False) for x in trn(tn(v))]


# ---------- Quelle: Abschnitte ----------

def _skip(s, i):
    n = len(s)
    while i < n:
        if s[i] in ' \t\r\n':
            i += 1
        elif s.startswith('//', i):
            j = s.find('\n', i)
            i = n if j < 0 else j + 1
        elif s.startswith('/*', i):
            j = s.find('*/', i + 2)
            i = n if j < 0 else j + 2
        else:
            break
    return i


def _skip_str(s, i):
    q = s[i]
    i += 1
    n = len(s)
    while i < n:
        if s[i] == '\\':
            i += 2
            continue
        if s[i] == q:
            return i + 1
        i += 1
    return i


def _ident_at(s, i):
    i = _skip(s, i)
    if i < len(s) and (s[i].isalpha() or s[i] == '_'):
        j = i + 1
        while j < len(s) and (s[j].isalnum() or s[j] == '_'):
            j += 1
        return s[i:j], j
    return '', i


def _balanced(s, i, op, cl):
    n = len(s)
    d = 0
    while i < n:
        if s.startswith('//', i):
            j = s.find('\n', i)
            i = n if j < 0 else j + 1
            continue
        if s.startswith('/*', i):
            j = s.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        c = s[i]
        if c in '"\'':
            i = _skip_str(s, i)
            continue
        if c == op:
            d += 1
        elif c == cl:
            d -= 1
            if d == 0:
                return i + 1
        i += 1
    return i


def _until_semi(s, i):
    n = len(s)
    d = p = 0
    while i < n:
        if s.startswith('//', i):
            j = s.find('\n', i)
            i = n if j < 0 else j + 1
            continue
        if s.startswith('/*', i):
            j = s.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        c = s[i]
        if c in '"\'':
            i = _skip_str(s, i)
            continue
        if c in '({[':
            d += 1
        elif c in ')}]':
            if d == 0 and c == '}':
                return i
            d = max(0, d - 1)
        elif c == ';' and d == 0:
            return i + 1
        i += 1
    return i


def end_of_stmt(s, i):
    i0 = _skip(s, i)
    if i0 >= len(s):
        return i0
    if s[i0] == '{':
        return _balanced(s, i0, '{', '}')
    k, j = _ident_at(s, i0)
    if k == 'if':
        p = _skip(s, j)
        if p < len(s) and s[p] == '(':
            p = _balanced(s, p, '(', ')')
        p = end_of_stmt(s, p)
        q = _skip(s, p)
        k2, j2 = _ident_at(s, q)
        if k2 == 'else':
            p = end_of_stmt(s, j2)
        return p
    if k in ('while', 'switch', 'for'):
        p = _skip(s, j)
        if p < len(s) and s[p] == '(':
            p = _balanced(s, p, '(', ')')
        return end_of_stmt(s, p)
    if k == 'do':
        p = end_of_stmt(s, j)
        q = _skip(s, p)
        k2, j2 = _ident_at(s, q)
        if k2 == 'while':
            r = _skip(s, j2)
            if r < len(s) and s[r] == '(':
                r = _balanced(s, r, '(', ')')
            r = _skip(s, r)
            if r < len(s) and s[r] == ';':
                r += 1
            return r
        return p
    return _until_semi(s, i0)


def _case_value(expr):
    e = expr.strip()
    m = re.fullmatch(r'([+-]?)\s*(0x[0-9a-fA-F]+|\d+)', e)
    if not m:
        return e
    n = int(m.group(2), 16) if m.group(2).lower().startswith('0x') else int(m.group(2))
    if m.group(1) == '-':
        n = -n
    return n


def _case_key(labels):
    parts = []
    for v in labels:
        if v == 'default':
            parts.append('default')
        elif isinstance(v, int):
            parts.append(hex(v) if v < 0 or v > 9 else str(v))
        else:
            parts.append(str(v))
    parts_s = sorted(parts, key=lambda x: (x == 'default', x))
    return 'C:' + '&'.join(parts_s)


def _split_cases(s, i, end):
    """i zeigt hinter die oeffnende Klammer des switch-Rumpfes."""
    segs = []
    depth = 0
    labels = []
    lab_at = None
    body_at = None
    pos = i
    n = end
    while pos < n:
        if s.startswith('//', pos):
            j = s.find('\n', pos)
            pos = n if j < 0 else j + 1
            continue
        if s.startswith('/*', pos):
            j = s.find('*/', pos + 2)
            pos = n if j < 0 else j + 2
            continue
        c = s[pos]
        if c in '"\'':
            pos = _skip_str(s, pos)
            continue
        if c == '{':
            depth += 1
            pos += 1
            continue
        if c == '}':
            if depth == 0:
                break
            depth -= 1
            pos += 1
            continue
        if depth == 0:
            k, j = _ident_at(s, pos)
            if k in ('case', 'default') and _skip(s, pos) == pos:
                # nur wenn wir wirklich auf dem Schluesselwort stehen (kein Rest einer Ident)
                if pos == _skip(s, pos) or True:
                    at = _skip(s, pos)
                    if at == pos or s.startswith(k, at):
                        if body_at is not None and s[body_at:at].strip():
                            segs.append((list(labels), lab_at, at))
                            labels = []
                            lab_at = None
                        if lab_at is None:
                            lab_at = at
                        if k == 'default':
                            labels.append('default')
                            col = s.find(':', j)
                            body_at = col + 1 if col >= 0 else j
                            pos = body_at
                            continue
                        # Ausdruck bis ':' bei Klammerntiefe 0
                        p = j
                        dpar = 0
                        while p < n:
                            if s.startswith('//', p):
                                q = s.find('\n', p)
                                p = n if q < 0 else q + 1
                                continue
                            if s[p] in '"\'':
                                p = _skip_str(s, p)
                                continue
                            if s[p] == '(':
                                dpar += 1
                            elif s[p] == ')':
                                dpar -= 1
                            elif s[p] == ':' and dpar == 0:
                                labels.append(_case_value(s[j:p]))
                                body_at = p + 1
                                pos = body_at
                                break
                            p += 1
                        else:
                            pos = p
                        continue
        pos += 1
    if labels and lab_at is not None:
        segs.append((list(labels), lab_at, pos))
    return segs


def _fp(text):
    calls = tuple(re.findall(r'\b(f_[0-9a-fA-F]{3,}|[A-Za-z_]\w*)\s*\(', text)[:12])
    calls = tuple(c for c in calls if c not in KW_STMT and c not in TYPE_KW)
    consts = []
    for m in re.finditer(r'\b0x[0-9a-fA-F]+|\b\d+\b', text):
        consts.append(m.group(0).lower())
        if len(consts) >= 12:
            break
    raw = (calls, tuple(consts))
    h = hashlib.sha1(repr(raw).encode('latin1', 'replace')).hexdigest()[:8]
    return h


def _is_decl(stmt):
    s = stmt.strip()
    if not s or s[0] in '{(#*!~':
        return False
    if s.startswith('//'):
        return False
    k, j = _ident_at(s, 0)
    if not k or k in KW_STMT:
        return False
    if k in TYPE_KW:
        return True
    rest = s[j:]
    r = rest.lstrip()
    if r.startswith('(') or r.startswith('.') or r.startswith('->') or r.startswith('['):
        return False
    if r.startswith('=') or r.startswith('++') or r.startswith('--'):
        return False
    # Typname + Deklarator: zweites Ident, Zeiger oder Referenz
    if r[:1] in '*&' or re.match(r'[A-Za-z_]', r):
        return True
    return False


def _decl_names(stmt):
    """Namen aus einer Deklaration. Initialisierer werden abgetrennt."""
    s = stmt.strip().rstrip(';').strip()
    # Initialisierer bei Tiefe 0 entfernen
    out = []
    buf = []
    d = 0
    i = 0
    while i < len(s):
        c = s[i]
        if c in '"\'':
            j = _skip_str(s, i)
            buf.append(s[i:j])
            i = j
            continue
        if c in '({[':
            d += 1
        elif c in ')}]':
            d = max(0, d - 1)
        if c == '=' and d == 0:
            # bis Komma auf Tiefe 0 ueberspringen
            i += 1
            while i < len(s):
                if s[i] in '({[':
                    d += 1
                elif s[i] in ')}]':
                    d = max(0, d - 1)
                elif s[i] == ',' and d == 0:
                    break
                i += 1
            continue
        if c == ',' and d == 0:
            out.append(''.join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    out.append(''.join(buf))
    names = []
    types = []
    spec = ''
    for piece in out:
        ids = re.findall(r'[A-Za-z_]\w*', piece)
        ids = [x for x in ids if x not in TYPE_KW and x not in ('struct', 'class', 'enum', 'union')]
        if not ids:
            continue
        name = ids[-1]
        prefix = piece[:piece.rfind(name)].strip()
        nur_sterne = prefix.replace('*', '').replace('&', '').strip() == ''
        if prefix and not nur_sterne:
            spec = re.sub(r'[*&\s]+$', '', prefix).strip()
            typ = prefix
        elif spec:
            typ = (spec + (' ' + prefix if prefix else '')).strip()
        else:
            typ = prefix
        if not typ:
            continue
        names.append(name)
        types.append(typ)
    return list(zip(types, names))


def _consts_of(text):
    s = set()
    for m in re.finditer(r'\b0x[0-9a-fA-F]+|\b\d+\b', text):
        raw = m.group(0)
        s.add(raw.lower())
        try:
            n = int(raw, 16) if raw.lower().startswith('0x') else int(raw)
        except ValueError:
            continue
        s.add(str(n))
        s.add(hex(n))
    return s


def _calls_of(text):
    return [c for c in re.findall(r'\b([A-Za-z_]\w*)\s*\(', text) if c not in KW_STMT and c not in TYPE_KW]


def _brace_delta(text):
    d = 0
    i = 0
    n = len(text)
    while i < n:
        if text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
            continue
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        if text[i] in '"\'':
            i = _skip_str(text, i)
            continue
        if text[i] == '{':
            d += 1
        elif text[i] == '}':
            d -= 1
        i += 1
    return d


@dataclass
class Abschnitt:
    key: str
    kind: str
    text: str
    labels: list = field(default_factory=list)
    consts: set = field(default_factory=set)
    calls: list = field(default_factory=list)
    locals_used: list = field(default_factory=list)
    balanced: bool = True
    kruecke: bool = False
    verboten: str = ''


@dataclass
class Funktion:
    name: str
    signatur: str
    text: str          # ganze Definition
    prefix: str        # vor der Definition im Ausschnitt (Helfer)
    abschnitte: list = field(default_factory=list)
    lokale: list = field(default_factory=list)   # (typ, name) in Reihenfolge
    datei: str = ''
    ganz: bool = False
    grund: str = ''


def _function_span(text, fkt):
    """(start, end, sig_start) der Definition. Bevorzugt //@ f_xxxxxx."""
    mark = re.search(r'(?m)^//@\s*' + re.escape(fkt) + r'\b.*$', text)
    search_from = mark.end() if mark else 0
    # Definition: Name, dann Parameter, dann { vor ;
    for m in re.finditer(r'\b' + re.escape(fkt) + r'\b', text[search_from:]):
        abs_m = search_from + m.start()
        j = m.end() + search_from
        # zurueck zum Zeilenanfang fuer die Signatur, aber nicht ueber den Marker
        line = text.rfind('\n', 0, abs_m) + 1
        if mark and line < mark.end() and abs_m >= mark.end():
            line = mark.end()
            if line < len(text) and text[line] == '\n':
                line += 1
        k = j
        # Parameterliste finden
        k = _skip(text, k)
        if k >= len(text) or text[k] != '(':
            continue
        k = _balanced(text, k, '(', ')')
        k2 = _skip(text, k)
        # cv-qualifier / const
        while True:
            idn, k3 = _ident_at(text, k2)
            if idn in ('const', 'volatile', 'override', 'final', 'noexcept'):
                k2 = _skip(text, k3)
                continue
            break
        if k2 < len(text) and text[k2] == '{':
            end = _balanced(text, k2, '{', '}')
            return line, end
        if k2 < len(text) and text[k2] == ';':
            continue  # Prototyp
        # Konstruktor-Initialisierer : ... {
        if k2 < len(text) and text[k2] == ':':
            p = k2
            d = 0
            while p < len(text):
                if text[p] in '"\'':
                    p = _skip_str(text, p)
                    continue
                if text[p] == '{':
                    if d == 0:
                        end = _balanced(text, p, '{', '}')
                        return line, end
                    d += 1
                elif text[p] == '(':
                    d += 1
                elif text[p] in ')}':
                    d = max(0, d - 1)
                p += 1
    return None


def _body_brace(func_text):
    """Index der oeffnenden Klammer des Rumpfes."""
    i = 0
    n = len(func_text)
    # letzte { auf Tiefe 0 vor viel Inhalt: die Rumpfklammer ist die erste { auf Tiefe 0
    dpar = 0
    while i < n:
        if func_text.startswith('//', i):
            j = func_text.find('\n', i)
            i = n if j < 0 else j + 1
            continue
        if func_text.startswith('/*', i):
            j = func_text.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        c = func_text[i]
        if c in '"\'':
            i = _skip_str(func_text, i)
            continue
        if c == '(':
            dpar += 1
        elif c == ')':
            dpar = max(0, dpar - 1)
        elif c == '{' and dpar == 0:
            return i
        i += 1
    return None


def _if_parts(s, i, end):
    """Spannt then und else innerhalb einer if-Anweisung, die bei i beginnt."""
    k, j = _ident_at(s, i)
    p = _skip(s, j)
    cond_s = p
    if p < len(s) and s[p] == '(':
        p = _balanced(s, p, '(', ')')
    cond = s[cond_s:p]
    then_s = _skip(s, p)
    then_e = end_of_stmt(s, then_s)
    else_s = else_e = None
    q = _skip(s, then_e)
    k2, j2 = _ident_at(s, q)
    if k2 == 'else':
        else_s = _skip(s, j2)
        else_e = end_of_stmt(s, else_s)
    return cond, then_s, then_e, else_s, else_e


def _walk_block(s, i, end, acc, counts):
    """Top-Level-Anweisungen zwischen i und end in acc legen."""
    while True:
        i = _skip(s, i)
        if i >= end:
            return i
        if s[i] == '}':
            return i
        st = i
        k, j = _ident_at(s, i)
        if k == 'switch':
            p = _skip(s, j)
            if p < len(s) and s[p] == '(':
                p = _balanced(s, p, '(', ')')
            b = _skip(s, p)
            if b < len(s) and s[b] == '{':
                inner = b + 1
                bend = _balanced(s, b, '{', '}') - 1
                for labels, a, c in _split_cases(s, inner, bend):
                    if not labels:
                        continue
                    acc.append((a, c, 'case', _case_key(labels), labels))
                i = bend + 1
                continue
        if k == 'if':
            cond, ts, te, es, ee = _if_parts(s, i, end)
            h = _fp(cond)
            n = counts.get(h, 0)
            counts[h] = n + 1
            suf = '' if n == 0 else f'#{n}'
            acc.append((ts, te, 'then', f'IF:{h}:then{suf}', []))
            if es is not None:
                acc.append((es, ee, 'else', f'IF:{h}:else{suf}', []))
                i = ee
            else:
                i = te
            continue
        if k in ('for', 'while', 'do'):
            e = end_of_stmt(s, i)
            h = _fp(s[st:e])
            n = counts.get('L' + h, 0)
            counts['L' + h] = n + 1
            suf = '' if n == 0 else f'#{n}'
            acc.append((st, e, 'loop', f'LOOP:{h}{suf}', []))
            i = e
            continue
        e = end_of_stmt(s, i)
        if e <= st:
            break
        acc.append((st, e, 'stmt', None, []))
        i = e
    return i


def parse_funktion(text, fkt, datei=''):
    sp = _function_span(text, fkt)
    if not sp:
        return None
    a, b = sp
    func = text[a:b]
    br = _body_brace(func)
    if br is None:
        return None
    sig = func[:br].strip()
    inner_s = br + 1
    # schliessende Klammer ist das letzte Zeichen der Definition, sofern balanced
    inner_e = len(func) - 1
    while inner_e > inner_s and func[inner_e] != '}':
        inner_e -= 1
    acc = []
    counts = {}
    _walk_block(func, inner_s, inner_e, acc, counts)
    # Schluessel fuer einfache Anweisungen, Prolog gruppieren
    stmts = []
    for a0, b0, kind, key, labels in acc:
        stmts.append([a0, b0, kind, key, labels])
    # fuehrende Deklarationen zusammenziehen
    prolog = []
    rest = []
    started = False
    for st in stmts:
        chunk = func[st[0]:st[1]]
        if not started and st[2] == 'stmt' and _is_decl(chunk):
            prolog.append(st)
        else:
            started = True
            rest.append(st)
    abschnitte = []
    if prolog:
        abschnitte.append(_make_abs(func, prolog[0][0], prolog[-1][1], 'K_PROLOG', 'prolog', []))
    # Epilog: Anweisungen nach dem letzten switch-Fall, wenn es Faelle gibt
    last_case = max((i for i, st in enumerate(rest) if st[2] == 'case'), default=-1)
    epilog = []
    body = rest
    if last_case >= 0:
        # alles nach dem letzten Fall, das nicht selbst ein Fall ist
        after = []
        before = []
        seen = False
        for st in rest:
            if st[2] == 'case':
                seen = True
                before.append(st)
            elif seen:
                after.append(st)
            else:
                before.append(st)
        body = before
        epilog = after
    fp_count = {}
    for st in body:
        if st[3] is None:
            h = _fp(func[st[0]:st[1]])
            fp_count[h] = fp_count.get(h, 0) + 1
            n = fp_count[h] - 1
            suf = '' if n == 0 else f'#{n}'
            st[3] = f'S:{h}{suf}'
        abschnitte.append(_make_abs(func, st[0], st[1], st[3], st[2], st[4]))
    if epilog:
        abschnitte.append(_make_abs(func, epilog[0][0], epilog[-1][1], 'K_EPILOG', 'epilog', []))
    lokale = []
    for sec in abschnitte:
        if sec.kind == 'prolog' or (sec.kind == 'stmt' and _is_decl(sec.text)):
            for part in _decl_stmts(sec.text):
                if _is_decl(part):
                    lokale.extend(_decl_names(part))
    # Dubletten-Namen: erste Deklaration zaehlt
    gesehen = set()
    lok2 = []
    for t, n in lokale:
        if n in gesehen:
            continue
        gesehen.add(n)
        lok2.append((t, n))
    for sec in abschnitte:
        ids = set(re.findall(r'\b([A-Za-z_]\w*)\b', sec.text))
        sec.locals_used = [n for t, n in lok2 if n in ids]
    fn = Funktion(name=fkt, signatur=sig, text=func, prefix='', abschnitte=abschnitte,
                  lokale=lok2, datei=datei)
    return fn


def _make_abs(func, a, b, key, kind, labels):
    chunk = func[a:b]
    verb = ''
    if re.search(r'\b__asm\b|\basm\s*\{', chunk):
        verb = 'inline-asm'
    if re.search(r'#\s*pragma\s+aux\b[^;\n]*=\s*"', chunk):
        verb = 'pragma-code'
    kr = bool(re.search(r'KRUECKE|volatile\b|#\s*pragma\s+aux\b', chunk, re.I))
    return Abschnitt(key=key, kind=kind, text=chunk, labels=list(labels),
                     consts=_consts_of(chunk), calls=_calls_of(chunk),
                     balanced=(_brace_delta(chunk) == 0), kruecke=kr, verboten=verb)


def signatur_kern(sig):
    """Typen ohne Parameternamen, zum Vergleich zweier Fassungen."""
    m = re.search(r'\((.*)\)', sig, re.S)
    if not m:
        return re.sub(r'\s+', ' ', sig).strip()
    params = []
    d = 0
    buf = []
    for c in m.group(1):
        if c in '<([':
            d += 1
        elif c in '>)]':
            d = max(0, d - 1)
        if c == ',' and d == 0:
            params.append(''.join(buf))
            buf = []
        else:
            buf.append(c)
    if ''.join(buf).strip():
        params.append(''.join(buf))
    types = []
    for p in params:
        p = p.strip()
        if not p:
            continue
        # letzten Ident (Name) abtrennen, wenn davor ein Typ steht
        ids = list(re.finditer(r'[A-Za-z_]\w*', p))
        if len(ids) >= 2 and ids[-1].group(0) not in TYPE_KW:
            p = p[:ids[-1].start()]
        types.append(re.sub(r'\s+', ' ', p).strip())
    head = sig[:sig.find('(')]
    head = re.sub(r'\s+', ' ', head).strip()
    return head + '(' + ','.join(types) + ')'


def gleiche_signatur(a, b):
    return signatur_kern(a.signatur) == signatur_kern(b.signatur)


def baue(fn, ersatz):
    """Funktionstext, in dem Abschnitte mit passendem Schluessel ersetzt sind.

    ersatz: key -> text. Nur ausgeglichene Klammern. Verbotene Stuecke werden nicht eingesetzt.
    """
    if not fn.abschnitte:
        return fn.text
    # von hinten, Offsets bleiben im Original gueltig, weil wir am Original schneiden
    stuecke = []
    # Spannen aus dem Original ueber die Abschnittstexte suchen (erstes Vorkommen, in Reihenfolge)
    pos = 0
    spans = []
    for sec in fn.abschnitte:
        k = fn.text.find(sec.text, pos)
        if k < 0:
            k = fn.text.find(sec.text)
        if k < 0:
            return None
        spans.append((k, k + len(sec.text), sec))
        pos = k + len(sec.text)
    out = []
    cursor = 0
    for a, b, sec in spans:
        out.append(fn.text[cursor:a])
        neu = ersatz.get(sec.key)
        if neu is None or neu == sec.text:
            out.append(fn.text[a:b])
        else:
            if _brace_delta(neu) != 0:
                out.append(fn.text[a:b])
            elif re.search(r'\b__asm\b|\basm\s*\{', neu) or re.search(r'#\s*pragma\s+aux\b[^;\n]*=\s*"', neu):
                out.append(fn.text[a:b])
            else:
                mark = ''
                if re.search(r'KRUECKE|volatile\b|#\s*pragma\s+aux\b', neu, re.I) and 'MISCHER: Kruecke' not in neu:
                    mark = '/* MISCHER: Kruecke aus Spenderfassung */ '
                out.append(mark + neu)
        cursor = b
    out.append(fn.text[cursor:])
    return ''.join(out)


def setze_funktion(unit, fkt, neu_text):
    sp = _function_span(unit, fkt)
    if not sp:
        return None
    a, b = sp
    return unit[:a] + neu_text.strip() + '\n' + unit[b:]


def lokale_namen(fn):
    return {n for _, n in fn.lokale}


def decl_text(typ, name):
    t = typ.strip() or 'int'
    return f'{t} {name};'


def prolog_mit(fn, extra_decls, pos='ende'):
    """Neue Deklarationen in den Prolog. pos: ende|anfang|index."""
    sec = next((s for s in fn.abschnitte if s.key == 'K_PROLOG'), None)
    block = ''
    if isinstance(pos, int):
        lines = [d.strip() for d in extra_decls]
        if sec:
            stmts = _decl_stmts(sec.text)
            i = max(0, min(pos, len(stmts)))
            stmts[i:i] = lines
            block = '\n    '.join(stmts)
        else:
            block = '\n    '.join(lines)
    else:
        lines = [d.strip() for d in extra_decls]
        if sec:
            base = sec.text.strip()
            if pos == 'anfang':
                block = '\n    '.join(lines + [base])
            else:
                block = base + '\n    ' + '\n    '.join(lines)
        else:
            block = '\n    '.join(lines)
    ersatz = {}
    if sec:
        ersatz['K_PROLOG'] = '\n    ' + block + '\n'
        return baue(fn, ersatz)
    # kein Prolog: hinter der oeffnenden Klammer einfuegen
    br = _body_brace(fn.text)
    if br is None:
        return None
    return fn.text[:br + 1] + '\n    ' + block + '\n' + fn.text[br + 1:]


def _decl_stmts(text):
    """Deklarationsanweisungen grob an Semikolons auf Tiefe 0."""
    parts = []
    buf = []
    d = 0
    i = 0
    while i < len(text):
        c = text[i]
        if c in '"\'':
            j = _skip_str(text, i)
            buf.append(text[i:j])
            i = j
            continue
        if c in '({[':
            d += 1
        elif c in ')}]':
            d = max(0, d - 1)
        buf.append(c)
        if c == ';' and d == 0:
            parts.append(''.join(buf).strip())
            buf = []
        i += 1
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def _idents(text):
    return set(re.findall(r'\b([A-Za-z_]\w*)\b', text))


def objekt_makros(text):
    """Objektartige #defines (kein NAME(...)). Name -> Rumpf."""
    out = {}
    if not text:
        return out
    for m in re.finditer(r'(?m)^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+(.+)$', text):
        body = m.group(2).strip()
        if body.endswith('\\'):
            continue
        body = re.sub(r'\s*/\*.*?\*/', '', body).strip()
        body = re.sub(r'\s*//.*$', '', body).strip()
        if body:
            out[m.group(1)] = body
    return out


def definier_zeilen(text):
    """Jedes #define, erste Zeile gewinnt. Name -> ganze Zeile."""
    out = {}
    if not text:
        return out
    for line in text.splitlines():
        m = re.match(r'\s*#\s*define\s+([A-Za-z_]\w*)', line)
        if m:
            out.setdefault(m.group(1), line.strip())
    return out


def expand_objekt(text, makros, tiefe=6):
    """Ersetzt objektartige Makros, auch mehrstufig. Strings und Kommentare bleiben."""
    if not text or not makros or tiefe <= 0:
        return text or ''
    out = []
    i = 0
    n = len(text)
    changed = False
    while i < n:
        if text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j + 1
            out.append(text[i:j])
            i = j
            continue
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(text[i:j])
            i = j
            continue
        if text[i] in '"\'':
            j = _skip_str(text, i)
            out.append(text[i:j])
            i = j
            continue
        m = re.match(r'[A-Za-z_]\w*', text[i:])
        if m:
            name = m.group(0)
            if name in makros:
                out.append(' ' + makros[name] + ' ')
                changed = True
            else:
                out.append(name)
            i += len(name)
            continue
        out.append(text[i])
        i += 1
    neu = ''.join(out)
    if not changed:
        return neu
    return expand_objekt(neu, makros, tiefe - 1)


def _decl_string(stmt, name):
    s = stmt.strip()
    if not s.endswith(';'):
        s += ';'
    namen = _decl_names(s)
    if len(namen) == 1:
        return s
    for typ, n in namen:
        if n == name:
            if not typ or typ == '?':
                return ''
            return decl_text(typ, name)
    return ''


def _for_init_text(text, i):
    k, j = _ident_at(text, i)
    if k != 'for':
        return None
    p = _skip(text, j)
    if p >= len(text) or text[p] != '(':
        return None
    inner = p + 1
    d = 1
    q = inner
    while q < len(text) and d:
        if text.startswith('//', q) or text.startswith('/*', q) or text[q] in '"\'':
            if text[q] in '"\'':
                q = _skip_str(text, q)
            elif text.startswith('//', q):
                nl = text.find('\n', q)
                q = len(text) if nl < 0 else nl + 1
            else:
                nl = text.find('*/', q + 2)
                q = len(text) if nl < 0 else nl + 2
            continue
        if text[q] == '(':
            d += 1
        elif text[q] == ')':
            d -= 1
        elif text[q] == ';' and d == 1:
            return text[inner:q].strip()
        q += 1
    return None


def deklarations_index(text):
    """Name -> Deklarationsanweisung, auch in Bloecken und for-Koepfen. Erste gewinnt."""
    idx = {}
    if not text:
        return idx

    def merke(stmt):
        chunk = stmt.strip()
        if not chunk:
            return
        probe = chunk if chunk.endswith(';') else chunk + ';'
        if not _is_decl(probe):
            return
        for _typ, name in _decl_names(probe):
            if name in idx or name in KW_STMT or name in TYPE_KW:
                continue
            zeile = _decl_string(probe, name)
            if zeile:
                idx[name] = zeile

    i = 0
    n = len(text)
    start = 0
    dparen = 0
    # struct/union/enum/class-Rumpf: Felder sind keine Lokalen.
    skip_brace = 0
    while i < n:
        if text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
            continue
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        c = text[i]
        if c in '"\'':
            i = _skip_str(text, i)
            continue
        if c == '{':
            pre = text[start:i].strip()
            ist_typrumpf = bool(re.search(r'\b(struct|union|enum|class)\b', pre)) and not pre.endswith(')')
            if ist_typrumpf or skip_brace:
                skip_brace += 1
            else:
                start = i + 1
        elif c == '}':
            if skip_brace:
                skip_brace -= 1
            else:
                start = i + 1
        elif c == '(' and skip_brace == 0:
            dparen += 1
        elif c == ')' and skip_brace == 0:
            dparen = max(0, dparen - 1)
        elif c == ';' and dparen == 0 and skip_brace == 0:
            merke(text[start:i + 1])
            start = i + 1
        elif c == ';' and dparen == 1 and skip_brace == 0:
            # for (int i = 0; ...) Der Initialisierer endet am ersten Semikolon in der Klammer.
            kopf = text[start:i]
            if re.search(r'\bfor\s*\([^;]*$', kopf):
                merke(kopf[kopf.rfind('(') + 1:])
        i += 1
    return idx


def _parameter_namen(signatur):
    m = re.search(r'\((.*)\)', signatur or '', re.S)
    if not m:
        return set()
    namen = set()
    for st in m.group(1).split(','):
        ids = [x for x in re.findall(r'[A-Za-z_]\w*', st) if x not in TYPE_KW and x not in ('struct', 'class')]
        if ids:
            namen.add(ids[-1])
    return namen


def noetige_deklarationen(basis_text, spender_text, sec_text, makro_texte):
    """Deklarationen, die der eingesetzte Abschnitt braucht und die Basis nicht hat.

    Makros wie `#define END return r` werden vorher expandiert, sonst sieht der
    Abschnitt den Namen r nicht. Deklarationen in Bloecken des Spenders zaehlen mit.
    """
    makros = {}
    for t in makro_texte or []:
        makros.update(objekt_makros(t))
    verwendet = _idents(expand_objekt(sec_text or '', makros))
    basis_idx = deklarations_index(basis_text)
    sec_idx = deklarations_index(sec_text)
    sp_idx = deklarations_index(spender_text)
    habe = set(basis_idx) | set(sec_idx)
    extra = []
    warteschlange = []
    for n in verwendet:
        if n in habe or n in KW_STMT or n in TYPE_KW or n not in sp_idx:
            continue
        warteschlange.append(n)
    gesehen = set()
    while warteschlange:
        n = warteschlange.pop(0)
        if n in gesehen or n in habe:
            continue
        gesehen.add(n)
        decl = sp_idx[n]
        if not decl or decl.strip().startswith('?'):
            continue
        extra.append(decl)
        habe.add(n)
        for m in _idents(expand_objekt(decl, makros)):
            if m in habe or m in gesehen or m in KW_STMT or m in TYPE_KW or m not in sp_idx:
                continue
            warteschlange.append(m)
    return extra


def _felder(decl):
    return set(re.findall(r'\b([A-Za-z_]\w*)\b', decl or ''))


def gleiche_struct_decls(fn_text, quellen):
    """Ersetzt eine lokale Struktur, wenn der Text ein Feld nutzt, das sie nicht hat."""
    if not fn_text:
        return fn_text
    idx = deklarations_index(fn_text)
    zugriffe = re.findall(r'\b([A-Za-z_]\w*)\s*(?:\.|->)\s*([A-Za-z_]\w*)', fn_text)
    if not zugriffe:
        return fn_text
    indizes = [deklarations_index(t) for t in quellen or [] if t]
    text = fn_text
    gesehen = set()
    for var, feld in zugriffe:
        if var in gesehen:
            continue
        alt = idx.get(var) or ''
        if not alt or feld in _felder(alt):
            continue
        neu = None
        for qi in indizes:
            cand = qi.get(var) or ''
            if cand and feld in _felder(cand) and re.search(r'\b(struct|union)\b', cand):
                neu = cand if cand.endswith(';') else cand + ';'
                break
        if not neu or neu == alt:
            continue
        if alt not in text:
            continue
        text = text.replace(alt, neu, 1)
        gesehen.add(var)
    return text


def deklarationen_fuer_text(fn_text, fkt, quellen, makro_texte=None):
    """Lokale, die der gebaute Text benutzt und nicht deklariert.

    Gesucht wird in den Spender- und Basistexten. Struct-Felder und unbekannte
    Typen werden nicht erfunden.
    """
    if not fn_text:
        return []
    makros = {}
    for t in list(makro_texte or []) + list(quellen or []):
        makros.update(objekt_makros(t or ''))
    verwendet = _idents(expand_objekt(fn_text, makros))
    fn = parse_funktion(fn_text, fkt) or parse_funktion('//@ ' + fkt + '\n' + fn_text, fkt)
    habe = set(deklarations_index(fn_text))
    if fn:
        habe |= _parameter_namen(fn.signatur)
        habe |= {n for _, n in fn.lokale}
    indizes = []
    for t in quellen or []:
        if t:
            indizes.append(deklarations_index(t))
    felder_von = {}
    for var, feld in re.findall(r'\b([A-Za-z_]\w*)\s*(?:\.|->)\s*([A-Za-z_]\w*)', fn_text):
        felder_von.setdefault(var, set()).add(feld)
    extra = []
    for name in verwendet:
        if (name in habe or name in KW_STMT or name in TYPE_KW or name.startswith('f_')):
            continue
        decl = None
        braucht = felder_von.get(name) or set()
        beste = -1
        for idx in indizes:
            cand = idx.get(name) or ''
            if not cand or cand.strip().startswith('?'):
                continue
            if not braucht:
                decl = cand
                break
            treffer = sum(1 for f in braucht if f in _felder(cand))
            if treffer > beste and treffer > 0:
                decl, beste = cand, treffer
        if not decl:
            continue
        extra.append(decl if decl.endswith(';') else decl + ';')
        habe.add(name)
    return extra


def fehlende_defines(sec_text, unit_text, spender_texte):
    """#define-Zeilen, die der Abschnitt benutzt und die Einheit nicht hat."""
    habe = definier_zeilen(unit_text)
    benutzt = _idents(sec_text or '')
    extra = []
    gesehen = set()
    for sp in spender_texte or []:
        for name, zeile in definier_zeilen(sp).items():
            if name in habe or name not in benutzt or name in gesehen:
                continue
            gesehen.add(name)
            extra.append(zeile)
    return extra


def fehlende_symbole(ausgabe):
    return re.findall(r"symbol '([A-Za-z_]\w*)' has not been declared", ausgabe or '')


def prolog_stellungen(fn_text, fkt, grenze=6):
    """Dieselbe Funktion mit umgestellten Prolog-Deklarationen.

    Die Stellung der Lokalen aendert bei Watcom Stapelplaetze und Register.
    """
    fn = parse_funktion(fn_text, fkt) or parse_funktion('//@ ' + fkt + '\n' + fn_text, fkt)
    if fn is None:
        return []
    sec = next((s for s in fn.abschnitte if s.key == 'K_PROLOG'), None)
    if sec is None:
        return []
    decls = [s for s in _decl_stmts(sec.text) if _is_decl(s if s.endswith(';') else s + ';')]
    if len(decls) < 2:
        return []
    roh = [
        list(reversed(decls)),
        decls[-1:] + decls[:-1],
        decls[1:] + decls[:1],
    ]
    if len(decls) >= 3:
        roh.append([decls[1], decls[0]] + decls[2:])
        roh.append(decls[::2] + decls[1::2])
    out = []
    gesehen = {re.sub(r'\s+', '', fn.text)}
    for st in roh:
        if len(out) >= grenze:
            break
        block = '\n    '.join(s.strip() for s in st)
        neu = baue(fn, {'K_PROLOG': '\n    ' + block + '\n'})
        if not neu:
            continue
        k = re.sub(r'\s+', '', neu)
        if k in gesehen:
            continue
        gesehen.add(k)
        out.append(neu)
    return out


def mit_deklarationen(fn_text, fkt, decls):
    """Haengt fehlende Deklarationen an den Prolog. Schon vorhandene Namen bleiben."""
    if not decls:
        return fn_text
    fn = parse_funktion(fn_text, fkt) or parse_funktion('//@ ' + fkt + '\n' + fn_text, fkt)
    if fn is None:
        return fn_text
    habe = {n for _, n in fn.lokale} | _parameter_namen(fn.signatur)
    neu = []
    for d in decls:
        probe = d.strip()
        if not probe.endswith(';'):
            probe += ';'
        namen = [n for _, n in _decl_names(probe)]
        if namen and all(n in habe for n in namen):
            continue
        neu.append(probe)
        habe.update(namen)
    if not neu:
        return fn_text
    return prolog_mit(fn, neu, 'ende') or fn_text


def repariere_fehlende(unit_text, fkt, ausgabe, texte):
    """Fehlende Bezeichner aus Spendertexten oder Makro-Ruempfen in die Funktion setzen.

    Rueckgabe (neuer Einheitstext oder None, anzahl ergaenzter Namen).
    """
    symbole = fehlende_symbole(ausgabe)
    if not symbole or not unit_text:
        return None, 0
    fn = parse_funktion(unit_text, fkt)
    if not fn:
        return None, 0
    habe = {n for _, n in fn.lokale} | _parameter_namen(fn.signatur) | set(deklarations_index(fn.text))
    makros = objekt_makros(unit_text)
    for t in texte or []:
        makros.update(objekt_makros(t))
    makro_namen = set()
    for body in makros.values():
        for ident in _idents(body):
            if ident not in TYPE_KW and ident not in KW_STMT:
                makro_namen.add(ident)
    decls = []
    for name in symbole:
        if name in habe or name in KW_STMT or name in TYPE_KW:
            continue
        gefunden = None
        for t in [fn.text] + list(texte or []):
            if not t:
                continue
            idx = deklarations_index(t)
            if name in idx:
                gefunden = idx[name]
                break
        if gefunden is None and name in makro_namen and not name.startswith('f_') and len(name) <= 32:
            gefunden = decl_text('int', name)
        if not gefunden or str(gefunden).strip().startswith('?'):
            continue
        decls.append(gefunden)
        habe.add(name)
    if not decls:
        return None, 0
    neu_fn = prolog_mit(fn, decls, 'ende')
    if not neu_fn:
        return None, 0
    neu_unit = setze_funktion(unit_text, fkt, neu_fn)
    if not neu_unit or neu_unit == unit_text:
        return None, 0
    return neu_unit, len(decls)


def konflikt_lokale(basis, spender_fn, sec_text):
    """Fehlende Deklarationen oder Namenskonflikt. Rueckgabe (extra, konflikt).

    Fehlende Namen werden geliefert, nicht als Abbruch gewertet. Ein echter
    Typkonflikt bleibt als Hinweis, verwirft den Abschnitt aber nicht mehr:
    die Deklaration der Basis bleibt, der Name wird nicht ein zweites Mal angelegt.
    """
    extra = noetige_deklarationen(basis.text, spender_fn.text, sec_text, [basis.text, spender_fn.text])
    habe = {n: t for t, n in basis.lokale}
    fremd = {n: t for t, n in spender_fn.lokale}
    konflikt = None
    for n, t in fremd.items():
        if n in habe and re.sub(r'\s+', ' ', habe[n]) != re.sub(r'\s+', ' ', t):
            konflikt = n
            break
    return extra, konflikt


def helfer_zeilen(dateitext, namen, basis_text):
    """Deklarationen/Definitionen aus der Spenderdatei, die die Basis nicht hat."""
    if not namen:
        return []
    zeilen = []
    for name in namen:
        if name in ('if', 'for', 'while', 'switch', 'return'):
            continue
        if re.search(r'\b' + re.escape(name) + r'\b', basis_text):
            continue
        # eine Definitions- oder Deklarationszeile
        m = re.search(r'(?m)^[^\n]*\b' + re.escape(name) + r'\s*\([^;{]*\)\s*[{;]', dateitext)
        if not m:
            continue
        # wenn { dann ganze Funktion mitnehmen, sofern klein
        if m.group(0).rstrip().endswith('{'):
            # start at line
            line = dateitext.rfind('\n', 0, m.start()) + 1
            br = dateitext.find('{', m.start())
            if br < 0:
                continue
            end = _balanced(dateitext, br, '{', '}')
            chunk = dateitext[line:end].strip()
            if chunk.count('\n') <= 80:
                zeilen.append(chunk)
        else:
            zeilen.append(m.group(0).strip())
    return zeilen


def verbotener_code(text):
    if re.search(r'\b__asm\b|\basm\s*\{', text):
        return 'inline-asm'
    if re.search(r'#\s*pragma\s+aux\b[^;\n]*=\s*"', text):
        return 'pragma-code'
    return ''


# ---------- Messen ----------

def _obj_pubs_and_code(obj):
    import struct
    import sys
    if GW not in sys.path:
        sys.path.insert(0, GW)
    import omf
    d = open(obj, 'rb').read()
    pubs = []
    i = 0
    while i + 3 < len(d):
        ty = d[i]
        if ty == 0xF1:
            break
        L = struct.unpack_from('<H', d, i + 1)[0]
        b = d[i + 3:i + 2 + L]
        if ty in (0x90, 0x91) and b:
            j = 1 if b[0] < 0x80 else 2
            if j < len(b):
                j += 1 if b[j] < 0x80 else 2
            while j < len(b):
                l = b[j]
                if j + 1 + l > len(b):
                    break
                nm = b[j + 1:j + 1 + l].decode('latin1', 'replace')
                j += 1 + l
                if j + (4 if ty & 1 else 2) > len(b):
                    break
                off = struct.unpack_from('<I' if ty & 1 else '<H', b, j)[0]
                j += 4 if ty & 1 else 2
                if j >= len(b):
                    break
                j += 1 if b[j] < 0x80 else 2
                pubs.append((off, nm))
        i += 3 + L
    mo = omf.modules(obj)[0]
    cs = [x for x in mo['segs'].values() if x.get('cls') == 'CODE' and x.get('data')]
    if not cs:
        return pubs, b''
    sg = max(cs, key=lambda x: len(x['data']))
    return pubs, bytes(sg['data'])


def code_segment(obj):
    _, data = _obj_pubs_and_code(obj)
    return data


def _funktions_grenzen(obj, fkt):
    want = fkt.replace('f_', '').lower()
    pubs, data = _obj_pubs_and_code(obj)
    if not data:
        return None, None, b''
    marks = []
    for off, nm in pubs:
        m = re.search(r'f_([0-9a-fA-F]{4,8})', nm)
        if m:
            marks.append((off, m.group(1).lower()))
    marks.sort()
    start = end = None
    for i, (off, nm) in enumerate(marks):
        if nm == want:
            start = off
            end = marks[i + 1][0] if i + 1 < len(marks) else len(data)
            break
    if start is None and len(marks) == 1:
        start, end = marks[0][0], len(data)
    if start is None:
        return None, None, data
    return start, end, data


def obj_asm(obj, fkt):
    """Befehle einer Funktion aus einem OBJ (objdump, intel)."""
    start, end, data = _funktions_grenzen(obj, fkt)
    if start is None:
        return []
    blob = data[start:end]
    fd, name = tempfile.mkstemp(prefix='mischer_', suffix='.bin')
    os.write(fd, blob)
    os.close(fd)
    try:
        r = subprocess.run(['objdump', '-D', '-b', 'binary', '-mi386', '-Mintel', name],
                           capture_output=True, text=True)
    finally:
        os.unlink(name)
    return load_objdump_text(r.stdout)


def emu_compile(src, obj, extra_opt=None, timeout=120):
    """Watcom im Emulator. extra_opt z. B. ['-d1']. Rueckgabe (ok, ausgabe)."""
    fd, script = tempfile.mkstemp(prefix='mischer_emu_', suffix='.py', dir=tempfile.mkdtemp(prefix='mischer_'))   # 06.11. Claude: eigener Ordner - fremde struct.py in /tmp verdeckte die Standardbibliothek
    os.close(fd)
    open(script, 'w', encoding='utf-8').write(
        'import os,sys\n'
        f'sys.path[:0]=[os.path.expanduser("~/.w106_pylib"), {EMU!r}]\n'
        'from comp import comp, kopf\n'
        'opt=list(kopf(sys.argv[1])[1])\n'
        'extra=sys.argv[3].split() if len(sys.argv)>3 and sys.argv[3] else []\n'
        'for x in extra:\n'
        '    if x not in opt: opt.append(x)\n'
        'ok,out,e=comp(sys.argv[1], sys.argv[2], extra=opt)\n'
        'sys.stdout.write("OK\\n" if ok else "FAIL\\n")\n'
        'sys.stdout.write(out[-800:])\n'
    )
    env = os.environ.copy()
    env['PYTHONPATH'] = PYLIB + os.pathsep + env.get('PYTHONPATH', '')
    cmd = ['python3', script, src, obj]
    if extra_opt:
        cmd.append(' '.join(extra_opt))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return False, 'timeout'
    finally:
        os.unlink(script)
    out = (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')
    return out.startswith('OK'), out


def parse_stand(text):
    """Adresse (klein) -> Rest in Befehlen. GLEICH = 0."""
    funs = {}
    for line in text.splitlines():
        m = re.match(r'^([0-9A-Fa-f]{4,8})\s+\d+/\d+\s+(\d+)\s+Befehle', line)
        if m:
            funs[m.group(1).lower()] = int(m.group(2))
            continue
        m = re.match(r'^([0-9A-Fa-f]{4,8})\s+\d+/\d+\s+GLEICH\b', line)
        if m:
            funs[m.group(1).lower()] = 0
    return funs


def nativ(einheit, datei, fkt, timeout=300):
    """probe_queue. Entscheidungsmass. Nie parallel mit derselben WORKER_ID (das Skript sperrt)."""
    env = os.environ.copy()
    env['WORKER_ID'] = WORKER_ID
    r = subprocess.run(['python3', PROBE_Q, einheit, datei, fkt], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=timeout)
    text = (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')
    stand = parse_stand(text)
    key = fkt.replace('f_', '').lower()
    rest = stand.get(key)
    if rest is None and 'NICHT UEBERSETZT' in text:
        rest = None
    groesse_verloren = False
    if rest:   # Regel der Uebernahme (uebernahmeschutz.compare): hat p3 die Originalgroesse, darf ein Kandidat sie nicht verlieren
        g = _groessen(text).get(key)
        b = _groessen_p3(einheit).get(key)
        if g and b and ((b[0] == b[1] and g[0] != g[1]) or g[0] != b[0]):   # 07.11. Claude: wie uebernahmeschutz.compare auch 'Originalgroesse veraendert'
            groesse_verloren = True
            rest = None
    return {'rest': rest, 'stand': stand, 'text': text, 'rc': r.returncode, 'groesse_verloren': groesse_verloren}


def _groessen(text):
    """Adresse (klein) -> (Originalbytes, uebersetzte Bytes) aus Richterausgabe."""
    out = {}
    for line in text.splitlines():
        m = re.match(r'^([0-9A-Fa-f]{4,8})\s+(\d+)/(\d+)\s', line)
        if m:
            out[m.group(1).lower()] = (int(m.group(2)), int(m.group(3)))
    return out


def _groessen_p3(einheit):
    try:
        qs = [x for x in (os.path.join(LIVE, einheit + '.fstand'), os.path.join(P3, einheit + '_P1.fstand')) if os.path.exists(x)]
        return _groessen(open(max(qs, key=os.path.getmtime), encoding='latin-1').read())   # 05.11.: neuere Messung gilt
    except OSError:
        return {}


def gesperrt(einheit):
    if not os.path.isfile(SPERREN):
        return False
    jetzt = time.time()
    for l in open(SPERREN, encoding='utf-8', errors='replace'):
        p = l.rstrip('\n').split('\t')
        if len(p) < 4 or p[2] != einheit:
            continue
        try:
            bis = float(p[3])
        except ValueError:
            bis = jetzt + 1
        if bis > jetzt:
            return True
    return False


def asm_verbucht(fkt):
    if not os.path.isfile(ASM_VERBUCHT):
        return False
    try:
        a = int(fkt.replace('f_', ''), 16)
    except ValueError:
        return False
    for l in open(ASM_VERBUCHT, encoding='utf-8', errors='replace'):
        if l.startswith('#') or not l.strip():
            continue
        z = l.split('\t')
        if len(z) < 2:
            continue
        try:
            lo, hi = int(z[0], 16), int(z[1], 16)
        except ValueError:
            continue
        if lo <= a < hi:
            return True
    return False


# ---------- Bewertung je Abschnitt ----------

def d1_erlaubt():
    """E0: -d1 laesst das CODE-Segment unveraendert. Nur dann zur Zuordnung."""
    p = os.path.join(HERE, 'eichung', 'e0.json')
    if not os.path.isfile(p):
        return False
    try:
        return json.load(open(p)).get('aendert_code') is False
    except (OSError, KeyError, ValueError):
        return False


def linnum_pairs(obj):
    """(Quellzeile, Segmentoffset) aus OMF 0x94/0x95."""
    import struct
    d = open(obj, 'rb').read()
    i = 0
    pairs = []
    while i + 3 < len(d):
        t = d[i]
        if t == 0xF1:
            break
        L = struct.unpack_from('<H', d, i + 1)[0]
        c = d[i + 3:i + 2 + L]
        if t in (0x94, 0x95) and len(c) >= 2:
            width = 4 if t == 0x95 else 2
            p = 2
            while p + 2 + width <= len(c):
                line = struct.unpack_from('<H', c, p)[0]
                off = struct.unpack_from('<I' if width == 4 else '<H', c, p + 2)[0]
                if 1 <= line < 20000:
                    pairs.append((line, off))
                p += 2 + width
        if L == 0:
            break
        i += 3 + L
    return pairs


def zeilen_zuordnung(obj, fkt, unit, fn):
    """Befehlsadresse (im Funktionsblob) -> Abschnittschluessel, ueber -d1-Zeilen."""
    start, end, _ = _funktions_grenzen(obj, fkt)
    if start is None:
        return None
    rel = sorted((off - start, line) for line, off in linnum_pairs(obj) if start <= off < end)
    if not rel:
        return None
    sp = _function_span(unit, fkt)
    if not sp:
        return None
    base = unit[:sp[0]].count('\n') + 1
    ranges = []
    pos = 0
    for sec in fn.abschnitte:
        k = fn.text.find(sec.text, pos)
        if k < 0:
            continue
        ls = base + fn.text[:k].count('\n')
        le = base + fn.text[:k + len(sec.text)].count('\n')
        ranges.append((ls, le, sec.key))
        pos = k + len(sec.text)

    def key_fuer(addr):
        line = None
        for off, ln in rel:
            if off <= addr:
                line = ln
            else:
                break
        if line is None:
            return None
        for a, b, key in ranges:
            if a <= line <= b:
                return key
        return None

    return key_fuer


def bewerte(fn, orig_ins, neu_ins, zeilen=None):
    """Abschnitt -> {dist, dist_struct, status}. Fallvergleich, sonst Zeilen, sonst Konstanten."""
    ergebnis = {}
    reg = _dispatch_reg(orig_ins)
    values = []
    for sec in fn.abschnitte:
        if sec.kind == 'case':
            for lab in sec.labels:
                if isinstance(lab, int):
                    values.append(lab)
    fall = {}
    if reg and values:
        try:
            for v, st, d, ds in zaehl_faelle(orig_ins, neu_ins, values, reg):
                fall[v] = (st, d, ds)
        except (ValueError, KeyError, IndexError):
            fall = {}
    ganz = align_dist(orig_ins, neu_ins)
    # nicht-gleiche Befehle der neuen Fassung den Abschnitten zuordnen
    opcodes = ganz['opcodes']
    Braw = [t for _, t in neu_ins]
    schlecht = set()
    for op, i1, i2, j1, j2 in opcodes:
        if op == 'equal':
            continue
        for j in range(j1, j2):
            schlecht.add(j)
    attr = {sec.key: [] for sec in fn.abschnitte}
    rest_idx = []
    for j in schlecht:
        if j >= len(neu_ins):
            continue
        if zeilen is not None:
            key = zeilen(neu_ins[j][0])
            if key in attr:
                attr[key].append(j)
                continue
        raw = Braw[j]
        nums = set(re.findall(r'0x[0-9a-f]+|\b\d+\b', raw.lower()))
        nums |= {str(int(x, 16)) if x.startswith('0x') else x for x in list(nums) if x.startswith('0x') or x.isdigit()}
        best = None
        bests = 0
        for sec in fn.abschnitte:
            sc = len(nums & {c.lower() for c in sec.consts})
            calls = [c.lower() for c in sec.calls]
            if any(len(c) > 3 and c[2:] in raw and c.startswith('f_') for c in calls):
                sc += 2
            if sc > bests:
                best, bests = sec, sc
        if best is not None and bests > 0:
            attr[best.key].append(j)
        else:
            rest_idx.append(j)
    for sec in fn.abschnitte:
        if sec.kind == 'case' and fall:
            ds = [fall[v] for v in sec.labels if isinstance(v, int) and v in fall]
            if ds:
                st = 'OK' if all(x[0] == 'OK' for x in ds) else ('REG' if all(x[0] != 'STRUKT' for x in ds) else 'STRUKT')
                # Fallvergleich-Spur laeuft in gemeinsame Enden. Zum Mischen zaehlt die Zeile, wenn -d1 sie liefert.
                lokal = len(attr[sec.key]) if zeilen is not None else sum(x[2] for x in ds)
                ergebnis[sec.key] = {'dist': sum(x[1] for x in ds), 'dist_struct': lokal,
                                     'status': st, 'quelle': 'zeilen' if zeilen is not None else 'fallvgl'}
                continue
        d = len(attr[sec.key])
        # Struktur: gleiche Zuordnung auf register-normalisierter Sicht ist hier nicht getrennt verfuegbar.
        # dist_struct = 0 wenn der Fallvergleich fehlt und keine Konstanten-Abweichung liegt.
        ergebnis[sec.key] = {'dist': d, 'dist_struct': d, 'status': 'OK' if d == 0 else 'STRUKT',
                             'quelle': 'zeilen' if zeilen is not None else 'konstanten'}
    ergebnis['_GANZ'] = {'dist': ganz['dist'], 'dist_struct': ganz['dist_struct'],
                         'orig_befehle': ganz['orig_befehle'], 'neu_befehle': ganz['neu_befehle'],
                         'status': 'OK' if ganz['dist'] == 0 else 'STRUKT'}
    ergebnis['_REST'] = {'dist': len(rest_idx), 'dist_struct': len(rest_idx), 'status': 'OK' if not rest_idx else 'STRUKT'}
    return ergebnis


def matrix_zeilen(fassungen_bew):
    """fassungen_bew: liste (name, bewertung)."""
    keys = []
    for name, bew in fassungen_bew:
        for k in bew:
            if k not in keys and not k.startswith('_'):
                keys.append(k)
    zeilen = ['abschnitt\t' + '\t'.join(n for n, _ in fassungen_bew)]
    for k in keys:
        z = [k]
        for name, bew in fassungen_bew:
            b = bew.get(k)
            z.append('' if not b else f"{b['status']}:{b['dist']}")
        zeilen.append('\t'.join(z))
    return '\n'.join(zeilen) + '\n'


# ---------- Ernte ----------

FASSUNG_GLOBS = ('*.CPP', '*.cpp', '*.c', '*.cc', '*.cxx')


def _walk_dateien(muster, wurzeln):
    dateien = []
    for w in wurzeln:
        if not os.path.isdir(w):
            continue
        for dirpath, dirnames, filenames in os.walk(w):
            dirnames[:] = [d for d in dirnames if d not in ('sicherung', '__pycache__', '.git', 'node_modules')]
            if os.path.basename(dirpath) == 'worker':
                dirnames[:] = [d for d in dirnames if d != 'ernte']
            for fn in filenames:
                if not fn.lower().endswith(('.cpp', '.c', '.cc')):
                    continue
                pf = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(pf) > 2_500_000:
                        continue
                except OSError:
                    continue
                dateien.append(pf)
    # Inhalt erst in sammle pruefen
    return [p for p in dateien if muster in open(p, encoding='latin1', errors='replace').read()]


def _rg_bin():
    p = shutil.which('rg')
    if p:
        return p
    cand = '/usr/lib/node_modules/@openai/worker/node_modules/@openai/worker-linux-x64/vendor/x86_64-unknown-linux-musl/worker-path/rg'
    return cand if os.path.isfile(cand) else None


def _rg_dateien(muster, wurzeln):
    rg = _rg_bin()
    if not rg:
        return _walk_dateien(muster, wurzeln)
    cmd = [rg, '-l', '-g', '*.CPP', '-g', '*.cpp', '-g', '*.c', '-g', '*.cc', '--glob', '!**/sicherung/**',
           '--glob', '!**/__pycache__/**', '--glob', '!**/harvest/**', '-F', muster]
    # mehrere Muster nicht. Eine Suche.
    dateien = []
    for w in wurzeln:
        if not os.path.isdir(w):
            continue
        r = subprocess.run(cmd + [w], capture_output=True, text=True)
        for line in (r.stdout or '').splitlines():
            if line:
                dateien.append(line)
    return dateien


def sammle(einheit, fkt, extra_wurzeln=None):
    """Alle Fassungen der Funktion. Dubletten per Hash des Rumpfes weg."""
    wurzeln = [
        os.path.join(ROOT, 'Blind', 'arbeit'),
        os.path.join(ROOT, 'Flick', 'arbeit'),   # 04.11.: Flickmodus-Fassungen mit ernten
        os.path.join(PC.resolve_path('logs_dir', _CFG), 'work_pool'),
        os.path.join(PC.resolve_path('logs_dir', _CFG), 'worker_drafts'),
        os.path.join(PC.resolve_path('logs_dir', _CFG), 'candidates_archive'),
        os.path.join(ROOT, 'Analyse', 'Pass2', 'anordnungen', einheit),
        os.path.join(ROOT, 'Quelle', 'cpp', 'p1'),
        os.path.join(ROOT, 'Quelle', 'cpp', 'p2'),
        os.path.join(ROOT, 'Quelle', 'cpp', 'p3'),
        os.path.join(ROOT, 'Quelle', 'ghidra_2910'),
    ]
    if extra_wurzeln:
        wurzeln.extend(extra_wurzeln)
    # gezielte Datei der Einheit zuerst, dann Textsuche
    kandidaten = []
    for stufe in ('p3', 'p2', 'p1'):
        p = os.path.join(ROOT, 'Quelle', 'cpp', stufe, f'{einheit}_P1.CPP')
        if os.path.isfile(p):
            kandidaten.append(p)
    ghidra = os.path.join(ROOT, 'Quelle', 'ghidra_2910', f'{einheit}.c')
    if os.path.isfile(ghidra):
        kandidaten.append(ghidra)
    kandidaten.extend(_rg_dateien(fkt, wurzeln))
    gesehen = set()
    funde = []
    for pfad in kandidaten:
        if pfad in gesehen:
            continue
        gesehen.add(pfad)
        try:
            if os.path.getsize(pfad) > 2_500_000:
                continue
            text = open(pfad, encoding='latin1', errors='replace').read()
        except OSError:
            continue
        if fkt not in text:
            continue
        fn = parse_funktion(text, fkt, pfad)
        if not fn or len(fn.text) < 20:
            continue
        h = hashlib.sha1(re.sub(r'\s+', '', fn.text).encode('latin1', 'replace')).hexdigest()
        ghid = 'ghidra' if 'ghidra' in pfad.replace('\\', '/') else ''
        funde.append({'hash': h, 'pfad': pfad, 'fn': fn, 'text': text, 'ghidra': ghid,
                      'signatur': signatur_kern(fn.signatur)})
    # Dubletten
    uniq = {}
    for f in funde:
        uniq.setdefault(f['hash'], f)
    return list(uniq.values())


def schreibe_ernte(einheit, fkt, funde):
    ordner = os.path.join(HERE, 'ernte', f'{einheit}_{fkt}')
    os.makedirs(ordner, exist_ok=True)
    zeilen = ['hash\tsignatur\tghidra\tpfad\tabschnitte']
    for i, f in enumerate(funde):
        name = f'f{i:03d}.cpp'
        open(os.path.join(ordner, name), 'w', encoding='latin1', errors='replace').write(f['fn'].text)
        if f['ghidra']:
            open(os.path.join(ordner, name + '.ghidra'), 'w').write('ghidra\n')
        zeilen.append(f"{f['hash'][:12]}\t{f['signatur']}\t{f['ghidra'] or '-'}\t{f['pfad']}\t{len(f['fn'].abschnitte)}")
        f['ernte'] = name
    open(os.path.join(ordner, 'LISTE.tsv'), 'w', encoding='utf-8').write('\n'.join(zeilen) + '\n')
    return ordner


# ---------- Kreuzen ----------

def _basis_waehlen(fassungen, bew, basis_pfad):
    if basis_pfad:
        for f in fassungen:
            if os.path.abspath(f['pfad']) == os.path.abspath(basis_pfad) or f['pfad'].endswith(basis_pfad):
                return f
    # kleinste Ganz-Distanz, dann kuerzester Text
    def key(f):
        b = bew.get(f['hash'], {})
        g = b.get('_GANZ', {})
        return (g.get('dist', 10**9), len(f['fn'].text))
    return min(fassungen, key=key)


def waehle_spender(bew, fassungen):
    """Je Abschnitt die Fassung mit kleinster Strukturdistanz, dann Exaktdistanz."""
    keys = []
    by_hash = {f['hash']: f for f in fassungen}
    for f in fassungen:
        for sec in f['fn'].abschnitte:
            if sec.key not in keys:
                keys.append(sec.key)
    wahl = {}
    for k in keys:
        best = None
        bestv = (10**9, 10**9)
        for f in fassungen:
            b = bew.get(f['hash'], {}).get(k)
            if not b:
                continue
            v = (b.get('dist_struct', 10**9), b.get('dist', 10**9))
            if v < bestv:
                bestv = v
                best = f
        if best is not None:
            wahl[k] = best
    return wahl


def misch_quelltext(basis, fassungen, wahl, basis_unit):
    """Baut den Funktionstext. Liefert (text, notizen, verworfen)."""
    notizen = []
    verworfen = []
    ersatz = {}
    extras = []
    by_hash = {f['hash']: f for f in fassungen}
    for sec in basis['fn'].abschnitte:
        sp = wahl.get(sec.key)
        if sp is None or sp['hash'] == basis['hash']:
            continue
        if not gleiche_signatur(basis['fn'], sp['fn']):
            verworfen.append((sec.key, 'signatur'))
            continue
        fremd = next((s for s in sp['fn'].abschnitte if s.key == sec.key), None)
        if fremd is None:
            continue
        if fremd.verboten:
            verworfen.append((sec.key, fremd.verboten))
            continue
        if not fremd.balanced:
            verworfen.append((sec.key, 'klammern'))
            continue
        extra = noetige_deklarationen(
            basis['fn'].text, sp['fn'].text, fremd.text,
            [basis_unit, sp.get('text', ''), basis['text']])
        # Helfer und Defines, die nur der Spender hat (END, CX, ...)
        calls = [c for c in fremd.calls if c.startswith('f_') or c[:1].isupper()]
        helfer = helfer_zeilen(sp['text'], calls, basis_unit)
        helfer = list(helfer) + fehlende_defines(fremd.text, basis_unit, [sp.get('text', '')])
        if any(verbotener_code(h) for h in helfer):
            verworfen.append((sec.key, 'helfer-verboten'))
            continue
        ersatz[sec.key] = fremd.text
        extras.extend(helfer)
        if extra:
            notizen.append((sec.key, extra, sp))
        if fremd.kruecke:
            notizen.append((sec.key, 'kruecke', sp['pfad']))
    text = baue(basis['fn'], ersatz)
    if text is None:
        return None, notizen, verworfen + [('*', 'spanne')], []
    text = gleiche_struct_decls(
        text, [basis['fn'].text] + [f['fn'].text for f in fassungen]) or text
    # fehlende Deklarationen an den Prolog (Ende). Positionen probiert der Aufrufer.
    decl = []
    for item in notizen:
        if isinstance(item[1], list):
            decl.extend(item[1])
    if decl:
        # in den schon gebauten Text parsen und Prolog ergaenzen
        tmp = parse_funktion(text, basis['fn'].name)
        if tmp:
            neu = prolog_mit(tmp, decl, 'ende')
            if neu:
                text = neu
                notizen.append(('K_PROLOG', 'decls+' + str(len(decl)), 'ende'))
    mehr = deklarationen_fuer_text(
        text, basis['fn'].name,
        [basis['fn'].text] + [f['fn'].text for f in fassungen],
        [basis_unit] + [f.get('text') or '' for f in fassungen])
    if mehr:
        tmp = parse_funktion(text, basis['fn'].name)
        if tmp:
            neu = prolog_mit(tmp, mehr, 'ende')
            if neu:
                text = neu
                notizen.append(('K_PROLOG', 'rest+' + str(len(mehr)), 'ende'))
    text = gleiche_struct_decls(
        text, [basis['fn'].text] + [f['fn'].text for f in fassungen]) or text
    # Helfer vor die Funktion, der Aufrufer setzt in die Einheit
    return text, notizen, verworfen, extras


def decl_varianten(fn_text, fkt, decls):
    """Dieselbe Funktion mit den neuen Deklarationen an verschiedenen Prologstellen."""
    fn = parse_funktion(fn_text if fn_text.strip().startswith('//') or ' ' in fn_text[:1] else fn_text, fkt)
    # fn_text ist der Funktionstext
    fn = parse_funktion('//@ ' + fkt + '\n' + fn_text, fkt) if parse_funktion(fn_text, fkt) is None else parse_funktion(fn_text, fkt)
    if fn is None or not decls:
        return [fn_text]
    sec = next((s for s in fn.abschnitte if s.key == 'K_PROLOG'), None)
    n = len(_decl_stmts(sec.text)) if sec else 0
    stellen = list(range(n + 1))
    if len(stellen) > 8:
        stellen = [0, n // 2, n]
    out = []
    gesehen = set()
    for pos in stellen:
        # decls stecken evtl. schon drin (Ende). Variante neu aus dem Text ohne sie ist Aufgabe des Aufrufers.
        t = prolog_mit(fn, decls, pos)
        if not t:
            continue
        h = re.sub(r'\s+', '', t)
        if h in gesehen:
            continue
        gesehen.add(h)
        out.append(t)
    return out or [fn_text]


def lexikase(kandidaten, abschnitt_scores, breite, seed=1):
    """Lexicase: jeder Abschnitt ein Testfall. kandidaten sind Namen, scores[name][key]=dist."""
    import random
    keys = []
    for sc in abschnitt_scores.values():
        for k in sc:
            if not k.startswith('_') and k not in keys:
                keys.append(k)
    if not keys or not kandidaten:
        return kandidaten[:breite]
    rng = random.Random(seed)
    sieger = []
    for _ in range(max(breite, 3)):
        pool = list(kandidaten)
        ordnung = list(keys)
        rng.shuffle(ordnung)
        for k in ordnung:
            if len(pool) <= 1:
                break
            def sc(name, k=k):
                return abschnitt_scores.get(name, {}).get(k, {}).get('dist_struct', 10**9)
            best = min(sc(n) for n in pool)
            pool = [n for n in pool if sc(n) == best]
        if pool and pool[0] not in sieger:
            sieger.append(pool[0])
        if len(sieger) >= breite:
            break
    for n in kandidaten:
        if n not in sieger:
            sieger.append(n)
        if len(sieger) >= breite:
            break
    return sieger


def gruppen_aus_tausch(vorher, nachher):
    """Abschnitte, deren Distanz sich mitbewegt hat, bilden eine Gruppe."""
    gruppe = []
    for k, b in nachher.items():
        if k.startswith('_'):
            continue
        a = vorher.get(k)
        if not a:
            continue
        if b.get('dist_struct', 0) != a.get('dist_struct', 0):
            gruppe.append(k)
    return gruppe


# ---------- Stamm, Abdeckung, Empfehlung ----------

def stamm_aus(fn, einheit, fkt):
    """STAMM.md und stamm.json. Kennungen worker.. in Quellreihenfolge."""
    data = {
        'einheit': einheit,
        'fkt': fkt,
        'signatur': fn.signatur.strip(),
        'lokale': [{'typ': t, 'name': n, 'reihenfolge': i} for i, (t, n) in enumerate(fn.lokale)],
        'abschnitte': [],
    }
    for i, sec in enumerate(fn.abschnitte, start=1):
        kid = f'K{i:02d}'
        data['abschnitte'].append({
            'kennung': kid, 'key': sec.key, 'kind': sec.kind,
            'helfer': sec.calls, 'lokale': sec.locals_used,
            'kruecke': sec.kruecke, 'text': sec.text,
        })
    zeilen = [f'# Stammvertrag {einheit} {fkt}', '', '## Signatur', '', '```', fn.signatur.strip(), '```', '',
              '## Lokale Variablen (Reihenfolge ist bindend)', '',
              'nr\ttyp\tname']
    for i, (t, n) in enumerate(fn.lokale):
        zeilen.append(f'{i}\t{t}\t{n}')
    zeilen += ['', '## Abschnitte', '', 'kennung\tschluessel\tart\thelfer']
    for a in data['abschnitte']:
        zeilen.append(f"{a['kennung']}\t{a['key']}\t{a['kind']}\t{','.join(a['helfer'][:8])}")
    zeilen += ['', '## Abschnittstexte des Stamms (nur als Vertrag, Astlaeufe schreiben neu)', '']
    for a in data['abschnitte']:
        zeilen.append(f"### {a['kennung']} {a['key']}")
        zeilen.append('')
        zeilen.append('```')
        zeilen.append(a['text'].rstrip())
        zeilen.append('```')
        zeilen.append('')
    return '\n'.join(zeilen) + '\n', data


def auftrag_ast(data, nur=None):
    """Vorlage fuer einen Astlauf. nur=Kennung -> nur diesen Abschnitt."""
    sig = data['signatur']
    lok = '\n'.join(f"- {x['typ']} {x['name']}" for x in data['lokale']) or '- (keine)'
    abs_ = '\n'.join(f"- {a['kennung']} ({a['kind']}, Schluessel {a['key']})" for a in data['abschnitte'])
    ziel = data['fkt']
    einheit = data['einheit']
    if nur:
        aufgabe = (f'Schreibe NUR Abschnitt {nur} neu. Alle anderen Abschnitte bleiben woertlich wie im Stamm. '
                   f'Die Signatur, die lokalen Variablen (Namen, Typen, Reihenfolge) und die Abschnittskennungen bleiben.')
    else:
        aufgabe = ('Schreibe ALLE Abschnitte selbst. Halte den Stammvertrag ein: dieselbe Signatur, dieselben lokalen '
                   'Variablen in derselben Reihenfolge, dieselben Abschnittskennungen. Der Code je Abschnitt ist deiner.')
    return f'''# Astlauf {einheit} {ziel}

Du rekonstruierst nur die Funktion {ziel} in der Einheit {einheit}.
{aufgabe}

## Stammvertrag

Signatur:

```
{sig}
```

Lokale Variablen, Reihenfolge bindend:

{lok}

Abschnitte:

{abs_}

Den Stammtext der Abschnitte darfst du lesen (STAMM.md im selben Ordner), aber du schreibst den Abschnitt neu, nicht als Kopie mit anderen Namen.

## Verboten

- baseline directories, Vorversuche und alte Fassungen dieser Funktion nicht oeffnen.
- Kein Inline-Assembler, kein `#pragma aux` mit Codekoerper, keine gefaelschten Linknamen.
- Keine andere Funktion der Einheit aendern.

## Ablage

Schreibe die ganze Einheit nach `arbeit/{einheit}_P1.CPP` in deinem Ordner (die mitgegebene Einheit, nur {ziel} ersetzt).
Messe mit:

```
cd "{ROOT}"
WORKER_ID=$ID python3 03_richter/probe_queue.py {einheit} <deine Datei> {ziel}
```

Hoere auf, wenn die Funktion GLEICH ist oder 45 Minuten um sind. Keine Abgabe nach p3.
'''


def abdeckung_zeile(lauf, fassungen_bew, konsens_keys):
    """Eine Zeile: welche Abschnitte dieser Lauf neu trifft."""
    getroffen = []
    for name, bew in fassungen_bew:
        for k, b in bew.items():
            if k.startswith('_'):
                continue
            if b.get('status') == 'OK' or b.get('dist', 1) == 0:
                getroffen.append(k)
    return lauf, sorted(set(getroffen))


def empfehlung_text(abdeckung_zeilen, alle_keys, rest):
    """abdeckung_zeilen: liste von (lauf, menge getroffener keys), in Reihenfolge."""
    if not alle_keys:
        return 'keine Abschnitte erkannt'
    gesehen = set()
    neu_letzte = []
    for lauf, keys in abdeckung_zeilen:
        neu = [k for k in keys if k not in gesehen]
        neu_letzte.append(neu)
        gesehen.update(keys)
    offen = [k for k in alle_keys if k not in gesehen]
    if len(neu_letzte) >= 2 and not neu_letzte[-1] and not neu_letzte[-2]:
        if offen:
            return 'Stopp: 2 Laeufe ohne neuen Abschnitt -> Zugkarte fuer ' + ','.join(offen)
        if rest and rest > 0:
            return 'Stopp: Struktur komplett, Rest Register -> Strom K'
        return 'Stopp: 2 Laeufe ohne neuen Abschnitt'
    if not offen and rest and rest > 0:
        return 'Stopp: Struktur komplett, Rest Register -> Strom K'
    if offen:
        return 'weitere Astlaeufe fuer ' + ','.join(offen)
    return 'alle Abschnitte getroffen'


def konsens(fassungen, schwelle=None):
    """Abschnitte, die mehrere Fassungen gleich schreiben. Liefert (key -> (anzahl, text_norm, gegen_original_ok?))."""
    from collections import Counter
    gruppen = {}
    for f in fassungen:
        for sec in f['fn'].abschnitte:
            nrm = re.sub(r'\s+', ' ', sec.text).strip()
            gruppen.setdefault(sec.key, Counter())[nrm] += 1
    out = {}
    n = len(fassungen)
    mind = schwelle if schwelle is not None else max(2, (n + 1) // 2)
    for k, c in gruppen.items():
        text, anz = c.most_common(1)[0]
        if anz >= mind:
            out[k] = {'anzahl': anz, 'text': text, 'fassungen': n}
    return out


def vielfalt_paar(a, b):
    """Anteil der Abschnitte, die nur eine der beiden Fassungen trifft (Text verschieden)."""
    ka = {s.key: re.sub(r'\s+', ' ', s.text).strip() for s in a['fn'].abschnitte}
    kb = {s.key: re.sub(r'\s+', ' ', s.text).strip() for s in b['fn'].abschnitte}
    keys = set(ka) | set(kb)
    if not keys:
        return 0.0
    anders = sum(1 for k in keys if ka.get(k) != kb.get(k))
    return anders / len(keys)


def harte_markdown(fn, orig_ins, bew, einheit, fkt):
    """Abschnitte, die keine Fassung trifft."""
    zeilen = [f'# Harte Abschnitte {einheit} {fkt}', '']
    reg = _dispatch_reg(orig_ins) if orig_ins else None
    n = 0
    for sec in fn.abschnitte:
        b = bew.get(sec.key)
        if b and b.get('dist', 1) == 0 and b.get('status') == 'OK':
            continue
        # nur wenn wirklich niemand trifft: der Aufrufer uebergibt die Vereinigung
        n += 1
        zeilen.append(f'## {sec.key} ({sec.kind})')
        zeilen.append('')
        zeilen.append('Quellabschnitt:')
        zeilen.append('')
        zeilen.append('```')
        zeilen.append(sec.text.rstrip()[:2000])
        zeilen.append('```')
        zeilen.append('')
        if sec.kind == 'case' and orig_ins and reg:
            for lab in sec.labels:
                if not isinstance(lab, int):
                    continue
                try:
                    ao, bo = fall_asm(orig_ins, orig_ins, lab, reg)
                except (ValueError, KeyError, IndexError):
                    continue
                zeilen.append(f'ASM-Ausschnitt Fall {lab} (Original, normalisiert, Auszug):')
                zeilen.append('')
                zeilen.append('```')
                zeilen.append('\n'.join(ao[:40]))
                zeilen.append('```')
                zeilen.append('')
                break
        if b:
            zeilen.append(f"Abweichung der Basis: Status {b.get('status')} Distanz {b.get('dist')} ({b.get('quelle')}).")
            zeilen.append('')
    if n == 0:
        zeilen.append('Kein harter Abschnitt: jede Kennung hat mindestens eine treffende Fassung.')
    return '\n'.join(zeilen) + '\n', n


# ---------- Minimierer (Delta-Debugging) ----------

def anweisungs_spannen(fn):
    """Entfernbare Anweisungen: nicht die Signatur, nicht leere Prologe."""
    spans = []
    pos = 0
    for sec in fn.abschnitte:
        k = fn.text.find(sec.text, pos)
        if k < 0:
            continue
        if sec.kind in ('stmt', 'then', 'else', 'loop', 'case'):
            spans.append((k, k + len(sec.text), sec.key))
        elif sec.kind == 'prolog':
            # einzelne Deklarationen
            base = k
            for part in _decl_stmts(sec.text):
                j = fn.text.find(part, base)
                if j < 0:
                    continue
                spans.append((j, j + len(part), 'decl'))
                base = j + len(part)
        pos = k + len(sec.text)
    return spans


def ddmin(n, testen):
    """Klassisches ddmin ueber n entfernbare Stuecke. testen(tuple indizes weg) -> True wenn noch gut.

    Liefert die groesste Menge, die weg darf.
    """
    weg = tuple(range(n))
    if n == 0 or not testen(weg):
        # nicht alles auf einmal; Teilmengen suchen
        pass
    gran = 2
    aktuell = []
    # starte bei leerem Wegnehmen und nimm dazu, was die Pruefung vertraegt: einfacher ddmin auf der Komplementmenge
    # Wir suchen eine Teilmenge R von Anweisungen, die entfernt werden darf.
    def ok(entfernt):
        return testen(tuple(sorted(entfernt)))

    if n == 1:
        return (0,) if ok((0,)) else ()
    # Teile
    kandidat = list(range(n))
    # ddmin: minimale fehlschlagende Menge ist hier "darf nicht weg". Wir wollen maximale Menge die ok ist.
    # Greedy rueckwaerts ist robust und bei kleinen n genug; echtes ddmin dazu.
    gran = 2
    entfernt = []
    # Zuerst ddmin-artig von der vollen Menge absteigen
    teile = [list(range(n))]
    beste = []
    stack = [tuple(range(n))]
    gesehen = set()
    while stack and len(gesehen) < 40:
        cur = stack.pop()
        if cur in gesehen or not cur:
            continue
        gesehen.add(cur)
        if ok(cur):
            if len(cur) > len(beste):
                beste = list(cur)
            continue
        if len(cur) == 1:
            continue
        mid = len(cur) // 2
        stack.append(cur[:mid])
        stack.append(cur[mid:])
    return tuple(beste)


def entferne(fn_text, fkt, indizes):
    fn = parse_funktion(fn_text, fkt) or parse_funktion('//@ ' + fkt + '\n' + fn_text, fkt)
    if fn is None:
        return None
    spans = anweisungs_spannen(fn)
    weg = []
    for i in indizes:
        if 0 <= i < len(spans):
            weg.append(spans[i])
    if not weg:
        return fn.text
    weg.sort(reverse=True)
    text = fn.text
    for a, b, _k in weg:
        text = text[:a] + text[b:]
    return text


# ---------- Ergebniszeile ----------

def ergebnis_anfuegen(felder):
    pfad = os.path.join(HERE, 'ERGEBNIS.tsv')
    neu = not os.path.isfile(pfad)
    with open(pfad, 'a', encoding='utf-8') as h:
        if neu:
            h.write('datum\teinheit\tfkt\tfassungen\tmischbar\trest_basis\trest_mischung\tstatus\tlauf\n')
        h.write('\t'.join(str(x) for x in felder) + '\n')


def abgeben(einheit, fkt, datei, rest_vorher, rest_nachher, grund):
    if gesperrt(einheit):
        log(f'nicht abgeben: {einheit} ist gesperrt')
        return False
    if rest_nachher is None or (rest_vorher is not None and rest_nachher > rest_vorher):
        log('nicht abgeben: nicht besser als die Basis')
        return False
    os.makedirs(KAND, exist_ok=True)
    ziel = os.path.join(KAND, f'{einheit}_P1.CPP')
    shutil.copyfile(datei, ziel)
    status = 'GLEICH' if rest_nachher == 0 else 'besser'
    import datetime
    zeile = '\t'.join([
        datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00'),
        einheit, fkt, str(rest_vorher if rest_vorher is not None else ''),
        str(rest_nachher), status, '', 'mischer1358 ' + grund,
    ])
    with open(ERGEBNISSE, 'a', encoding='utf-8') as h:
        h.write(zeile + '\n')
    subprocess.run(['python3', VERTEILER, 'fertig', WORKER_ID, einheit, status, grund], cwd=ROOT)
    log(f'abgegeben {ziel} ({status})')
    return True
