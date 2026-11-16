#!/usr/bin/env python3
"""emu106.py - Watcom C/C++ 10.6 (BINW/WPP386.EXE & WCC386.EXE, CF image) in Unicorn CPU emulator.

Usage:
  python3 emu106.py [--root DIR] -- ARGS...        e.g.  -- S.CPP -4r -oneatx -zp1 -s -zq

The Watcom 32-bit CF executable invokes DOS int 21h services through a 32-bit extender stub
(push ebp / call fword [handler] / pop ebp / ret). We hook that stub address in Unicorn and
service file/memory/environment calls directly in Python. Files under --root are resolved
case-insensitively as drive C:. Diagnostic tools import Emu106 and attach hooks to internal
compiler routines.
"""
import argparse
import os
import struct
import sys
import time
import unicorn as U
from unicorn import x86_const as X

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from w106cfg import EXE as EXE_DEFAULT

GDT, INFO = 0x1000, 0x10000
STACK_LO, STACK_HI = 0x100000, 0x400000
BASE = 0x400000
HEAP_LO, HEAP_HI = 0x1000000, 0x10000000
STUB, EXIT = 0x6B198, 0x6B196          # Watcom 10.6 BINW/WPP386.EXE (CF size 0xCB656): int-21h stub & exit retf


def cf_load(path, base):
    d = open(path, 'rb').read()
    at = struct.unpack_from('<H', d, 8)[0] * 16
    sig, foff, size, reloc, mem, entry = struct.unpack_from('<6I', d, at)
    assert sig == 0x4643, 'not a Watcom CF header'
    img = bytearray(mem)
    img[:size] = d[foff:foff + size]
    p = reloc
    n_rel = 0
    while True:
        cnt = struct.unpack_from('<H', img, p)[0]
        p += 2
        if cnt == 0:
            break
        hi, lo = struct.unpack_from('<HH', img, p)
        p += 4
        off = (hi << 16) | lo
        for i in range(cnt):
            if i:
                off += struct.unpack_from('<H', img, p)[0]
                p += 2
            v = struct.unpack_from('<I', img, off)[0]
            struct.pack_into('<I', img, off, (v + base) & 0xFFFFFFFF)
            n_rel += 1
    return dict(size=size, mem=mem, entry=entry, reloc=reloc, nrel=n_rel), img


def gdt_entry(base, limit, access, flags):
    e = (limit & 0xFFFF) | ((base & 0xFFFFFF) << 16) | ((access & 0xFF) << 40) | (((limit >> 16) & 0xF) << 48)
    e |= ((flags & 0xF) << 52) | (((base >> 24) & 0xFF) << 56)
    return struct.pack('<Q', e)


class Ende(Exception):
    pass


