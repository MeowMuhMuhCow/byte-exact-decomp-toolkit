#!/usr/bin/env python3
"""mkfix.py - Generate tiered compile-time bug-fix switch header (`fix_switches.h`) from a switch table.

Supports three build tiers from a single source tree:
  - FIX_BUGS=0: 100% byte-exact original executable
  - FIX_BUGS=1: Stage A (certain crashes, memory corruption, operator-precedence bugs)
  - FIX_BUGS=2: Stage B (all fixes; beneficial player exploits toggleable via -DFIX_EXPLOITS=0)
"""
import argparse
import csv
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))
import project_config as PC


def load_switches(tsv_path: Path) -> list[tuple[str, str, bool, str, str]]:
    if not tsv_path or not tsv_path.is_file():
        return [
            ("FIX_001", "A", False, "unit_001 / f_400010", "Example Stage A safety fix"),
            ("FIX_002", "B", True, "unit_002 / f_400200", "Example Stage B logic/exploit fix"),
        ]
    rows = []
    with tsv_path.open(encoding="utf-8") as f:
        for r in csv.reader(f, delimiter="\t"):
            if not r or r[0].startswith("#") or r[0] == "switch_name":
                continue
            rows.append((r[0], r[1], r[2].lower() in ("1", "true", "yes"), r[3], r[4] if len(r) > 4 else ""))
    return rows


def render_fix_inc(switches: list[tuple[str, str, bool, str, str]]) -> str:
    lines = [
        "/* Auto-generated compile-time bug-fix switches (included by fix_switches.h) */",
        "",
    ]
    for name, stage, exploit, loc, desc in switches:
        if stage == "A":
            macro = "FIX_STAGE_A_EXPLOIT" if exploit else "FIX_STAGE_A"
        else:
            macro = "FIX_STAGE_B_EXPLOIT" if exploit else "FIX_STAGE_B"
        lines.append(f"/* {name}: {loc} - {desc} */")
        lines.append(f"#ifndef {name}")
        lines.append(f"#define {name} {macro}")
        lines.append("#endif")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify or generate compile-time bug-fix switch header (fix_switches.h).")
    ap.add_argument("--table", type=Path, default=None, help="TSV file listing switches (switch_name, stage A|B, exploit, location, description)")
    ap.add_argument("--out", type=Path, default=None, help="Output .inc path")
    ap.add_argument("--write", action="store_true", help="Write the generated .inc file")
    args = ap.parse_args()

    cfg = PC.load_config()
    inc_dir = Path(PC.resolve_path("inc_dir", cfg, "src/inc"))
    out_path = args.out or (inc_dir / "fix_switches.h")
    switches = load_switches(args.table)

    cnt_a = sum(1 for _, s, _, _, _ in switches if s == "A")
    cnt_b = sum(1 for _, s, _, _, _ in switches if s == "B")
    cnt_ex = sum(1 for _, _, ex, _, _ in switches if ex)
    print(f"Switches loaded: {len(switches)} ({cnt_a} Stage A, {cnt_b} Stage B, {cnt_ex} toggleable exploits)")

    if args.write:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_fix_inc(switches), encoding="utf-8")
        print(f"[OK] Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
