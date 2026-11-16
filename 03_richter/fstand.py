# fstand.py OBJ VA [FUNK|-t] - Funktionsstand je Einheit (Phase 4, 22.10.2026). Ersetzt fdiff.py fuer die Zaehlung.
# Zuordnung nach SYMBOL (f_xxxxxx im OBJ <-> Adresse), nicht nach Offset: fehlende Funktionen (FEHLT), zusaetzliche (EXTRA,
# i_xxx/statics) und Groessenaenderungen verschieben nichts mehr. Funktionsende: naechstes Symbol im OBJ bzw. naechste
# Funktion laut clobber.tsv im Original. rel32-Ziele (call/jmp/jcc) werden auf Symbolnamen aufgeloest (Original: f_xxxxxx,
# OBJ: Pub-Name; Fixup-Ziel = EXT = Platzhalter). GLEICH = gleiche Groesse und identische normierte Befehlsfolge.
# Ausgabe: je Funktion "ADR orig/neu GLEICH|n Befehle|FEHLT", EXTRA-Zeilen, Summenzeile. -t: eine TSV-Zeile (gleich,n,bytes_gleich,bytes).
import sys,os,re,subprocess,difflib,struct,tempfile
_HERE=os.path.dirname(os.path.abspath(__file__))
_ROOT=os.path.normpath(os.path.join(_HERE,'..'))
for _p in (_HERE, os.path.join(_ROOT,'02_basis'), _ROOT):
    if _p not in sys.path: sys.path.insert(0,_p)
import project_config as PC
_CFG=PC.load_config()
import omf, le
img=open(PC.resolve_path('flat_bin',_CFG),'rb').read()
B=int(_CFG.get('binary',{}).get('code_base_offset',0x10000) or 0x10000)
Q=PC.resolve_path('project_root',_CFG)
_UNITS_TSV=PC.resolve_path('units_tsv',_CFG)
_FUNCS_TSV=PC.resolve_path('functions_tsv',_CFG)
_CLOBBER_TSV=PC.resolve_path('clobber_tsv',_CFG)
obj,va=sys.argv[1],int(sys.argv[2],16); arg=sys.argv[3] if len(sys.argv)>3 else None
_TXL=None
if os.environ.get('FSTAND_FLACH','1')=='1':
    try:
        if any(c.get('data') for c in omf.modules(obj)[0]['comdats']):
            _TXL=max([len(_s['data']) for _s in omf.modules(obj)[0]['segs'].values() if _s['cls']=='CODE'] or [0])
            import subprocess as _sp, tempfile as _tf
            _t=_tf.NamedTemporaryFile(suffix='.OBJ',delete=False).name
            _r=_sp.run([sys.executable,os.path.join(_HERE,'flach.py'),obj,_t],capture_output=True,text=True)
            if _r.returncode==0 and os.path.getsize(_t)>0: obj=_t
            else: _TXL=None
    except Exception: pass
JSON=(arg=='--json'); TARGETS={int(x.removeprefix('f_'),16) for x in sys.argv[4:]} if JSON else set(); DIFFS={}
F=int(arg,16) if arg and arg not in ('-t','--json') else None; TSV=(arg=='-t'); PAD=os.environ.get('FSTAND_PAD','1')=='1'
_EXCL=PC.load_excluded_table_addresses(_CFG)
_fset=set()
if _FUNCS_TSV and os.path.isfile(_FUNCS_TSV):
    _fset|={int(l.split('\t')[0],16) for l in open(_FUNCS_TSV) if re.match(r'[0-9a-fA-F]{6}\t',l)}
if _CLOBBER_TSV and os.path.isfile(_CLOBBER_TSV):
    _fset|={int(l[2:8],16) for l in open(_CLOBBER_TSV) if l.startswith('f_')}
if _UNITS_TSV and os.path.isfile(_UNITS_TSV):
    _fset|={int(x,16) for l in open(_UNITS_TSV) for x in l.rstrip('\n').split('\t')[2:4] if re.match(r'[0-9a-fA-F]{6}$',x)}
FUN=sorted(_fset - _EXCL)
m=omf.modules(obj)[0]; cs=[s for s in m['segs'].values() if s['cls']=='CODE']+m['comdats']
sg=max(cs,key=lambda s:len(s['data'])); d,mk=sg['data'],sg['mask']; n=len(d)
# Symbolidentität: Segmentbezug erhalten; Daten sind keine Codegrenzen.
_CODE_SEG=next((k for k,v in m['segs'].items() if v is sg),None)
if _CODE_SEG is None: raise ValueError('Symbolzuordnung: ausgewaehlter Code ohne eindeutiges SEGDEF')
SYMBOL_AUDIT={'noncode_publics':[],'ambiguous_offsets':[],'position_rejected':[], 'other_code_segments':[]}
_OTHER_CODE_EXTRA=[]
for _si,_sv in m['segs'].items():
    if _si!=_CODE_SEG and _sv['cls']=='CODE' and _sv['data']:
        _OTHER_CODE_EXTRA.append((0,'SEGMENT_%d::%s'%(_si,_sv['name']),len(_sv['data'])))
        SYMBOL_AUDIT['other_code_segments'].append({'segment':_si,'name':_sv['name'],'bytes':len(_sv['data'])})
