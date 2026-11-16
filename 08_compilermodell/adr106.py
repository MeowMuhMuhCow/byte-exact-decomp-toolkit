#!/usr/bin/env python3
"""Bildoffsets Watcom 10.6, WPP386 und WCC386. worker, 2026-11-03.

ADR[compiler][name] ist der Offset im CF-Abbild. Geladen wird bei 0x400000,
der Hook liegt bei BASE + Offset. Belege: ADRESSEN_WCC.tsv.

Compiler aus der Quellzeile // CC wcc386, sonst wpp386 (wie comp.kopf).
Stub und Exit sind keine Codegenerator-Adressen. WCC-Werte dort aus der
Eichung worker, nicht aus der Signatur.

Knotenoeffsets (savings +0x14, Name-id +0x24, Konflikt +8/+0x14/+0x20)
sind in beiden Abbildern dieselben Bytes. Wo ein Align vollstaendig ist,
wurde jedes Displacement mitverglichen.
"""
import re

BASE = 0x400000

# Gleiche Struktur in beiden Compilern. Nicht Bildadressen.
OFF = dict(
    conf_next=0,
    conf_name=8,
    conf_savings=0x14,
    conf_with=0x20,
    name_class=4,
    name_size=8,
    name_sym=0x14,
    name_id=0x24,
    name_flags=0x2A,
    sym_inner=0x0C,
    currproc_sym=0x84,
    ins_line=0x20,
    ins_id=0x34,
    dag_ins=4,
    dag_ready=0x0C,
    dag_stallable=0x10,
    dag_flags=0x11,
    dag_height=0x14,
)

STUB = {'wpp386': 0x6B198, 'wcc386': 0x33BC4}
EXIT = {'wpp386': 0x6B196, 'wcc386': 0x33BC2}

_WPP = dict(
    ConstSavings=0x76A08,
    LatePickResetAufrufer=0x7D4DC,
    CalcSavings=0x8A86C,
    NameConflict=0x8B67C,
    AssignOtherLocals=0x90C42,
    TempAllocVorliste=0x90C68,
    TempAllocNach=0x90C6D,
    TempAllocBefore=0x90CDC,
    IdVergabe=0x91853,
    CountRegMoves=0x93744,
    GiveBestReg=0x93BC8,
    GiveBestRegSchleife=0x93C77,
    CountRegMovesNach=0x93CE5,
    GiveBestRegGewaehlt=0x93D9D,
    InMemory=0x93EF8,
    GiveRegister=0x93F40,
    GiveRegisterNach=0x93F7D,
    AssignConflicts=0x94020,
    SortConflictsVor=0x9408F,
    SortConflictsNach=0x94094,
    ConfBefore=0x94148,
    AllocBefore=0x952E5,
    LatePick=0x9EBFE,
    LatePickStore=0x9EC84,
    LatePickReset=0x9EF5B,
    LatePickResetHook=0x9EF5E,
    StallCost=0x9FE93,
    ScheduleIns=0xA0152,
    ScheduleInsRunde=0xA01AC,
    ScheduleInsKostenSkost=0xA01F1,
    ScheduleInsKostenErster=0xA01F9,
    ScheduleInsKosten=0xA01FE,
    ScheduleInsHoehe=0xA0216,
    ScheduleInsIndex=0xA0240,
    ScheduleInsStallable=0xA0255,
    ScheduleInsFpseq=0xA0271,
    ScheduleInsId=0xA027F,
    ScheduleInsIdReadme=0xA0281,
    ScheduleInsWahl=0xA02AC,
    SortList=0xA3667,
    SortListStelle=0xA36E5,
    SortById=0xA7E60,
    ConstToTemp=0xAA23E,
    FPStkOver=0xACA51,
    FPCalcStk=0xACACD,
    ByteRegs=0xC1100,
    WordRegs=0xC1124,
    DwordRegs=0xC1330,
    RegsInUse=0xC6840,
    LastTemp=0xC6860,
    NamesConstant=0xC6868,
    NamesTemp=0xC6870,
    ConfList=0xC6880,
    NameHead=0xC688C,
    CurrProc=0xC6894,
    SavIndex=0xC6AE4,
    SavLoad=0xC6AE8,
    SavB14=0xC6B14,
    SavUse=0xC6B40,
    SavDef=0xC6B6C,
    SavB98=0xC6B98,
    SavBC4=0xC6BC4,
    Weight=0xC6BF0,
    WeightMax=0xC6C04,
    LatePickStateWord=0xC7078,
    LatePickStateByte=0xC707C,
    LatePickStateDword=0xC7080,
)

