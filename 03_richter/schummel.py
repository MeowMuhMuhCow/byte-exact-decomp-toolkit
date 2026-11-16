# schummel.py - Secondary inline-assembly / #pragma aux body audit.
# Verdaechtig: #pragma aux NAME = "..." (Inline-Asm-Rumpf), _asm/__asm, _emit/__emit__, db-Bytes.
# Erlaubt: Rumpf steht schon im Bestand derselben Einheit ODER in meta/allowed_pragma.tsv (ein normalisierter Rumpf je Zeile).
#   python3 schummel.py            -> Report over src_p3_dir (alle Asm-Ruempfe, verdaechtige markiert)
#   python3 schummel.py KANDIDAT BESTAND -> neue verdaechtige Stellen des Kandidaten (Exit 1, wenn welche)
import sys,os,re,glob
sys.path.insert(0,os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')))
import project_config as PC
_CFG=PC.load_config()
Q=PC.resolve_path('project_root',_CFG)
ERL=PC.resolve_path('allowed_pragma_tsv',_CFG)
RP=re.compile(r'#pragma\s+aux\s+\w+\s*=\s*((?:"[^"]*"\s*)+)')
RX=re.compile(r'\b(__asm|_asm|__emit__|_emit)\b')
HART=re.compile(r'"\s*(db|dw|dd)\b|"\s*(push|pop|call|jmp|ret)\b',re.I)   # Bytes/Stack/Spruenge im Rumpf: nie automatisch erlaubt
def norm(r): return ' '.join(x.strip().lower() for x in re.findall(r'"([^"]*)"',r) if x.strip()) or '(leer)'
def ruempfe(t):
    t=re.sub(r'//[^\n]*','',t)
    return [norm(m.group(1)) for m in RP.finditer(t)]+[m.group(1) for m in RX.finditer(t)]
def erlaubt():
    try: return set(l.strip() for l in open(ERL,encoding='latin1') if l.strip() and not l.startswith('#'))
    except OSError: return set()
def neu(kand,bestand,erl=None):
    erl=erlaubt() if erl is None else erl; alt=set(ruempfe(bestand or ''))
    return [r for r in ruempfe(kand) if r not in alt and r not in erl]
if __name__=='__main__':
    lies=lambda f: open(f,encoding='latin1').read().replace('\r','')
    if len(sys.argv)==3:
        n=neu(lies(sys.argv[1]),lies(sys.argv[2]) if os.path.exists(sys.argv[2]) else '')
        for r in n: print('NEU VERDAECHTIG:',r)
        sys.exit(1 if n else 0)
    erl=erlaubt(); z={}
    for f in sorted(glob.glob(PC.resolve_path('src_p3_dir', _CFG)+'/*_P1.CPP')):
        for r in ruempfe(lies(f)): z.setdefault(r,[]).append(os.path.basename(f)[:-7])
    for r,us in sorted(z.items(),key=lambda x:-len(x[1])):
        k='ERLAUBT' if r in erl else 'HART' if HART.search('"'+r) else 'offen'
        print(f'{k:8s} {len(us):3d}x  {r[:70]:70s}  {" ".join(sorted(set(us)))[:80]}')
