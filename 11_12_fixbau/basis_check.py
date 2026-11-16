#!/usr/bin/env python3
"""basis_check.py - Prove statically that every switched source file reproduces the verified baseline at FIX_BUGS=0."""
import argparse
import difflib
from pathlib import Path
import re
import sys


def read_text(p: Path) -> str:
    b = p.read_bytes()
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def is_fix_cond(c: str) -> bool:
    return bool(re.search(r"\b(FIX_|PLOG_)", c))


def strip_fix_branches(text: str, warnings: list[str]) -> list[str]:
    out = []
    stack = []  # [is_fix_block, currently_active]

    def active() -> bool:
        return all(t for _, t in stack)

    for ln in text.splitlines():
        s = ln.strip()
        m = re.match(r"#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)", s)
        if m:
            kw, cond = m.group(1), m.group(2)
            if kw in ("if", "ifdef", "ifndef"):
                if is_fix_cond(cond):
                    cc = cond.split("/*")[0].replace(" ", "")
                    neg = kw == "ifndef" or cc.startswith("!") or "==0" in cc
                    if neg:
                        warnings.append("NEG:" + s)
                    stack.append([True, neg])
                    continue
                stack.append([False, True])
                if active():
                    out.append(ln)
                continue
            if kw == "elif":
                if stack and stack[-1][0]:
                    warnings.append("ELIF:" + s)
                    stack[-1][1] = False
                    continue
                if active():
                    out.append(ln)
                continue
            if kw == "else":
                if stack and stack[-1][0]:
                    stack[-1][1] = not stack[-1][1]
                    continue
                if active():
                    out.append(ln)
                continue
            if kw == "endif":
                if stack:
                    is_f, _ = stack.pop()
                    if is_f:
                        continue
                if active():
                    out.append(ln)
                continue
        if not active():
            continue
        if re.match(r'^\s*#\s*include\s+"r_fix\.h"', ln, re.I):
            continue
        out.append(ln)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify that #else branches (FIX_BUGS=0) match baseline sources line-for-line.")
    ap.add_argument("--src", required=True, type=Path, help="Directory with switched C/C++ files")
    ap.add_argument("--baseline", required=True, type=Path, help="Directory with unswitched verified C/C++ files")
    args = ap.parse_args()

    diffs_found = 0
    checked = 0
    for p in sorted(args.src.glob("*.[cC]*")):
        b_path = args.baseline / p.name
        if not b_path.is_file():
            continue
        checked += 1
        warn = []
        a = [x.rstrip() for x in strip_fix_branches(read_text(p), warn)]
        b = [x.rstrip() for x in strip_fix_branches(read_text(b_path), [])]
        if a != b:
            diffs_found += 1
            d = [x for x in difflib.unified_diff(b, a, lineterm="", n=0) if x[:1] in "+-" and not x.startswith(("+++", "---"))]
            print(f"{p.name}\tMISMATCH ({len(d)} lines)\t{' | '.join(warn)}")
        else:
            print(f"{p.name}\tMATCH (FIX_BUGS=0 identical)")
    print(f"Summary: {checked} files checked, {diffs_found} mismatches.")
    return 1 if diffs_found else 0


if __name__ == "__main__":
    raise SystemExit(main())
