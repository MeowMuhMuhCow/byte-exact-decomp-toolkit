#!/usr/bin/env python3
"""frisch.py [N] [--for FAMILY] - Rank open functions by attempts since the last drop in Rest (Circle of Freshness)."""
import glob
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import project_config as PC

cfg = PC.load_config()
LOGS_DIR = PC.resolve_path("logs_dir", cfg, os.path.join(ROOT, "logs"))
FSTAND_DIR = os.path.join(LOGS_DIR, "live_fstand")
P3_DIR = PC.resolve_path("src_p3_dir", cfg)
N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 30
FOR_FAM = sys.argv[sys.argv.index("--for") + 1].lower() if "--for" in sys.argv else None

last_change = {}
ratchet_log = os.path.join(LOGS_DIR, "ratchet_commits.log")
if os.path.isfile(ratchet_log):
    for l in open(ratchet_log, encoding="utf-8", errors="replace"):
        p = l.strip().split("\t")
        if len(p) >= 2:
            last_change[p[1]] = p[0][:16]

attempts, families = {}, {}
run_log = os.path.join(LOGS_DIR, "agent_runs.tsv")
if os.path.isfile(run_log):
    for l in open(run_log, encoding="utf-8", errors="replace"):
        p = l.rstrip("\n").split("\t")
        if len(p) >= 6 and "START" in p[5] and p[4].startswith("f_"):
            k = (p[3], p[4])
            if p[0][:16] < last_change.get(p[3], ""):
                continue
            attempts[k] = attempts.get(k, 0) + 1
            families.setdefault(k, set()).add(p[2])

rows = []
for f in sorted(glob.glob(os.path.join(FSTAND_DIR, "*.fstand"))):
    u = os.path.basename(f)[:-7]
    for l in open(f, encoding="latin-1"):
        m = re.match(r"([0-9A-F]{4,8})\s+(\d+)/(\d+)\s+(\d+)\s+(?:Befehle|insns)", l)
        if not m:
            continue
        k = (u, "f_" + m.group(1).lower())
        fams = families.get(k, set())
        if FOR_FAM and FOR_FAM in {x.lower() for x in fams}:
            continue
        rows.append((
            attempts.get(k, 0),
            int(m.group(4)),
            u,
            k[1],
            m.group(2) + "/" + m.group(3),
            last_change.get(u, "-"),
            ",".join(sorted(fams)),
        ))

rows.sort(key=lambda z: (z[0] > 0, z[0], z[1]))
print("tries  rest  unit               func       size        last_commit      families_tried")
for z in rows[:N]:
    print("%5d %5d  %-18s %-10s %-11s %-16s %s" % z)
print(f"-- {len(rows)} open functions listed, {sum(1 for z in rows if z[0] == 0)} untried at current Rest")
