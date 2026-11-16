# Step 13 — Release Packaging, Shift-and-Add Binary Patch (`NDP2`), and Copyright Audit (`13_release/`)

Tools for assembling a self-contained clean-room build package (`mk_baupaket.py`), encoding size-shifted executables into compact, copyright-free `NDP2` binary patches (`mkpatch.py`), applying `.ndp` patches without a compiler (`patchen.py` for Linux/macOS/Windows and `patchen.ps1` for Windows PowerShell 5.1), auditing every 64-byte sliding window against the original binary (`pruefe_patch_rechte.py`), and checking repository hygiene (`check_repo_hygiene.py`).

## Included Scripts

| Script | Purpose |
|---|---|
| `mk_baupaket.py` | Bundles active C/C++ units, headers, and minimal link baseline into a standalone developer package. |
| `mkpatch.py` | Encodes a shifted target executable against the original executable as an `NDP2` patch (`hdr_s` + `sub_s` + non-zero modulo-256 `adds` + `lits`, raw-Deflate compressed) with automatic 64-byte window self-test. |
| `pruefe_patch_rechte.py` | Verifies that `0` sliding 64-byte windows of `lits`, `adds`, `adds+lits`, uncompressed `raw`, or `.ndp` occur in the original binary. |
| `patchen.py` | Zero-dependency Python 3 `NDP2` patcher with MD5 pre- and post-verification. |
| `patchen.ps1` | Zero-dependency Windows PowerShell 5.1 `NDP2` patcher (`System.IO.Compression.DeflateStream`). |
| `check_repo_hygiene.py` | Audits the repository tree for forbidden binary extensions, files `> 1 MB`, and personal/project strings. |

## Usage

```bash
# Create an NDP2 patch between an original and a shifted executable
python3 13_release/mkpatch.py --orig Original/TARGET.EXE --target Build/TARGET_FIX.EXE --out Patch/TARGET_FIX.ndp

# Audit all 64-byte sliding windows
python3 13_release/pruefe_patch_rechte.py --window 64 --orig Original/TARGET.EXE Patch/TARGET_FIX.ndp

# Apply patches to reproduce the target executable
python3 13_release/patchen.py --spiel Original --name TARGET.EXE --ziel Build --patch-dir Patch
```