# Nicht abgeflachte Code-/unklare COMDATs bleiben sichtbar, Daten gesondert.
SYMBOL_AUDIT['noncode_comdats']=[]
for _cd in m['comdats']:
    _cs=m['segs'].get(_cd.get('seg'),{}).get('cls')
    if _cs in ('DATA','BSS','CONST'):
        SYMBOL_AUDIT['noncode_comdats'].append({'name':_cd['name'],'segment':_cd.get('seg'),'class':_cs,'bytes':len(_cd['data'])})
    elif _cd['data']:
        _OTHER_CODE_EXTRA.append((0,'COMDAT_UNGEKLAERT::'+_cd['name'],len(_cd['data'])))
dd=open(obj,'rb').read(); i=0; pubs=[]
while i<len(dd):
    t=dd[i]; L=struct.unpack_from('<H',dd,i+1)[0]; b=dd[i+3:i+2+L]
    if t in (0x90,0x91,0xB6,0xB7):
        _group,j=omf.idx(b,0); _segment,j=omf.idx(b,j)
        if _segment==0: j+=2  # absolute PUBDEF besitzt einen Frame
        while j<len(b):
            l=b[j]; nm=b[j+1:j+1+l].decode('latin1'); j+=1+l
            off=struct.unpack_from('<I' if t&1 else '<H',b,j)[0]; j+=4 if t&1 else 2; j+=1 if b[j]<0x80 else 2
            if _segment==_CODE_SEG and off<n: pubs.append((off,nm))
            elif _segment!=_CODE_SEG:
                _sv=m['segs'].get(_segment,{})
                if _sv.get('cls')!='CODE': SYMBOL_AUDIT['noncode_publics'].append({'name':nm,'segment':_segment,'class':_sv.get('cls','ABSOLUT' if _segment==0 else 'UNBEKANNT'),'offset':off})
    i+=3+L
pubs=sorted(set(pubs)); offs=sorted(set(o for o,_ in pubs))
if _TXL is not None:   
    _lim=None            # zur Folgeeinheit (Schwanz-Einheit), sonst EXTRA/Fehlgrenzen und die Endfuellung zaehlt als Abweichung
    try:
        for _l in open(_UNITS_TSV,encoding='utf-8'):
            _t2=_l.rstrip('\n').split('\t')
            if len(_t2)>3 and re.match(r'[0-9a-fA-F]{6}$',_t2[2]) and re.match(r'[0-9a-fA-F]{6}$',_t2[3]) and int(_t2[2],16)==int(sys.argv[2],16): _lim=int(_t2[3],16)-int(_t2[2],16)
    except Exception: _lim=None
    if _lim and _TXL<=_lim<n:
        pubs=[p for p in pubs if p[0]<_lim]; offs=sorted(set(o for o,_ in pubs)); n=_lim; d=d[:n]; mk=mk[:n]
        if not any(d[_TXL:n]): n=_TXL; d=d[:n]; mk=mk[:n]; pubs=[p for p in pubs if p[0]<n]; offs=sorted(set(o for o,_ in pubs))   # nur Nullfuellung bis zum Schnitt -> wie ungeplaettet (objdump-unabhaengig)
def sym(nm):
    # Primär benannter Konstruktor: f_-Klasse ist hier die Konstruktoradresse.
    # Destruktoren und lokale Klassenkontexte gehören ausdrücklich NICHT dazu.
    _ctor=re.match(r'^W\?\$ct:f_([0-9a-f]{6})\$n\(',nm)
    if _ctor: return 'f_'+_ctor[1]
    if re.match(r'^W\?\$Wsi[0-9]+tab\$',nm): return nm  # Watcom-Sprungtabelle im CODE-Segment
    _sym_Alias=_CFG.get('symbol_aliases',{}).get(f'{int(sys.argv[2],16):06x}',{})
    if nm in _sym_Alias: return _sym_Alias[nm]
    if any(nm.startswith(p) for p in _CFG.get('code_data_prefixes',[])): return nm
    mm=re.match(r'W?\??f_([0-9a-f]{6})\b',nm); return 'f_%06x'%int(mm.group(1),16) if mm else nm
FUN_ORIG=FUN[:]  # nur Originalstarts duerfen als FEHLT ergaenzt werden
byoff={}; FUN=sorted(set(FUN)|{int(sym(nm)[2:],16) for _,nm in pubs if re.match(r'f_[0-9a-f]{6}$',sym(nm))})  # OBJ-Symbole ergaenzen die Funktionstabelle
# Explizite primäre Namen haben Vorrang; mehrere Identitäten bleiben unklar.
_EXPLICIT={}; _BY_OFFSET={}
for o,nm in pubs:
    _s=sym(nm); _BY_OFFSET.setdefault(o,set())
    if re.fullmatch(r'f_[0-9a-f]{6}',_s):
        _BY_OFFSET[o].add(_s); _EXPLICIT.setdefault(int(_s[2:],16),set()).add(o)
    byoff.setdefault(o,_s)
