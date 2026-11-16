# Step 2 — Reassemblable Baseline, Unit Cutting, and Ghidra Export (`02_basis/`)

Tools for parsing 32-bit Linear Executables (`LE`) and 16-bit DOS (`MZ`) headers, building a flat relocated image, cutting module and function boundaries, generating a 100 % byte-exact reassemblable assembly baseline, and exporting initial `__watcall` C drafts via headless Ghidra.

## Included Scripts

| Script | Purpose |
|---|---|
| `le.py` | Parses 32-bit `LE` headers, page tables, and fixup records (`load_le`) as well as 16-bit `MZ` relocation tables (`parse_mz_relocs`). |
| `omf.py` | Complete OMF `.OBJ` and `.LIB` parser supporting `LEDATA`, `LIDATA`, `COMDAT`, `FIXUPP`, `PUBDEF`, `EXTDEF`, and library relocation masks. |
| `x86_disasm.py` | Self-contained pure-Python x86-32 instruction length decoder and Watcom NOP-padding recognizer (uses Capstone when available, pure-Python fallback otherwise). |
| `mkimg.py` | Applies `LE` page fixups to construct the flat memory image (`target_flat.bin`). |
| `zerleg.py` / `zerleg2.py` | Cuts function boundaries from call/jump targets, matches OMF runtime library functions, and assigns functions to translation units via path anchors and monotonic data-reference DP. |
| `genasm2.py` / `modwrite.py` | Emits symbolic `WASM` assembly preserving exact 512-byte page fixup order so the baseline reassembles to the original hash. |
| `teile.py` | Splits `_DATA` assembly slices cleanly at a verified boundary address. |
| `grenzen.py` / `grenzen_anwenden.py` | Audits and updates translation-unit boundaries against monotonic function ordering. |
| `ghidra/TargetSetup.java` | Ghidra pre-script splitting `CODE`/`DATA` blocks and creating functions at exact binary boundaries. |
| `ghidra/TargetParams.java` | Fixed-point dataflow pass inferring Watcom register parameters (`EAX`, `EDX`, `EBX`, `ECX` byte-wise read-before-write) and stack parameters (`ret N`), applying `__watcall` signatures. |
| `ghidra/TargetDecomp.java` | Exports initial C drafts grouped per translation unit (`<unit>.c`). |
| `ghidra/x86gcc_watcall.cspec` | Compiler specification defining Watcom 32-bit register calling convention (`__watcall`) for Ghidra headless runs. |
| `ghidra/ghidra_headless.sh` | Automated wrapper running `TargetSetup`, `TargetParams`, and `TargetDecomp`. |
