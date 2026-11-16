#!/bin/bash
# run_blind_draft.sh - Model-neutral launcher for memoryless blind rewriting of a single function.
# Usage:
#   LLM_CLI_CMD="your-llm-cli --prompt-file" bash 05_blind/run_blind_draft.sh --family model_a --unit UNIT --func f_xxxxxx [--id B01]
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
eval "$(python3 "$ROOT/project_config.py" --env-sh)"

FAMILY="generic"
UNIT=""
FUNC=""
WID="B$(date +%H%M%S)"
while [ $# -gt 0 ]; do
    case "$1" in
        --family) FAMILY="$2"; shift 2;;
        --unit) UNIT="$2"; shift 2;;
        --func) FUNC="$2"; shift 2;;
        --id) WID="$2"; shift 2;;
        *) shift;;
    esac
done

[ -z "$UNIT" ] || [ -z "$FUNC" ] && { echo "Usage: run_blind_draft.sh --family NAME --unit UNIT --func FUNC [--id ID]"; exit 1; }

WORK_FILE=$(python3 "$HERE/blind_template.py" "$UNIT" "$FUNC" "$WID")
DRAFTS_SUB="$CFG_DRAFTS_DIR/$WID"
PROMPT_FILE="$DRAFTS_SUB/PROMPT.txt"

sed -e "s|{WORKER_ID}|$WID|g" \
    -e "s|{UNIT}|$UNIT|g" \
    -e "s|{FUNC}|$FUNC|g" \
    -e "s|{REST}|?|g" \
    -e "s|{WORK_FILE}|$WORK_FILE|g" \
    -e "s|{DRAFTS_DIR}|$DRAFTS_SUB|g" \
    "$HERE/PROMPT_SLIM.txt" > "$PROMPT_FILE"

echo "Prepared blind workspace: $WORK_FILE"
echo "Prompt written to:       $PROMPT_FILE"

if [ -n "$LLM_CLI_CMD" ]; then
    WORKER_ID="$WID" $LLM_CLI_CMD "$PROMPT_FILE"
else
    echo "Set LLM_CLI_CMD (e.g. 'claude -p <' or 'llm-cli --prompt-file' or 'agy -i') to invoke your LLM CLI automatically."
fi
