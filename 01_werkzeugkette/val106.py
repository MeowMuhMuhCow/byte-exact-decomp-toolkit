#!/usr/bin/env python3
"""val106.py [UNIT ...] - Validate emulated Watcom 10.6 compilation across verified units."""
import multiprocessing as mp
import os
import re
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bytecmp as B
from comp import comp
import w106cfg as C


def eine(u):
    src = os.path.join(C.PC.resolve_path('src_p3_dir', C._cfg), f'{u}_P1.CPP')
    fs = os.path.join(C.LIVE, f'{u}.fstand')
    if not (os.path.exists(src) and os.path.exists(fs)):
        return u, None, []
    obj = os.path.join(C.TMP, f'{u}_val_{os.getpid()}.obj')
    t0 = time.time()
    ok, out, e = comp(src, obj)
    dt = time.time() - t0
    if not ok or not os.path.exists(obj):
        return u, f'no OBJ ({out[-200:]})', []
    try:
        F = B.funcs(obj)
        res = []
        for l in open(fs):
            z = l.split()
            if len(z) < 3 or z[2] not in ('GLEICH', 'MATCH'):
                continue
            a = z[0].lower()
            sz = int(z[1].split('/')[0])
            if a not in F:
                res.append((a, -1))
                continue
            res.append((a, int(B.gleich(F[a], int(a, 16), sz))))
        return u, f'{dt:.1f}s', res
    finally:
        if os.path.exists(obj):
            os.remove(obj)


if __name__ == '__main__':
    units = sys.argv[1:]
    t = time.time()
    tot = same = miss = 0
    rows = []
    with mp.Pool(min(8, mp.cpu_count())) as p:
        for u, info, res in p.imap_unordered(eine, units):
            n = len(res)
            s = sum(1 for _, ok in res if ok == 1)
            m = sum(1 for _, ok in res if ok == -1)
            tot += n
            same += s
            miss += m
            rows.append(f'{u}\t{info}\t{n}\t{s}\t{m}')
    print(f'emu106 validation: {same}/{tot} matched functions identical ({100*same/max(1,tot):.1f}%), {miss} missing, {time.time()-t:.1f}s')
