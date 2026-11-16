# Step 8 — Bit-Exact Compiler Modeling, Register/List Forcing (`regforce` / `orakel`), and Inverse ShellSort Solving (`08_compilermodell/`)

Tools for resolving zero-core residual diffs (`Core = 0`, register, stack, or instruction-order ties) by hooking Watcom C/C++ 10.6's internal register allocator (`AssignConflicts` `0x94020`, `ConfBefore` `0x94148`, `GiveBestReg` `0x93BC8`, `CountRegMoves` `0x93744`), stack allocator (`AssignOtherLocals` `0x90C42`, `TempAllocBefore` `0x90CDC`), instruction scheduler (`ScheduleIns` `0xA0152`), and unstable ShellSort (`SortList` `0xA36E5`) inside the Unicorn emulator.

## Included Scripts

| Script | Purpose |
|---|---|
| `regforce.py` | **Force Register Assignment (`GiveBestReg` / `CountRegMoves`):** Traces candidate registers and move-savings scores for every variable/temporary (`tN`) in both `WPP386.EXE` and `WCC386.EXE`, and forces a chosen register at call `#K` (`--zwing K REG`, e.g. moving a table index from `EDX` to `ECX`) or sweeps all alternatives (`--alle`, `--weit`) to check whether the instruction diff drops to `0`. |
| `orakel.py` | **Unified List Oracle (`WPP386` & `WCC386`):** Forces alternative equal-weight (`--register`) or equal-size (`--stapel`) orders in the emulator to prove whether `Rest = 0` is reachable by tie-breaking alone, and computes single/pair raw-list edits (`WEG`, `DAZU`, `SCHIEBEN`) that produce the target order under ShellSort. |
| `schedforce.py` | **Force Instruction Scheduler Choice (`ScheduleIns`):** Traces ready-list DAG choices and forces an alternative ready instruction at choice `#K` (`--zwing K ID` or `--alle`). |
| `adr106.py` | Complete table of internal CF-image hook addresses for both `WPP386.EXE` (C++) and `WCC386.EXE` (C) in Watcom 10.6. |
| `regdump106.py` / `irlist.py` | Dumps the conflict list (`tN` temporaries and named locals) with loop-weighted `savings`, live ranges, and assigned registers. |
| `tiediag.py` / `tiesuche.py` / `tieplan.py` | Tests all equal-`savings` tie permutations in the register allocator and plans conflict-list edits. |
| `savdiag.py` / `savdiag_ra.py` | Perturbs individual conflict `savings` (`±1`, `±2`) to identify "Dose, Then Place" targets. |
| `slotdiag.py` / `slotdiag_c.py` / `slotdiag_ra.py` / `vorsort_c.py` | Dumps and perturbs the stack symbol list before/after `TempAllocBefore` size sorting. |
| `sched106.py` | Traces `ScheduleIns` bottom-up DAG scheduling and highlights `id` tie-breaks controllable via source statement order. |
| `latepick106.py` | Traces the round-robin `LatePick` register cursor (`0x9EBFE`) and its per-function reset (`0x9EF5B`). |
| `declsuche.py` | Automatically permutes the local variable declaration block at function start. |
| `watcom106_shellsort_solver.js` | Standalone Node.js simulator and **two-stage `{1, 2, 3} -> {3, 4, 5}` size-decoupled ShellSort solver** (`node watcom106_shellsort_solver.js --symtab symtab_template.json --twostage`). |
| `geister_min.py` | Delta-debugging control experiment demonstrating why naive chunk deletion of ghost variables fails without re-solving ShellSort gap chains. |

## Example Usage (`regforce.py` & `orakel.py`)

```bash
# 1. Inspect all GiveBestReg register choices and ties for a function
python3 08_compilermodell/regforce.py work/unit_001.cpp unit_001 f_400010

# 2. Force GiveBestReg call #3 to assign ECX instead of EDX and check if Rest drops
python3 08_compilermodell/regforce.py work/unit_001.cpp unit_001 f_400010 --zwing 3 ECX

# 3. Sweep all candidate registers across all calls in parallel
python3 08_compilermodell/regforce.py work/unit_001.cpp unit_001 f_400010 --alle --weit --procs 4

# 4. Run the stack/register List Oracle
python3 08_compilermodell/orakel.py unit_001 f_400010 work/unit_001.cpp --stapel
```
