# Step 3 — Frozen Judge, Static Gatekeeper, and Ratchet (`03_richter/`)

The tamper-proof verification core: a static pre-compile gatekeeper blocking cheats, a symbol-based OMF comparator (`fstand.py`), a 3-slot lock queue (`probe_queue.py`) writing SHA-256 measurement ledgers, and the distance-coupled / form ratchet.

## Included Scripts

| Script | Purpose |
|---|---|
| `fstand.py` | Frozen symbol-based OMF `.OBJ` vs. flat binary judge (flattens `COMDAT`s via `flach.py`, strips trailing alignment pad, reports `GLEICH`, `n Befehle`, `FEHLT`, and `EXTRA`). |
| `flach.py` | Flattens code `COMDAT` records behind `_TEXT` in reverse OMF order (matching `WLINK 10.6`). |
| `probe.sh` | Unified CLI testbench (`probe.sh UNIT FILE [FUNC]`, `orig`, `quelle`, `demo`, `asm`, `PROBE_ABSCHNITT=1`). |
| `probe_queue.py` | 3-slot `flock` queue around `probe.sh` logging SHA-256 source/baseline proofs to `MESSUNGEN.jsonl`. |
| `pfoertner.py` / `schummel.py` | Static gatekeeper rejecting inline assembly (`__asm`, `_emit`, `db`), unauthorized `#pragma aux` clauses, and modified external prototypes. |
| `abschnitt.py` / `fsmod.py` | Register- and stack-blind basic-block section comparator (`Core` / `Formkern`). |
| `diagnose.py` | Classifies instruction diffs into root-cause categories (`Form`, `Typbreite`, `Register`, `Stapelplatz`, etc.). |
| `adr_pruefung.py` | Verifies that global data addresses masked by Level-2 relocation comparison are referenced in the exact original order. |
| `uebernahmeschutz.py` / `sperre.py` / `uebernahme.py` | Distance-coupled ratchet (`Rest <= 40` byte-size guard, waived on halving) and form-ratchet collector with per-unit `flock` + MD5 concurrency protection. |
| `t1format.py` / `omf_extra.py` / `native_ergebnis.py` | Structured JSON output encoder and cryptographic `EXTRA` symbol binder. |
