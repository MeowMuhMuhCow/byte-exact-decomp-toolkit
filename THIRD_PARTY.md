# Third-Party Dependencies and Notices

All scripts and tools in this repository were written from scratch and are released under the **MIT License** (see `LICENSE`).

No third-party binaries, shared libraries, commercial compilers, or proprietary target executables are bundled in this repository.

## Optional Python Packages (`requirements.txt`)

The in-process 32-bit compiler emulator (`01_werkzeugkette/` and `08_compilermodell/`) uses two external Python packages that you install separately via `pip install -r requirements.txt`:

1. **Unicorn Engine (`unicorn`)**
   - **Purpose:** CPU emulation for running 32-bit DOS/PE compiler binaries (`WPP386.EXE` / `WCC386.EXE`) deterministically in-process.
   - **License:** GPLv2 (maintained by the Unicorn Engine project, https://www.unicorn-engine.org/).
   - **Note:** No Unicorn code or prebuilt library (`libunicorn.so`) is included in this repository; our Python scripts invoke the public `unicorn` Python API at runtime if installed.

2. **Capstone Disassembly Framework (`capstone`)**
   - **Purpose:** x86 instruction decoding for compiler-emulator diagnostics and instruction-level diffing.
   - **License:** BSD License (maintained by the Capstone Engine project, https://www.capstone-engine.org/).
   - **Note:** The release builder (`09_gesamtbau/` and `13_release/`) includes a self-contained pure-Python x86 disassembler (`x86_disasm.py`) and does not require Capstone.

## External System Tools (User-Provided)

Depending on which steps of the workflow you run, you provide your own local installations of:
- **Historical Compiler Toolchain:** e.g., Watcom C/C++ 10.6 (`WPP386.EXE`, `WCC386.EXE`, `WASM.EXE`, `WLINK.EXE`) or Open Watcom (for testing the standalone example), or Borland C++ for 16-bit targets.
- **GNU Binutils (`objdump`):** Optional helper for linear disassembly in `03_richter/` and `11_12_fixbau/`.
- **DOSBox:** Used for final linking (`WLINK`) and boot testing when running on Linux/macOS/Windows.
- **Node.js (`node`):** Standard Node.js runtime (no npm packages required) for the fast standalone ShellSort stack/register solver in `08_compilermodell/`.
- **Ghidra:** Optional headless initial decompiler and boundary exporter in `02_basis/`.