_WCC = dict(
    ConstSavings=0x48C5A,
    LatePickResetAufrufer=0x4C3CD,
    CalcSavings=0x5A3EC,
    NameConflict=0x5ACEF,
    AssignOtherLocals=0x5EAAF,
    TempAllocVorliste=0x5EAD5,
    TempAllocNach=0x5EADA,
    TempAllocBefore=0x5EB49,
    IdVergabe=0x5F6C0,
    CountRegMoves=0x61004,
    GiveBestReg=0x61488,
    GiveBestRegSchleife=0x61537,
    CountRegMovesNach=0x615A5,
    GiveBestRegGewaehlt=0x6165D,
    InMemory=0x617B8,
    GiveRegister=0x61800,
    GiveRegisterNach=0x6183D,
    AssignConflicts=0x618E0,
    SortConflictsVor=0x6194F,
    SortConflictsNach=0x61954,
    ConfBefore=0x61A08,
    AllocBefore=0x62BA5,
    LatePick=0x6C4BE,
    LatePickStore=0x6C544,
    LatePickReset=0x6C81B,
    LatePickResetHook=0x6C81E,
    StallCost=0x6D753,
    ScheduleIns=0x6DA12,
    ScheduleInsRunde=0x6DA6C,
    ScheduleInsKostenSkost=0x6DAB1,
    ScheduleInsKostenErster=0x6DAB9,
    ScheduleInsKosten=0x6DABE,
    ScheduleInsHoehe=0x6DAD6,
    ScheduleInsIndex=0x6DB00,
    ScheduleInsStallable=0x6DB15,
    ScheduleInsFpseq=0x6DB31,
    ScheduleInsId=0x6DB3F,
    ScheduleInsIdReadme=0x6DB41,
    ScheduleInsWahl=0x6DB6C,
    SortList=0x70330,
    SortListStelle=0x703AE,
    SortById=0x5A056,
    ConstToTemp=0x748D9,
    FPStkOver=0x770EC,
    FPCalcStk=0x77168,
    ByteRegs=0x7F444,
    WordRegs=0x7F468,
    DwordRegs=0x7F674,
    RegsInUse=0x858E0,
    LastTemp=0x85900,
    NamesConstant=0x85908,
    NamesTemp=0x85910,
    ConfList=0x85920,
    NameHead=0x8592C,
    CurrProc=0x85934,
    SavIndex=0x864F4,
    SavLoad=0x864F8,
    SavB14=0x86524,
    SavUse=0x86550,
    SavDef=0x8657C,
    SavB98=0x865A8,
    SavBC4=0x865D4,
    Weight=0x86600,
    WeightMax=0x86614,
    LatePickStateWord=0x86798,
    LatePickStateByte=0x8679C,
    LatePickStateDword=0x867A0,
)

ADR = {'wpp386': _WPP, 'wcc386': _WCC}

# Namen, die ein Werkzeug wirklich anspringt oder ausliest.
WERKZEUG = dict(
    regdump=('SortConflictsNach', 'GiveRegisterNach', 'InMemory', 'CurrProc'),
    regforce=('GiveBestRegSchleife', 'CountRegMovesNach', 'GiveBestRegGewaehlt', 'RegsInUse', 'CurrProc'),
    slotdiag_ra=('TempAllocNach', 'CurrProc'),
    schedforce=('ScheduleIns', 'ScheduleInsRunde', 'ScheduleInsWahl',
                'ScheduleInsKostenErster', 'ScheduleInsKosten', 'ScheduleInsHoehe',
                'ScheduleInsIndex', 'ScheduleInsStallable', 'ScheduleInsFpseq', 'ScheduleInsId',
                'CurrProc'),
)


