#!/usr/bin/env python3
"""schedforce.py SOURCE.CPP UNIT FUNC [--zwing K ID] [--alle] [--procs N] [--nur-mehr]

Trace or force instruction-scheduler DAG choices inside Watcom 10.6's ScheduleIns
(0xA0152 in WPP386 / 0x6DA12 in WCC386) and score the resulting .OBJ with fstand.py.
"""
import argparse
import multiprocessing as mp
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLKIT_ROOT = os.path.normpath(os.path.join(HERE, '..'))
for _p in (HERE, os.path.join(TOOLKIT_ROOT, '01_werkzeugkette'), TOOLKIT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import unicorn as U
from unicorn import x86_const as X
import w106cfg as C
from emu106 import BASE
from comp import comp
import adr106
from regforce import judge_rest

GRUENDE = (
    'ScheduleInsKostenErster', 'ScheduleInsKosten', 'ScheduleInsHoehe',
    'ScheduleInsIndex', 'ScheduleInsStallable', 'ScheduleInsFpseq', 'ScheduleInsId',
)
GRUNDNAME = {
    'ScheduleInsKostenErster': 'cost(first)',
    'ScheduleInsKosten': 'cost',
    'ScheduleInsHoehe': 'height',
    'ScheduleInsIndex': 'index_adj',
    'ScheduleInsStallable': 'stallable',
    'ScheduleInsFpseq': 'fpseq',
    'ScheduleInsId': 'id',
}


def lauf(src, unit, fkt, force=None, mit=None):
    cc = adr106.compiler_aus_quelle(src)
    A = adr106.fuer(cc)
    O = adr106.OFF
    st = {'k': -1, 'cur': False, 'blk': 0, 'ready': [], 'reason': None}
    namen = adr106.quellfunktionen(src)

    def hook(e):
        track = adr106.ProcTrack(e, cc, namen)

        def dag(p):
            i = e.u32(p + O['dag_ins'])
            try:
                ln = struct.unpack('<H', e.rd(i + O['ins_line'], 2))[0]
            except Exception:
                ln = 0
            return dict(
                dag=p, ins=i, id=e.u32(i + O['ins_id']), h=e.u32(p + O['dag_height']),
                st=e.rd(p + O['dag_stallable'], 1)[0],
                vis=e.rd(p + O['dag_flags'], 1)[0] & 1, ln=ln,
            )

        def h_entry(uc, a, s, _):
            st['cur'] = fkt in track.name()
            if st['cur']:
                st['blk'] += 1

        def h_round(uc, a, s, _):
            if not st['cur']:
                return
            p = e.u32(e.r(X.UC_X86_REG_EBP) - 8)
            L = []
            while p:
                d = dag(p)
                if not d['vis']:
                    L.append(d)
                p = e.u32(p + O['dag_ready'])
            st['ready'] = L
            st['reason'] = None

        def h_reason(label):
            def h(uc, a, s, _):
                if st['cur']:
                    st['reason'] = label
            return h

        def h_pick(uc, a, s, _):
            if not st['cur']:
                return
            st['k'] += 1
            p = e.r(X.UC_X86_REG_ECX)
            if not p:
                return
            if force and st['k'] == force[0]:
                alt = [d for d in st['ready'] if d['id'] == force[1]]
                if alt:
                    e.w(X.UC_X86_REG_ECX, alt[0]['dag'])
                    p = alt[0]['dag']
            if mit is not None:
                d = dag(p)
                mit.append(dict(
                    k=st['k'], blk=st['blk'], id=d['id'], ln=d['ln'], h=d['h'],
                    reason=st['reason'], nready=len(st['ready']),
                    ready=[x['id'] for x in st['ready']],
                ))

        e.uc.hook_add(U.UC_HOOK_CODE, h_entry, begin=BASE + A['ScheduleIns'], end=BASE + A['ScheduleIns'])
        e.uc.hook_add(U.UC_HOOK_CODE, h_round, begin=BASE + A['ScheduleInsRunde'], end=BASE + A['ScheduleInsRunde'])
        e.uc.hook_add(U.UC_HOOK_CODE, h_pick, begin=BASE + A['ScheduleInsWahl'], end=BASE + A['ScheduleInsWahl'])
        for n in GRUENDE:
            e.uc.hook_add(U.UC_HOOK_CODE, h_reason(GRUNDNAME[n]), begin=BASE + A[n], end=BASE + A[n])

    obj = os.path.join(C.TMP, 'sf_%d_%s.obj' % (os.getpid(), force[0] if force else 'base'))
    ok, out, e = comp(src, obj, hook=hook)
    if not ok:
        return 9999
    r = judge_rest(obj, unit, fkt)
    try:
        os.remove(obj)
    except OSError:
        pass
    return r


def _job(a):
    src, u, fkt, k, i = a
    return k, i, lauf(src, u, fkt, (k, i))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('einheit')
    ap.add_argument('fkt')
    ap.add_argument('--zwing', nargs=2, type=int, metavar=('K', 'ID'), help='Force choice #K to pick instruction ID')
    ap.add_argument('--alle', action='store_true')
    ap.add_argument('--procs', type=int, default=4)
    ap.add_argument('--max', type=int, default=200)
    ap.add_argument('--nur-mehr', action='store_true')
    A = ap.parse_args()
    fkt = A.fkt.lower() if A.fkt.lower().startswith('f_') else 'f_' + A.fkt.lower()

    if A.zwing:
        r = lauf(A.src, A.einheit, fkt, force=(A.zwing[0], A.zwing[1]))
        print(f'{A.einheit} {fkt}: forced choice #{A.zwing[0]} -> id {A.zwing[1]} => Rest {r}')
        return

    mit = []
    n0 = lauf(A.src, A.einheit, fkt, None, mit)
    print(f'{A.einheit} {fkt}: baseline Rest {n0}, {len(mit)} scheduler choices ({sum(1 for m in mit if m["nready"] > 1)} with >=2 ready)')
    alts = []
    for m in mit:
        if A.nur_mehr and m['nready'] < 2:
            continue
        print('  #%-3d B%-2d id %-6d L%-4d h %-3d %-12s ready(%d): %s' % (
            m['k'], m['blk'], m['id'], m['ln'], m['h'], m['reason'] or '?', m['nready'],
            ' '.join(str(i) for i in m['ready'][:8]),
        ))
        alts += [(m['k'], i) for i in m['ready'] if i != m['id']]
    if not A.alle or n0 in (0, 9999):
        return
    alts = alts[:A.max]
    with mp.get_context('fork').Pool(A.procs, maxtasksperchild=40) as p:
        R = p.map(_job, [(A.src, A.einheit, fkt, k, i) for k, i in alts])
    R.sort(key=lambda x: x[2])
    for k, i, n in R[:15]:
        print(f'  {n:4d} insns: choice #{k} -> id {i}')


if __name__ == '__main__':
    main()
