# Self-Contained Mini-Example (`beispiel/`)

This folder contains a small, self-contained C++ program (`4` functions: a clamp helper, a `for`-loop accumulator, a 5-case `switch` dispatcher, and a batch caller) written from scratch so you can test the toolkit without any proprietary game files.

## Files

- `original_source/demo_unit.cpp` — The reference 4-function source file compiled to create the synthetic `"Original"` target binary.
- `broken_draft/demo_unit.cpp` — A draft where `f_400020` has an intentional arithmetic bug (`-` instead of `+=`), causing the Judge (`03_richter/fstand.py`) to report `3/4 GLEICH` and `1` differing instruction.
- `run_example.py` — Automated end-to-end walkthrough that:
  1. Compiles `original_source/demo_unit.cpp` in-process via Unicorn (`01_werkzeugkette/comp.py`) and builds the flat image and symbol tables.
  2. Runs the Gatekeeper (`03_richter/pfoertner.py`) and Exact Judge (`03_richter/fstand.py`) on `broken_draft/demo_unit.cpp`.
  3. Repairs the function, verifies `4/4 GLEICH, EXTRA 0`, and confirms `100 %` MD5 identity with the original `.OBJ`.
  4. Runs `08_compilermodell/regforce.py` to display Watcom 10.6's internal `GiveBestReg` candidate scores for the loop function.

## Running the Example

Provide the path to your local `WPP386.EXE` (Watcom C++ 10.6) via `W106_EXE`:

```bash
W106_EXE=/path/to/WPP386.EXE W106_H=/path/to/H python3 beispiel/run_example.py
```