_AMBIG=set()
for _of,_ids in _BY_OFFSET.items():
    if len(_ids)==1: byoff[_of]=next(iter(_ids))
    elif len(_ids)>1:
        _AMBIG.add(_of); byoff[_of]='AMBIG_SYMBOLS::'+','.join(sorted(_ids))
        SYMBOL_AUDIT['ambiguous_offsets'].append({'offset':_of,'identities':sorted(_ids)})
_FO=set(FUN_ORIG); _LO0=int(sys.argv[2],16)
_UNIT_ENDS=set()
for _line in open(_UNITS_TSV):
    _cols=_line.rstrip('\n').split('\t')
    if len(_cols)>=4 and re.fullmatch(r'[0-9a-fA-F]{6}',_cols[2]) and re.fullmatch(r'[0-9a-fA-F]{6}',_cols[3]) and int(_cols[2],16)==_LO0:
        _UNIT_ENDS.add(int(_cols[3],16))
_UNIT_END=next(iter(_UNIT_ENDS)) if len(_UNIT_ENDS)==1 else None
for o,nm in pubs:   
    if not re.match(r'f_[0-9a-f]{6}$',byoff.get(o,'')) and not nm.startswith('W?$Wsi') and (_LO0+o) in _FO:
        _context=bool(re.search(r'\bf_[0-9a-f]{6}\b',nm))
        if o not in _AMBIG and _UNIT_END is not None and _LO0<=_LO0+o<_UNIT_END and _LO0+o not in _EXPLICIT and not _context:
            byoff[o]='f_%06x'%(_LO0+o)
        else:
            SYMBOL_AUDIT['position_rejected'].append({'offset':o,'name':nm,'would_be':'f_%06x'%(_LO0+o),'explicit_elsewhere':_LO0+o in _EXPLICIT,'embedded_context':_context,'outside_or_ambiguous_unit':_UNIT_END is None or not _LO0<=_LO0+o<_UNIT_END})
SZ={7:4,5:2,6:6}; o=bytearray(img); va=B   # ganzes Bild, Fixups maskiert (Funktionen ausserhalb der Einheit, z. B. Zwillinge, vergleichbar)
for s,t,g in le.fixups:
    for k in range(SZ.get(t,4)):
        if 0<=s-B+k<len(o): o[s-B+k]=0
LO=int(sys.argv[2],16)
# Belegte Datenbereiche unmittelbar hinter dem Originalcode (Tabelle einschl. Padding).
# Nur ein OBJ-Endrest derselben Laenge darf aus dem Codevergleich fallen.
DATA_TAIL={
    (int(k.split(':')[0],16),int(k.split(':')[1],16)):int(v)
    for k,v in _CFG.get('data_tails',{}).items()
}
_END_OVR={
    (int(k.split(':')[0],16),int(k.split(':')[1],16)):int(v,16) if isinstance(v,str) else int(v)
    for k,v in _CFG.get('function_end_overrides',{}).items()
}
a=bytearray(d)
for k in range(n):
    if mk[k]: a[k]=0
ADR=[]; ADRALL=[]
PADX=re.compile(r'^(nop|xchg\s+ax,ax|int3|mov\s+(e?[a-d]x|e?[sd]i),\2|lea\s+(e?[a-d]x|e?[sd]i|esp|ebp),\[\3(\+eiz\*1)?\+0x0\]|lea\s+(e?[a-d]x|e?[sd]i),\[\5\]|add\s+BYTE PTR \[eax\],al|data16.*|nop\s+.*|xchg\s+eax,eax|\.byte 0x0)$')   
ENDX=re.compile(r'^(ret|jmp|iret|retf)')
def kern(L,A,ganz):   
    k=len(L)
    while k>0 and PADX.match(L[k-1].strip()): k-=1
    if k>0 and ENDX.match(L[k-1]): return L[:k],(A[k]-A[0]) if k<len(A) else ganz
    return L,ganz
RX=re.compile(r'^(call|j\w+)\s+0x([0-9a-f]+)$')
def dis(buf,base,res,ist_obj=False):
    with tempfile.NamedTemporaryFile(prefix='decomp_fs_',suffix='.bin',dir='/tmp') as p:
        p.write(bytes(buf)); p.flush()
        out=subprocess.run(['objdump','-D','-z','-b','binary','-mi386','-Mintel','--no-show-raw-insn',p.name],capture_output=True,text=True).stdout
    r=[]; ADR.clear()
    for l in out.splitlines():
        if l[:1]!=' ' or ':' not in l: continue
        x=l.split('\t',1)[-1].strip(); adr=int(l.split(':')[0],16)
        q=RX.match(x)
        if q:
            tg=int(q.group(2),16)
            if ist_obj and ((q.group(1) in ('call','jmp') and tg==adr+5) or (q.group(1) not in ('call','jmp') and tg==adr+6)): x=q.group(1)+' EXT'   # Fixup (maskiert) = Platzhalter; worker: auch bedingter Sprung rel32 (6 B) in fremde Funktion (bedingter Endsprung)
            elif tg<len(buf): x=q.group(1)+' +%x'%tg
            else: x=q.group(1)+' '+res((base+tg)&0xffffffff)
        r.append(x); ADR.append(adr)
    ADRALL[:]=ADR[:]
    while r and r[-1] in ('add    BYTE PTR [eax],al','(bad)'): r.pop(); ADR.pop()
    return r
