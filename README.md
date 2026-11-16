# Byte-Exact Decompilation Toolkit (Watcom C/C++ 10.6 & Legacy x86/DOS)

A self-contained, project-neutral toolkit for reconstructing **100 % byte-identical C/C++ source code** from unmodified legacy executables (32-bit Watcom C/C++ 10.6 `LE`/`OMF` DOS/4GW binaries, with 16-bit `MZ`/`OMF` support where applicable) using an exact compiler judge, multi-family blind rewriting, horizontal recombination, bit-exact compiler modeling, form-ratchet cleanup, compile-time switched bug fixes, and copyright-free `NDP2` binary patches.

For theoretical background and empirical benchmarks ("the Why"), see the accompanying method description.

---

## 1. Purpose & Clean-Room Principles

Given an unmodified retail executable (`Original/TARGET.EXE`) and the historical compiler toolchain (`Compiler/`), this toolkit implements the complete 13-step workflow:
1. **Zero proprietary bytes in the repository:** No compiler binaries, no game executables, no `.OBJ`/`.LIB` files, and no target data tables are included.
2. **Single configuration file (`project.json`):** Every script reads all project paths, binary offsets, and table exclusions from `project.json` (via `project_config.py`, overridable via `DECOMP_PROJECT_CONFIG=/path/to/project.json`).
3. **Exact verification at every stage:** Generators never score their own output; a static gatekeeper (`pfoertner.py`), a frozen symbol-based OMF comparator (`fstand.py`), and a full-image linker/relocation auditor (`bauen.py`) enforce regression-free ratchets up to 100 % MD5/SHA-256 identity.

---

## 2. Installation & Requirements

- **Python 3.10+** (standard library only for the Judge, Gatekeeper, Full Builder, De-Crutcher, Binary Verifiers, and `NDP2` Patcher).
- **Optional Python packages** for the in-process Unicorn compiler emulator (`01_werkzeugkette/` and `08_compilermodell/`):
  ```bash
  pip install -r requirements.txt
  ```
- **Node.js (`node`):** Standard runtime (no npm packages required) for the standalone two-stage ShellSort solver (`08_compilermodell/watcom106_shellsort_solver.js`).
- **System tools (user-provided):**
  - Historical compiler toolchain (e.g., Watcom C/C++ 10.6 `WPP386.EXE`, `WCC386.EXE`, `WASM.EXE`, `WLINK.EXE`) in `Compiler/`.
  - `objdump` (GNU binutils) for linear disassembly in `03_richter/` and `11_12_fixbau/`.
  - `dosbox` for final `WLINK` linking and boot verification.
  - `Ghidra` (optional) for headless initial export in `02_basis/ghidra/`.

---

## 3. Configuration (`project.json`)

Edit `project.json` in the toolkit root (or point `export DECOMP_PROJECT_CONFIG=/path/to/my_project.json` to your own config file):

```json
{
  "project_name": "my_legacy_game",
  "paths": {
    "project_root": ".",
    "orig_exe": "Original/TARGET.EXE",
    "flat_bin": "Original/target_flat.bin",
    "compiler_dir": "Compiler",
    "compiler_cpp": "Compiler/WPP386.EXE",
    "compiler_c": "Compiler/WCC386.EXE",
    "compiler_include": "Compiler/H",
    "src_dir": "src/cpp",
    "src_p3_dir": "src/cpp/verified",
    "inc_dir": "src/inc",
    "units_tsv": "meta/units.tsv",
    "excluded_tables_tsv": "meta/excluded_tables.tsv"
  },
  "binary": {
    "format": "LE",
    "stub_offset": 232804,
    "code_base_offset": 65536,
    "default_cpp_flags": "-4r -oneatx -zp1 -s"
  }
}
```

---

## 4. Workflow Step by Step (Folders `01` – `13`)

