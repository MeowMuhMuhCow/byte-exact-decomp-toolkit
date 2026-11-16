#!/usr/bin/env python3
"""lib_version_match.py - Pin exact compiler minor version by matching OMF runtime .LIB modules against a binary image.

Usage:
  python3 lib_version_match.py --code-bin target_flat.bin --lib-dir-a /path/to/v105/LIB386 --lib-dir-b /path/to/v106/LIB386 CLIB3R.LIB PLIB3R.LIB
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '02_basis')))
import omf


def items(m):
    out = []
    for s in m['segs'].values():
        if s['cls'] == 'CODE' and len(s['data']) >= 12:
            out.append((m['name'] + ':' + s['name'], s))
    for c in m['comdats']:
        if len(c['data']) >= 12:
            out.append((m['name'] + ':' + c['name'], c))
    return out


def find_in_code(code, it):
    data, mask = it['data'], it['mask']
    best = (0, 0)
    st = None
    for k in range(len(data) + 1):
        if k < len(data) and not mask[k]:
            if st is None:
                st = k
        else:
            if st is not None and k - st > best[1] - best[0]:
                best = (st, k)
            st = None
    a, b = best
    if b - a < 6:
        return None
    anc = bytes(data[a:b])
    hits = []
    p = code.find(anc)
    while p >= 0:
        base = p - a
        if base >= 0 and base + len(data) <= len(code):
            ok = all(mask[k] or code[base + k] == data[k] for k in range(len(data)))
            if ok:
                hits.append(base)
        p = code.find(anc, p + 1)
    return hits


def load_lib(lib_dir, lib_name):
    ms = omf.modules(os.path.join(lib_dir, lib_name))
    return {n: it for m in ms for n, it in items(m)}


def main():
    ap = argparse.ArgumentParser(description='Compare two compiler runtime library directories against a target binary.')
    ap.add_argument('--code-bin', required=True, help='Flat code image or binary to search')
    ap.add_argument('--lib-dir-a', required=True, help='First candidate LIB386 directory (e.g. Watcom 10.5)')
    ap.add_argument('--lib-dir-b', required=True, help='Second candidate LIB386 directory (e.g. Watcom 10.6)')
    ap.add_argument('libs', nargs='+', help='Library filenames (e.g. CLIB3R.LIB PLIB3R.LIB)')
    args = ap.parse_args()

    code = open(args.code_bin, 'rb').read()
    for lib in args.libs:
        A = load_lib(args.lib_dir_a, lib)
        B = load_lib(args.lib_dir_b, lib)
        common = set(A) & set(B)
        diff = [n for n in common if bytes(A[n]['data']) != bytes(B[n]['data']) or bytes(A[n]['mask']) != bytes(B[n]['mask'])]
        ra = rb = both = 0
        sa, sb = [], []
        for n in diff:
            ha = find_in_code(code, A[n])
            hb = find_in_code(code, B[n])
            if ha and hb:
                both += 1
            elif ha:
                ra += 1
                sa.append(n)
            elif hb:
                rb += 1
                sb.append(n)
        tot_a = sum(1 for it in A.values() if find_in_code(code, it))
        tot_b = sum(1 for it in B.values() if find_in_code(code, it))
        print(f'{lib}: modules A={len(A)} B={len(B)} | matched total A={tot_a} B={tot_b} | differing={len(diff)}: only_A={ra} only_B={rb} both={both}')
        if sa:
            print('  only A:', sa[:12])
        if sb:
            print('  only B:', sb[:12])


if __name__ == '__main__':
    main()
