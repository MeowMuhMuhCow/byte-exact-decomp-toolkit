#!/usr/bin/env python3
"""sprache_einsetzen.py (worker, 15.11.2026, maintainer "ja bau mal"): Funktionsbeschreibungen aus dem Gemini-Katalog
(GEM1_KATALOG/katalog/<EINHEIT>.md) als Kommentare in den Quelltext setzen. Ohne KI.
- Einheitenbeschreibung als Kopfkommentar an den Dateianfang.
- Je Funktion der Katalogabschnitt als Blockkommentar direkt NACH der Markerzeile //@ f_xxxxxx (Marker bleibt, wo er ist).
- Prueft je Datei: Quelltext ohne Kommentare ist zeichengleich mit vorher (sonst wird die Datei nicht geschrieben).
- Zeilenenden (CRLF) und Kodierung (UTF-8 bzw. Latin-1) der Datei bleiben erhalten. Schon gesetzte Katalogkommentare werden ersetzt.
Aufruf: python3 sprache_einsetzen.py [--p3] [--ohne a,b,c] [--nur a,b]
  ohne --p3: schreibt nach SPRACHE/neu/<EINHEIT>_P1.CPP (Probe). Mit --p3: sichert p3 und schreibt hinein.
"""
import sys, os, re, glob, shutil, time, textwrap
from pathlib import Path
HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
if str(TOOLKIT_ROOT) not in sys.path: sys.path.insert(0, str(TOOLKIT_ROOT))
import project_config as PC
_CFG = PC.load_config()
ROOT = Path(PC.resolve_path('project_root', _CFG))
KAT = Path(PC.resolve_path('catalogue_dir', _CFG, str(ROOT / 'docs/catalogue')))
P3 = Path(PC.resolve_path('src_p3_dir', _CFG))
OUT = Path(PC.resolve_path('logs_dir', _CFG, str(TOOLKIT_ROOT / 'logs'))) / 'comments'
ANF, END = '/* === Beschreibung (Katalog) ===', '=== Ende Beschreibung === */'
ERSATZ = {'–': '-', '—': '-', '→': '->', '←': '<-', '≥': '>=', '≤': '<=', '≠': '!=', '…': '...',
          '„': '"', '“': '"', '”': '"', '‚': "'", '‘': "'", '’': "'", ' ': ' ', '×': 'x', '≈': '~'}

def md_zu_text(zeilen):
    out = []
    for l in zeilen:
        l = l.rstrip()
        if re.match(r'^\s*-{3,}\s*$', l): continue
        l = re.sub(r'^#+\s*', '', l)
        l = l.replace('**', '').replace('`', '')
        for a, b in ERSATZ.items(): l = l.replace(a, b)
        l = l.replace('*/', '* /').replace('/*', '/ *')
        out.append(l)
    while out and not out[0].strip(): out.pop(0)
    while out and not out[-1].strip(): out.pop()
    wrapped = []
    for l in out:
        if len(l) <= 110: wrapped.append(l); continue
        ind = len(l) - len(l.lstrip()); sub = ' ' * (ind + (2 if l.lstrip().startswith(('-', '1', '2', '3', '4', '5', '6', '7', '8', '9')) else 0))
        wrapped += textwrap.wrap(l, 110, subsequent_indent=sub, break_long_words=False, break_on_hyphens=False)
    return wrapped

def katalog(u):
    p = KAT / f'{u}.md'
    if not p.exists(): return None, {}
    L = p.read_text(encoding='utf-8', errors='replace').split('\n')
    kopf, fkt, cur, buf = [], {}, None, []
    for l in L:
        m = re.match(r'^#{2,4}\s.*?\b(f_[0-9a-f]{6})\b', l)
        if m:
            if cur: fkt[cur] = buf
            elif buf: kopf = buf
            cur, buf = m.group(1), []
            continue
        if re.match(r'^#{1,3}\s*Funktionen\s*$', l): continue
        buf.append(l)
    if cur: fkt[cur] = buf
    else: kopf = buf
    return md_zu_text(kopf), {k: md_zu_text(v) for k, v in fkt.items()}

def ohne_kommentare(t):
    t = re.sub(r'/\*.*?\*/', ' ', t, flags=re.S); t = re.sub(r'//[^\n]*', '', t)
    return re.sub(r'\s+', ' ', t).strip()

def alte_raus(t):
    return re.sub(re.escape(ANF) + r'.*?' + re.escape(END) + r'\r?\n', '', t, flags=re.S)

def block(zeilen, nl):
    return ANF + nl + nl.join(' * ' + z if z else ' *' for z in zeilen) + nl + ' ' + END + nl

def main():
    a = sys.argv[1:]
    in_p3 = '--p3' in a
    ohne = set(a[a.index('--ohne') + 1].split(',')) if '--ohne' in a else set()
    nur = set(a[a.index('--nur') + 1].split(',')) if '--nur' in a else None
    ziel = P3 if in_p3 else OUT / 'neu'; ziel.mkdir(parents=True, exist_ok=True)
    sich = None
    stats = dict(dateien=0, funktionen=0, ohne_katalog=0, uebersprungen=0, fehler=0)
    for f in sorted(P3.glob('*_P1.CPP')):
        u = f.name[:-7]
        if u in ohne or (nur and u not in nur): stats['uebersprungen'] += 1; continue
        roh = f.read_bytes()
        try: t, enc = roh.decode('utf-8'), 'utf-8'
        except UnicodeDecodeError: t, enc = roh.decode('latin-1'), 'latin-1'
        nl = '\r\n' if '\r\n' in t else '\n'
        kopf, fk = katalog(u)
        if kopf is None: stats['ohne_katalog'] += 1; continue
        neu = alte_raus(t)
        n = 0
        def ers(m):
            nonlocal n
            k = m.group(1)
            if k in fk and fk[k]: n += 1; return m.group(0) + block(fk[k], nl)
            return m.group(0)
        neu = re.sub(r'^//@ (f_[0-9a-f]{6})[^\r\n]*\r?\n', ers, neu, flags=re.M)
        if kopf: neu = block(kopf, nl) + neu
        if ohne_kommentare(neu) != ohne_kommentare(t):
            print(f'!! {u}: Code wuerde sich aendern - NICHT geschrieben', flush=True); stats['fehler'] += 1; continue
        b = neu.encode(enc, errors='replace')
        if in_p3:
            if sich is None:
                sich = ROOT / f'_archiv/2026-11-15_vor_SPRACHE_{time.strftime("%H%M")}'; sich.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, sich / f.name)
            tmp = f.with_suffix('.CPP.tmp_sprache'); tmp.write_bytes(b); os.replace(tmp, f)
        else:
            (ziel / f.name).write_bytes(b)
        stats['dateien'] += 1; stats['funktionen'] += n
    print('FERTIG', stats, '->', ziel, ('Sicherung: %s' % sich) if sich else '', flush=True)

if __name__ == '__main__':
    main()
