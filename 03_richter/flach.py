# flach.py IN.OBJ OUT.OBJ [DROP=name1,name2] - Flatten code COMDATs behind _TEXT in WLINK 10.6 reverse order (16-byte aligned, 0x00 padded).
import sys,struct
src,dst=sys.argv[1],sys.argv[2]; WEG=set(sys.argv[3].split(',')) if len(sys.argv)>3 else set()
raw=open(src,'rb').read(); recs=[]; i=0
while i<len(raw):
    t=raw[i]; L=struct.unpack_from('<H',raw,i+1)[0]; recs.append([t,bytearray(raw[i+3:i+2+L])]); i+=3+L
def idx(c,j): return (c[j],j+1) if c[j]<0x80 else (((c[j]&0x7f)<<8)|c[j+1],j+2)
def eidx(v): return bytes([v]) if v<0x80 else bytes([0x80|(v>>8),v&0xff])
lnames=['']; segs=[None]; text=None; cds={}; order=[]; keep=[]; cur=None
for t,c in recs:
    if t==0x96:
        j=0
        while j<len(c): n=c[j]; lnames.append(c[j+1:j+1+n].decode('latin1')); j+=1+n
    if t in (0x98,0x99):
        acbp=c[0]; j=1+(3 if (acbp>>5)==0 else 0)
        ln=struct.unpack_from('<I' if t==0x99 else '<H',c,j)[0]; lp=j; j+=4 if t==0x99 else 2
        sn,j=idx(c,j); cn,j=idx(c,j); segs.append([lnames[sn],lnames[cn],ln,len(keep),lp,t])
        if lnames[sn]=='_TEXT': text=len(segs)-1
    if t in (0xC2,0xC3):
        fl=c[0]; attr=c[1]; j=3; off=struct.unpack_from('<I' if t==0xC3 else '<H',c,j)[0]; j+=4 if t==0xC3 else 2
        ti,j=idx(c,j); s=None
        if (attr&0x0f)==0:
            g,j=idx(c,j); s,j=idx(c,j)
            if g==0 and s==0: j+=2
        ni,j=idx(c,j); nm=lnames[ni]
        if s==text and s is not None:
            if nm not in cds: cds[nm]=[]; order.append(nm)
            cur=cds[nm]; cur.append([off,bytes(c[j:]),[]]); continue
        cur=None
    elif t in (0x9C,0x9D) and cur is not None:
        cur[-1][2].append((t,bytes(c))); continue
    elif t in (0xA0,0xA1,0xA2,0xA3): cur=None
    keep.append([t,c])
mend=[k for k in keep if k[0] in (0x8A,0x8B)]; keep=[k for k in keep if k[0] not in (0x8A,0x8B)]
base=segs[text][2]; out=[]; pubs=[]
for nm in reversed(order):
    if nm in WEG: continue
    base=(base+15)&~15; ln=0
    for off,data,fx in cds[nm]:
        out.append([0xA1,bytearray(eidx(text)+struct.pack('<I',base+off)+data)])
        for ft,fc in fx: out.append([ft,bytearray(fc)])
        ln=max(ln,off+len(data))
    pubs.append((nm,base)); base+=ln
# _TEXT-Laenge anpassen
s=segs[text]; c=keep[s[3]][1]
if s[5]==0x99: struct.pack_into('<I',c,s[4],base)
else: struct.pack_into('<H',c,s[4],base)
pb=bytearray(b'\x00'+eidx(text))
for nm,o in pubs: b=nm.encode('latin1'); pb+=bytes([len(b)])+b+struct.pack('<I',o)+b'\x00'
recs2=keep+out+([[0x91,pb]] if pubs else [])+mend
w=bytearray()
for t,c in recs2: w+=bytes([t])+struct.pack('<H',len(c)+1)+bytes(c)+b'\x00'
open(dst,'wb').write(w)
print(f'flach: {len(pubs)} COMDATs ins _TEXT gelegt, _TEXT jetzt {base:#x}: '+', '.join(f'{n}@{o:#x}' for n,o in pubs),file=sys.stderr)
