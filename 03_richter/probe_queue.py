#!/usr/bin/env python3
"""probe_queue.py - 3-slot flock queue around probe.sh with automatic SHA-256 measurement ledger logging."""
import fcntl
import hashlib
import json
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
agent = os.environ.get('WORKER_ID', 'worker_01')
if not re.fullmatch(r'[A-Za-z0-9_-]+', agent) or len(sys.argv) < 2:
    sys.exit('Alphanumeric WORKER_ID and probe arguments required')

locks = pathlib.Path(PC.resolve_path('lock_dir', cfg, '/tmp/decomp_judge_locks'))
locks.mkdir(parents=True, exist_ok=True)
args = sys.argv[1:]
source = None
basis_hash = ''
source_hash = ''

if len(args) >= 2 and re.fullmatch(r'[A-Za-z0-9_]+', args[0]):
    candidate = pathlib.Path(args[1])
    if not candidate.is_absolute():
        candidate = pathlib.Path(PC.resolve_path('project_root', cfg)) / candidate
    if candidate.is_file() and candidate.suffix.lower() in ('.cpp', '.c'):
        source = candidate.resolve()
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        for key in ('src_p3_dir', 'src_p2_dir', 'src_p1_dir', 'src_dir'):
            bdir = PC.resolve_path(key, cfg)
            if bdir:
                bp = pathlib.Path(bdir) / (args[0] + '_P1.CPP')
                if bp.exists():
                    basis_hash = hashlib.sha256(bp.read_bytes()).hexdigest()
                    break

with (locks / ('id_' + agent)).open('a') as own:
    fcntl.flock(own, fcntl.LOCK_EX)
    while True:
        held = None
        for slot in (1, 2, 3):
            c = (locks / ('slot_' + str(slot))).open('a')
            try:
                fcntl.flock(c, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = c
                break
            except BlockingIOError:
                c.close()
        if held is not None:
            break
        time.sleep(0.3)
    try:
        logs_dir = pathlib.Path(PC.resolve_path('logs_dir', cfg, str(ROOT / 'logs'))) / agent / 'native_belege'
        logs_dir.mkdir(parents=True, exist_ok=True)
        stem = str(time.time_ns())
        log = logs_dir / (stem + '.log')
        start = time.time()
        snippets = []
        with log.open('w') as fo:
            proc = subprocess.Popen(
                ['bash', str(HERE / 'probe.sh'), *args],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace'
            )
            for line in proc.stdout:
                print(line, end='', flush=True)
                fo.write(line)
                if re.search(r'GLEICH.*EXTRA', line):
                    snippets.append(line.strip())
            rc = proc.wait()
        native = rc == 0 and bool(snippets) and source is not None
        if native:
            record = {
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'id': agent,
                'unit': args[0],
                'source': str(source),
                'source_sha256': source_hash,
                'basis_sha256': basis_hash,
                'variant': bool(basis_hash and source_hash != basis_hash),
                'log': str(log),
                'native': True,
                'duration_s': round(time.time() - start, 3),
                'summary': snippets,
            }
            with (logs_dir / 'MESSUNGEN.jsonl').open('a') as ledger:
                fcntl.flock(ledger, fcntl.LOCK_EX)
                ledger.write(json.dumps(record, ensure_ascii=False) + '\n')
        sys.exit(rc)
    finally:
        held.close()
