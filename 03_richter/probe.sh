#!/bin/bash
# probe.sh - Unified compilation and exact judge harness for a single translation unit.
#   probe.sh UNIT FILE.CPP [FUNC ...]   -> Compile unit, print per-function status (GLEICH / n Befehle), and diff target functions
#   probe.sh orig UNIT FUNC             -> Disassemble target function from the original flat binary
#   probe.sh quelle UNIT                -> Print path to the best existing source file (p3 > p2 > p1)
#   PROBE_ABSCHNITT=1 probe.sh UNIT FILE.CPP FUNC -> Show register/stack-masked basic-block sections (structural Core)
#   probe.sh demo UNIT FUNC             -> Show unoptimized demo partner disassembly
#   probe.sh asm FILE.CPP [FLAGS]       -> Compile arbitrary file and disassemble emitted .OBJ functions
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
eval "$(python3 "$ROOT/project_config.py" --env-sh)"

lo_von() {
    awk -F'	' -v u="$1" '$2==u{print $3; exit}' "$CFG_UNITS_TSV"
}
adr() {
    echo "$1" | sed 's/^f_//' | tr 'a-f' 'A-F'
}

if [ -n "$WORKER_ID" ]; then
    mkdir -p "$CFG_LOCK_DIR"
    exec 8>"$CFG_LOCK_DIR/probe_lock_$WORKER_ID"
    flock 8
fi

case "$1" in
quelle)
    for d in "$CFG_SRC_P3_DIR" "$CFG_SRC_P2_DIR" "$CFG_SRC_P1_DIR" "$CFG_SRC_DIR"; do
        if [ -f "$d/${2}_P1.CPP" ]; then echo "$d/${2}_P1.CPP"; exit 0; fi
        if [ -f "$d/${2}.cpp" ]; then echo "$d/${2}.cpp"; exit 0; fi
        if [ -f "$d/${2}.c" ]; then echo "$d/${2}.c"; exit 0; fi
    done
    echo "no source found for $2"
    exit 1
    ;;
orig)
    U=$2; A=$(adr "$3")
    BASE_HEX="${CFG_BIN_CODE_BASE_OFFSET:-65536}"
    st=$((16#$A))
    SZ="${4:-256}"
    objdump -D -b binary -mi386 -Mintel --adjust-vma="$BASE_HEX" --start-address=$st --stop-address=$((st+SZ)) "$CFG_FLAT_BIN" | tail -n +8
    exit 0
    ;;
demo)
    U=$2; A=$(echo "$3" | sed 's/^f_//' | tr 'A-F' 'a-f')
    Z=$(awk -F'	' -v u="$U" -v f="f_$A" '$1==u&&$2==f' "$CFG_DEMO_MAPPING_TSV" 2>/dev/null | head -1)
    [ -z "$Z" ] && { echo "no demo partner for $U f_$A"; exit 1; }
    s=$((16#$(echo "$Z" | cut -f5))); e=$((16#$(echo "$Z" | cut -f9)))
    objdump -D -b binary -mi386 -Mintel --no-show-raw-insn --adjust-vma=0x10000 --start-address=$s --stop-address=$e "$CFG_DEMO_FLAT_BIN" | tail -n +8
    exit 0
    ;;
asm)
    F=$2; shift 2
    [ -f "$F" ] || { echo "File $F missing"; exit 1; }
    TMP_OBJ=$(mktemp --suffix=.obj)
    trap 'rm -f "$TMP_OBJ"' EXIT
    python3 "$ROOT/01_werkzeugkette/comp.py" "$F" "$TMP_OBJ" >/dev/null
    objdump -D -b binary -mi386 -Mintel --no-show-raw-insn "$TMP_OBJ" | tail -n +8
    exit 0
    ;;
esac

U=$1; F=$2; shift 2
LO=$(lo_von "$U")
[ -z "$LO" ] && { echo "Unit $U unknown in $CFG_UNITS_TSV"; exit 1; }
[ -f "$F" ] || { echo "File $F missing"; exit 1; }

TMP_OBJ=$(mktemp --suffix=.obj)
trap 'rm -f "$TMP_OBJ"' EXIT

python3 - "$F" "$U" "$LO" "$TMP_OBJ" "$@" <<'PY'
import os, sys, subprocess
f, U, LO, tmp_obj = sys.argv[1:5]
FK = [a.lower().replace('f_', '') for a in sys.argv[5:]]
here = os.getcwd()
root = os.environ.get('ROOT', os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(f)), '..')))
comp_py = os.path.join(os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '.', '01_werkzeugkette', 'comp.py')
PY
python3 "$ROOT/01_werkzeugkette/comp.py" "$F" "$TMP_OBJ" >/dev/null || {
    echo "COMPILE_FAILED"
    exit 1
}

python3 "$HERE/fstand.py" "$TMP_OBJ" "$LO"
for a in "$@"; do
    clean_a=$(echo "$a" | sed 's/^f_//' | tr 'A-F' 'a-f')
    if [ -n "$PROBE_ABSCHNITT" ]; then
        echo "===== Sections f_${clean_a} (register/stack-masked structural Core)"
        python3 "$HERE/abschnitt.py" "$TMP_OBJ" "$LO" "$clean_a" -v
    else
        echo "===== Diff f_${clean_a} (--- original, +++ compiled)"
        DIFF_OUT=$(python3 "$HERE/fstand.py" "$TMP_OBJ" "$LO" "$clean_a")
        echo "$DIFF_OUT"
        if [ -n "$DIFF_OUT" ]; then
            echo "$DIFF_OUT" | python3 "$HERE/diagnose.py" || true
        fi
    fi
done
