"""fdiff.py UNIT FUNC [OBJ] - Unified diff of emu106 compilation against original binary using Capstone."""
import difflib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bytecmp as B
import capstone as c
import w106cfg as C

md = c.Cs(c.CS_ARCH_X86, c.CS_MODE_32)


def norm(b, sym):
    i = next(md.disasm(b, 0))
    t = i.mnemonic + ' ' + i.op_str
    m = B._mask(b) or set()
    if m and all(b[k] == 0 for k in m):
        t = re.sub(r'0x[0-9a-f]{3,}', 'REL', t)
    return t


def lst(F, a):
    return [norm(b, s) for b, s in F[a]]


def orig(a, n):
    base = C.CODE_BASE
    o = B.FLAT[a - base:a - base + n]
    r = []
    for i in md.disasm(o, a):
        r.append(i.mnemonic + ' ' + i.op_str)
    return r


if __name__ == '__main__':
    u, f = sys.argv[1], sys.argv[2].replace('f_', '').lower()
    obj = sys.argv[3] if len(sys.argv) > 3 else os.path.join(C.TMP, f'{u}.obj')
    F = B.funcs(obj)
    ours = lst(F, f)
    n = sum(len(b) for b, _ in F[f])
    o = orig(int(f, 16), n)
    o = [re.sub(r'0x[0-9a-f]{5,}', 'REL', x) for x in o]
    ours = [re.sub(r'0x[0-9a-f]{5,}', 'REL', x) for x in ours]
    for l in difflib.unified_diff(o, ours, 'original', 'compiled', lineterm='', n=2):
        print(l)