import bisect
def res_o(ad):   # Ziel als Symbol(+Abstand): Spruenge in Nachbarfunktionen (geteilte Enden) vergleichbar
    k=bisect.bisect_right(FUN,ad)-1
    return ('f_%06x'%FUN[k]+('' if FUN[k]==ad else '+%x'%(ad-FUN[k]))) if k>=0 else '?%06x'%ad
def res_a(of):
    k=bisect.bisect_right(offs,of)-1
    return (byoff[offs[k]]+('' if offs[k]==of else '+%x'%(of-offs[k]))) if k>=0 else '?%x'%of
"""Enge Zusatzprüfung für bereits erkannte Originalfüllung gegen OBJ-Nullfüllung.

Nur mit identischem Kern und identischer Kerngrenze aufrufen. Kein Schneiden
von Originalbytes; kein allgemeines Entfernen von Daten nach ret.
"""
import struct

_PAD_TARGET_CACHE = {}


def _padding_encoded_targets(blob, base):
    key = bytes(blob), base
    if key in _PAD_TARGET_CACHE: return _PAD_TARGET_CACHE[key]
    targets = set()
    for i, opcode in enumerate(blob):
        if opcode in (0xe8, 0xe9) and i + 5 <= len(blob):
            targets.add((base + i + 5 + struct.unpack_from('<i', blob, i + 1)[0]) & 0xffffffff)
        elif opcode == 0x0f and i + 6 <= len(blob) and 0x80 <= blob[i + 1] <= 0x8f:
            targets.add((base + i + 6 + struct.unpack_from('<i', blob, i + 2)[0]) & 0xffffffff)
        if (opcode == 0xeb or 0x70 <= opcode <= 0x7f or 0xe0 <= opcode <= 0xe3) and i + 2 <= len(blob):
            targets.add((base + i + 2 + struct.unpack_from('<b', blob, i + 1)[0]) & 0xffffffff)
    # Eher zu streng: auch Bytefolgen mitten in Daten/Befehlen gelten als Verdacht.
    _PAD_TARGET_CACHE[key] = targets
    return targets


def _padding_referenced(blob, base, low, high):
    # VORSCHLAG padfix (05.11.2026): Dword-Suche ignoriert Fundstellen, die selbst rel32-Operand
    # eines CALL/JMP (E8/E9) oder Jcc (0F 80..8F) sind. Deren Ziel ist oben schon dekodiert;
    # die rohe Verschiebung (z.B. 0x0cab2b) ist keine Adresse und gab Fehlalarm.
    if any(low <= p < high for p in _padding_encoded_targets(blob, base)): return True
    b = bytes(blob)
    for p in range(low, high):
        k = struct.pack('<I', p); pos = b.find(k)
        while pos >= 0:
            rel32 = (pos >= 1 and b[pos - 1] in (0xe8, 0xe9)) or (pos >= 2 and b[pos - 2] == 0x0f and 0x80 <= b[pos - 1] <= 0x8f)
            if not rel32: return True
            pos = b.find(k, pos + 1)
    return False


def zero_tail_allowed(original, compiled, mask, cut, orig_base, obj_base,
                      original_image, image_base, object_code, function_starts,
                      object_starts, fixups):
    """Statische konservative Referenzprüfung; Kernvergleich erfolgt beim Aufrufer."""
    size = len(original); tail = size - cut
    if len(compiled) != size or len(mask) != size or not 0 < tail <= 15 or cut <= 0: return False
    if any(compiled[cut:]) or any(mask[cut:]) or not any(original[cut:]): return False
    if not all((base + size) % 16 == 0 or ((base + size) % 4 == 0 and tail <= 3)
               for base in (orig_base, obj_base)): return False
    if any(orig_base + cut <= p < orig_base + size for p in function_starts): return False
    if any(obj_base + cut <= p < obj_base + size for p in object_starts): return False
    if any(orig_base + cut <= s < orig_base + size or orig_base + cut <= target < orig_base + size
           for s, kind, target in fixups): return False
    if _padding_referenced(original_image, image_base, orig_base + cut, orig_base + size): return False
    if _padding_referenced(object_code, 0, obj_base + cut, obj_base + size): return False
    return True

"""Enger Gegenrichtungsfall: genau ein Original-Nullbyte gegen genau ein NOP.

Vorbedingungen des Aufrufers: gleiche normalisierte Kerne/Kerngrenzen,
abschließendes RET, kein bekannter DATA_TAIL. Vorhandene PAD-Regel unverändert.
"""
# Generiertes reines OMF-Fragment aus omf_extra.py; AST-identisch bis Namenspraefix.
_padomf_LOCSZ = {0: 1, 1: 2, 2: 2, 3: 4, 4: 1, 5: 2, 9: 4, 11: 6, 13: 4}
_padomf_KNOWN_RECORDS = {128, 136, 138, 139, 140, 142, 144, 145, 148, 149, 150, 152, 153, 154, 156, 157, 160, 161, 162, 163, 180, 182, 183, 188, 194, 195, 196, 197, 202, 204}

