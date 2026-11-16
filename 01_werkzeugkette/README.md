# Step 1 — Pin and Emulate the Original Toolchain (`01_werkzeugkette/`)

Tools for extracting historical compiler distributions, pinning exact minor runtime versions against a target binary, running 32-bit Watcom C/C++ 10.6 (`WPP386.EXE` / `WCC386.EXE`) deterministically in-process via Unicorn CPU emulation (`2–4 s` per unit, bit-identical to native), and sweeping compiler flags per translation unit.

## Included Scripts

| Script | Purpose |
|---|---|
| `w106cfg.py` | Central configuration bridge reading paths from `../project.json` (or `W106_*` environment overrides). |
| `emu106.py` | In-process Unicorn CPU emulator for Watcom 10.6 CF-format binaries (`WPP386.EXE` and `WCC386.EXE`), servicing DOS `int 21h` calls in Python. |
| `comp.py` | High-level wrapper that compiles a `.CPP` or `.C` unit in `emu106`, honoring per-file `// OPT` and `// CC wcc386` headers. |
| `bytecmp.py` | Disassembles `.OBJ` via `wdis` and compares function bytes against the flat target image with relocation masking. |
| `fdiff.py` / `fdiff2.py` | Instruction-level aligned diffing between emulated compilation and the target binary using Capstone. |
| `variante.py` | Fast in-memory text substitution and compilation scorer. |
| `val106.py` | Multi-process validator checking that `100 %` of matched functions compile identically in `emu106`. |
| `iso.py` | Pure-Python ISO-9660 reader/extractor for compiler installation CDs. |
| `lib_version_match.py` | Matches OMF `.LIB` runtime modules from candidate compiler versions against the target binary image. |
| `flag_sweep.py` | Sweeps 22 Watcom optimization, alignment, calling-convention, and inline-depth flag combinations on a unit. |

## Example Usage

```bash
# Compile a unit in-process via Unicorn
python3 01_werkzeugkette/comp.py work/unit_001.cpp /tmp/unit_001.obj

# Sweep compiler flags on a unit
python3 01_werkzeugkette/flag_sweep.py --unit unit_001 --src work/unit_001.cpp --lo 010010 --hi 0104b0
```
