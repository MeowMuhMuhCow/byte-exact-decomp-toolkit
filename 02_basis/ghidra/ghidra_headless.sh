#!/bin/bash
# ghidra_headless.sh - Run Ghidra headless initial analysis, __watcall parameter inference, and C draft export.
set -e
S=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$S/../.." && pwd)
eval "$(python3 "$ROOT/project_config.py" --env-sh)"

GHIDRA_DIR="${GHIDRA_HOME:-/opt/ghidra}"
WORK_DIR="${CFG_WORK_DIR}/ghidra"
mkdir -p "$WORK_DIR/scripts" "$WORK_DIR/proj" "$WORK_DIR/out"
cp "$S"/*.java "$S"/*.cspec "$WORK_DIR/scripts/"

LANG_DIR="$GHIDRA_DIR/Ghidra/Processors/x86/data/languages"
if [ -d "$LANG_DIR" ]; then
    [ -f "$LANG_DIR/x86gcc.cspec.orig" ] || cp "$LANG_DIR/x86gcc.cspec" "$LANG_DIR/x86gcc.cspec.orig"
    cp "$WORK_DIR/scripts/x86gcc_watcall.cspec" "$LANG_DIR/x86gcc.cspec"
fi

TARGET_EXE="$CFG_ORIG_EXE" python3 "$S/../mkimg.py" "$CFG_FLAT_BIN"

"$GHIDRA_DIR/support/analyzeHeadless" "$WORK_DIR/proj" TargetProj \
    -import "$CFG_FLAT_BIN" -loader BinaryLoader -loader-baseAddr 0x10000 \
    -processor x86:LE:32:default -cspec gcc -scriptPath "$WORK_DIR/scripts" \
    -preScript TargetSetup.java "$WORK_DIR/functions.tsv" -max-cpu 2 > "$WORK_DIR/analyse.log" 2>&1

"$GHIDRA_DIR/support/analyzeHeadless" "$WORK_DIR/proj" TargetProj \
    -process "$(basename "$CFG_FLAT_BIN")" -noanalysis -scriptPath "$WORK_DIR/scripts" \
    -postScript TargetParams.java \
    -postScript TargetDecomp.java "$WORK_DIR/functions.tsv" "$CFG_UNITS_TSV" "$WORK_DIR/out" > "$WORK_DIR/decomp.log" 2>&1

grep "TargetDecomp:" "$WORK_DIR/decomp.log" || true
