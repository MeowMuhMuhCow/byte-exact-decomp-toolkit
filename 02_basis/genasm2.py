#!/usr/bin/env python3
"""genasm2.py - Convert an LE binary into a symbolic WASM baseline module preserving exact fixup ordering."""
import json
import os
import struct
import sys
from le import d, L, objs, fixups, CODE, DATA, CB, DB

fx = {s: (t, tv) for s, t, tv in fixups}
SZ = {7: 4, 5: 2, 6: 6}
eip = struct.unpack_from('<I', d, L + 0x1C)[0] + CB
tg = set(tv for t, tv in fx.values())
tg.add(eip)

MODS = [json.load(open(m)) for m in os.environ.get('MODS', '').split(',') if m and os.path.isfile(m)]
INS = {}
for J in MODS:
    tg |= set(J['labels'])
    for a, n, txt in J['ins']:
        if txt:
            INS[a] = (n, txt)


def lab(a):
    return f'L{a:06X}'


def safe(c):
    while any(c - k in fx for k in range(1, 6)):
        c -= 1
    return c


glob_path = os.environ.get('GLOBORDER_JSON', 'globorder.json')
G = json.load(open(glob_path)) if os.path.isfile(glob_path) else sorted(fx.keys())


def intervals(lo, hi):
    ss = [x for x in G if lo <= x < hi]
    rk = {x: i for i, x in enumerate(ss)}
    srt = sorted(ss)
    if not srt:
        return [(lo, hi, 0)]
    out = []
    start = lo
    first = rk[srt[0]]
    for a, b in zip(srt, srt[1:]):
        if rk[b] != rk[a] + 1:
            cut = a + SZ[fx[a][0]]
            out.append((start, cut, first))
            start = cut
            first = rk[b]
    out.append((start, hi, first))
    return sorted(out, key=lambda x: x[2])


if __name__ == '__main__':
    out_asm = sys.argv[1] if len(sys.argv) > 1 else 'BASELINE.ASM'
    out = open(out_asm, 'w', newline='\r\n')
    w = out.write
    w('.386p\n.387\n.model flat\n')
    norg = 0

    def body(base, data, a, b):
        p = a
        buf = []

        def flush():
            if buf:
                w('db ' + ','.join(f'0{x:02X}h' for x in buf) + '\n')
                buf.clear()

        while p < b:
            if p in tg:
                flush()
                w(f'{lab(p)} label byte\n')
            if p in INS:
                n, txt = INS[p]
                if p + n <= b and not any(p + k in tg for k in range(1, n)):
                    flush()
                    w(txt + '\n')
                    p += n
                    continue
            if p in fx:
                t, tv = fx[p]
                flush()
                n = SZ[t]
                w({7: 'dd', 5: 'dw', 6: 'df'}[t] + f' {lab(tv)}\n')
                for k in range(1, n):
                    if p + k in tg:
                        w(f'{lab(p + k)} equ $-{n - k}\n')
                p += n
                continue
            buf.append(data[p - base] if p - base < len(data) else 0)
            p += 1
            if len(buf) == 16:
                flush()
        flush()
        return p

    def seg(name, align, cls, lo, hi, base, data):
        global norg
        w(f"{name} segment {align} public use32 '{cls}'\n")
        pos = lo
        last = lo
        for a, b, _ in intervals(lo, hi):
            if a != pos:
                w(f'org {a - lo}\n')
                norg += 1
            pos = body(base, data, a, b)
            last = max(last, pos)
        if pos != last:
            w(f'org {last - lo}\n')
        return last

    seg('_TEXT', 'para', 'CODE', CB, CB + len(CODE), CB, CODE)
    w('_TEXT ends\n')
    DE = DB + objs[1]['vsize']
    last = seg('_DATA', 'para', 'DATA', DB, DB + len(DATA), DB, DATA)
    q = last
    stops = sorted(x for x in tg if q <= x < DE)
    for x in stops:
        if x > q:
            w(f'db {x - q} dup(?)\n')
        w(f'{lab(x)} label byte\n')
        q = x
    w("_DATA ends\nSTACK segment byte stack use32 'STACK'\n")
    if DE > q:
        w(f'db {DE - q} dup(?)\n')
    w('STACK ends\nDGROUP group _DATA,STACK\n')
    w(f'public {lab(eip)}\nend\n')
    out.close()
    print('Wrote', out_asm, 'org jumps:', norg)
