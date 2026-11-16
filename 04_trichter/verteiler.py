#!/usr/bin/env python3
"""verteiler.py - "Circle of Freshness" funnel dispatcher and lease manager.

Routes open units/functions by structural Core, instruction count, and freshness
(attempts since the last reduction in Rest):
  python3 verteiler.py next WORKER_ID [--lane deep|fast|large|closing] [--n 1]
  python3 verteiler.py done WORKER_ID UNIT [STATUS]
  python3 verteiler.py status
"""
import argparse
import csv
import fcntl
import json
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
V_DIR = os.path.join(LOGS_DIR, "funnel")
os.makedirs(V_DIR, exist_ok=True)

STATUS_TSV = os.path.join(LOGS_DIR, "live_status.tsv")
SPERREN_TSV = os.path.join(V_DIR, "LEASES.tsv")
LOG_TSV = os.path.join(V_DIR, "FUNNEL_LOG.tsv")
LEASE_SECONDS = 4 * 3600

now_iso = lambda: time.strftime("%Y-%m-%dT%H:%M:%S")


def load_open_units():
    O = {}
    if not os.path.isfile(STATUS_TSV):
        return O
    for r in csv.DictReader(open(STATUS_TSV, encoding="utf-8", errors="replace"), delimiter="\t"):
        if r.get("rest") in ("FEHLT", "MISSING", None):
            continue
        try:
            rest = int(r["rest"])
        except ValueError:
            continue
        if rest <= 0:
            continue
        u = r["unit"]
        fn = r["func"]
        core = int(r.get("core") or rest)
        insns = int(r.get("insns") or 0)
        failed = int(r.get("failed_at_current_rest") or 0)
        F = O.setdefault(u, {})
        if fn not in F or rest < F[fn]["rest"]:
            F[fn] = dict(func=fn, rest=rest, core=core, insns=insns, bytes=r.get("bytes", ""), failed=failed)
    return {u: list(F.values()) for u, F in O.items()}


def read_leases():
    L = []
    if os.path.isfile(SPERREN_TSV):
        for l in open(SPERREN_TSV, encoding="utf-8").read().splitlines()[1:]:
            z = l.split("\t")
            if len(z) >= 4 and float(z[3]) > time.time():
                L.append(z)
    return L


def write_leases(L):
    tmp = SPERREN_TSV + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("timestamp\tid\tunit\texpires\n" + "".join("\t".join(z[:4]) + "\n" for z in L))
    os.replace(tmp, SPERREN_TSV)


def log_event(*cols):
    is_new = not os.path.isfile(LOG_TSV)
    with open(LOG_TSV, "a", encoding="utf-8") as h:
        if is_new:
            h.write("timestamp\taction\tid\tunit\tinfo\n")
        h.write("\t".join([now_iso()] + [str(y) for y in cols]) + "\n")


def carousel_locks():
    """Lock units returned 'open' by >= 2 distinct workers within 6 hours."""
    now = time.time()
    if not os.path.isfile(LOG_TSV):
        return set()
    events = []
    for line in open(LOG_TSV, encoding="utf-8").read().splitlines()[1:]:
        z = line.split("\t")
        if len(z) < 5 or z[1] != "done" or z[4] != "open":
            continue
        try:
            t = time.mktime(time.strptime(z[0][:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        if now - 12 * 3600 <= t <= now:
            events.append((t, z[2], z[3]))
    seen, until = {}, {}
    for t, wid, unit in sorted(events):
        ids = {a: ts for a, ts in seen.get(unit, {}).items() if t - ts < 6 * 3600}
        ids[wid] = t
        seen[unit] = ids
        if len(ids) >= 2:
            until[unit] = t + 6 * 3600
    return {u for u, exp in until.items() if exp > now}


def rank_candidates(wid, lane):
    O = load_open_units()
    leases = read_leases()
    busy = {z[2]: z[1] for z in leases if z[1] != wid}
    own = {z[2] for z in leases if z[1] == wid}
    blocked = carousel_locks()
    C = []
    for u, F in O.items():
        if u in busy or u in own or u in blocked:
            continue
        if lane == "fast" and (len(F) > 3 or max(f["rest"] for f in F) > 30):
            continue
        if lane == "closing":
            sr = sum(f["rest"] for f in F)
            if len(F) > 2 or sr > 15:
                continue
        if lane == "large" and not any(f["rest"] > 40 or f["insns"] >= 200 for f in F):
            continue
        fresh = 0 if any(f["failed"] == 0 for f in F) else 1
        sr = sum(f["rest"] for f in F)
        band = 0 if sr <= 30 else 1 if sr <= 80 else 2
        C.append((len(F), band, fresh, sr, u, sorted(F, key=lambda f: f["rest"])))
    C.sort()
    return C


def main():
    ap = argparse.ArgumentParser(description="Circle-of-Freshness funnel dispatcher.")
    ap.add_argument("action", choices=["next", "done", "status"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--lane", default="deep", choices=["deep", "fast", "large", "closing"])
    ap.add_argument("--n", type=int, default=1)
    A = ap.parse_args()

    lk = open(os.path.join(V_DIR, ".lock"), "w")
    fcntl.flock(lk, fcntl.LOCK_EX)

    if A.action == "next":
        wid = A.args[0] if A.args else "worker_01"
        C = rank_candidates(wid, A.lane)[:A.n]
        if not C:
            print("# No matching open units available.")
            return
        L = read_leases()
        print("unit\tfunc\trest\tcore\topen_in_unit\tfresh")
        for n, band, fr, sr, u, F in C:
            L.append([now_iso(), wid, u, str(time.time() + LEASE_SECONDS)])
            log_event("next", wid, u, f"{n} open, Rest {sr}")
            for f in F:
                print(f"{u}\t{f['func']}\t{f['rest']}\t{f['core']}\t{n}\t{'yes' if fr == 0 else 'no'}")
        write_leases(L)
    elif A.action == "done":
        wid, u = A.args[0], A.args[1]
        st = A.args[2] if len(A.args) > 2 else "open"
        write_leases([z for z in read_leases() if not (z[1] == wid and z[2] == u)])
        log_event("done", wid, u, st)
        print(f"released: {u} ({st})")
    else:
        O = load_open_units()
        L = read_leases()
        print(f"Open units: {len(O)}, open functions: {sum(len(F) for F in O.values())}, active leases: {len(L)}")
        for lane in ("deep", "fast", "large", "closing"):
            print(f"  available for {lane}: {len(rank_candidates('-', lane))} units")


if __name__ == "__main__":
    main()
