# Step 6 — Horizontal Recombination (The Mixer & Phase R) and Vertical Inpainting (Layering) (`06_mischer_layern/`)

Tools for crossing partial section hits across multi-family blind drafts horizontally (`mischer_o14.py` with calibrated emulator judge `Spearman = 1.000` and Phase R global hunk selection via Ridge regression, log-odds association, and interval DP) and rewriting isolated stubborn windows vertically while freezing matching sections (`layer_window.sh`).

## Included Scripts

| Script | Purpose |
|---|---|
| `mischer_o14.py` | Main horizontal recombiner (`python3 mischer_o14.py UNIT FUNC`) with online Beta-posterior survival model, coupled block follow-up, and Phase R token-hunk DP. |
| `mischer_lib_o14.py` | Original-instruction coordinate alignment (`cov[i]`, `seg[i]`), calibrated emulator judge (`O14_EICHUNG=1`), and identifier alignment. |
| `mischer.py` / `mischer_lib.py` | Multi-depth AST/block splitter (4 nesting levels), automatic donor local-declaration puller, and draft harvester. |
| `layer_window.sh` | Vertical inpainting starter: runs `PROBE_ABSCHNITT=1` to pinpoint the non-matching basic-block window and freezes all matching sections. |
