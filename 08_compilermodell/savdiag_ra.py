#!/usr/bin/env python3
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_WK = _os.path.normpath(_os.path.join(_HERE, '..', '01_werkzeugkette'))
for _p in (_HERE, _WK):
    if _p not in _sys.path: _sys.path.insert(0, _p)
"""savdiag_ra.py - Nutzwert-Diagnose wie Werkzeuge/emu106/savdiag.py,
zusÃ¤tzlich die savcode.h-Rechnung neben dem gemessenen Abbildwert.

Rechnung (CalcSavings 0x8A86C, Kostentabellen zur Laufzeit):
  +use_save je Nutzung, noch einmal wenn Operand 0 ein Register-Ziel fÃ¼ttert
  (Opcode < 0x2E und Ergebnis N_REGISTER),
  +def_save je Definition, noch einmal wenn die Quelle schon N_REGISTER ist,
  gleiche Stapelzelle bei mov/convert zÃ¤hlt als Ladekosten statt Definition,
  +index_save je Index, mal das Schleifengewicht der Blocktiefe.
  0 bei Konflikt auf Halt, available==0 ohne Index/Segment, oder genau einer Instruktion.
  Liegt der Nutzwert danach nicht Ã¼ber den Kosten: 0.
Das Abbild an der Sortierstelle 0x9408F ist dieser Wert plus ConstSavings
(x86regsv.c, 0x76A08): const-Temp erbt die Kette, jeder positive Nicht-const-Konflikt
bekommt MaxConstSave dazu. Der Deckel 400 steht in der Aufgabenformel; das Abbild
multipliziert mit der vollen Tabelle (ab Tiefe 3 auch 8000 und hÃ¶her). Beide Zahlen
stehen in der Zeile, Abweichungen sind gekennzeichnet.
--alle schreibt hier nichts. HÃ¶chstens 2 Prozesse als Vorgabe.
"""
import sys, os, struct, argparse, multiprocessing as mp

def _emu_dir():
    p = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        cand = os.path.join(p, 'Werkzeuge', 'emu106')
        if os.path.isdir(cand):
            return cand
        p = os.path.dirname(p)
    raise SystemExit('Werkzeuge/emu106 nicht gefunden')

sys.path.insert(0, _emu_dir())
import w106cfg as C
import unicorn as U
from unicorn import x86_const as X
from emu106 import BASE
from comp import comp
import regdump106 as R
from latepick106 import fname
from fdiff2 import diff
import irlist

DS = (-2, -1, 1, 2)
OP_BLOCK, OP_CONVERT, OP_MOV = 0x4B, 0x24, 0x26
FIRST_COND = 0x2E
N_MEMORY, N_TEMP, N_REG, N_INDEX = 1, 2, 3, 4
NO_LOCATION = 0x7FFFFFFF
A_USE, A_DEF, A_LOAD, A_INDEX = 0xC6B40, 0xC6B6C, 0xC6AE8, 0xC6AE4
A_WEIGHT, A_WEIGHT_MAX = 0xC6BF0, 0xC6C04
A_HEAD = 0xC688C
DECKEL = 400
CONST_TEMP = 0x100
CST_CALCULATED = 0x0008

def _u8(e, a):
    return e.rd(a, 1)[0]

def _u16(e, a):
    return struct.unpack('<H', e.rd(a, 2))[0]

def _i32(e, a):
    return struct.unpack('<i', e.rd(a, 4))[0]

def const_temp(e, n):
    return bool(n) and _u8(e, n + 4) == N_TEMP and (_u16(e, n + 0x2A) & CONST_TEMP) != 0

def name_conflict(e, ins, opnd):
    """NameConflict 0x8B67C: Temp vorher dealias, Konfliktzeiger Name+0x0C, Bereich Ã¼ber ins-id."""
    if not opnd:
        return 0
    cls = _u8(e, opnd + 4)
    if cls == N_TEMP:
        opnd = dealias(e, opnd)
    elif cls != N_MEMORY:
        return 0
    conf = e.u32(opnd + 0x0C)
    iid = _i32(e, ins + 0x34)
    for _ in range(64):
        if not conf:
            return 0
        first, last = e.u32(conf + 0x38), e.u32(conf + 0x3C)
        if first and last and _i32(e, first + 0x34) <= iid <= _i32(e, last + 0x34):
            return conf
        conf = e.u32(conf + 4)
    return 0

