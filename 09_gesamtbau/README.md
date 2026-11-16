# Step 9 — Full Image Link and Relocation Audit (`09_gesamtbau/`)

Self-contained pure-Python builder (`bauen.py`) and 18 OMF/linker/relocation audit modules (`werkzeuge/*.py`). Compiles all C/C++ units fresh, binds symbols to baseline labels, flattens `COMDAT`s in linker order, audits every 32-bit relocation (`call rel32`, global data fixups, out-of-line `switch` tables) to resolve the blind spot of Level-2 per-function matching, links with `WLINK 10.6`, and verifies `100 %` MD5/SHA-256 identity.

## Usage

```bash
python3 09_gesamtbau/bauen.py              # Build original byte-exact executable (FIX_BUGS=0)
python3 09_gesamtbau/bauen.py --fix 1      # Build Stage A bug-fix executable (FIX_BUGS=1)
python3 09_gesamtbau/bauen.py --fix 2      # Build Stage B bug-fix executable (FIX_BUGS=2)
```
