"""kern123.py - Restricted C subset parser for local declaration and macro-hazard analysis."""
import re

NAME = r'[A-Za-z_]\w*'
TYPES = r'(?:unsigned short|unsigned char|signed char|unsigned int|unsigned long|short|char|int|long|unsigned)'
WIDTH = {'char':1,'signed char':1,'unsigned char':1,'short':2,'unsigned short':2,
         'int':4,'long':4,'unsigned':4,'unsigned int':4,'unsigned long':4}


def fresh(lines, stem):
    source='\n'.join(lines);name=stem;i=0
    while re.search(r'\b'+re.escape(name)+r'\b',source):
        i+=1;name=stem+'_'+str(i)
    return name


def plain(line):
    return not any(c in line for c in ('"', "'", '#', '//', '/*', '*/', '\\'))


def rename(line, mapping):
    """Keine Felder, Literale oder Kommentare umschreiben."""
    if not plain(line):
        if any(re.search(r'\b'+re.escape(k)+r'\b',line) for k in mapping):
            raise ValueError('Name in Kommentar/Makro/Literal')
        return line
    return re.sub(r'(?<![\w.>])('+ '|'.join(map(re.escape,mapping))+r')\b',
                  lambda m:mapping[m[0]],line)


def split_args(text):
    result=[];depth=0;start=0
    for i,c in enumerate(text):
        if c in '([':depth+=1
        elif c in ')]':depth-=1
        elif c==',' and depth==0:result.append(text[start:i].strip());start=i+1
        if depth<0:raise ValueError('Klammern')
    if depth:raise ValueError('Klammern')
    return result+[text[start:].strip()]


def declarations(lines, block):
    """Eindeutige lokale Skalare/Zeiger; keine Qualifizierer und Schatten."""
    out={}
    for j in range(block['start']+1,block['ende']):
        m=re.fullmatch(r'(\s*)('+TYPES+r')(\s*\*\s*|\s+)('+NAME+r')(?:\s*=\s*([^;]+))?;\s*',lines[j])
        if m:
            ind,t,star,n,init=m.groups();t=t+(' *' if '*' in star else '')
            if n in out:raise ValueError('Verdeckte lokale Variable')
            out[n]=(t,j,init,ind)
    return out


def type_width(t):
    return 4 if t.endswith('*') else WIDTH[t]


def bindings(lines,block):
    """Konservative Deklarationsbindungen, einschliesslich unbekannter Typen."""
    source='\n'.join(lines[block['start']+1:block['ende']]);result={}
    pattern=re.compile(r'(?:^|(?<=[;{}])|\bfor\s*\()\s*((?:(?:const|volatile|static|register|struct|class)\s+)*(?:(?:unsigned|signed)\s+)?\w+)\s+([^;{}]+);',re.M)
    for match in pattern.finditer(source):
        typ,items=match.groups()
        if typ.split()[0] in ('return','delete','goto','throw','else'):continue
        for part in items.split(','):
            lhs=part.split('=',1)[0].strip();m=re.fullmatch(r'([*&]*\s*)('+NAME+r')(\s*(?:\[[^]]*\]|\([^;]*\)))?',lhs)
            if m:
                ptr,name,arr=m.groups();result.setdefault(name,[]).append((typ,ptr.strip(),arr))
    return result


def macro_hazards(lines,block,names):
    """Freie Namen in tatsaechlich benutzten Makros; Formalparameter sind lokal."""
    macros={};i=0
    while i<len(lines):
        line=lines[i];i+=1
        while line.endswith('\\') and i<len(lines):line=line[:-1]+' '+lines[i];i+=1
        m=re.match(r'^\s*#\s*define\s+('+NAME+r')(?:\(([^)]*)\))?\s*(.*)',line)
        if m:macros[m[1]]=(set(re.findall(NAME,m[2] or '')),m[3])
    def identifiers(text):
        text=re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*',' ',text,flags=re.S)
        return set(re.findall(r'(?<![\w.>])'+NAME+r'\b',text))
    used=identifiers('\n'.join(lines[block['start']+1:block['ende']]))&set(macros)
    todo=list(used);visited=set();hazards=set(names)&set(macros)
    while todo:
        name=todo.pop()
        if name in visited:continue
        visited.add(name);params,body=macros[name];free=identifiers(body)-params
        hazards.update(free&set(names));todo.extend(free&set(macros)-visited)
    return hazards


def region_ok(lines,block,names):
    """Kein eigener Praeprozessor oder uneindeutiges Namensbinding."""
    text='\n'.join(lines[block['start']+1:block['ende']])
    if re.search(r'\b(?:asm|__asm|goto|class|struct|union|typedef)\b',text):return False
    if any(not plain(l) for l in lines[block['start']+1:block['ende']] if l.strip()):return False
    if macro_hazards(lines,block,names):return False
    for name in names:
        if re.search(r'\b(?:const|volatile)\s+[^;{}]*\b'+re.escape(name)+r'\b',text):return False
    return True


def apply(lines, changes):
    result=[]
    for i,line in enumerate(lines):
        if ('ins',i) in changes:result.extend(changes[('ins',i)].splitlines())
        result.extend(changes.get(i,line).splitlines())
    return result