def _padomf_idx(data, pos):
    if pos >= len(data):
        raise ValueError('OMF-Index fehlt')
    if data[pos] & 128:
        if pos + 1 >= len(data):
            raise ValueError('OMF-Index abgeschnitten')
        return ((data[pos] & 127) << 8 | data[pos + 1], pos + 2)
    return (data[pos], pos + 1)

def _padomf_records(raw):
    pos = 0
    while pos < len(raw):
        if pos + 3 > len(raw):
            raise ValueError('OMF-Kopf abgeschnitten')
        typ, size = struct.unpack_from('<BH', raw, pos)
        end = pos + size + 3
        if not size or end > len(raw):
            raise ValueError('OMF-Satz abgeschnitten')
        rec = raw[pos:end]
        if rec[-1] and sum(rec) & 255:
            raise ValueError('OMF-Prüfsumme falsch')
        yield (typ, rec[3:-1])
        pos = end

def _padomf_fixups(raw):
    """Relokationen mit Eigentümer und konservativer kanonischer Zielidentität.

    Segmentinterne Addenden werden NICHT semantisch umgedeutet. Verschiebt sich
    ein solches Ziel, ist der EXTRA-Körper hier geändert/erneut zu prüfen.
    """
    ln = ['']
    ext = [None]
    segs = {}
    groups = {}
    result = []
    frames = {}
    targets = {}
    cds = {}
    last = None
    recs = list(_padomf_records(raw))
    if not recs or recs[0][0] != 128 or recs[-1][0] not in (138, 139):
        raise ValueError('Genau ein vollständiges OMF-Modul erwartet')
    if sum((t == 128 for t, _ in recs)) != 1:
        raise ValueError('Mehrere OMF-Module')

    def word(data, pos, width):
        if pos + width > len(data):
            raise ValueError('OMF-Zahl abgeschnitten')
        return (int.from_bytes(data[pos:pos + width], 'little'), pos + width)

    def names(data):
        pos = 0
        while pos < len(data):
            size = data[pos]
            pos += 1
            if pos + size > len(data):
                raise ValueError('OMF-Name abgeschnitten')
            yield data[pos:pos + size].decode('latin1')
            pos += size
    for typ, data in recs:
        if typ in (176, 184):
            raise ValueError('%s (0x%02x) verändert EXTDEF-Indizes und wird für EXTRA nicht unterstützt' % ('COMDEF' if typ == 176 else 'LCOMDEF', typ))
        if typ not in _padomf_KNOWN_RECORDS:
            raise ValueError('Nicht unterstützter OMF-Satz 0x%02x; Tabellen-/Alias-/Codewirkung ungeprüft' % typ)
        if typ in (150, 202):
            ln.extend(names(data))
        elif typ in (152, 153):
            pos = 1 + (3 if data[0] >> 5 == 0 else 0)
            _, pos = word(data, pos, 4 if typ & 1 else 2)
            name, pos = _padomf_idx(data, pos)
            cls, pos = _padomf_idx(data, pos)
            overlay, pos = _padomf_idx(data, pos)
            segs[len(segs) + 1] = (ln[name], ln[cls], ln[overlay])
        elif typ == 154:
            name, pos = _padomf_idx(data, 0)
            members = []
            while pos < len(data):
                if data[pos] != 255:
                    raise ValueError('Unbekannter GRPDEF-Eintrag')
                seg, pos = _padomf_idx(data, pos + 1)
                members.append(seg)
            groups[len(groups) + 1] = (ln[name], members)
        elif typ in (140, 180):
            pos = 0
            while pos < len(data):
                size = data[pos]
                pos += 1
                if pos + size > len(data):
                    raise ValueError('EXTDEF abgeschnitten')
                ext.append(data[pos:pos + size].decode('latin1'))
                _, pos = _padomf_idx(data, pos + size)
        elif typ == 188:
            pos = 0
            while pos < len(data):
                ni, pos = _padomf_idx(data, pos)
                ext.append(ln[ni])
                _, pos = _padomf_idx(data, pos)
        elif typ in (160, 161):
            seg, pos = _padomf_idx(data, 0)
            off, pos = word(data, pos, 4 if typ & 1 else 2)
            last = (('seg', seg), off)
        elif typ in (162, 163):
            raise ValueError('LIDATA wird für EXTRA nicht geraten')
        elif typ in (194, 195):
            flags, attr = data[:2]
            if flags & 2:
                raise ValueError('Iterierter COMDAT ungeprüft')
            off, pos = word(data, 3, 4 if typ & 1 else 2)
            _, pos = _padomf_idx(data, pos)
            if attr & 15 == 0:
                group, pos = _padomf_idx(data, pos)
                seg, pos = _padomf_idx(data, pos)
                if not group and (not seg):
                    _, pos = word(data, pos, 2)
            ni, pos = _padomf_idx(data, pos)
            name = ln[ni]
            if not flags & 1:
                cds[name] = cds.get(name, 0) + 1
            if cds.get(name) != 1:
                raise ValueError('Mehrdeutiger COMDAT: ' + name)
            last = (('comdat', name), off)
        elif typ in (156, 157):
            pos = 0

            def datum(method):
                nonlocal pos
                if method < 3:
                    value, pos = _padomf_idx(data, pos)
                    return value
                if method == 3:
                    value, pos = word(data, pos, 2)
                    return value
                if method in (4, 5):
                    return None
                raise ValueError('Unbekannte FIXUPP-Methode')
            while pos < len(data):
                head = data[pos]
                pos += 1
                if not head & 128:
                    method = head >> 2 & (7 if head & 64 else 3)
                    value = datum(method)
                    (frames if head & 64 else targets)[head & 3] = (method, value)
                    continue
                loc = head >> 2 & 15
                if loc not in _padomf_LOCSZ:
                    raise ValueError('Unbekannte FIXUPP-Breite')
                if pos + 2 > len(data):
                    raise ValueError('FIXUPP abgeschnitten')
                offset = (head & 3) << 8 | data[pos]
                desc = data[pos + 1]
                pos += 2
                if desc & 128:
                    frame = frames[desc >> 4 & 3]
                else:
                    method = desc >> 4 & 7
                    frame = (method, datum(method))
                if desc & 8:
                    target = targets[desc & 3]
                else:
                    method = desc & 3
                    target = (method, datum(method))
                disp = 0
                if not desc & 4:
                    disp, pos = word(data, pos, 4 if typ & 1 else 2)
                if last is None:
                    raise ValueError('FIXUPP ohne Dateneigentümer')
                result.append(dict(owner=last[0], offset=last[1] + offset, width=_padomf_LOCSZ[loc], location=loc, relative=not bool(head & 64), frame=frame, target=target, displacement=disp))

    def segment(index):
        value = segs[index]
        if list(segs.values()).count(value) != 1:
            raise ValueError('Mehrdeutige SEGDEF-Identität')
        return value

    def canon(pair):
        method, value = pair
        if method == 0:
            return ('segment', segment(value))
        if method == 1:
            name, members = groups[value]
            return ('group', name, [segment(i) for i in members])
        if method == 2:
            if not value or value >= len(ext):
                raise ValueError('EXTDEF-Index fehlt')
            return ('external', ext[value])
        return ('absolute' if method == 3 else 'location' if method == 4 else 'target', value)
    for entry in result:
        entry['frame'] = canon(entry['frame'])
        entry['target'] = canon(entry['target'])
    return result

