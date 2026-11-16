# Step 5 — Memoryless Blind Drafts & Recipe Slim (`05_blind/`)

Model-neutral starters for stripping a stuck function from its translation unit, generating independent blind rewrites across diverse LLM families with the exact judge as the sole tool, and running deep single-function sessions under **Recipe Slim** (`~4.6k`-char prompt, zero legacy failure dossiers).

## Included Files

| File | Purpose |
|---|---|
| `blind_template.py` | Copies a unit from the verified codebase and deletes the target function body, leaving only its declaration and a placeholder comment. |
| `PROMPT_SLIM.txt` | Compact single-function prompt template (`~1.2k–4.6k` chars) without historical attempt notes. |
| `run_blind_draft.sh` | Model-neutral blind rewrite launcher (`LLM_CLI_CMD="..." bash run_blind_draft.sh --family ... --unit ... --func ...`). |
