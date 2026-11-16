#!/usr/bin/env python3
"""teile.py ASM_DIR SLICE_NAME SPLIT_HEX NEW_NAME - Split a _DATA assembly slice at a given hex address."""
import os
import re
import sys

M, S, ADR, NEU = sys.argv[1], sys.argv[2], int(sys.argv[3], 16), sys.argv[4]
L = open(f'{M}/{S}.ASM').read().split('\n')
a = L.index(next(l for l in L if l.startswith('_DATA segment')))
e = L.index('_DATA ends')
kopf = [l for l in L[:a] if not l.startswith('public ')]
body = L[a + 1:e]
assert not any(l.startswith('org') for l in body), 'org inside slice'
start = int(re.match(r'L([0-9A-F]{6})', body[0]).group(1), 16)
pos = start
A, B = [], []
for l in body:
    m = re.match(r'L([0-9A-F]{6}) label', l)
    if m:
        assert int(m.group(1), 16) == pos, (l, hex(pos))
        (A if pos < ADR else B).append(l)
        continue
    t, _, rest = l.partition(' ')
    vals = [v.strip() for v in rest.split(',')]
    w = {'db': 1, 'dd': 4}[t]
    if pos >= ADR:
        B.append(l)
    elif pos + w * len(vals) <= ADR:
        A.append(l)
    else:
        assert t == 'db'
        k = ADR - pos
        A.append('db ' + ','.join(vals[:k]))
        B.append('db ' + ','.join(vals[k:]))
    pos += w * len(vals)
if not any(re.match(rf'L{ADR:06X} label', l) for l in B):
    B.insert(0, f'L{ADR:06X} label byte')


def write_slice(name, part):
    pubs = [f'public {m}' for m in re.findall(r'^(L[0-9A-F]{6}) label', '\n'.join(part), re.M)]
    open(f'{M}/{name}.ASM', 'w').write('\n'.join(kopf + pubs + [L[a]] + part + ['_DATA ends', 'end', '']))


write_slice(S, A)
write_slice(NEU, B)
print(f'{S}: {start:06X}-{ADR:06X}, {NEU}: {ADR:06X}-{pos:06X}')
