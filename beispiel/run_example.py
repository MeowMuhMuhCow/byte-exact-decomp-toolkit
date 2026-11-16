#!/usr/bin/env python3
"""run_example.py - Self-contained end-to-end walkthrough of the reconstruction toolkit on a 4-function C++ unit.

Demonstrates:
  1. Compiling `original_source/demo_unit.cpp` via `01_werkzeugkette/comp.py` to build a synthetic
     "Original" binary image and baseline tables (`units.tsv`, `functions.tsv`).
  2. Running the Static Gatekeeper (`03_richter/pfoertner.py`) and the Exact Judge (`03_richter/fstand.py`)
     on `broken_draft/demo_unit.cpp` (where 1 of the 4 functions has an intentional bug), showing
     `3/4 GLEICH` and the exact instruction diff.
  3. Applying mechanical mutation (`+=` vs `-=` operator repair) and re-judging to reach `4/4 GLEICH, EXTRA 0`
     and 100% byte/MD5 identity with the original object.
  4. Tracing `GiveBestReg` register choices via `08_compilermodell/regforce.py`.
  5. Generating a copyright-free `NDP2` binary patch (`13_release/mkpatch.py`), auditing 64-byte windows
     (`13_release/pruefe_patch_rechte.py`), and applying it (`13_release/patchen.py`).
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
for p in ( str(TOOLKIT_ROOT), str(TOOLKIT_ROOT / "01_werkzeugkette"), str(TOOLKIT_ROOT / "02_basis") ):
    if p not in sys.path:
        sys.path.insert(0, p)

import omf


def extract_pubdefs(obj_path: Path) -> list[tuple[int, str]]:
    dd = obj_path.read_bytes()
    i = 0
    pubs = []
    while i < len(dd):
        t = dd[i]
        L = struct.unpack_from("<H", dd, i + 1)[0]
        b = dd[i + 3 : i + 2 + L]
        if t in (0x90, 0x91, 0xB6, 0xB7):
            _, j = omf.idx(b, 0)
            seg, j = omf.idx(b, j)
            if seg == 0:
                j += 2
            while j < len(b):
                l = b[j]
                nm = b[j + 1 : j + 1 + l].decode("latin1")
                j += 1 + l
                off = struct.unpack_from("<I" if t & 1 else "<H", b, j)[0]
                j += 4 if t & 1 else 2
                j += 1 if b[j] < 0x80 else 2
                pubs.append((off, nm))
        i += 3 + L
    return sorted(set(pubs))


def build_synthetic_le(code_bytes: bytes, base_va: int = 0x10000) -> bytes:
    """Wrap raw _TEXT bytes into a minimal valid LE image so le.py + fstand.py can parse it directly."""
    npages = (len(code_bytes) + 4095) // 4096 or 1
    lastpg = len(code_bytes) % 4096 or 4096
    padded_code = code_bytes.ljust(npages * 4096, b"\x00")
    le_hdr = bytearray(0xC0)
    le_hdr[0:4] = b"LE\x00\x00"
    struct.pack_into("<I", le_hdr, 0x14, npages)
    struct.pack_into("<I", le_hdr, 0x28, 4096)
    struct.pack_into("<I", le_hdr, 0x2C, lastpg)
    struct.pack_into("<I", le_hdr, 0x40, 0x80)   # object table offset
    struct.pack_into("<I", le_hdr, 0x44, 1)      # 1 object
    struct.pack_into("<I", le_hdr, 0x68, 0x98)   # fixup page table offset
    struct.pack_into("<I", le_hdr, 0x6C, 0x98 + (npages + 1) * 4)  # fixup record table offset
    struct.pack_into("<6I", le_hdr, 0x80, len(code_bytes), base_va, 0x2005, 1, npages, 0)
    fpt = b"\x00\x00\x00\x00" * (npages + 1)
    return bytes(le_hdr[:0x98]) + fpt + padded_code


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="decomp_example_"))
    try:
        print(f"=== 1. Setting up isolated example workspace in {work} ===")
        compiler_cpp = os.environ.get("W106_EXE")
        compiler_h = os.environ.get("W106_H")
        if not compiler_cpp or not os.path.isfile(compiler_cpp):
            print("NOTE: Set W106_EXE=/path/to/WPP386.EXE and W106_H=/path/to/H to run compilation.")
            return 0

        cfg_path = work / "project.json"
        orig_src = (HERE / "original_source" / "demo_unit.cpp").read_text(encoding="utf-8")
        broken_src = (HERE / "broken_draft" / "demo_unit.cpp").read_text(encoding="utf-8")

        # First compile to discover exact function offsets inside _TEXT
        env = dict(os.environ, W106_EXE=compiler_cpp, W106_H=compiler_h or "", W106_TMP=str(work))
        tmp_obj0 = work / "pass0.obj"
        subprocess.run([sys.executable, str(TOOLKIT_ROOT / "01_werkzeugkette/comp.py"), str(HERE / "original_source/demo_unit.cpp"), str(tmp_obj0)], env=env, check=True, stdout=subprocess.DEVNULL)

        pubs = extract_pubdefs(tmp_obj0)
        mod = omf.modules(str(tmp_obj0))[0]
        code_seg = max((s for s in mod["segs"].values() if s["cls"] == "CODE"), key=lambda s: len(s["data"]))
        code_len = len(code_seg["data"])

        base_va = 0x400000
        addr_map = {}
        func_starts = []
        for off, nm in pubs:
            m = re.search(r"f_([0-9a-f]{6})", nm)
            if m:
                old_name = "f_" + m.group(1)
                new_va = base_va + off
                new_name = f"f_{new_va:06x}"
                addr_map[old_name] = new_name
                func_starts.append((new_va, new_name))

        for old_n, new_n in addr_map.items():
            orig_src = orig_src.replace(old_n, new_n)
            broken_src = broken_src.replace(old_n, new_n)

        orig_cpp_path = work / "orig_unit.cpp"
        broken_cpp_path = work / "broken_unit.cpp"
        orig_cpp_path.write_text(orig_src, encoding="utf-8")
        broken_cpp_path.write_text(broken_src, encoding="utf-8")

        orig_obj = work / "orig.obj"
        subprocess.run([sys.executable, str(TOOLKIT_ROOT / "01_werkzeugkette/comp.py"), str(orig_cpp_path), str(orig_obj)], env=env, check=True, stdout=subprocess.DEVNULL)
        mod = omf.modules(str(orig_obj))[0]
        _cseg = max((s for s in mod["segs"].values() if s["cls"] == "CODE"), key=lambda s: len(s["data"]))
        code_bytes = bytes(0 if _cseg["mask"][k] else _cseg["data"][k] for k in range(len(_cseg["data"])))
        orig_obj_md5 = hashlib.md5(orig_obj.read_bytes()).hexdigest()
        print(f"  Compiled reference .OBJ ({len(code_bytes)} code bytes, MD5={orig_obj_md5})")

        flat_bin = work / "target_flat.bin"
        flat_bin.write_bytes(code_bytes)
        orig_exe = work / "TARGET.EXE"
        orig_exe.write_bytes(build_synthetic_le(code_bytes, base_va))

        units_tsv = work / "units.tsv"
        units_tsv.write_text(f"1\tdemo_unit\t{base_va:06x}\t{base_va + len(code_bytes):06x}\n", encoding="utf-8")

        funcs_tsv = work / "functions.tsv"
        flines = []
        for idx, (va, nm) in enumerate(func_starts):
            end_va = func_starts[idx + 1][0] if idx + 1 < len(func_starts) else (base_va + len(code_bytes))
            flines.append(f"{va:06X}\t{end_va:06X}\t{end_va - va}\tdemo_unit\tpfad\t")
        funcs_tsv.write_text("\n".join(flines) + "\n", encoding="utf-8")

        cfg = {
            "project_name": "example_project",
            "paths": {
                "project_root": str(work),
                "orig_exe": str(orig_exe),
                "flat_bin": str(flat_bin),
                "compiler_cpp": compiler_cpp,
                "compiler_include": compiler_h or "",
                "src_dir": str(work),
                "src_p3_dir": str(work),
                "units_tsv": str(units_tsv),
                "functions_tsv": str(funcs_tsv),
                "logs_dir": str(work / "logs"),
                "lock_dir": str(work / "locks"),
                "tmp_dir": str(work / "tmp"),
            },
            "binary": {
                "code_base_offset": base_va,
                "default_cpp_flags": "-4r -oneatx -zp1 -s",
            },
        }
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        env["DECOMP_PROJECT_CONFIG"] = str(cfg_path)

        print("\n=== 2. Gatekeeper & Exact Judge on broken_draft/demo_unit.cpp ===")
        gk = subprocess.run([sys.executable, str(TOOLKIT_ROOT / "03_richter/pfoertner.py"), str(broken_cpp_path)], env=env, capture_output=True, text=True)
        print("  Gatekeeper:", gk.stdout.strip())
        broken_obj = work / "broken.obj"
        subprocess.run([sys.executable, str(TOOLKIT_ROOT / "01_werkzeugkette/comp.py"), str(broken_cpp_path), str(broken_obj)], env=env, check=True, stdout=subprocess.DEVNULL)
        jdg = subprocess.run([sys.executable, str(TOOLKIT_ROOT / "03_richter/fstand.py"), str(broken_obj), f"{base_va:06x}"], env=env, capture_output=True, text=True)
        for line in jdg.stdout.strip().splitlines():
            print("   ", line)

        target_fn = func_starts[1][1]
        diff_out = subprocess.run([sys.executable, str(TOOLKIT_ROOT / "03_richter/fstand.py"), str(broken_obj), f"{base_va:06x}", target_fn[2:]], env=env, capture_output=True, text=True).stdout
        print(f"\n  Instruction diff on {target_fn}:")
        for line in diff_out.strip().splitlines():
            print("   ", line)

        print("\n=== 3. Mechanical Mutation Repair -> 4/4 GLEICH & Exact Hash Match ===")
        repaired_src = broken_src.replace("total = total - (int)arr[i] * scale;", "total += (int)arr[i] * scale;")
        repaired_cpp_path = work / "repaired_unit.cpp"
        repaired_cpp_path.write_text(repaired_src, encoding="utf-8")
        repaired_obj = work / "repaired.obj"
        subprocess.run([sys.executable, str(TOOLKIT_ROOT / "01_werkzeugkette/comp.py"), str(repaired_cpp_path), str(repaired_obj)], env=env, check=True, stdout=subprocess.DEVNULL)
        jdg2 = subprocess.run([sys.executable, str(TOOLKIT_ROOT / "03_richter/fstand.py"), str(repaired_obj), f"{base_va:06x}"], env=env, capture_output=True, text=True)
        for line in jdg2.stdout.strip().splitlines():
            print("   ", line)
        repaired_md5 = hashlib.md5(repaired_obj.read_bytes()).hexdigest()
        print(f"  Original .OBJ MD5: {orig_obj_md5}")
        print(f"  Repaired .OBJ MD5: {repaired_md5} -> {'EXACT MATCH!' if orig_obj_md5 == repaired_md5 else 'MISMATCH'}")
        assert orig_obj_md5 == repaired_md5

        print("\n=== 4. Tracing & Forcing GiveBestReg Register Allocation via regforce.py ===")
        rf = subprocess.run([sys.executable, str(TOOLKIT_ROOT / "08_compilermodell/regforce.py"), str(repaired_cpp_path), "demo_unit", target_fn], env=env, capture_output=True, text=True)
        for line in rf.stdout.strip().splitlines():
            print("   ", line)
        print(f"\n  Forcing GiveBestReg decision #1 (table index t12: EDX -> ECX) on {target_fn}:")
        rf_force = subprocess.run([sys.executable, str(TOOLKIT_ROOT / "08_compilermodell/regforce.py"), str(repaired_cpp_path), "demo_unit", target_fn, "--zwing", "1", "ECX"], env=env, capture_output=True, text=True)
        for line in rf_force.stdout.strip().splitlines():
            print("   ", line)

        print("\n=== 5. Copyright-Free NDP2 Binary Patch Generation, Window Audit & Application ===")
        fixed_exe = work / "TARGET_FIXED.EXE"
        fixed_bytes = bytearray(orig_exe.read_bytes())
        fixed_bytes[-16:] = b"PATCH_TEST_TAG\x00\x00"
        fixed_exe.write_bytes(bytes(fixed_bytes))
        patch_dir = work / "patches"
        patch_dir.mkdir(exist_ok=True)
        patch_ndp = patch_dir / "TARGET_FIXED.ndp"
        subprocess.run([sys.executable, str(TOOLKIT_ROOT / "13_release/mkpatch.py"), "--orig", str(orig_exe), "--target", str(fixed_exe), "--out", str(patch_ndp)], env=env, check=True)
        audit = subprocess.run([sys.executable, str(TOOLKIT_ROOT / "13_release/pruefe_patch_rechte.py"), "--orig", str(orig_exe), str(patch_ndp)], env=env, capture_output=True, text=True, check=True)
        for line in audit.stdout.strip().splitlines():
            print("   ", line)
        out_dir = work / "patched_out"
        subprocess.run([sys.executable, str(TOOLKIT_ROOT / "13_release/patchen.py"), "--spiel", str(work), "--name", "TARGET.EXE", "--ziel", str(out_dir), "--patch-dir", str(patch_dir)], env=env, check=True)
        patched_out = out_dir / "TARGET_FIXED.EXE"
        assert hashlib.md5(patched_out.read_bytes()).hexdigest() == hashlib.md5(fixed_exe.read_bytes()).hexdigest()
        print("    Patched output MD5 matches fixed reference executable 100%.")

        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
