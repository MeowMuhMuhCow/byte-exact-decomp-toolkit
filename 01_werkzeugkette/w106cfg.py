"""w106cfg.py - Central configuration adapter for the Unicorn-based Watcom 10.6 emulator tools.

Reads all paths from the central `project.json` via `project_config.py`, while allowing
environment variable overrides (`W106_PROJ`, `W106_EXE`, `W106_C_EXE`, `W106_H`,
`W106_INC`, `W106_LIVE`, `W106_FLAT`, `W106_WDIS`, `W106_TMP`, `W106_OUT`).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import project_config as PC

_cfg = PC.load_config()

PROJ = os.environ.get("W106_PROJ") or PC.resolve_path("project_root", _cfg)
EXE = os.environ.get("W106_EXE") or PC.resolve_path("compiler_cpp", _cfg)
C_EXE = os.environ.get("W106_C_EXE") or PC.resolve_path("compiler_c", _cfg)
H = os.environ.get("W106_H") or PC.resolve_path("compiler_include", _cfg)
INC = os.environ.get("W106_INC") or PC.resolve_path("src_dir", _cfg)
LIVE = os.environ.get("W106_LIVE") or os.path.join(PC.resolve_path("logs_dir", _cfg), "live_fstand")
FLAT = os.environ.get("W106_FLAT") or PC.resolve_path("flat_bin", _cfg)
WDIS = os.environ.get("W106_WDIS") or PC.resolve_path("wdis", _cfg)
TMP = os.environ.get("W106_TMP") or PC.resolve_path("tmp_dir", _cfg, "/tmp/w106")
OUT = os.environ.get("W106_OUT") or os.path.join(PC.resolve_path("logs_dir", _cfg), "emu106")
UNITS_TSV = os.environ.get("W106_UNITS_TSV") or PC.resolve_path("units_tsv", _cfg)
CODE_BASE = int(_cfg.get("binary", {}).get("code_base_offset", 0x10000) or 0x10000)

os.makedirs(TMP, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
