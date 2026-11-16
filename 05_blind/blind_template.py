#!/usr/bin/env python3
"""blind_template.py UNIT FUNC WORKER_ID - Create a working copy of UNIT with FUNC body stripped for memoryless blind rewriting."""
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import project_config as PC

cfg = PC.load_config()
U, FL, ID = sys.argv[1], [x.lower().replace('f_', '') for x in sys.argv[2].split(',')], sys.argv[3]

src = None
for key in ('src_p3_dir', 'src_p2_dir', 'src_p1_dir', 'src_dir'):
    d = PC.resolve_path(key, cfg)
    if d:
        for cand in (f'{U}_P1.CPP', f'{U}.cpp', f'{U}.c'):
            p = os.path.join(d, cand)
            if os.path.isfile(p):
                src = p
                break
    if src:
        break
if not src:
    sys.exit(f'No source file found for unit {U}')

s = open(src, encoding='latin-1').read().replace('\r', '')
for F in FL:
    m = None
    for mm in re.finditer(r'^[^\n;#/]*?\b(?:f_' + F + r'|' + F + r')\s*\([^;{]*?\)\s*(const\s*)?\{', s, re.M | re.I):
        m = mm
        break
    if not m:
        sys.exit(f'Function definition {F} not found in {src}')
    i = m.end() - 1
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                break
        elif c == '/' and s[j:j + 2] == '//':
            j = s.find('\n', j)
            if j < 0:
                break
        elif c == '/' and s[j:j + 2] == '/*':
            j = s.find('*/', j) + 1
        elif c in '"\'':
            k = j + 1
            while k < len(s) and s[k] != c:
                k += 2 if s[k] == '\\' else 1
            j = k
        j += 1
    kopf = s[m.start():m.end() - 1].rstrip()
    dekl = kopf + ';' if '::' not in kopf else '// (class method declaration in header)'
    s = (
        s[:m.start()]
        + f'// BLIND REWRITE: Write f_{F} from scratch from the target assembly (probe.sh orig {U} f_{F}).\n'
        + f'{dekl}\n'
        + s[j + 1:]
    )

drafts_dir = os.path.join(PC.resolve_path('drafts_dir', cfg, os.path.join(str(ROOT), 'drafts')), ID)
os.makedirs(drafts_dir, exist_ok=True)
out = os.path.join(drafts_dir, os.path.basename(src))
open(out, 'w', encoding='latin-1').write(s)
print(out)
