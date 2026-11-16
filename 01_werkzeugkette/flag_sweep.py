#!/usr/bin/env python3
"""flag_sweep.py - Sweep per-unit Watcom compiler flag variants and score each against the exact judge.

Usage:
  python3 flag_sweep.py --unit UNIT_NAME --src SOURCE.CPP --lo START_HEX [--hi END_HEX]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comp import comp
import w106cfg as C

VARIANTS = [
    ('baseline', None, ''),
    ('od', '-4r -od -zp1 -s', ''),
    ('oc', '-4r -oneatxc -zp1 -s', ''),
    ('of', '-4r -oneatxf -zp1 -s', ''),
    ('ol+', '-4r -oneatxl+ -zp1 -s', ''),
    ('os', '-4r -oneasx -zp1 -s', ''),
    ('no_e', '-4r -onatx -zp1 -s', ''),
    ('ou', '-4r -oneatxu -zp1 -s', ''),
    ('5r', '-5r -oneatx -zp1 -s', ''),
    ('3r', '-3r -oneatx -zp1 -s', ''),
    ('no_s', '-4r -oneatx -zp1', ''),
    ('j', '-4r -oneatx -zp1 -s -j', ''),
    ('ri', '-4r -oneatx -zp1 -s -ri', ''),
    ('inl0', None, '#pragma inline_depth(0)\n'),
    ('zp4', '-4r -oneatx -zp4 -s', ''),
    ('no_a', '-4r -onetx -zp1 -s', ''),
    ('no_n', '-4r -oeatx -zp1 -s', ''),
    ('oe40', '-4r -oneatx -oe=40 -zp1 -s', ''),
    ('oe80', '-4r -oneatx -oe=80 -zp1 -s', ''),
    ('oe400', '-4r -oneatx -oe=400 -zp1 -s', ''),
    ('xs', '-4r -oneatx -zp1 -s -xs', ''),
    ('zm', '-4r -oneatx -zp1 -s -zm', ''),
]

FSTAND = os.path.normpath(os.path.join(C.HERE, '..', '03_richter', 'fstand.py'))


def parse_fstand(txt):
    r = {}
    for l in txt.splitlines():
        mm = re.match(r'([0-9A-F]{4,8})\s+(\d+)/(\d+)\s+(GLEICH|MATCH|(\d+) (?:Befehle|insns)|FEHLT|MISSING)', l)
        if mm:
            rest = 0 if mm[4] in ('GLEICH', 'MATCH') else int(mm[5]) if mm[5] else 99999
            r[mm[1]] = (rest, int(mm[2]), int(mm[3]))
    return r


def main():
    ap = argparse.ArgumentParser(description='Sweep Watcom 10.6 compiler flags on a single unit.')
    ap.add_argument('--unit', required=True)
    ap.add_argument('--src', required=True)
    ap.add_argument('--lo', required=True)
    ap.add_argument('--hi', default='')
    args = ap.parse_args()

    src_text = open(args.src, encoding='latin1').read()
    m = re.search(r'^// OPT (.*)$', src_text, re.M)
    base_opt = m.group(1).strip().split() if m else ['-4r', '-oneatx', '-zp1', '-s']

    base_res = None
    for name, opt_str, prefix in VARIANTS:
        opts = opt_str.split() if opt_str else base_opt
        with tempfile.NamedTemporaryFile(dir=C.TMP, suffix='.CPP', mode='w', encoding='latin1', delete=False) as tf:
            tf.write(prefix + src_text)
            tmp_src = tf.name
        tmp_obj = tmp_src + '.obj'
        try:
            ok, out, _ = comp(tmp_src, tmp_obj, extra=opts)
            if not ok or not os.path.exists(tmp_obj):
                print(f'{args.unit}\t{name}\tCOMPILE_ERROR')
                continue
            cmd = [sys.executable, FSTAND, tmp_obj, args.lo] + ([args.hi] if args.hi else [])
            fst_out = subprocess.run(cmd, capture_output=True, text=True, errors='replace').stdout
            parsed = parse_fstand(fst_out)
            if name == 'baseline':
                base_res = parsed
            matched = sum(1 for v in parsed.values() if v[0] == 0)
            total_rest = sum(v[0] for v in parsed.values() if v[0] < 99999)
            print(f'{args.unit}\t{name}\tmatched={matched}/{len(parsed)}\ttotal_rest={total_rest}\tflags={" ".join(opts)}')
        finally:
            for p in (tmp_src, tmp_obj):
                if os.path.exists(p):
                    os.remove(p)


if __name__ == '__main__':
    main()