def const_anwenden(e, info):
    """ConstSavings 0x76A08 auf die gezÃ¤hlten CalcSavings-Werte. Schreibt nach und maxconst."""
    if not info:
        return
    byptr = {}
    for d in info:
        w = d.get('savcode', 0)
        if any('Adresse/NEEDS_MEMORY' in t for t in (d.get('tor') or [])):
            w = 0
        d['nach'] = 0 if w is None or w < 0 else w
        if d.get('conf'):
            byptr[d['conf']] = d
    links = {}
    blk = e.u32(BASE + A_HEAD)
    seenb = set()
    nb = 0
    while blk and blk not in seenb and nb < 4000:
        seenb.add(blk)
        nb += 1
        ins = e.u32(blk + 4)
        seen = set()
        ns = 0
        while ins and ins not in seen and ns < 8000:
            seen.add(ins)
            ns += 1
            op = _u8(e, ins + 0x22)
            if op == OP_BLOCK:
                break
            if op == OP_MOV and _u8(e, ins + 0x3F):
                op0, res = e.u32(ins + 0x44), e.u32(ins + 0x30)
                if const_temp(e, op0) and const_temp(e, res):
                    conf, other = name_conflict(e, ins, op0), name_conflict(e, ins, res)
                    if conf in byptr and other in byptr:
                        if (byptr[conf].get('state', 0) & CST_CALCULATED) and (byptr[other].get('state', 0) & CST_CALCULATED):
                            links[conf] = other
            ins = e.u32(ins + 4)
        nxt = e.u32(blk + 0x28)
        blk = nxt
    visited = set()
    for d in info:
        p = d.get('conf')
        if not p or not d.get('const') or not (d.get('state', 0) & CST_CALCULATED):
            continue
        other = links.get(p)
        guard = 0
        while other and guard < 64:
            guard += 1
            d['nach'] = (d['nach'] + byptr[other]['nach']) & 0xFFFFFFFF
            if other in visited:
                break
            other = links.get(other)
        visited.add(p)
    maxconst = 0
    for d in info:
        if d.get('const') and (d.get('state', 0) & CST_CALCULATED) and d['nach'] >= maxconst:
            maxconst = d['nach']
    for d in info:
        d['maxconst'] = maxconst
        if d.get('const') or not (d.get('state', 0) & CST_CALCULATED):
            continue
        if d['nach']:
            d['nach'] = (d['nach'] + maxconst) & 0xFFFFFFFF

def dealias(e, n):
    for _ in range(8):
        if not n or _u8(e, n + 4) != N_TEMP:
            return n
        if (_u8(e, n + 0x2A) & 2) == 0:
            return n
        nxt = e.u32(n + 0x1C)
        if not nxt or nxt == n:
            return n
        n = nxt
    return n

def gleich(e, op, name):
    if not op:
        return False
    if _u8(e, op + 4) == N_TEMP:
        op = dealias(e, op)
    return op == name

def _tab(e, basis, klasse):
    if klasse > 13:
        return 1
    return e.u32(BASE + basis + 4 * klasse)

def gewicht(e, blk, deckel):
    t = _u8(e, blk + 0x50)
    w = e.u32(BASE + (A_WEIGHT_MAX if t >= 5 else A_WEIGHT + 4 * t))
    return min(w, deckel) if deckel else w

