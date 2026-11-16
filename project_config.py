#!/usr/bin/env python3
"""Central project configuration loader for the byte-exact reconstruction toolkit.

All tools read paths, binary offsets, and table exclusions from a single JSON
configuration file (`project.json` in the toolkit root by default, or overridden
via the `DECOMP_PROJECT_CONFIG` environment variable).
"""
import json
import os
import sys

TOOLKIT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(TOOLKIT_ROOT, "project.json")


def get_config_path() -> str:
    env_path = os.environ.get("DECOMP_PROJECT_CONFIG")
    if env_path:
        return os.path.abspath(env_path)
    return DEFAULT_CONFIG_PATH


def load_config(config_path: str = None) -> dict:
    path = os.path.abspath(config_path) if config_path else get_config_path()
    if not os.path.isfile(path):
        return {
            "project_name": "target_project",
            "paths": {"project_root": TOOLKIT_ROOT},
            "binary": {"default_cpp_flags": "-4r -oneatx -zp1 -s", "default_c_flags": "-4r -oneatx -zp1 -s"},
            "excluded_table_addresses": [],
            "_config_dir": TOOLKIT_ROOT,
        }
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_config_dir"] = os.path.dirname(path)
    return cfg


def resolve_path(key: str, config: dict = None, default: str = "") -> str:
    cfg = config if config is not None else load_config()
    paths = cfg.get("paths", {})
    base_dir = cfg.get("_config_dir", TOOLKIT_ROOT)
    proj_root_raw = paths.get("project_root", ".")
    if os.path.isabs(proj_root_raw):
        proj_root = proj_root_raw
    else:
        proj_root = os.path.normpath(os.path.join(base_dir, proj_root_raw))

    if key == "project_root":
        return proj_root

    val = paths.get(key, default)
    if not val:
        return ""
    if os.path.isabs(val):
        return val
    return os.path.normpath(os.path.join(proj_root, val))


def load_excluded_table_addresses(config: dict = None) -> set:
    """Return the set of non-executable jump/data table start addresses inside _TEXT."""
    cfg = config if config is not None else load_config()
    result = set()
    for item in cfg.get("excluded_table_addresses", []):
        if isinstance(item, int):
            result.add(item)
        elif isinstance(item, str):
            s = item.strip()
            if s:
                result.add(int(s, 16) if s.startswith(("0x", "0X")) else int(s, 0))
    tsv_path = resolve_path("excluded_tables_tsv", cfg)
    if tsv_path and os.path.isfile(tsv_path):
        with open(tsv_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.lower().startswith("address"):
                    continue
                tok = line.split()[0]
                try:
                    result.add(int(tok, 16) if tok.startswith(("0x", "0X")) else int(tok, 16))
                except ValueError:
                    pass
    return result


def main():
    cfg = load_config()
    if len(sys.argv) >= 3 and sys.argv[1] == "--path":
        print(resolve_path(sys.argv[2], cfg, sys.argv[3] if len(sys.argv) > 3 else ""))
    elif len(sys.argv) >= 3 and sys.argv[1] == "--binary":
        print(cfg.get("binary", {}).get(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))
    elif len(sys.argv) >= 2 and sys.argv[1] == "--env-sh":
        # Emit shell variable assignments for bash wrappers
        keys = [
            "project_root", "orig_exe", "flat_bin", "demo_flat_bin",
            "compiler_dir", "compiler_cpp", "compiler_c", "compiler_include",
            "wdis", "dosbox", "src_dir", "src_p3_dir", "src_p2_dir", "src_p1_dir",
            "inc_dir", "asm_dir", "build_dir", "work_dir", "drafts_dir",
            "logs_dir", "measurements_file", "lock_dir", "tmp_dir",
            "units_tsv", "excluded_tables_tsv", "allowed_pragma_tsv",
            "named_pragma_tsv", "allowed_prototype_tsv", "demo_mapping_tsv",
        ]
        for k in keys:
            v = resolve_path(k, cfg).replace('"', '\\"')
            print(f'CFG_{k.upper()}="{v}"')
        for bk, bv in cfg.get("binary", {}).items():
            sval = str(bv).replace('"', '\\"')
            print(f'CFG_BIN_{bk.upper()}="{sval}"')
    else:
        print(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
