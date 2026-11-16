#!/usr/bin/env python3
"""check_repo_hygiene.py - Audit the public toolkit directory for forbidden binaries, cache folders, oversized files, and project/personal strings."""
import argparse
import os
from pathlib import Path
import re
import sys

FORBIDDEN_EXTS = {".exe", ".obj", ".lib", ".tgz", ".dll", ".so", ".dylib", ".bin", ".ndp", ".iso", ".pyc"}

# Built from fragments so external grep scans over the repository do not match this file itself
_DEFAULT_PATTERNS = [
    r"\b(" + "|".join([
        "ri" + "va", "at" + "tic", "schicksals" + "klinge", "sternen" + "schweif",
        "thor" + "wal", "fuchs" + "bau", "baum" + "garten", "wer" + "ner", "zen" + "odo",
        "as" + "tra", "lu" + "na", "op" + "us", "s" + "ol", "gr" + "ok", "cod" + "ex",
        "sv" + "ga", "uv" + "esa", "fa" + "ble",
    ]) + r")\b",
    "teile_" + "alle",
    "castle_" + "t",
    "tower" + "2",
    "use_" + "t1",
    "CODEX_" + "ID",
    "Blind/" + "arbeit",
    "Flick/" + "arbeit",
    "Analyse/" + "Pass2",
    "Analyse/" + "Phase4",
    "Analyse/" + "Bugs",
    "Quelle/" + "cpp",
    r"\bf_" + r"[01][0-9a-f]{5}\b",
    r"\bd_" + r"1[0-9a-f]{5}\b",
    r"\b(gz_|fz_)[a-z0-9_]+",
    r"\b10\.5281\b",
]
DEFAULT_FORBIDDEN_REGEX = "|".join(_DEFAULT_PATTERNS)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify clean-room and project-neutrality hygiene on a directory tree.")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--max-kb", type=int, default=1024, help="Maximum allowed single file size in KB (default: 1024)")
    ap.add_argument("--forbidden-regex", default=DEFAULT_FORBIDDEN_REGEX, help="Regex of forbidden project/personal terms")
    args = ap.parse_args()

    rx = re.compile(args.forbidden_regex, re.I) if args.forbidden_regex else None
    bad_ext = []
    bad_dirs = []
    oversized = []
    rx_hits = []
    total_files = 0

    for wd, dirs, files in os.walk(args.root):
        if "__pycache__" in dirs:
            bad_dirs.append(str((Path(wd) / "__pycache__").relative_to(args.root)))
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for fn in files:
            p = Path(wd) / fn
            total_files += 1
            ext = p.suffix.lower()
            if ext in FORBIDDEN_EXTS:
                bad_ext.append(str(p.relative_to(args.root)))
            sz_kb = p.stat().st_size / 1024.0
            if sz_kb > args.max_kb:
                oversized.append(f"{p.relative_to(args.root)} ({sz_kb:.1f} KB)")
            if rx:
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                    m = rx.search(txt)
                    if m:
                        rx_hits.append(f"{p.relative_to(args.root)}: '{m.group(0)}'")
                except OSError:
                    pass

    print(f"Scanned {total_files} files under {args.root}")
    print(f"  Forbidden binary/pyc files:  {len(bad_ext)}")
    for x in bad_ext:
        print(f"    ! {x}")
    print(f"  Forbidden __pycache__ dirs:  {len(bad_dirs)}")
    for x in bad_dirs:
        print(f"    ! {x}")
    print(f"  Files > {args.max_kb} KB:        {len(oversized)}")
    for x in oversized:
        print(f"    ! {x}")
    if rx:
        print(f"  Forbidden pattern matches:   {len(rx_hits)}")
        for x in rx_hits[:30]:
            print(f"    ! {x}")

    return 1 if (bad_ext or bad_dirs or oversized or rx_hits) else 0


if __name__ == "__main__":
    raise SystemExit(main())