def original_zero_nop_allowed(original, compiled, mask, cut, orig_base, obj_base,
                              original_image, image_base, object_code,
                              function_starts, object_starts, original_fixups,
                              model, code_segment, object_publics, object_fixups):
    size = len(original)
    if len(compiled) != size or len(mask) != size or cut <= 0 or size-cut != 1: return False
    if original[cut:] != b'\x00' or compiled[cut:] != b'\x90' or any(mask[cut:]): return False
    if (orig_base+size)%16 or (obj_base+size)%16: return False
    if any(a != b and not m for a,b,m in zip(original[:cut],compiled[:cut],mask[:cut])): return False
    ol,oh = orig_base+cut,orig_base+size
    nl,nh = obj_base+cut,obj_base+size
    if any(ol <= p < oh for p in function_starts) or any(nl <= p < nh for p in object_starts): return False
    if any(s < oh and s+{7:4,5:2,6:6}.get(kind,4) > ol or ol <= target < oh
           for s,kind,target in original_fixups): return False
    if _padding_referenced(original_image,image_base,ol,oh): return False
    if _padding_referenced(object_code,0,nl,nh): return False
    # Die Zusatzregel ist absichtlich nicht für ungeklärte COMDATs zuständig.
    if model['comdats']: return False
    codes = [(i,s) for i,s in model['segs'].items() if s['cls']=='CODE' and s['data']]
    if len(codes)!=1 or codes[0][0]!=code_segment: return False
    if bytes(codes[0][1]['data'])!=bytes(object_code): return False
    for seg in model['segs'].values():
        if bytes(seg['data']).find(struct.pack('<I',nl))>=0: return False
    # Vollständige Relokationsabdeckung; unbekannte Formen nicht erraten.
    covered={i:set() for i in model['segs']}
    pubnames={name:off for off,name in object_publics}
    for fix in object_fixups:
        if fix['owner'][0]!='seg' or fix['owner'][1] not in model['segs']: return False
        si=fix['owner'][1]; seg=model['segs'][si]; p=fix['offset']; width=fix['width']
        if width!=4 or fix['location'] not in (9,13) or p<0 or p+width>len(seg['data']): return False
        covered[si].update(range(p,p+width))
        if si==code_segment and p<nh and p+width>nl: return False
        # Nur unmittelbare externe Symbolziele ohne Addend: kein versteckter
        # Segmentoffset. Unbekannte externe Identitäten erhalten genau die
        # bestehende EXT-Semantik, keine neue Zielgleichheitsbehauptung.
        if fix['target'][0]!='external' or fix['displacement'] or any(seg['data'][p:p+width]): return False
        name=fix['target'][1]
        if name in pubnames and nl<=pubnames[name]<nh: return False
        adr=(re.match(r'^(?:W\?)?[fd]_([0-9a-f]{6})(?:\b|\$)',name)
             or re.match(r'^W\?\$ct:f_([0-9a-f]{6})\$n\(',name))
        if adr and ol<=int(adr[1],16)<oh: return False
    if any(covered[i]!={p for p,b in enumerate(s['mask']) if b} for i,s in model['segs'].items()): return False
    return True

