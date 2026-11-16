# ros.py: lokale Muster-Suche ("Rosetta"). Original-Fenster (Befehlsliste) normalisieren und in allen GLEICH-Funktionen suchen.
import re,sys
def norm(x, regs=False):
    x=re.sub(r'\s+',' ',x.strip())
    x=re.sub(r'^(call|j\w+) 0x[0-9a-f]+$',r'\1 J',x)
    x=re.sub(r'\[esp(\+0x[0-9a-f]+)?\]','[S]',x)
    x=re.sub(r'ds:0x[0-9a-f]+','ds:A',x)
    x=re.sub(r'0x[0-9a-f]+','I',x)
    return x
REG=r'\b(e?[a-d]x|[a-d][lh]|e?si|e?di|e?bp)\b'
FAM={'eax':'a','ax':'a','al':'a','ah':'a','ebx':'b','bx':'b','bl':'b','bh':'b','ecx':'c','cx':'c','cl':'c','ch':'c','edx':'d','dx':'d','dl':'d','dh':'d','esi':'si','si':'si','edi':'di','di':'di','ebp':'bp','bp':'bp'}
def abstr(seq):
    m={}; out=[]
    for x in seq:
        def f(g):
            r=g.group(1); k=FAM[r]
            if k not in m: m[k]='R%d'%len(m)
            return m[k]+'.'+str(len(r))
        out.append(re.sub(REG,f,x))
    return out
ORIG={}
_orig_p=__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),'orig.tsv')
if __import__('os').path.isfile(_orig_p):
    for l in open(_orig_p):
        if not l.strip() or l.startswith('#'): continue
        a,u,st,r=l.rstrip('\n').split('\t'); ORIG[a]=(u,st,r.split('|'))
def suche(fenster, regs=False, nur_gleich=True):
    q=[norm(x) for x in fenster]; L=len(q)
    if regs: q=abstr(q)
    hits=[]
    for a,(u,st,ins) in ORIG.items():
        if nur_gleich and st!='G': continue
        n=[norm(x) for x in ins]
        for i in range(len(n)-L+1):
            w=n[i:i+L]
            if regs: w=abstr(w)
            if w==q: hits.append((a,u,i)); break
    return hits
if __name__=='__main__':
    a=sys.argv[1]; i1,i2=int(sys.argv[2]),int(sys.argv[3])
    f=ORIG[a][2][i1:i2]; print('\n'.join(f))
    for regs in (False,True):
        h=suche(f,regs); print('regs abstrakt' if regs else 'exakt', len(h), ' '.join('f_%s(%s)@%d'%x for x in h[:12]))
