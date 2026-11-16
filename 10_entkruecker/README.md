# Step 10 — De-Crutching by Binary Chunk Halving and Strip-Verified Comments (`10_entkruecker/`)

Tools for cleaning up matched source code under the **form-ratchet** (`Rest = 0` and `EXTRA = 0` preserved across all functions):
1. `muster.py` & `zusammen2.py`: Recognizes search crutches (`volatile`, `(x & 0) ? 0 : x`, `x ^ x`, `x |= x & 0`, `*(T *)&local`, dead round-trips, `// KRUECKE`) and removes the maximum subset via binary chunk halving (`<= 8` native judge runs per unit), automatically inserting a null statement `;` when removing the sole body of an `if`/`else`/`loop`.
2. `sprache_einsetzen.py`: Formats Markdown function descriptions from `docs/catalogue/<UNIT>.md` into ASCII/Latin-1 C block comments after each `//@ f_xxxxxx` marker and **proves before saving that stripping comments leaves the code character-identical**.

## Usage

```bash
# Run self-test of crutch pattern detector
python3 10_entkruecker/muster.py

# De-crutch a unit via binary chunk halving
python3 10_entkruecker/zusammen2.py --frisch --budget 8 unit_001

# Inject strip-verified function comments
python3 10_entkruecker/sprache_einsetzen.py --p3
```