def fuer(compiler):
    c = (compiler or 'wpp386').lower()
    if c in ('wcc', 'wcc386', 'c'):
        return ADR['wcc386']
    if c in ('wpp', 'wpp386', 'cpp', 'c++'):
        return ADR['wpp386']
    raise KeyError(compiler)


def name(compiler):
    c = (compiler or 'wpp386').lower()
    if c in ('wcc', 'wcc386', 'c'):
        return 'wcc386'
    if c in ('wpp', 'wpp386', 'cpp', 'c++'):
        return 'wpp386'
    raise KeyError(compiler)


def compiler_aus_quelle(path):
    """// CC wcc386 irgendwo in der Datei, sonst wpp386. Gleiche Regel wie comp.kopf."""
    with open(path, errors='replace') as f:
        for zeile in f:
            if re.match(r'^// CC wcc386\b', zeile.strip()):
                return 'wcc386'
    return 'wpp386'


def aus_quelle(path):
    return fuer(compiler_aus_quelle(path))


def funktionsname(emu, compiler):
    """Name ueber die C++-Symbolkette. CurrProc+0x84 -> +8 -> Symbol.

    WPP386: +8 ist ein Zeiger, die Kette endet im Quellnamen.
    WCC386: +8 und name+0x14 sind kleine Indizes. Die Kette wirft oder liefert leer.
    Dann ProcTrack nehmen.
    """
    A = fuer(compiler)
    cp = emu.u32(BASE + A['CurrProc'])
    if cp < BASE:
        return ''
    fs = emu.u32(emu.u32(cp + OFF['currproc_sym']) + 8)
    if fs < BASE:
        return ''
    return emu.cstr(emu.u32(emu.u32(fs + OFF['sym_inner']) + OFF['sym_inner']), 80)


def quellfunktionen(path):
    """//@ f_xxxxxx in Dateireihenfolge. Watcom uebersetzt sie in dieser Reihenfolge."""
    namen = []
    with open(path, errors='replace') as f:
        for zeile in f:
            m = re.match(r'\s*//@\s+(f_[0-9A-Fa-f]+)\b', zeile)
            if m:
                namen.append(m.group(1).lower())
    return namen


class ProcTrack:
    """Aktuelle Funktion.

    CurrProc selbst ist ein wiederverwendetes Objekt, die Adresse bleibt.
    Das Symbol daran (CurrProc+0x84) wechselt je Funktion. Unter WPP386
    liefert die Symbolkette den Quellnamen. Unter WCC386 ist das ein Index,
    dann gilt die //@-Reihenfolge der bisher gesehenen Symbole.
    """

    def __init__(self, emu, compiler, namen):
        self.e = emu
        self.addr = BASE + fuer(compiler)['CurrProc']
        self.compiler = compiler
        self.namen = [n.lower() for n in namen]
        self.gesehen = {}
        self.kette = {}

    def name(self):
        cp = self.e.u32(self.addr)
        sym = self.e.u32(cp + OFF['currproc_sym']) if cp >= BASE else 0
        if not sym:
            return ''
        if sym not in self.gesehen:
            self.gesehen[sym] = len(self.gesehen)
            try:
                self.kette[sym] = funktionsname(self.e, self.compiler) or ''
            except Exception:
                self.kette[sym] = ''
        i = self.gesehen[sym]
        if self.kette.get(sym):
            return self.kette[sym]
        if 0 <= i < len(self.namen):
            return self.namen[i]
        return ''


if __name__ == '__main__':
    fehl = [k for k in _WPP if k not in _WCC]
    print('namen', len(_WPP), 'fehlen_in_wcc', fehl)
    print('stub', {k: hex(v) for k, v in STUB.items()})
