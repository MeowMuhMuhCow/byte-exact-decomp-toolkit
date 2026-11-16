#!/usr/bin/env python3
"""geister_min.py (worker, 15.11.2026, target: "bytegleich und sinnvoll, moeglichst wenige Geister"):
Minimiert die Watcom-Geistervariablen (unbenutzte volatile ghost_* Lokale) einer Einheit, ohne KI.
Verfahren: Delta-Debugging. Bloecke von Geisterzeilen probeweise loeschen, Einheit nativ messen (probe_queue);
bleibt jede Funktion wie vorher (GLEICH, EXTRA gleich), bleibt der Block weg. Blockgroesse halbiert sich bis 1
oder bis das Messbudget aufgebraucht ist. Schreibt NICHT nach p3.
Ergebnis: GEISTER_MIN/<EINHEIT>_P1.CPP (beste gemessene Fassung) + ERGEBNIS.tsv + <EINHEIT>.log
Aufruf: ENTK_ID=worker python3 -u geister_min.py EINHEIT [--budget N]
"""
import sys, os, re, time, importlib.util
from pathlib import Path
HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
if str(TOOLKIT_ROOT) not in sys.path: sys.path.insert(0, str(TOOLKIT_ROOT))
import project_config as PC
_CFG = PC.load_config()
ROOT = Path(PC.resolve_path('project_root', _CFG))
OUT = Path(PC.resolve_path('logs_dir', _CFG, str(TOOLKIT_ROOT / 'logs'))) / 'ghost_min'
P3 = Path(PC.resolve_path('src_p3_dir', _CFG))
os.environ.setdefault('ENTK_ID', 'worker_gm')
_s = importlib.util.spec_from_file_location('z2', str(TOOLKIT_ROOT / '10_entkruecker/zusammen2.py')); z = importlib.util.module_from_spec(_s); _s.loader.exec_module(z)
GEIST = re.compile(r'^\s*volatile\s+[A-Za-z_][A-Za-z0-9_ ]*\s+ghost_[A-Za-z0-9_]+\s*;\s*$')

def main():
    u = sys.argv[1]
    budget = int(sys.argv[sys.argv.index('--budget') + 1]) if '--budget' in sys.argv else 600
    zeilen = open(P3 / f'{u}_P1.CPP', encoding='latin-1').read().split('\n')
    geister = [i for i, l in enumerate(zeilen) if GEIST.match(l)]
    arbeit = OUT / 'arbeit' / u; arbeit.mkdir(parents=True, exist_ok=True)
    log = open(OUT / f'{u}.log', 'a', encoding='utf-8')
    def L(t):
        t = time.strftime('%H:%M:%S ') + t; print(t, flush=True); log.write(t + '\n'); log.flush()
    n_mess = [0]
    def text_ohne(weg):
        w = set(weg); return '\n'.join(l for i, l in enumerate(zeilen) if i not in w)
    def messe_text(t):
        n_mess[0] += 1; p = arbeit / f'v{n_mess[0]:04d}.CPP'
        open(p, 'w', encoding='latin-1').write(t); return z.messe(u, p)
    basis = z.messe(u, P3 / f'{u}_P1.CPP')
    if basis.get('fehler'): L(f'{u}: Basis nicht messbar: {basis.get("grund")}'); return
    L(f'{u}: {len(geister)} Geisterzeilen, Budget {budget} Messungen')
    weg = []            # bestaetigt entfernbar
    rest = list(geister)
    groesse = max(1, len(rest) // 2)
    while groesse >= 1 and n_mess[0] < budget and rest:
        i = 0; gewonnen = False
        while i < len(rest) and n_mess[0] < budget:
            block = rest[i:i + groesse]
            st = messe_text(text_ohne(weg + block))
            if not st.get('fehler') and not z.unterschiede(basis, st):
                weg += block; rest = rest[:i] + rest[i + groesse:]; gewonnen = True
                L(f'  -{len(block)} ok (Block {groesse}) -> noch {len(rest)} Geister, Messung {n_mess[0]}')
                open(OUT / f'{u}_P1.CPP', 'w', encoding='latin-1').write(text_ohne(weg))
            else:
                i += groesse
        if not gewonnen or groesse > 1:
            groesse //= 2
    # Endfassung nachmessen
    if weg:
        st = messe_text(text_ohne(weg))
        if st.get('fehler') or z.unterschiede(basis, st):
            L('!! Endfassung nicht gleich - verworfen'); weg = []
            try: os.rename(OUT / f'{u}_P1.CPP', OUT / f'{u}_P1.CPP.verworfen')
            except OSError: pass
    L(f'{u}: FERTIG {len(geister)} -> {len(geister) - len(weg)} Geister ({len(weg)} entfernt), {n_mess[0]} Messungen')
    neu = not (OUT / 'ERGEBNIS.tsv').exists()
    with open(OUT / 'ERGEBNIS.tsv', 'a', encoding='utf-8') as fh:
        if neu: fh.write('einheit\tgeister_vorher\tgeister_nachher\tmessungen\n')
        fh.write(f'{u}\t{len(geister)}\t{len(geister) - len(weg)}\t{n_mess[0]}\n')

if __name__ == '__main__':
    main()
