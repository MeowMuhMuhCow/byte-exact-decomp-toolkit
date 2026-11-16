#!/usr/bin/env python3
"""uebernahme.py (Claude worker, 15.11.2026): Entkrueckung der Nacht (ENTK_SKRIPT S0-S3 + Geminis K1-K3) pruefen und nach p3 uebernehmen.
Je Einheit: Kandidat = candidate drafts.
  1. Pfoertner (worker): ABGEWIESEN -> bleibt
  2. p3 und Kandidat nativ messen (probe_queue): Kandidat darf in KEINER Funktion schlechter sein als p3, EXTRA gleich
  3. Sicherung der p3-Datei, Schreiben ueber sperre.schreibe (md5-Schutz)
Vorher wird ganz p3 gesichert (Shell-Wrapper). Protokoll: ENTK_UEBERNAHME/PROTOKOLL.tsv
Aufruf: python3 -u uebernahme.py [--trocken] [--nur A,B]
"""
import sys, os, re, csv, glob, time, shutil, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
LOGS = Path(PC.resolve_path('logs_dir', _CFG)); ZIEL = sys.argv[sys.argv.index('--ziel') + 1] if '--ziel' in sys.argv else 'p3'   # 16.11. worker: auch p1 (video_drv1_neu)
P3 = Path(PC.resolve_path('src_dir', _CFG)) / ZIEL; OUT = LOGS / 'ratchet_accept'
sys.dont_write_bytecode = True
os.environ.setdefault('ENTK_ID', 'K9'); os.environ['ENTK_OUT'] = str(OUT.relative_to(ROOT) / 'arbeit')
_s = importlib.util.spec_from_file_location('z2', str(A48 / 'worker/zusammen2.py')); z = importlib.util.module_from_spec(_s); _s.loader.exec_module(z)
sys.path.insert(0, str(ROOT / 'Werkzeuge/phase4')); import sperre
_p = importlib.util.spec_from_file_location('pf1352', str(A48 / 'worker/pfoertner.py')); pf = importlib.util.module_from_spec(_p); _p.loader.exec_module(pf)
TROCKEN = '--trocken' in sys.argv
NUR = set(sys.argv[sys.argv.index('--nur') + 1].split(',')) if '--nur' in sys.argv else None
STEMPEL = time.strftime('%Y%m%d_%H%M'); SICH = OUT / f'_{ZIEL}_vor_{STEMPEL}'; PROT = OUT / 'PROTOKOLL.tsv'
def lies(p): return open(p, encoding='latin-1').read()
def prot(*x):
    neu = not PROT.exists()
    with open(PROT, 'a', encoding='utf-8') as fh:
        if neu: fh.write('zeit\teinheit\tquelle\tergebnis\tgrund\n')
        fh.write('\t'.join([time.strftime('%Y-%m-%dT%H:%M:%S')] + [str(v) for v in x]) + '\n')
def main():
    kand = {}
    for f in sorted(glob.glob(str(A48 / 'ENTK_SKRIPT/S?/*_P1.CPP'))): kand[os.path.basename(f)[:-7]] = (f, 'Skript ' + Path(f).parent.name)
    for f in sorted(glob.glob(str(A48 / 'ENTK_GEM/K*/*_P1.CPP'))): kand[os.path.basename(f)[:-7]] = (f, 'Agent ' + Path(f).parent.name)
    if '--dir' in sys.argv:   # 15.11.: nur Kandidaten aus einem Ordner (z. B. GEISTER_UEB)
        d = Path(sys.argv[sys.argv.index('--dir') + 1]); d = d if d.is_absolute() else ROOT / d
        kand = {os.path.basename(f)[:-7]: (f, 'Ordner ' + d.name) for f in sorted(glob.glob(str(d / '*_P1.CPP')))}
    tl = [l.split('\t')[1] for l in open(Path(PC.resolve_path('units_tsv', _CFG)), encoding='utf-8', errors='replace') if l.strip()]
    # 15.11.: Windows-Laufwerk ist gross/klein-blind, K6 schrieb GROSSE Dateinamen -> auf echten Einheitennamen abbilden
    echt = {x.lower(): x for x in tl}
    neu = {}
    for k, v in kand.items():
        u2 = echt.get(k.lower(), k)
        if u2 not in neu or v[1].startswith('Gemini'):
            neu[u2] = v
    kand = neu
    reihe = [u for u in tl if u in kand] + sorted(u for u in kand if u not in tl)
    if NUR: reihe = [u for u in reihe if u in NUR]
    print(f'{len(reihe)} Kandidaten ({"TROCKEN" if TROCKEN else "UEBERNAHME"})', flush=True)
    n_ok = n_gleich = 0; zaehl = {}
    for i, u in enumerate(reihe, 1):
        vf, quelle = kand[u]; p3f = P3 / f'{u}_P1.CPP'
        def melde(erg, grund=''):
            zaehl[erg] = zaehl.get(erg, 0) + 1; prot(u, quelle, erg, grund[:240]); print(f'[{i}/{len(reihe)}] {u} ({quelle}): {erg} {grund[:100]}', flush=True)
        if not p3f.exists(): melde('KEIN_P3'); continue
        t3, tv = lies(p3f), lies(vf)
        if t3 == tv: melde('SCHON_GLEICH'); continue
        er = pf.pruefen(tv, t3, bestand=False)
        if er['status'] == 'ABGEWIESEN': melde('ABGEWIESEN', '; '.join(er['ab'])); continue
        md5_vor = sperre.lese_md5(str(p3f))
        b, n = z.messe(u, p3f), z.messe(u, Path(vf))
        if b.get('fehler') or n.get('fehler'): melde('MESSFEHLER', b.get('grund', '') + ' / ' + n.get('grund', '')); continue
        probs = z.unterschiede(b, n)
        if probs: melde('NICHT_GLEICH', ','.join(map(str, probs[:8]))); continue
        if TROCKEN: n_ok += 1; melde('OK_TROCKEN'); continue
        SICH.mkdir(parents=True, exist_ok=True); shutil.copy2(p3f, SICH / p3f.name)
        gut, info = sperre.schreibe(str(ROOT), u, tv, None, md5_vor, os.environ.get('UEB_HERKUNFT', 'entkrueckung_1511'), ziel_dir=ZIEL)
        if gut: n_ok += 1; melde('UEBERNOMMEN')
        else: melde('KONFLIKT', str(info))
    print(f'FERTIG: {n_ok} von {len(reihe)} {"ok (trocken)" if TROCKEN else "uebernommen"}. {zaehl}. Protokoll: {PROT}', flush=True)
if __name__ == '__main__':
    main()
