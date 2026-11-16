# aehnlich_b.py (worker, 08.11.2026): ZWEITES Aehnlichkeitsmass fuer Schwestern (Lewis "Long Tail": zwei Masse parallel,
# sie waehlen zu ~90 % verschiedene Spitzenkandidaten). aehnlich5.py misst die Befehlsfolge; dieses hier misst, WAS die Funktion
# benutzt und WIE sie gebaut ist: 0.4 * Jaccard(aufgerufene Funktionen) + 0.3 * Jaccard(benutzte globale Adressen)
# + 0.3 * Kosinus(Befehlshistogramm). Nur GELOESTE (GLEICH) Vorlagen, Groesse 1/3..3x. 0 Tokens, lokal.
# Aufruf: python3 aehnlich_b.py [FSTAND_DIR] -> logs/similar_b.tsv (gleiches Format wie aehnlich5.tsv)
import os, re, sys, glob, subprocess, bisect, collections, math
Q6 = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
H = os.path.expanduser('~'); H = H + '/target' if os.path.isdir(H + '/target/gw') else H
FS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PC.resolve_path('logs_dir', _CFG), 'live_fstand')
import project_config as PC; _CFG=PC.load_config(); img=PC.resolve_path('flat_bin',_CFG); dump=os.path.join(PC.resolve_path('tmp_dir',_CFG,'/tmp'),'target_objdump.txt')
if not os.path.exists(dump):
    os.makedirs(os.path.dirname(dump), exist_ok=True)
    open(dump, 'w').write(subprocess.run(['objdump', '-D', '-b', 'binary', '-mi386', '-Mintel', '--no-show-raw-insn', '--adjust-vma=0x10000', img], capture_output=True, text=True).stdout)
ins = {}
for l in open(dump, errors='replace'):
    m = re.match(r'\s*([0-9a-f]+):\s+(\S+)\s*(.*)', l)
    if m: ins[int(m.group(1), 16)] = (m.group(2), m.group(3))
adr = sorted(ins)
fk = {}
for f in glob.glob(FS + '/*.fstand'):
    u = os.path.basename(f)[:-7]
    for l in open(f, errors='replace'):
        m = re.match(r'([0-9A-F]{6})\s+(\d+)/(\d+)\s+(GLEICH|(\d+) Befehle)', l.strip())
        if m: fk[(u, int(m.group(1), 16))] = (int(m.group(2)), 0 if m.group(4) == 'GLEICH' else int(m.group(5)))
def merkmale(a, n):
    i = bisect.bisect_left(adr, a); calls = set(); glob_ = set(); hist = collections.Counter()
    while i < len(adr) and adr[i] < a + n:
        op, arg = ins[adr[i]]; hist[op] += 1
        if op.startswith('call'):
            m = re.match(r'(0x[0-9a-f]+)', arg)
            if m: calls.add(int(m.group(1), 16))
        for g in re.findall(r'(?:ds:|\[)(0x[0-9a-f]{4,})', arg):
            v = int(g, 16)
            if v >= 0x10000: glob_.add(v)
        i += 1
    return calls, glob_, hist
M = {k: merkmale(k[1], v[0]) for k, v in fk.items() if v[0] >= 16}
# sehr haeufige Ziele (Hilfsfunktionen, die jeder ruft) tragen kaum Information -> raus
hc = collections.Counter(c for k in M for c in M[k][0]); hg = collections.Counter(g for k in M for g in M[k][1])
for k in M:
    c, g, h = M[k]; M[k] = ({x for x in c if hc[x] < 300}, {x for x in g if hg[x] < 300}, h, math.sqrt(sum(v * v for v in h.values())) or 1)
def jac(a, b): return len(a & b) / len(a | b) if (a or b) else 0.0
def kos(a, b): return sum(v * b[0].get(o, 0) for o, v in a[0].items()) / (a[1] * b[1])
gl = [k for k in M if fk[k][1] == 0]; of = [k for k in M if fk[k][1] > 0]
AUS = os.environ.get('AB_AUS', Q6 + '/logs/similar_b.tsv')
out = open(AUS + '.neu', 'w')
out.write('einheit\tfkt\tbytes\trest' + ''.join('\tv%d_einheit\tv%d_fkt\tv%d_aehnl' % (i, i, i) for i in range(1, 6)) + '\n')
for k in sorted(of, key=lambda k: -fk[k][0]):
    c, g, h, nh = M[k]; L = fk[k][0]; sc = []
    for o in gl:
        if not (L / 3 <= fk[o][0] <= L * 3): continue
        c2, g2, h2, nh2 = M[o]
        s = 0.4 * jac(c, c2) + 0.3 * jac(g, g2) + 0.3 * kos((h, nh), (h2, nh2))
        sc.append((s, o))
    sc.sort(reverse=True)
    z = [k[0], 'f_%06x' % k[1], str(L), str(fk[k][1])]
    for s, o in sc[:5]: z += [o[0], 'f_%06x' % o[1], '%.2f' % s]
    out.write('\t'.join(z) + '\n')
out.close(); os.replace(AUS + '.neu', AUS); print('offen', len(of), 'geloest', len(gl))
