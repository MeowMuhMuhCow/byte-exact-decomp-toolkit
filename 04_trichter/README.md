# Step 4 — Work Division by Funnel Stage, Cost, and Function Size (`04_trichter/`)

Tools for tracking open functions by structural `Core` and instruction count (`< 50` to `> 1,000` instructions), maintaining the **Circle of Freshness** (resetting "tried" status whenever a function's `Rest` drops), and monitoring parallel AI worker sessions.

## Included Scripts

| Script | Purpose |
|---|---|
| `verteiler.py` | Funnel dispatcher and lease manager (`next`, `done`, `status`) with 4-hour leases and a 6-hour carousel brake. |
| `frisch.py` | Ranks open functions by attempt count *since the last baseline commit* and filters out model families that already tried the current state. |
| `kern123.py` | C subset analyzer checking local scalar/pointer declarations and macro hazards. |
| `laeuft.py` | Live process monitor displaying active workers, elapsed time, and `MESSUNGEN.jsonl` measurement counts. |