def zaehlung(e, conf):
    """savcode-Nutzwert eines Konflikts. savcode ist der Wert ohne Deckel (wie CalcSavings speichert)."""
    name = e.u32(conf + 8)
    first = e.u32(conf + 0x38)
    last = e.u32(conf + 0x3C)
    state = _u16(e, conf + 0x54)
    avail = e.u32(conf + 0x1C)
    abbild = e.u32(conf + 0x14)
    klasse = _u8(e, name + 5) if name else 0
    usage = _u16(e, name + 0x18) if name else 0
    use, defn, load = _tab(e, A_USE, klasse), _tab(e, A_DEF, klasse), _tab(e, A_LOAD, klasse)
    index_save = e.u32(BASE + A_INDEX)
    gew = [e.u32(BASE + A_WEIGHT + 4 * i) for i in range(5)] + [e.u32(BASE + A_WEIGHT_MAX)]
    roh = roh_offen = 0
    tiefe = 0
    tor = []
    if first and last and name:
        blk = e.u32(conf + 0x0C)
        ins = first
        if os.environ.get('SAV_TRACE'):
            print('  name %s first %s last %s' % (hex(name), hex(first), hex(last)))
        gesehen = set()
        schritte = 0
        while blk and ins and schritte < 20000:
            schritte += 1
            treffer = 0
            fertig = False
            while ins and schritte < 20000:
                schritte += 1
                if ins in gesehen:
                    fertig = True
                    break
                gesehen.add(ins)
                op = _u8(e, ins + 0x22)
                if op == OP_BLOCK:
                    break
                nops = _u8(e, ins + 0x3F)
                if nops > 8:
                    nops = 8
                res = e.u32(ins + 0x30)
                for i in range(nops):
                    opn = e.u32(ins + 0x44 + 4 * i)
                    if not opn:
                        continue
                    if gleich(e, opn, name):
                        treffer += use
                        if i == 0 and op < FIRST_COND and res and _u8(e, res + 4) == N_REG:
                            treffer += use
                    elif _u8(e, opn + 4) == N_INDEX:
                        if gleich(e, e.u32(opn + 0x0C), name):
                            treffer += index_save
                if res:
                    if gleich(e, res, name):
                        selbe = False
                        if op in (OP_MOV, OP_CONVERT) and nops:
                            op0 = e.u32(ins + 0x44)
                            if op0 and _u8(e, res + 4) == N_TEMP and _u8(e, op0 + 4) == N_TEMP:
                                loc = e.u32(res + 0x20)
                                if loc != NO_LOCATION and loc == e.u32(op0 + 0x20):
                                    selbe = True
                        if selbe:
                            treffer -= load
                        else:
                            treffer += defn
                            if nops:
                                op0 = e.u32(ins + 0x44)
                                if op0 and _u8(e, op0 + 4) == N_REG:
                                    treffer += use
                    elif _u8(e, res + 4) == N_INDEX:
                        if gleich(e, e.u32(res + 0x0C), name):
                            treffer += index_save
                if ins == last:
                    fertig = True
                    break
                ins = e.u32(ins + 4)
            w = gewicht(e, blk, None)
            tiefe = max(tiefe, _u8(e, blk + 0x50))
            roh += treffer * min(w, DECKEL)
            roh_offen += treffer * w
            if os.environ.get('SAV_TRACE'):
                print('    blk %s tiefe %d w %d treffer %d' % (hex(blk), _u8(e, blk + 0x50), w, treffer))
            if fertig:
                break
            blk = e.u32(blk + 0x28)
            ins = e.u32(blk + 4) if blk else 0
    sav = roh_offen
    if state & 4:
        sav = 0
        tor.append('conflict_on_hold')
    elif avail == 0 and not (state & 0x240):
        sav = 0
        tor.append('available==0')
    elif first == last or not first or not last:
        sav = 0
        tor.append('eine Instruktion')
    elif roh_offen <= 0:
        sav = 0
        tor.append('save<=cost')
    sav_deckel = 0 if tor else roh
    if sav != abbild and abbild == 0 and roh_offen > 0 and (usage & 0x88) and not tor:
        tor.append('save<=cost Adresse/NEEDS_MEMORY')
    return dict(savcode=sav, sav_deckel=sav_deckel, roh=roh, roh_offen=roh_offen, tor=tor, usage=usage,
                tiefe=tiefe, gewichte=gew, use=use, defn=defn, load=load, index_save=index_save)

def lauf(src, fkt, unit, k=None, d=0, info=None):
    st = {'n': -1}
    def hook(e):
        rd = R.RegDump.__new__(R.RegDump)
        rd.e = e
        def h(uc, a, s, _):
            if fname(e) != fkt:
                return
            st['n'] += 1
            if st['n'] != 0:
                return
            p = e.r(X.UC_X86_REG_EAX)
            i = 0
            while p:
                if info is not None:
                    dd = rd.name_info(p)
                    dd['savings'] = e.u32(p + 0x14)
                    dd['first'] = irlist.ins(e, e.u32(p + 0x38))
                    try:
                        dd.update(zaehlung(e, p))
                    except Exception as ex:
                        dd.update(savcode=-1, roh=-1, roh_offen=-1, tor=['ZAEHLFEHLER %s' % ex],
                                  usage=0, tiefe=0, gewichte=[])
                    nm = dd.get('name') or 0
                    dd['state'] = _u16(e, p + 0x54)
                    fl = _u16(e, nm + 0x2A) if nm else 0
                    dd['flags'] = fl
                    dd['const'] = 1 if dd.get('cls') == N_TEMP and (fl & CONST_TEMP) else 0
                    info.append(dd)
                if i == k:
                    v = e.u32(p + 0x14)
                    uc.mem_write(p + 0x14, struct.pack('<I', max(0, v + d)))
                p = e.u32(p)
                i += 1
            if info is not None:
                try:
                    const_anwenden(e, info)
                except Exception as ex:
                    for row in info:
                        row.setdefault('tor', []).append('CONSTFEHLER %s' % ex)
        e.uc.hook_add(U.UC_HOOK_CODE, h, begin=BASE + 0x9408F, end=BASE + 0x9408F)
    obj = os.path.join(C.TMP, 'sav_%d.obj' % os.getpid())
    ok, out, e = comp(src, obj, hook=hook)
    if not ok:
        return 9999
    try:
        return diff(unit, fkt, obj, 0)[0]
    except Exception:
        return 9999

