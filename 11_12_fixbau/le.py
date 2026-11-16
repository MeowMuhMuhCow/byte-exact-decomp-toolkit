import struct
def lade(b):
    """b = inneres MZ+LE (ohne DOS/4GW-Vorspann). Liefert objs, fixups[(srcobj,srcoff,tgtobj,tgtoff,typ)]"""
    le=struct.unpack_from('<I',b,0x3c)[0]; H=lambda o,f='<I':struct.unpack_from(f,b,le+o)[0]
    npages=H(0x14); pagesize=H(0x28); objtab=le+H(0x40); nobj=H(0x44); pmap=le+H(0x48)
    fpt=le+H(0x68); frt=le+H(0x6c); datapages=H(0x80); lastpage=H(0x2c)
    objs=[]
    for i in range(nobj):
        vsize,base,flags,pidx,pcnt,_=struct.unpack_from('<6I',b,objtab+24*i); objs.append(dict(vsize=vsize,base=base,flags=flags,pidx=pidx,pcnt=pcnt))
    fpt_e=[struct.unpack_from('<I',b,fpt+4*i)[0] for i in range(npages+1)]
    def page2obj(p):
        for i,o in enumerate(objs):
            if o['pidx']<=p+1<o['pidx']+o['pcnt']: return i,(p+1-o['pidx'])*pagesize
    fx=[]
    for p in range(npages):
        oi,poff=page2obj(p); q=frt+fpt_e[p]; end=frt+fpt_e[p+1]
        while q<end:
            src=b[q]; flg=b[q+1]; q+=2
            if src&0x20: cnt=b[q]; q+=1; offs=None
            else: offs=[struct.unpack_from('<h',b,q)[0]]; q+=2
            if flg&3!=0: raise Exception('nur interne Fixups erwartet %x'%flg)
            if flg&0x40: to=b[q]|(b[q+1]<<8); q+=2
            else: to=b[q]; q+=1
            if (src&0xf)==2: toff=None
            elif flg&0x10: toff=struct.unpack_from('<I',b,q)[0]; q+=4
            else: toff=struct.unpack_from('<H',b,q)[0]; q+=2
            if offs is None:
                offs=[struct.unpack_from('<h',b,q+2*k)[0] for k in range(cnt)]; q+=2*cnt
            for s in offs: fx.append((oi+1,poff+s,to,toff,src&0xf))
    return dict(objs=objs,fx=fx,pagesize=pagesize,datapages=datapages,pmap=pmap,npages=npages,b=b,lastpage=lastpage)
def objdaten(L,i):
    """Bytes eines Objekts (1-basiert) aus den Datenseiten"""
    b=L['b']; o=L['objs'][i-1]; ps=L['pagesize']; out=bytearray()
    for k in range(o['pcnt']):
        p=o['pidx']-1+k; off=L['datapages']+p*ps
        n=ps if p<L['npages']-1 else L['lastpage']
        out+=b[off:off+n]
    out+=bytes(max(0,o['vsize']-len(out))); return bytes(out[:o['vsize']])
