#!/bin/bash
# layer_window.sh - Vertical Inpainting ("Layering"): freeze all matching sections of a function
# and prompt an LLM agent to rewrite only the isolated non-matching window.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
eval "$(python3 "$ROOT/project_config.py" --env-sh)"

UNIT=""
FUNC=""
WID="L$(date +%H%M%S)"
while [ $# -gt 0 ]; do
    case "$1" in
        --unit) UNIT="$2"; shift 2;;
        --func) FUNC="$2"; shift 2;;
        --id) WID="$2"; shift 2;;
        *) shift;;
    esac
done

[ -z "$UNIT" ] || [ -z "$FUNC" ] && { echo "Usage: layer_window.sh --unit UNIT --func f_xxxxxx [--id ID]"; exit 1; }

SRC_FILE=$(bash "$ROOT/03_richter/probe.sh" quelle "$UNIT")
WORK_DIR="$CFG_DRAFTS_DIR/$WID"
mkdir -p "$WORK_DIR"
WORK_FILE="$WORK_DIR/$(basename "$SRC_FILE")"
cp "$SRC_FILE" "$WORK_FILE"

echo "=== Running section-level structural Core analysis (PROBE_ABSCHNITT=1) ==="
SECTIONS=$(PROBE_ABSCHNITT=1 WORKER_ID="$WID" bash "$ROOT/03_richter/probe.sh" "$UNIT" "$WORK_FILE" "$FUNC" || true)
echo "$SECTIONS" > "$WORK_DIR/SECTIONS.txt"

cat > "$WORK_DIR/LAYER_PROMPT.txt" <<TXT
Worker ID: $WID
Target Unit: $UNIT
Target Function: $FUNC
Working File: $WORK_FILE

VERTICAL INPAINTING (LAYERING) TASK:
All sections marked 'exakt' in $WORK_DIR/SECTIONS.txt already match the target binary and MUST remain untouched.
Rewrite ONLY the section(s) marked 'ABWEICHEND' or 'struktur' in $WORK_FILE, keeping the rest of the function frozen.
Save every compiled intermediate version as $WORK_DIR/v001.cpp, v002.cpp, ...
Measure with:
  WORKER_ID=$WID python3 $ROOT/03_richter/probe_queue.py $UNIT $WORK_FILE $FUNC
TXT

echo "Prepared Layering workspace: $WORK_FILE"
echo "Section report:              $WORK_DIR/SECTIONS.txt"
echo "Prompt:                      $WORK_DIR/LAYER_PROMPT.txt"
if [ -n "$LLM_CLI_CMD" ]; then
    WORKER_ID="$WID" $LLM_CLI_CMD "$WORK_DIR/LAYER_PROMPT.txt"
fi