def job(a):
    src, fkt, unit, k, d = a
    return k, d, lauf(src, fkt, unit, k, d)

def diag(src, unit, fkt, pool):
    info = []
    n0 = lauf(src, fkt, unit, None, 0, info)
    if n0 in (0, 9999) or not info:
        return n0, info, []
    R_ = pool.map(job, [(src, fkt, unit, k, d) for k in range(len(info)) for d in DS if info[k]['savings'] + d >= 0])
    R_.sort(key=lambda x: x[2])
    return n0, info, R_

def zeile(info, k, d):
    x = info[k]
    return '%s (sav %d%+d) aus: %s' % (x['txt'], x['savings'], d, x['first'][:50])

def drucke_savcode(info):
    if not info or 'savcode' not in info[0]:
        print('  savcode.h: keine Konflikte gelesen')
        return
    g = info[0].get('gewichte') or []
    if g:
        print('  Schleifengewichte Abbild depth 0..5: %s' % ' '.join(str(x) for x in g))
        print('  Deckel %d ist die Aufgabenformel; CalcSavings benutzt die volle Tabelle.' % DECKEL)
    mc = max((d.get('maxconst') or 0) for d in info)
    if mc:
        print('  ConstSavings MaxConstSave %d (Additiv auf positive Nicht-const-Konflikte)' % mc)
    def _addr(d):
        return any('Adresse/NEEDS_MEMORY' in t for t in (d.get('tor') or []))
    n_ok = sum(1 for d in info if not _addr(d) and d.get('nach', d.get('savcode')) == d.get('savings'))
    print('  Zaehlung gegen Abbild: %d/%d treffen' % (n_ok, len(info)))
    for d in info:
        ab = d.get('savings', -1)
        sc = d.get('savcode', -1)
        nach = d.get('nach', sc)
        deckel = d.get('sav_deckel', d.get('roh'))
        addr = _addr(d)
        if addr:
            mark = 'ABWEICHUNG'
        elif nach == ab:
            mark = 'ok' if nach == sc else 'ok ConstSavings'
        elif deckel == ab and deckel not in (None, sc):
            mark = 'ABWEICHUNG Abbild folgt Deckel 400'
        else:
            mark = 'ABWEICHUNG'
        extra = ''
        if deckel not in (None, sc):
            extra += '  Deckel400 %d' % deckel
        if nach not in (None, sc) and not addr:
            extra += '  nach-Const %d' % nach
        if d.get('const'):
            extra += '  const'
        tor = ('  Tor ' + ', '.join(d.get('tor') or [])) if d.get('tor') else ''
        if sc not in (None, 0, ab, nach) and 'eine Instruktion' in (d.get('tor') or []):
            extra += '  Roh %d' % sc
        print('    %-16s abbild %6d  savcode %6d  %s%s%s' % (
            (d.get('txt') or '')[:16], ab, sc, mark, extra, tor))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('src', nargs='?')
    ap.add_argument('einheit', nargs='?')
    ap.add_argument('fkt', nargs='?')
    ap.add_argument('--alle', action='store_true')
    ap.add_argument('--procs', type=int, default=2)
    A = ap.parse_args()
    if A.alle:
        sys.exit('savdiag_ra: --alle gibt es hier nicht (wÃ¼rde auÃerhalb dieses Ordners schreiben)')
    if not A.src or not A.einheit or not A.fkt:
        ap.error('QUELLE EINHEIT FKT')
    if A.procs > 2:
        print('Hinweis: Auftrag erlaubt hÃ¶chstens 2 Emulator-Prozesse, --procs %d bleibt beim Aufrufer' % A.procs)
    pool = mp.get_context('fork').Pool(A.procs, maxtasksperchild=40)
    n0, info, R_ = diag(A.src, A.einheit, A.fkt, pool)
    print('%s %s: %d abweichende Befehle, %d Konflikte' % (A.einheit, A.fkt, n0, len(info)))
    drucke_savcode(info)
    for k, d, n in R_[:10]:
        print('  %4d Befehle: %s' % (n, zeile(info, k, d)))
    pool.close()
    pool.join()