### `01_werkzeugkette/` — Step 1: Pin and Emulate the Original Toolchain
- Extract compiler installation CDs (`iso.py`), match runtime `.LIB` versions against the target binary (`lib_version_match.py`), run 32-bit Watcom `WPP386.EXE` / `WCC386.EXE` deterministically in-process via Unicorn (`emu106.py`, `comp.py` in `2–4 s` per unit), and sweep per-unit compiler flags (`flag_sweep.py`).
  ```bash
  python3 01_werkzeugkette/comp.py work/unit_001.cpp /tmp/unit_001.obj
  python3 01_werkzeugkette/flag_sweep.py --unit unit_001 --src work/unit_001.cpp --lo 010010 --hi 0104b0
  ```

### `02_basis/` — Step 2: Reassemblable Baseline, Unit Cutting, and Ghidra Export
- Parse `LE` (32-bit) or `MZ` (16-bit) headers and fixups (`le.py`), build the flat relocated memory image (`mkimg.py`), cut function and translation-unit boundaries (`zerleg.py`, `zerleg2.py`, `grenzen.py`), emit symbolic `WASM` assembly that reassembles to the exact original hash (`genasm2.py`), and run headless Ghidra with fixed-point `__watcall` register parameter inference (`ghidra/TargetSetup.java`, `TargetParams.java`, `TargetDecomp.java`).
  ```bash
  python3 02_basis/mkimg.py Original/target_flat.bin
  bash 02_basis/ghidra/ghidra_headless.sh
  ```

### `03_richter/` — Step 3: Frozen Judge, Static Gatekeeper, and Ratchet
- Reject inline assembly, raw bytes, unauthorized `#pragma aux` clauses, and altered external prototypes (`pfoertner.py`, `schummel.py`).
- Compare compiled OMF `.OBJ` symbols against the flat binary (`fstand.py`), flattening `COMDAT`s (`flach.py`) and reporting instruction distance (`Rest`), register/stack-masked structural sections (`abschnitt.py` / `PROBE_ABSCHNITT=1`), and `EXTRA` symbols.
- Serialize parallel worker measurements via a 3-slot `flock` queue (`probe_queue.py`) that logs cryptographic SHA-256 proofs to `MESSUNGEN.jsonl`, and commit strictly regression-free gains under the distance-coupled ratchet (`uebernahmeschutz.py`, `sperre.py`, `uebernahme.py`).
  ```bash
  python3 03_richter/pfoertner.py work/unit_001.cpp --gegen src/cpp/verified/unit_001_P1.CPP
  WORKER_ID=W01 python3 03_richter/probe_queue.py unit_001 work/unit_001.cpp f_400010
  ```

