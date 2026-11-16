#!/usr/bin/env python3
"""bisect_units.py - Partition modified fix units into N bisection groups (G1..GN) to isolate size-shift crashes."""
import argparse
from pathlib import Path
import shutil


def main():
    ap = argparse.ArgumentParser(description="Split modified units into N groups over the unswitched baseline for bisection.")
    ap.add_argument("--baseline", required=True, type=Path, help="Verified baseline source directory (Δ=0)")
    ap.add_argument("--fixed", required=True, type=Path, help="Switched fix source directory (Δ!=0)")
    ap.add_argument("--out", required=True, type=Path, help="Output directory for bisection groups G1..GN")
    ap.add_argument("--groups", type=int, default=4, help="Number of bisection groups (default: 4)")
    args = ap.parse_args()

    modified = []
    for p in sorted(args.fixed.glob("*.[cC]*")):
        b = args.baseline / p.name
        if b.is_file() and p.read_bytes() != b.read_bytes():
            modified.append(p.name)

    print(f"Modified units: {len(modified)} -> splitting into {args.groups} groups")
    for g in range(args.groups):
        g_dir = args.out / f"G{g + 1}"
        if g_dir.exists():
            shutil.rmtree(g_dir)
        shutil.copytree(args.baseline, g_dir)
        slice_units = modified[g::args.groups]
        for u in slice_units:
            shutil.copy2(args.fixed / u, g_dir / u)
        print(f"  G{g + 1}: {len(slice_units)} modified units ({', '.join(slice_units[:5])}...)")


if __name__ == "__main__":
    main()
