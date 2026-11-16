#!/usr/bin/env python3
"""laeuft.py - Real-time monitor for active AI worker sessions and their latest native judge measurements."""
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import project_config as PC

cfg = PC.load_config()
LOGS_DIR = pathlib.Path(PC.resolve_path("logs_dir", cfg, str(ROOT / "logs")))

ps = subprocess.run(["ps", "-eo", "pid,etimes,args"], capture_output=True, text=True).stdout.splitlines()[1:]
workers = {}
for l in ps:
    m = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)", l)
    if not m:
        continue
    pid, et, args = m.groups()
    if "laeuft.py" in args or "grep" in args:
        continue
    m_id = re.search(r"WORKER_ID=([A-Za-z0-9_-]+)|--id\s+([A-Za-z0-9_-]+)", args)
    if not m_id:
        continue
    wid = m_id.group(1) or m_id.group(2)
    m_u = re.search(r"--unit\s+([A-Za-z0-9_]+)", args)
    task = m_u.group(1) if m_u else args[:50]
    if wid in workers and workers[wid][0] >= int(et):
        continue
    workers[wid] = (int(et), task)

print(time.strftime("%H:%M"), " Active worker processes:", len(workers))
print(f"{'ID':12} {'Uptime':>8}  {'Last Measure':14} {'Measures':>9}  Task")
for wid, (et, task) in sorted(workers.items()):
    d = LOGS_DIR / wid / "native_belege"
    logs = sorted(d.glob("*.log"), key=os.path.getmtime) if d.exists() else []
    last_t = time.strftime("%H:%M", time.localtime(os.path.getmtime(logs[-1]))) if logs else "-"
    print(f"{wid:12} {et // 3600:>4}h{(et % 3600) // 60:02d}  {last_t:14} {len(logs):>9}  {task}")
