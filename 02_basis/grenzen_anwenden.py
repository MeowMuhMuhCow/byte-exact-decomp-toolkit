#!/usr/bin/env python3
"""grenzen_anwenden.py PROPOSALS.TSV [--apply] - Validate and apply gapless unit boundary updates to units.tsv."""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import project_config as PC

cfg = PC.load_config()
T = PC.resolve_path("units_tsv", cfg)
Z = [l.rstrip('\n').split('\t') for l in open(T, encoding='utf-8') if l.strip() and not l.startswith('#')]
idx = {z[1]: i for i, z in enumerate(Z) if len(z) >= 4}
FD = next((x for x in sys.argv[1:] if not x.startswith('--')), None)
if not FD:
    print("Usage: python3 grenzen_anwenden.py PROPOSALS.TSV [--apply]")
    sys.exit(1)
F = [l.rstrip('\n').split('\t') for l in open(FD, encoding='utf-8').read().splitlines()[1:] if l.strip() and not l.startswith('#')]
fehler = []
neu = {}
for u, av, ab, nv, nb, *q in F:
    if u not in idx:
        fehler.append(f'{u}: not in units.tsv')
        continue
    z = Z[idx[u]]
    if (z[2], z[3]) != (av, ab):
        fehler.append(f'{u}: units.tsv has {z[2]}-{z[3]}, proposal expected {av}-{ab}')
    neu[u] = (nv, nb)
rng = sorted((int(neu.get(z[1], (z[2], z[3]))[0], 16), int(neu.get(z[1], (z[2], z[3]))[1], 16), z[1]) for z in Z if len(z) >= 4)
alt = sorted((int(z[2], 16), int(z[3], 16), z[1]) for z in Z if len(z) >= 4)
for (a, b, u), (c, d, v) in zip(rng, rng[1:]):
    if c < b:
        fehler.append(f'Overlap {u} {a:06x}-{b:06x} / {v} {c:06x}-{d:06x}')
altnb = {u: (v, c == b) for (a, b, u), (c, d, v) in zip(alt, alt[1:])}
for (a, b, u), (c, d, v) in zip(rng, rng[1:]):
    if (u in neu or v in neu) and altnb.get(u, (None, False))[1] and c != b:
        fehler.append(f'New gap between {u} ({b:06x}) and {v} ({c:06x})')
for f in fehler:
    print('ERROR', f)
print(f'{len(F)} boundary updates checked, {len(fehler)} errors')
if '--apply' in sys.argv and not fehler:
    b = T.replace('.tsv', time.strftime('_backup_%m%d_%H%M.tsv'))
    shutil.copy(T, b)
    for u, (nv, nb) in neu.items():
        Z[idx[u]][2] = nv
        Z[idx[u]][3] = nb
    open(T + '.new', 'w', encoding='utf-8').write('\n'.join('\t'.join(z) for z in Z) + '\n')
    os.replace(T + '.new', T)
    print('Applied, backup saved to', os.path.basename(b))
