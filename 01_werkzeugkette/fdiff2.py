"""fdiff2.py UNIT FUNC [OBJ] - Align compiled vs. original instruction sequences and count differing instructions."""
import difflib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bytecmp as B
import capstone as c
import w106cfg as C

md = c.Cs(c.CS_ARCH_X86, c.CS_MODE_32)


def _norm(t):
    t = re.sub(r'^(j\w+|call|loop\w*) 0x[0-9a-f]+$', r'\1 T', t)
    t = re.sub(r'\[([^\]]*?)(\+ |- )?0x[0-9a-f]{5,}\]', lambda q: '[' + (q.group(1) or '') + 'A]', t)
    return re.sub(r'0x[0-9a-f]{5,}', 'A', t)


def eigen(ins, A):
    out = []
    p = 0
    for b, s in ins:
        md.detail = True
        try:
            i = next(md.disasm(b, A + p))
            t = (i.mnemonic + ' ' + i.op_str).strip()
        except StopIteration:
            out.append((p, b.hex(), b.hex()))
            p += len(b)
            continue
        raw = t
        if i.disp_size == 4:
            f = b[i.disp_offset:i.disp_offset + 4]
            if s or f == bytes(4):
                def rep(q):
                    inner = q.group(1)
                    if re.search(r'(\+ |- )?(0x[0-9a-f]+|\d+)$', inner):
                        return '[' + re.sub(r'(\+ |- )?(0x[0-9a-f]+|\d+)$', '', inner) + 'A]'
                    if re.search(r'[a-z]{2,3}', inner):
                        return q.group(0)
                    return '[A]'
                t = re.sub(r'\[([^\]]*)\]', rep, t)
        if i.imm_size == 4 and not t.startswith(('call', 'j')):
            f = b[i.imm_offset:i.imm_offset + 4]
            if f == bytes(4) and 'A]' not in t or (s and 'offset' in raw):
                t = re.sub(r', (0x[0-9a-f]+|\d+)$', ', A', t)
                t = re.sub(r'^(push|mov \w+,) (0x[0-9a-f]+|\d+)$', r'\1 A', t)
        out.append((p, _norm(t), raw))
        p += len(b)
    return out


def orig(A, n):
    base = C.CODE_BASE
    o = B.FLAT[A - base:A - base + n]
    return [
        (i.address - A, _norm((i.mnemonic + ' ' + i.op_str).strip()), (i.mnemonic + ' ' + i.op_str).strip())
        for i in md.disasm(o, A)
    ]


def diff(u, f, obj=None, ctx=1):
    f = f.replace('f_', '').lower()
    F = B.funcs(obj or os.path.join(C.TMP, u + '.obj'))
    A = int(f, 16)
    E = eigen(F[f], A)
    n = sum(len(b) for b, _ in F[f])
    O = orig(A, n)
    PAD = re.compile(r'^(lea (\w+), \[\2( \+ 0)?\]|mov (\w+), \4|nop|int3|xchg ax, ax|add byte ptr \[eax\], al|.?byte.*)$')
    while O and PAD.match(O[-1][2]):
        O.pop()
    while E and PAD.match(E[-1][2]):
        E.pop()
    sm = difflib.SequenceMatcher(None, [x[1] for x in O], [x[1] for x in E], autojunk=False)
    cnt = 0
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            if out and ctx:
                out.append('  %04x  %-34s | %s' % (O[i1][0], O[i1][2], E[j1][2]))
            continue
        cnt += max(i2 - i1, j2 - j1)
        out.append('  ...')
        for k in range(max(i2 - i1, j2 - j1)):
            l = O[i1 + k] if i1 + k < i2 else None
            r = E[j1 + k] if j1 + k < j2 else None
            out.append('! %04x  %-34s | %s' % ((l or r)[0], l[2] if l else '', r[2] if r else ''))
    return cnt, out


if __name__ == '__main__':
    n, out = diff(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print('%d differing instructions (left original, right compiled)' % n)
    print('\n'.join(out[:80]))