class Emu106:
    def __init__(self, root, args, exe=EXE_DEFAULT, env=None, fill=None, stub=None, exit=None):
        # Configurable stub/exit addresses (WPP386: 0x6B198/0x6B196; WCC386: 0x33BC4/0x33BC2)
        self.stub = STUB if stub is None else stub
        self.exit_ = EXIT if exit is None else exit
        self.hdr, img = cf_load(exe, BASE)
        self.img = bytes(img)
        self.fill = fill
        uc = self.uc = U.Uc(U.UC_ARCH_X86, U.UC_MODE_32)
        uc.mem_map(0, 0x100000)
        uc.mem_map(STACK_LO, STACK_HI - STACK_LO)
        uc.mem_map(BASE, (self.hdr['mem'] + 0xFFFF) & ~0xFFFF)
        uc.mem_map(HEAP_LO, HEAP_HI - HEAP_LO)
        uc.mem_write(GDT, b'\0' * 8 + gdt_entry(0, 0xFFFFF, 0x9A, 0xC) + gdt_entry(0, 0xFFFFF, 0x92, 0xC))
        uc.reg_write(X.UC_X86_REG_GDTR, (0, GDT, 3 * 8 - 1, 0))
        uc.hook_add(U.UC_HOOK_CODE, self._stub, begin=BASE + self.stub, end=BASE + self.stub)
        uc.hook_add(U.UC_HOOK_CODE, self._exit, begin=BASE + self.exit_, end=BASE + self.exit_)
        uc.hook_add(U.UC_HOOK_MEM_UNMAPPED | U.UC_HOOK_MEM_PROT, self._fault)
        self.trace = False
        self.start(root, args, env)

    def start(self, root, args, env=None):
        uc = self.uc
        self.root = os.path.abspath(root)
        self.cwd = ''
        self.out = bytearray()
        self.files = {}
        self.nexth = 5
        self.heap = HEAP_LO
        self.code = None
        self.fault = None
        self.finds = {}
        uc.mem_write(BASE, self.img)
        if self.fill is not None:
            uc.mem_write(STACK_LO, bytes([self.fill]) * (STACK_HI - STACK_LO))
        for r in (X.UC_X86_REG_SS, X.UC_X86_REG_DS, X.UC_X86_REG_ES, X.UC_X86_REG_FS, X.UC_X86_REG_GS):
            uc.reg_write(r, 0x10)
        env = env if env is not None else {'PATH': 'C:\\', 'INCLUDE': 'C:\\INC;C:\\H', 'WATCOM': 'C:\\'}
        envb = b''.join(('%s=%s' % kv).encode() + b'\0' for kv in env.items()) + b'\0'
        prog = b'C:\\BINW\\WPP386.EXE\0'
        argb = ' '.join(args).encode() + b'\0\0'
        p_env = INFO
        p_prog = p_env + len(envb)
        p_args = p_prog + len(prog)
        p_flag = (p_args + len(argb) + 15) & ~15
        p_start = p_flag + 16
        p_loader = p_start + 32
        uc.mem_write(p_env, envb + prog + argb)
        uc.mem_write(p_start, struct.pack('<5I', p_prog, p_args, p_env, p_flag, 0))
        uc.reg_write(X.UC_X86_REG_ESP, STACK_HI - 0x100)
        uc.reg_write(X.UC_X86_REG_EAX, 0x100)
        uc.reg_write(X.UC_X86_REG_EBX, BASE | 0x08)
        uc.reg_write(X.UC_X86_REG_ECX, p_loader)
        uc.reg_write(X.UC_X86_REG_EDX, 0)
        uc.reg_write(X.UC_X86_REG_EDI, p_start)
        uc.reg_write(X.UC_X86_REG_EBP, 0)
        uc.reg_write(X.UC_X86_REG_EFLAGS, 0x202)

    # -------------------------------------------------- Helpers
    def r(self, reg):
        return self.uc.reg_read(reg)

    def w(self, reg, v):
        self.uc.reg_write(reg, v & 0xFFFFFFFF)

    def rd(self, a, n):
        return bytes(self.uc.mem_read(a, n))

    def u32(self, a):
        return struct.unpack('<I', self.rd(a, 4))[0]

    def cstr(self, a, n=260):
        b = self.rd(a, n)
        return (b[:b.index(0)] if 0 in b else b).decode('latin-1')

    def host(self, dos, create=False):
        p = dos.replace('/', '\\')
        if len(p) >= 2 and p[1] == ':':
            p = p[2:]
        parts = p.split('\\') if p.startswith('\\') else (self.cwd.split('\\') if self.cwd else []) + p.split('\\')
        cur = self.root
        parts = [x for x in parts if x and x != '.']
        for i, x in enumerate(parts):
            try:
                names = os.listdir(cur)
            except OSError:
                return None
            hit = [n for n in names if n.lower() == x.lower()]
            if hit:
                cur = os.path.join(cur, hit[0])
            elif create and i == len(parts) - 1:
                cur = os.path.join(cur, x.upper())
            else:
                return None
        return cur

    def ok(self, eax=None):
        if eax is not None:
            self.w(X.UC_X86_REG_EAX, eax)
        self.cf(0)

    def err(self, code):
        self.w(X.UC_X86_REG_EAX, code)
        self.cf(1)

    def cf(self, c):
        f = self.r(X.UC_X86_REG_EFLAGS)
        self.w(X.UC_X86_REG_EFLAGS, (f | 1) if c else (f & ~1))

    # -------------------------------------------------- Hooks
    def _exit(self, uc, addr, size, _):
        if self.code is None:
            self.code = self.r(X.UC_X86_REG_EAX) & 0xFF
        uc.emu_stop()

    def _fault(self, uc, access, addr, size, value, _):
        self.fault = 'memory fault %d at %#x (eip %#x)' % (access, addr, self.r(X.UC_X86_REG_EIP))
        return False

    def _stub(self, uc, addr, size, _):
        ah = (self.r(X.UC_X86_REG_EAX) >> 8) & 0xFF
        al = self.r(X.UC_X86_REG_EAX) & 0xFF
        fn = getattr(self, 'dos_%02X' % ah, None)
        if self.trace:
            print('int21 %02X al=%02X' % (ah, al), file=sys.stderr)
        if fn is None:
            self.fault = 'unhandled DOS service %02X al=%02X' % (ah, al)
            uc.emu_stop()
            return
        try:
            fn(al)
        except Ende:
            uc.emu_stop()
            return
        uc.reg_write(X.UC_X86_REG_EIP, BASE + self.stub + 8)      # resume at stub ret

    # -------------------------------------------------- DOS Services
    def _fh(self):
        return self.r(X.UC_X86_REG_EBX) & 0xFFFF

    def _open(self, path, mode):
        h = next(k for k in range(5, 65536) if k not in self.files)
        self.files[h] = open(path, mode)
        return h

    def dos_3C(self, al):
        p = self.host(self.cstr(self.r(X.UC_X86_REG_EDX)), create=True)
        if p is None:
            return self.err(3)
        self.ok(self._open(p, 'w+b'))

    def dos_3D(self, al):
        name = self.cstr(self.r(X.UC_X86_REG_EDX))
        p = self.host(name)
        if p is None or os.path.isdir(p):
            return self.err(2)
        self.ok(self._open(p, 'r+b' if al & 3 else 'rb'))

    def dos_3E(self, al):
        h = self._fh()
        f = self.files.pop(h, None)
        if f:
            f.close()
        self.ok(0)

    def dos_3F(self, al):
        h = self._fh()
        n = self.r(X.UC_X86_REG_ECX)
        buf = self.r(X.UC_X86_REG_EDX)
        if h == 0:
            return self.ok(0)
        f = self.files.get(h)
        if f is None:
            return self.err(6)
        d = f.read(n)
        self.uc.mem_write(buf, d)
        self.ok(len(d))

    def dos_40(self, al):
        h = self._fh()
        n = self.r(X.UC_X86_REG_ECX)
        d = self.rd(self.r(X.UC_X86_REG_EDX), n) if n else b''
        if h in (1, 2):
            self.out += d
            return self.ok(n)
        f = self.files.get(h)
        if f is None:
            return self.err(6)
        if n == 0:
            f.truncate()
            return self.ok(0)
        f.write(d)
        self.ok(n)

    def dos_41(self, al):
        p = self.host(self.cstr(self.r(X.UC_X86_REG_EDX)))
        if p is None:
            return self.err(2)
        os.remove(p)
        self.ok(0)

    def dos_42(self, al):
        h = self._fh()
        f = self.files.get(h)
        if f is None:
            return self.err(6)
        off = ((self.r(X.UC_X86_REG_ECX) & 0xFFFF) << 16) | (self.r(X.UC_X86_REG_EDX) & 0xFFFF)
        if off & 0x80000000:
            off -= 1 << 32
        f.seek(off, al)
        pos = f.tell()
        self.w(X.UC_X86_REG_EDX, (self.r(X.UC_X86_REG_EDX) & 0xFFFF0000) | (pos >> 16))
        self.ok(pos)

    def dos_43(self, al):
        p = self.host(self.cstr(self.r(X.UC_X86_REG_EDX)))
        if p is None:
            return self.err(2)
        self.w(X.UC_X86_REG_ECX, 0x10 if os.path.isdir(p) else 0x20)
        self.ok(0)

    def dos_44(self, al):
        h = self._fh()
        if al == 0:
            self.w(X.UC_X86_REG_EDX, 0x80 if h < 5 else 0)
            return self.ok(0)
        self.err(1)

    def dos_48(self, al):
        n = self.r(X.UC_X86_REG_EBX)
        a = (self.heap + 0xFFFF) & ~0xFFFF
        if a + n > HEAP_HI:
            return self.err(8)
        self.heap = a + n
        self.ok(a)

    def dos_49(self, al):
        self.ok(0)

    def dos_4C(self, al):
        self.code = al
        raise Ende()

    def dos_19(self, al):
        self.ok(2)

    def dos_47(self, al):
        self.uc.mem_write(self.r(X.UC_X86_REG_ESI), self.cwd.encode() + b'\0')
        self.ok(0)

    def dos_2A(self, al):
        self.w(X.UC_X86_REG_ECX, 1996)
        self.w(X.UC_X86_REG_EDX, (6 << 8) | 1)
        self.w(X.UC_X86_REG_EAX, 6)
        self.cf(0)

    def dos_2C(self, al):
        self.w(X.UC_X86_REG_ECX, 12 << 8)
        self.w(X.UC_X86_REG_EDX, 0)
        self.cf(0)

    def dos_57(self, al):
        if al == 0:
            self.w(X.UC_X86_REG_ECX, 0x6000)
            self.w(X.UC_X86_REG_EDX, 0x20C1)
            return self.ok(0)
        self.ok(0)

    def dos_56(self, al):
        a = self.host(self.cstr(self.r(X.UC_X86_REG_EDX)))
        b = self.host(self.cstr(self.r(X.UC_X86_REG_EDI)), create=True)
        if a is None or b is None:
            return self.err(2)
        os.replace(a, b)
        self.ok(0)

    def dos_60(self, al):
        name = self.cstr(self.r(X.UC_X86_REG_EDX))
        p = name.replace('/', '\\')
        if not (len(p) >= 2 and p[1] == ':'):
            p = 'C:\\' + (self.cwd + '\\' if self.cwd else '') + p.lstrip('\\') if not p.startswith('\\') else 'C:' + p
        self.uc.mem_write(self.r(X.UC_X86_REG_EBX), p.upper().encode() + b'\0')
        self.ok(0)

    def dos_4E(self, al):
        import fnmatch
        pat = self.cstr(self.r(X.UC_X86_REG_EDX)).replace('/', '\\')
        dta = self.r(X.UC_X86_REG_EBX)
        d, _, f = pat.rpartition('\\')
        hd = self.host(d) if d else self.host('.')
        if hd is None or not os.path.isdir(hd):
            return self.err(3)
        hits = sorted(n for n in os.listdir(hd) if fnmatch.fnmatch(n.lower(), f.lower().replace('*.*', '*')))
        if not hits:
            return self.err(18)
        self.finds[dta] = (hd, hits[1:])
        self._dta(dta, hd, hits[0])
        self.ok(0)

    def dos_4F(self, al):
        dta = self.r(X.UC_X86_REG_EDX)
        if al:
            self.finds.pop(dta, None)
            return self.ok(0)
        hd, rest = self.finds.get(dta, (None, []))
        if not rest:
            return self.err(18)
        self.finds[dta] = (hd, rest[1:])
        self._dta(dta, hd, rest[0])
        self.ok(0)

    def _dta(self, dta, hd, n):
        p = os.path.join(hd, n)
        st = os.stat(p)
        attr = 0x10 if os.path.isdir(p) else 0x20
        self.uc.mem_write(
            dta + 0x15,
            struct.pack('<BHHI', attr, 0x6000, 0x20C1, st.st_size if attr == 0x20 else 0)
            + n.upper().encode()[:12] + b'\0'
        )

    # -------------------------------------------------- Run
    def run(self, max_s=120):
        t = time.time()
        try:
            self.uc.emu_start(BASE + self.hdr['entry'], 0, timeout=int(max_s * 1e6))
        except U.UcError as e:
            if self.fault is None:
                self.fault = 'UcError %s eip %#x' % (e, self.r(X.UC_X86_REG_EIP))
        for f in self.files.values():
            f.close()
        self.files = {}
        return self.code, time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--trace', action='store_true')
    ap.add_argument('args', nargs='*')
    a = ap.parse_args()
    e = Emu106(a.root, a.args)
    e.trace = a.trace
    code, dt = e.run()
    sys.stdout.write(e.out.decode('latin-1').replace('\r', ''))
    print('[emu106] Exit %s, %.2f s%s' % (code, dt, (', ' + e.fault) if e.fault else ''), file=sys.stderr)
    sys.exit(0 if code == 0 else 1)


if __name__ == '__main__':
    main()