### `04_trichter/` — Step 4: Work Division by Funnel Stage, Cost, and Function Size
- Dispatch open units by structural `Core` and instruction size (`verteiler.py`), rank functions under the **Circle of Freshness** (`frisch.py`: any drop in `Rest` resets a function's "tried" status across all tools), and monitor active worker processes (`laeuft.py`).
  ```bash
  python3 04_trichter/verteiler.py next W01 --lane deep
  python3 04_trichter/frisch.py 30
  ```

### `05_blind/` — Step 5: Memoryless Blind Drafts & Recipe Slim
- Strip a stuck function's body from its unit (`blind_template.py`), omitting decompiler drafts and legacy failure dossiers, and launch independent blind rewrites across diverse LLM families (`run_blind_draft.sh` + `PROMPT_SLIM.txt`) with the exact Judge as the sole tool while archiving all intermediate drafts (`v001.cpp`, `v002.cpp`, ...) for the Mixer.
  ```bash
  LLM_CLI_CMD="your-llm-cli --prompt-file" bash 05_blind/run_blind_draft.sh --family model_a --unit unit_001 --func f_400010
  ```

### `06_mischer_layern/` — Step 6: Horizontal Recombination (Mixer & Phase R) and Vertical Inpainting (Layering)
- Harvest multi-family drafts, align basic blocks in original instruction coordinates, pull missing donor local declarations automatically, and select optimal non-overlapping token hunks via **Phase R** (Ridge regression, log-odds site association, and interval DP in `mischer_o14.py`).
- Freeze matching sections and rewrite isolated stubborn windows vertically (`layer_window.sh`).
  ```bash
  python3 06_mischer_layern/mischer_o14.py unit_001 f_400010 --abgeben
  bash 06_mischer_layern/layer_window.sh --unit unit_001 --func f_400010
  ```

### `07_mutator_schwestern/` — Step 7: Siblings, Transplants, Rosetta, and Mechanical Mutators
- Find matched structural siblings using **Metric A** (`aehnlich.py`: normalized instruction sequence) and **Metric B** (`aehnlich_b.py`: calls + globals + opcode profile).
- Transplant sibling function bodies mechanically (`transplant.py`), search 3-instruction normalized assembly windows across all matched code (`rsuch.py`), and sweep local expression/type variations (`mutator.py`, `vmasch.py`, `operatoren.py`, `beam.py`).
  ```bash
  python3 07_mutator_schwestern/aehnlich.py
  python3 07_mutator_schwestern/aehnlich_b.py
  python3 07_mutator_schwestern/rsuch.py "mov R,DWORD PTR ds:A \| test R,R"
  ```

### `08_compilermodell/` — Step 8: Compiler Modeling, Register/List Forcing (`regforce` / `orakel`), and Inverse ShellSort
- When structural `Core = 0` and only register, stack, or scheduling ties remain ("wax"), hook `WPP386.EXE` / `WCC386.EXE` directly in Unicorn:
  - **`regforce.py` (Force Register Allocation in `GiveBestReg`):** Hooks `GiveBestReg` (`0x93BC8` / `0x61488`) and `CountRegMoves` (`0x93744` / `0x61004`). Without flags, it prints every conflict node's candidate registers, move-savings scores, and ties. With `--zwing K REG` (e.g., `--zwing 3 ECX`), it forces the `K`-th `GiveBestReg` decision to pick `REG` (for instance, moving a table index from `EDX` into `ECX`) and immediately scores the emitted `.OBJ` with `fstand.py` to check if the instruction diff drops to `0`. With `--alle` (or `--alle --weit`), it sweeps all candidate registers across all calls in parallel.
  - **`orakel.py` (List Oracle for Stack & Conflict Lists):** Forces alternative equal-size (`--stapel`) or equal-savings (`--register`) list orders at `TempAllocNach` / `SortConflictsNach` and computes single/pair raw-list edits (`WEG`, `DAZU`, `SCHIEBEN`) that produce the target order under Watcom's unstable ShellSort.
  - **`schedforce.py` / `tiediag.py` / `savdiag.py` / `slotdiag.py` / `latepick106.py`:** Fine-grained diagnostics for DAG scheduling, conflict savings, stack slots, and round-robin `LatePick` state.
  - **`watcom106_shellsort_solver.js`:** Standalone Node.js simulator and **two-stage `{1, 2, 3} -> {3, 4, 5}` size-decoupled ShellSort solver** for eliminating `volatile` ghost variables.
  ```bash
  # Trace GiveBestReg choices and force call #3 to ECX
  python3 08_compilermodell/regforce.py work/unit_001.cpp unit_001 f_400010
  python3 08_compilermodell/regforce.py work/unit_001.cpp unit_001 f_400010 --zwing 3 ECX
  python3 08_compilermodell/regforce.py work/unit_001.cpp unit_001 f_400010 --alle --weit --procs 4

  # Run the Stack/Register List Oracle and Two-Stage ShellSort Solver
  python3 08_compilermodell/orakel.py unit_001 f_400010 work/unit_001.cpp --stapel
  node 08_compilermodell/watcom106_shellsort_solver.js --symtab 08_compilermodell/symtab_template.json --twostage
  ```

### `09_gesamtbau/` — Step 9: Full Image Link and Relocation Audit
- Compile all units fresh, audit every 32-bit relocation against the unmasked flat binary to catch wrong `call rel32` targets or swapped globals invisible to per-function masking, verify 512-byte fixup page ordering, link with `WLINK 10.6`, and verify `100 %` MD5/SHA-256 identity (`bauen.py`).
  ```bash
  python3 09_gesamtbau/bauen.py
  ```

### `10_entkruecker/` — Step 10: Binary-Halving De-Crutching and Strip-Verified Comments
- Strip redundant search crutches via binary chunk halving (`zusammen2.py` + `muster.py`, `<= 8` native judge runs per unit) and inject function catalogue descriptions as C block comments with automatic character-identity verification on comment stripping (`sprache_einsetzen.py`).
  ```bash
  python3 10_entkruecker/muster.py
  python3 10_entkruecker/zusammen2.py --frisch --budget 8 unit_001
  python3 10_entkruecker/sprache_einsetzen.py --p3
  ```

### `11_12_fixbau/` — Steps 11 & 12: Switched Bug Fixes and Shifted-Binary Verification
- Generate tiered compile-time bug-fix switch headers (`mkfix.py` for `FIX_BUGS = 0 / 1 / 2`), prove `#else`-branch character identity at `FIX_BUGS=0` (`basis_check.py`), audit size-shifted `LE` builds (`ΔLength != 0`) for mid-function pointers (`zeiger_check.py`), misdirected `rel32` calls (`call_check.py`, `kreuz_check.py`), and data segment identity (`daten_check.py`), and bisect modified units (`bisect_units.py`).
  ```bash
  python3 11_12_fixbau/basis_check.py --src src/cpp/fixed --baseline src/cpp/verified
  python3 11_12_fixbau/zeiger_check.py --orig Original/TARGET.EXE Build/TARGET_FIX_STAGE_A.EXE
  python3 11_12_fixbau/call_check.py --orig Original/TARGET.EXE Build/TARGET_FIX_STAGE_A.EXE
  ```

### `13_release/` — Step 13: Release Packaging, `NDP2` Shift-and-Add Binary Patch, and Copyright Audit
- Package the clean-room builder (`mk_baupaket.py`), encode size-shifted executables into compact `NDP2` patches (`mkpatch.py`), verify `0` shared 64-byte windows against the original binary (`pruefe_patch_rechte.py`), apply patches without a compiler (`patchen.py` / `patchen.ps1`), and audit repository hygiene (`check_repo_hygiene.py`).
  ```bash
  python3 13_release/mkpatch.py --orig Original/TARGET.EXE --target Build/TARGET_FIX.EXE --out Patch/TARGET_FIX.ndp
  python3 13_release/pruefe_patch_rechte.py --window 64 --orig Original/TARGET.EXE Patch/TARGET_FIX.ndp
  python3 13_release/check_repo_hygiene.py
  ```

---

## 5. Self-Contained Example (`beispiel/`)

To try the pipeline without any proprietary game files, run `beispiel/run_example.py` with your local `WPP386.EXE`:

```bash
W106_EXE=/path/to/WPP386.EXE W106_H=/path/to/H python3 beispiel/run_example.py
```

It compiles a 4-function C++ unit (clamp, loop, `switch`, caller) into a synthetic `"Original"` target image, runs the Gatekeeper and Judge on a slightly broken draft (`3/4 GLEICH`, showing the instruction diff), repairs the function to `4/4 GLEICH` (`100 %` MD5 match), and traces `GiveBestReg` register allocation with `regforce.py`.

---

## 6. License

Released under the **MIT License** (see `LICENSE`, Copyright (c) 2026 MeowMuhMuhCow). Third-party runtime dependencies (`unicorn`, `capstone`) are documented in `THIRD_PARTY.md` and installed separately via `requirements.txt`.
