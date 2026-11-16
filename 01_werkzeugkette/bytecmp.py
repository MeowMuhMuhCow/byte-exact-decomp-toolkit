"""bytecmp.py - Compare function bytes from wdis output against flat target binary with relocation masking."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import w106cfg as C

FLAT = open(C.FLAT, 'rb').read() if (C.FLAT and os.path.isfile(C.FLAT)) else b''
HDR = re.compile(r'^([0-9A-F]{4,8})\t+(?!L\$)(.*\)):\s*$')
INS = re.compile(r'^([0-9A-F]{4,8})  ((?:[0-9A-F]{2} ?)+)\t+(\S+)\s*(.*)$')
CONT = re.compile(r'^([0-9A-F]{4,8})?\s+((?:[0-9A-F]{2} ?)+)\s*$')


def _sym(mn, tx):
    if mn.startswith(('j', 'loop')) and 'L$' in tx and '__near' not in tx and 'ptr' not in tx:
        return False
    return '__near' in tx or '__far' in tx or 'offset' in tx or 'L$' in tx


def _eigen(kopf):
    """Extract function hex suffix only if f_xxxxxx(...) closes the routine header with balanced parens."""
    k = kopf.strip()
    for m in reversed(list(re.finditer(r'f_([0-9a-f]{6})\(', k))):
        t = 0
        for j in range(m.end() - 1, len(k)):
            if k[j] == '(':
                t += 1
            elif k[j] == ')':
                t -= 1
                if t == 0:
                    if re.fullmatch(r'\s*(const)?\s*', k[j + 1:]):
                        return m.group(1)
                    break
    a = re.findall(r'f_([0-9a-f]{6})', k)
    return a[-1] if a and '(' not in k else None


def funcs(obj):
    t = subprocess.run([C.WDIS, obj], capture_output=True, text=True).stdout.split('\n')
    F = {}
    cur = None
    pend = None
    ONLY = re.compile(r'^([0-9A-F]{4,8})  ((?:[0-9A-F]{2} ?)+)\s*$')
    MN = re.compile(r'^\t+(\S+)\s*(.*)$')
    for l in t:
        m = HDR.match(l)
        if m:
            cur = _eigen(m.group(2))
            pend = None
            if cur:
                F.setdefault(cur, [])
            continue
        if l.startswith('Routine Size') or l.startswith('Segment:'):
            cur = None
            continue
        if not cur:
            continue
        m = INS.match(l)
        if m:
            F[cur].append([bytes.fromhex(m.group(2)), _sym(m.group(3).lower(), m.group(4))])
            pend = None
            continue
        m = ONLY.match(l)
        if m:
            pend = bytes.fromhex(m.group(2))
            continue
        m = MN.match(l)
        if m and pend is not None:
            F[cur].append([pend, _sym(m.group(1).lower(), m.group(2))])
            pend = None
    return F


import capstone as _c
_md = _c.Cs(_c.CS_ARCH_X86, _c.CS_MODE_32)
_md.detail = True


def _mask(b):
    try:
        i = next(_md.disasm(b, 0))
    except StopIteration:
        return None
    m = set()
    if i.disp_size == 4:
        m |= set(range(i.disp_offset, i.disp_offset + 4))
    if i.imm_size == 4:
        m |= set(range(i.imm_offset, i.imm_offset + 4))
    if not m and len(b) >= 5:
        m = set(range(len(b) - 4, len(b)))
    return m


def gleich(ins, addr, size):
    base = C.CODE_BASE
    o = FLAT[addr - base:addr - base + size]
    p = 0
    for b, sym in ins:
        if p >= size:
            break
        n = len(b)
        seg = o[p:p + n]
        if len(seg) < n:
            return False
        if seg != b:
            m = _mask(b) or set()
            if not sym:
                m = {k for k in m if b[k] == 0 and all(b[j] == 0 for j in m)}
            if any(seg[k] != b[k] for k in range(n) if k not in m):
                return False
        elif seg != b:
            return False
        p += n
    if p >= size:
        return True
    rest = o[p:]
    return all(x in (0, 0x90) for x in rest) or len(rest) <= 15 and rest[:1] in (b'\x8d', b'\x8b', b'\x89', b'\x90')