rows=[]; extra=list(_OTHER_CODE_EXTRA)
for k,(of,nm) in enumerate(pubs):
    if re.match(r'^W\?\$Wsi[0-9]+tab\$',nm): continue  # Daten bleiben in offs und byoff, aber nicht in rows/extra
    if any(nm.startswith(p) for p in _CFG.get('code_data_prefixes',[])): continue
    if re.match(r'^W\?\$Wsi[0-9]+t\$n\[\]s\$:\.0\$:\?f_[0-9a-f]{6}',nm): continue
    if k+1<len(pubs) and pubs[k+1][0]==of: continue
    on=offs[offs.index(of)+1] if offs.index(of)+1<len(offs) else n
    s=byoff[of] if of in _AMBIG else sym(nm)
    if not re.match(r'f_[0-9a-f]{6}$',s) and re.match(r'f_[0-9a-f]{6}$',byoff.get(of,'')): s=byoff[of]
    if not re.match(r'f_[0-9a-f]{6}$',s): extra.append((of,s,on-of)); continue
    ad=int(s[2:],16); ko=bisect.bisect_right(FUN,ad); an=FUN[ko] if ko<len(FUN) else ad+(on-of)
    an=_END_OVR.get((LO,ad),an)
    if ad<B or an-B>len(o): rows.append((ad,0,on-of,None,'AUSSERHALB')); continue
    A=dis(a[of:on],of,res_a,True); AA=ADRALL[:]; O=dis(o[ad-va:an-va],ad,res_o); OA=ADRALL[:]
    sm=difflib.SequenceMatcher(None,O,A,autojunk=False); nd=sum(max(i2-i1,j2-j1) for tg,i1,i2,j1,j2 in sm.get_opcodes() if tg!='equal')
    O2=[re.sub(r'^(call|j\w+) \S+$',r'\1 EXT',x) if y.endswith(' EXT') and x.split()[0]==y.split()[0] else x for x,y in zip(O,A)]+O[len(A):]   # Fixup-Ziel im OBJ = Platzhalter (worker: auch jcc)
    W=lambda L:[re.sub(r'^(call|jmp) (?!\+)\S+$',r'\1 *',x) for x in L]   # Befehlszahl: Aufrufziele ausgeblendet
    sm=difflib.SequenceMatcher(None,W(O2),W(A),autojunk=False); nd=sum(max(i2-i1,j2-j1) for tg,i1,i2,j1,j2 in sm.get_opcodes() if tg!='equal')
    if on==n and on-of<an-ad and A==O2[:len(A)] and all(x in ('nop','lea    eax,[eax+0x0]','lea    edx,[edx+0x0]','mov    eax,eax','mov    edx,edx','lea    ecx,[ecx+0x0]','mov    ecx,ecx','lea    ebx,[ebx+0x0]','mov    ebx,ebx') for x in O2[len(A):]): O2=O2[:len(A)]; an=ad+(on-of)
    if on==n and on-of+1==an-ad and A and ENDX.match(A[-1]) and O2[-1:]==['.byte 0'] and A==O2[:-1]:
        O2=O2[:-1]; an=ad+(on-of)  # final linker zero after exact terminal ret
    if on==n and A and ENDX.match(A[-1]) and A==O2[:len(A)] and len(O2)>len(A) and all(x in ('.byte 0','add    BYTE PTR [eax],al') for x in O2[len(A):]) and set(o[ad-va+(on-of):an-va])<={0} and an-(ad+(on-of))<=15 and (an%16==0 or (an%4==0 and an-(ad+(on-of))<=3)): O2=O2[:len(A)]; an=ad+(on-of)  
    gl=(an-ad==on-of) and A==O2
    if not gl and PAD:   
        Ak,ga=kern(A,AA,on-of); Ok,go=kern(O2[:len(OA)],OA,an-ad); gl=(Ak==Ok and ga==go)
        if not JSON and os.environ.get("FSDBG")==hex(ad): print(Ak[-3:],ga,Ok[-3:],go,len(Ak),len(Ok),A[-4:],O2[-4:])
    # Objdump schreibt ein letztes einzelnes Nullbyte als ".byte 0".
    # PADX kennt ".byte 0x0"; nur diese Darstellungsdifferenz eng nachprüfen.
    if not gl and PAD and A[-1:]==['.byte 0'] and (LO,ad) not in DATA_TAIL:
        Az=A[:-1]+['.byte 0x0']; Azk,gaz=kern(Az,AA,on-of)
        Ozk,goz=kern(O2[:len(OA)],OA,an-ad)
        if (Azk==Ozk and gaz==goz and Azk and re.fullmatch(r'ret(?:\s+0x[0-9a-f]+)?',Azk[-1])
                and zero_tail_allowed(img[ad-B:an-B],d[of:on],mk[of:on],gaz,ad,of,
                    img,B,d,FUN,offs,le.fixups)):
            gl=True
    # Separater Gegenrichtungsfall: einzelnes Original-Nullbyte gegen NOP.
    if not gl and PAD and O2[-1:]==['.byte 0'] and (LO,ad) not in DATA_TAIL:
        Ozn=O2[:-1]+['.byte 0x0']; Ozk,goz=kern(Ozn[:len(OA)],OA,an-ad)
        Azk,gaz=kern(A,AA,on-of)
        if Azk==Ozk and gaz==goz and Azk and re.fullmatch(r'ret(?:\s+0x[0-9a-f]+)?',Azk[-1]):
            try:
                _pfix=_padomf_fixups(dd)
            except (ImportError,ValueError,KeyError,IndexError,struct.error):
                _pfix=None  # unbekannte Relokationsbindung: keine Zusatzfreigabe
            if _pfix is not None and original_zero_nop_allowed(img[ad-B:an-B],d[of:on],mk[of:on],gaz,ad,of,
                    img,B,d,FUN,offs,le.fixups,m,_CODE_SEG,pubs,_pfix):
                gl=True
    tail=DATA_TAIL.get((LO,ad))
    if tail and on-of==an-ad+tail and on-tail in AA:
        # Vorher erkannte Befehle behalten ihre Sprungziel-Normalisierung.
        cut=AA.index(on-tail); Ac=A[:cut]; AAc=AA[:cut]
        core,_=kern(Ac,AAc,on-of-tail)
        if core and ENDX.match(core[-1]):
            Oc=[re.sub(r'^(call|j\w+) \S+$',r'\1 EXT',x) if y.endswith(' EXT') and x.split()[0]==y.split()[0] else x for x,y in zip(O,Ac)]+O[len(Ac):]
            smc=difflib.SequenceMatcher(None,W(Oc),W(Ac),autojunk=False)
            ndc=sum(max(i2-i1,j2-j1) for tg,i1,i2,j1,j2 in smc.get_opcodes() if tg!='equal')
            glc=(an-ad==on-of-tail) and Ac==Oc
            if not glc and PAD:
                Ack,gac=kern(Ac,AAc,on-of-tail); Ock,goc=kern(Oc[:len(OA)],OA,an-ad)
                glc=(Ack==Ock and gac==goc)
            if ndc<nd or glc: A,AA,O2=Ac,AAc,Oc  # Diff zeigt den Code ohne Datenrest
            nd=min(nd,ndc)     # eine Datenkorrektur darf keinen Rest erhoehen
            gl=gl or glc       # ein bisheriges GLEICH bleibt GLEICH
    rows.append((ad,an-ad,on-of,nd,'GLEICH' if gl else f'{nd} Befehle'))
    if JSON and ad in TARGETS:
        DIFFS[f'{ad:06x}']='\n'.join(difflib.unified_diff(O2,A,'original','neu',n=2,lineterm=''))
    elif F==ad:
        for l in difflib.unified_diff(O2,A,'original','neu',n=2,lineterm=''): print(l)
