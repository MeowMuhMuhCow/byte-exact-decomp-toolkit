#!/usr/bin/env python3
"""grenzen.py - Audit translation-unit boundaries against monotonic function ordering in an auxiliary/demo build."""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import project_config as PC

cfg = PC.load_config()
SPRUNG = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x4000
units_tsv = PC.resolve_path("units_tsv", cfg)
demo_tsv = PC.resolve_path("demo_mapping_tsv", cfg)

E = [l.rstrip('\n').split('\t') for l in open(units_tsv) if l.strip() and not l.startswith('#')]
einh = sorted((int(x[2], 16), int(x[3], 16), x[1]) for x in E if len(x) > 3)
Z = [l.rstrip('\n').split('\t') for l in open(demo_tsv) if l.strip() and not l.startswith('#')][1:]
P = sorted((int(x[1][2:], 16), int(x[4], 16), x[0], x[1], int(x[2]), int(x[3])) for x in Z if len(x) > 4)
bruch = []
for (a1, d1, u1, f1, b1, r1), (a2, d2, u2, f2, b2, r2) in zip(P, P[1:]):
    if d2 < d1:
        bruch.append((a2, u1, f1, u2, f2, 'demo_backward'))
    elif d2 - d1 > SPRUNG:
        bruch.append((a2, u1, f1, u2, f2, f'demo_jump_{d2 - d1:#x}'))
innen = [b for b in bruch if b[1] == b[3]]
c = collections.Counter(b[1] for b in innen)
print(f'Demo pairs: {len(P)}, breaks: {len(bruch)} (threshold {SPRUNG:#x}), inside single unit: {len(innen)} across {len(c)} units')
for u, n in c.most_common(15):
    print(f'  {u:18s} {n} internal breaks')
