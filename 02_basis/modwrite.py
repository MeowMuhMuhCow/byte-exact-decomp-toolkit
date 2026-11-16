#!/usr/bin/env python3
"""modwrite.py MODULE.JSON OUTPUT.ASM - Export a single code interval to a symbolic WASM .ASM file."""
import json
import re
import subprocess
import sys
import tempfile
from le import CODE, CB

mod_json, out_asm = sys.argv[1], sys.argv[2]
J = json.load(open(mod_json))
lo, hi = J['lo'], J['hi']
with tempfile.NamedTemporaryFile(suffix='.bin') as tf:
    tf.write(CODE[lo - CB:hi - CB])
    tf.flush()
    dis = {}
    for l in subprocess.run(
        ['objdump', '-D', '-b', 'binary', '-mi386', '-Mintel', f'--adjust-vma={lo:#x}', tf.name],
        capture_output=True, text=True
    ).stdout.splitlines():
        m = re.match(r'^\s+([0-9a-f]+):\t[0-9a-f ]+?\s*\t(.*)$', l)
        if m:
            dis[int(m.group(1), 16)] = m.group(2).strip()
labels = set(J['labels'])
with open(out_asm, 'w', newline='\r\n') as o:
    o.write(f'; Code 0x{lo:06X}-0x{hi:06X} - symbolic WASM baseline\n')
    for a, n, txt in J['ins']:
        if a in labels:
            o.write(f'\nL{a:06X}:\n')
        if txt:
            o.write(f'        {txt}\n')
        else:
            raw = ','.join(f'0{b:02X}h' for b in CODE[a - CB:a - CB + n])
            o.write(f'        db {raw}   ; {dis.get(a, "")}\n')