seen={r[0] for r in rows}
# Bei registrierten Einheiten alle Originalstarts im Bereich melden, auch vor
# der ersten und nach der letzten OBJ-Funktion. Sonst bleibt eine neu ergaenzte
# Randfunktion im Bestand unsichtbar und wird bei der Uebernahme nicht verglichen.
unit_hi=None
for line in open(_UNITS_TSV):
    cols=line.rstrip('\n').split('\t')
    if len(cols)>=4 and re.fullmatch(r'[0-9a-fA-F]{6}',cols[2]) and int(cols[2],16)==LO:
        unit_hi=int(cols[3],16); break
if unit_hi is None:
    hi=max([r[0] for r in rows]+[LO]); lo=min([r[0] for r in rows if r[0]>=LO]+[hi]); ko=bisect.bisect_left(FUN_ORIG,lo)
else:
    lo=LO; hi=unit_hi; ko=bisect.bisect_left(FUN_ORIG,lo)
for ad in FUN_ORIG[ko:]:
    if (unit_hi is not None and ad>=hi) or (unit_hi is None and ad>hi): break
    if ad not in seen:
        if 0<=ad-B<=len(img)-16 and all(B<=struct.unpack_from('<I',img,ad-B+4*_i)[0]<B+len(img) for _i in range(4)): continue   
        k2=bisect.bisect_right(FUN_ORIG,ad); an=FUN_ORIG[k2] if k2<len(FUN_ORIG) else ad; rows.append((ad,an-ad,0,None,'FEHLT'))
rows.sort(); g=sum(1 for r in rows if r[4]=='GLEICH'); bg=sum(r[1] for r in rows if r[4]=='GLEICH'); bt=sum(r[1] for r in rows)
nah=sum(1 for r in rows if r[3] is not None and 0<r[3]<=10 or (r[3]==0 and r[4]!='GLEICH'))
if JSON:
    import json,t1format
    print(json.dumps(t1format.pack(rows,extra,DIFFS),sort_keys=True))
elif TSV: print(f'{g}\t{len(rows)}\t{bg}\t{bt}\t{nah}\t{len(extra)}')
elif F is None:
    for ad,so,sn,nd,st in rows: print(f'{ad:06X} {so:4d}/{sn:<4d} {st}')
    for of,s,sz in extra: print(f'EXTRA  {s} {sz} B @+{of:x}')
    print(f'{g}/{len(rows)} GLEICH, Bytes {bg}/{bt}, Fast-Treffer(<=10 Bef) {nah}, EXTRA {len(extra)}')
