# Steps 11 & 12 — Switched Bug Fixes and Shifted-Binary Verification (`11_12_fixbau/`)

Tools for managing tiered compile-time bug-fix switches (`FIX_BUGS = 0 / 1 / 2`), proving statically that `FIX_BUGS=0` reproduces the verified baseline source character-for-character (`basis_check.py`), auditing size-shifted `LE` executables (`ΔLength != 0`) for mid-function pointers, misdirected `rel32` calls, and data segment shifts, and bisecting modified units (`bisect_units.py`).

## Included Scripts

| Script | Purpose |
|---|---|
| `mkfix.py` | Generates `fix_switches.h` defining per-bug compile-time switches mapped to Stage A (`FIX_BUGS=1`), Stage B (`FIX_BUGS=2`), and `FIX_EXPLOITS`. |
| `basis_check.py` | Evaluates `#if FIX_...` / `#else` blocks at `FIX_BUGS=0` and verifies character identity against the unswitched baseline. |
| `le.py` | Compact 38-line inner `LE` parser (`lade`, `objdaten`) extracting objects and page fixups. |
| `zeiger_check.py` | Verifies every `Code -> Code` and `Data -> Code` fixup in a shifted executable (`0` mid-function pointers). |
| `call_check.py` | Linearly disassembles all direct `call`/`jmp rel32` (`E8`/`E9`) instructions and checks 8-byte masked target signatures. |
| `kreuz_check.py` | Aligns original and shifted binaries via unique 24-byte anchors and reports any `rel32` call whose target shifted away from its original target. |
| `daten_check.py` | Proves that the data segment (`Object 2`) outside 4-byte fixups has `0` byte differences against the original executable. |
| `einheit_check.py` | Verifies that every unmodified unit preserves all its relative fixups at its shifted offset. |
| `bisect_units.py` | Splits modified units into `G1..G4` bisection trees over the `Δ=0` baseline. |

## Usage

```bash
python3 11_12_fixbau/zeiger_check.py --orig Original/TARGET.EXE Build/TARGET_FIX_STAGE_A.EXE
python3 11_12_fixbau/call_check.py --orig Original/TARGET.EXE Build/TARGET_FIX_STAGE_A.EXE
python3 11_12_fixbau/daten_check.py --orig Original/TARGET.EXE Build/TARGET_FIX_STAGE_A.EXE
python3 11_12_fixbau/kreuz_check.py --orig Original/TARGET.EXE Build/TARGET_FIX_STAGE_A.EXE
```
