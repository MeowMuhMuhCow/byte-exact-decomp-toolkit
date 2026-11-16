# sperre.py - Atomic per-unit file lock and MD5 optimistic concurrency guard.
# sondern der Kandidat nach conflict/<origin>/ gelegt; kreislauf.sh/zusammen.py nimmt ihn spaeter funktionsweise auf.
import os,fcntl,hashlib,time
def norm(t): return t.replace('\r','')
def md5(t): return hashlib.md5(norm(t).encode('latin1','replace')).hexdigest()
def lese_md5(f):
    try: return md5(open(f,encoding='latin1').read())
    except FileNotFoundError: return None
def schreibe(Q,U,text,fstand,erwartet,herkunft,ziel_dir='p3'):
    """erwartet = md5 des Bestands, auf dem der Kandidat beruht (None = Datei existierte nicht). -> (True, neuer_md5) oder (False, Konfliktpfad)."""
    if os.environ.get('R3_ZIELPRUEFUNG','0')=='1' and ziel_dir=='p3':
        import importlib.util,sys
        key='_decomp_r3_gate_live'
        if key not in sys.modules:
            spec=importlib.util.spec_from_file_location(key,os.path.join(Q,'Werkzeuge','phase4','r3_gate.py'))
            module=importlib.util.module_from_spec(spec);sys.modules[key]=module;spec.loader.exec_module(module)
        certificate=sys.modules[key].certify(Q,U,text,expected_stand=fstand,stage='p3:'+herkunft)
        if not certificate['allowed']:
            return False,'R3_ABGELEHNT: '+','.join(certificate['bad'])
        if fstand is None:fstand=certificate['fstand']
    sys.path.insert(0,os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')))
import project_config as PC
_lkdir=PC.resolve_path('lock_dir')
os.makedirs(_lkdir,exist_ok=True)
    d=os.path.join(PC.resolve_path('src_dir', _CFG), ziel_dir); os.makedirs(d,exist_ok=True); f=f'{d}/{U}_P1.CPP'
    with open(f'{_lkdir}/{U}.lock','w') as lk:
        fcntl.flock(lk,fcntl.LOCK_EX)
        if lese_md5(f)!=erwartet:
            k=os.path.join(PC.resolve_path('logs_dir', _CFG), 'conflict', herkunft); os.makedirs(k,exist_ok=True); kf=f'{k}/{U}_P1.CPP'
            open(kf,'w',newline='\r\n',encoding='latin1',errors='replace').write(norm(text))
            open(os.path.join(PC.resolve_path('logs_dir', _CFG), 'conflict', 'conflicts.tsv'),'a').write(f'{time.strftime("%d.%m. %H:%M:%S")}\t{U}\t{herkunft}\n')
            return False,kf
        tmp=f'{d}/.{U}_P1.{os.getpid()}.tmp'; open(tmp,'w',newline='\r\n',encoding='latin1',errors='replace').write(norm(text)); os.replace(tmp,f)
        if fstand is not None:
            tf=f'{d}/.{U}_P1.{os.getpid()}.ftmp'; open(tf,'w').write(fstand); os.replace(tf,f'{d}/{U}_P1.fstand')
        return True,md5(text)
