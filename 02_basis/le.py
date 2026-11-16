#!/usr/bin/env python3
"""le.py - Linear Executable (LE, 32-bit Watcom/DOS4GW) and MZ (16-bit Borland/DOS) binary parser.

Reads the target binary path from `project.json` (or `TARGET_EXE` environment variable),
parses objects, page tables, and fixup records, and exposes `CODE`, `DATA`, `CB`, `DB`,
`objs`, and `fixups` for downstream baseline and verification tools.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import project_config as PC


def parse_mz_relocs(d: bytes):
    """Parse 16-bit DOS MZ header and relocation table (e.g. Borland C++ 16-bit executables)."""
    if len(d) < 0x1C or d[:2] not in (b"MZ", b"ZM"):
        raise ValueError("not an MZ executable")
    last_page_bytes, pages, nrelocs, hdr_paras = struct.unpack_from("<4H", d, 2)
    reloc_ofs = struct.unpack_from("<H", d, 0x18)[0]
    hdr_size = hdr_paras * 16
    img_end = pages * 512 - (512 - last_page_bytes if last_page_bytes else 0)
    image = d[hdr_size:img_end]
    relocs = []
    for k in range(nrelocs):
        off, seg = struct.unpack_from("<HH", d, reloc_ofs + 4 * k)
        linear = seg * 16 + off
        relocs.append((seg, off, linear))
    return {"header_size": hdr_size, "image": image, "relocs": relocs}


def load_le(exe_path: str, stub_hint: int = 0):
    d = open(exe_path, "rb").read()
    start = stub_hint if stub_hint > 0 else (0x30000 if len(d) > 0x30000 else 0)
    L = d.find(b"LE\x00\x00", start)
    if L < 0:
        L = d.find(b"LE\x00\x00")
    if L < 0:
        raise ValueError(f"no LE header found in {exe_path}")
    u = lambda o, fmt="<I": struct.unpack_from(fmt, d, L + o)[0]
    npages = u(0x14)
    lastpg = u(0x2C)
    fpt = L + u(0x68)
    frt = L + u(0x6C)
    objs = []
    for k in range(u(0x44)):
        vs, ba, fl, pi, pc, _ = struct.unpack_from("<6I", d, L + u(0x40) + 24 * k)
        objs.append(dict(vsize=vs, base=ba, flags=fl, page=pi, npages=pc))
    # Page data starts near EOF for stub-bound DOS/4GW executables
    B = len(d) - ((npages - 1) * 4096 + lastpg)

    def img(i):
        o = objs[i]
        s = B + (o["page"] - 1) * 4096
        return d[s : s + min(o["vsize"], o["npages"] * 4096)]

    fixups = []
    for pg in range(npages):
        a, b = struct.unpack_from("<II", d, fpt + 4 * pg)
        oi = [k for k, o in enumerate(objs) if o["page"] - 1 <= pg < o["page"] - 1 + o["npages"]][0]
        pvb = objs[oi]["base"] + (pg - (objs[oi]["page"] - 1)) * 4096
        i = frt + a
        e = frt + b
        while i < e:
            st = d[i]
            fl = d[i + 1]
            i += 2
            if st & 0x20:
                cnt = d[i]
                i += 1
            else:
                so = struct.unpack_from("<h", d, i)[0]
                i += 2
            if fl & 0x40:
                on = struct.unpack_from("<H", d, i)[0]
                i += 2
            else:
                on = d[i]
                i += 1
            to = 0
            if (st & 0xF) != 2:
                if fl & 0x10:
                    to = struct.unpack_from("<I", d, i)[0]
                    i += 4
                else:
                    to = struct.unpack_from("<H", d, i)[0]
                    i += 2
            if st & 0x20:
                for _ in range(cnt):
                    so = struct.unpack_from("<h", d, i)[0]
                    i += 2
                    fixups.append((pvb + so, st & 0xF, objs[on - 1]["base"] + to))
            else:
                fixups.append((pvb + so, st & 0xF, objs[on - 1]["base"] + to))
    code = img(0) if len(objs) > 0 else b""
    data = img(1) if len(objs) > 1 else b""
    cb = objs[0]["base"] if len(objs) > 0 else 0x10000
    db = objs[1]["base"] if len(objs) > 1 else 0
    return d, L, objs, fixups, code, data, cb, db


_cfg = PC.load_config()
EXE = os.environ.get("TARGET_EXE") or PC.resolve_path("orig_exe", _cfg)
if EXE and os.path.isfile(EXE):
    d, L, objs, fixups, CODE, DATA, CB, DB = load_le(EXE, int(_cfg.get("binary", {}).get("stub_offset", 0) or 0))
else:
    d, L, objs, fixups, CODE, DATA, CB, DB = b"", 0, [], [], b"", b"", 0x10000, 0
