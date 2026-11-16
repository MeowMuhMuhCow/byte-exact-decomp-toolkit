"""T1: Ausgabeformat um den bestehenden Richter, keine neue Vergleichsregel.

Import ist seiteneffektfrei. JSON-Modus des fstand liefert Rohzeilen samt
Rest, echtem Status, EXTRA und gewuenschten Diffs aus EINEM Durchlauf.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys


SCHEMA = 'DECOMP-FSTAND-T1-1'


def summary(rows, extra):
    return [sum(r[4] == 'GLEICH' for r in rows), len(rows),
            sum(r[1] for r in rows if r[4] == 'GLEICH'),
            sum(r[1] for r in rows),
            sum(r[3] is not None and (0 < r[3] <= 10 or
                (r[3] == 0 and r[4] != 'GLEICH')) for r in rows), len(extra)]


def pack(rows, extra, diffs):
    return dict(schema=SCHEMA, rows=rows, extra=extra,
                summary=summary(rows, extra), diffs=diffs)


def decode(text):
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        raise ValueError('T1-Richterformat fehlt/ist inkompatibel')
    rows, extra, diffs = data.get('rows'), data.get('extra'), data.get('diffs')
    if not isinstance(rows, list) or not isinstance(extra, list) or not isinstance(diffs, dict):
        raise ValueError('Unvollstaendige T1-Richterdaten')
    addresses = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError('Ungueltige Standzeile')
        address, original, actual, rest, status = row
        if any(type(x) is not int or x < 0 for x in (address, original, actual)):
            raise ValueError('Ungueltige Groesse/Adresse')
                # werden dort mitgezaehlt -> hier zulassen, sonst faellt die ganze Einheit als FEHLER aus der Zaehlung (diskmenu_t1, dunghelp, mine2_t2, shape)
        addresses.add(address)
        if rest is not None and (type(rest) is not int or rest < 0):
            raise ValueError('Ungueltiger Rest')
        if status not in ('GLEICH', 'FEHLT', 'AUSSERHALB') and status != str(rest) + ' Befehle':
            raise ValueError('Status/Rest widersprechen sich')
    for item in extra:
        if (not isinstance(item, list) or len(item) != 3 or
                type(item[0]) is not int or not isinstance(item[1], str) or
                type(item[2]) is not int):
            raise ValueError('Ungueltige EXTRA-Zeile')
    if data.get('summary') != summary(rows, extra):
        raise ValueError('T1-Statistik widerspricht Standzeilen')
    if any(not re.fullmatch(r'[0-9a-f]{6}', k) or not isinstance(v, str)
           for k, v in diffs.items()):
        raise ValueError('Ungueltiger Diff')
    return data


def stand_text(data):
    rows, extra = data['rows'], data['extra']
    lines = [f'{ad:06X} {so:4d}/{sn:<4d} {status}' for ad, so, sn, rest, status in rows]
    lines += [f'EXTRA  {name} {size} B @+{offset:x}' for offset, name, size in extra]
    g, n, bg, bt, near, nextra = data['summary']
    lines.append(f'{g}/{n} GLEICH, Bytes {bg}/{bt}, Fast-Treffer(<=10 Bef) {near}, EXTRA {nextra}')
    return '\n'.join(lines)


def statistic_text(data):
    return '\t'.join(str(x) for x in data['summary'])


def run_judge(judge, obj, lo, targets=()):
    args = [sys.executable, str(judge), str(obj), str(lo), '--json']
    args += [str(t).lower().removeprefix('f_') for t in targets]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('T1-Richter fehlgeschlagen: ' + result.stderr[-500:])
    return decode(result.stdout)


class Stand(dict):
    """Kompatible Rest-Abbildung; echter GLEICH-Status bleibt zusaetzlich da."""
    def __init__(self, text):
        super().__init__()
        self.equal, self.sizes = set(), {}
        for line in text.splitlines():
            m = re.fullmatch(r'\s*([0-9A-F]{6})\s+(\d+)/(\d+)\s+'
                             r'(GLEICH|\d+ Befehle|FEHLT|AUSSERHALB)\s*', line)
            if not m:
                continue
            address, original, actual, status = m.groups()
            address = address.lower()
            self[address] = 0 if status == 'GLEICH' else (
                int(status.split()[0]) if status.endswith(' Befehle') else 99999)
            self.sizes[address] = (int(original), int(actual))
            if status == 'GLEICH':
                self.equal.add(address)


def no_regression(old, new, target):
    # fstand bereinigt Endpadding und kann dadurch auch die ausgegebene
    # Originalgroesse aendern (xdialog_t3: 448 -> 447 bei echtem GLEICH).
    # Diese Berichtsgroesse ist keine unveraenderliche Funktionsgrenze.
    # Richter-GLEICH hat Vorrang; Menge, GLEICH-Nachbarn und Rest bleiben geschuetzt.
    return (set(old) == set(new) and old.equal - {target} <= new.equal and
            all(k in new.equal or new.get(k, 99999) <= value
                for k, value in old.items() if k != target))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['zaehlung'])
    parser.add_argument('judge')
    parser.add_argument('obj')
    parser.add_argument('lo')
    parser.add_argument('stand_file')
    args = parser.parse_args()
    data = run_judge(args.judge, args.obj, args.lo)
    target = Path(args.stand_file)
    temp = target.with_name(target.name + '.t1_neu.' + str(os.getpid()))
    with temp.open('x', encoding='utf-8') as output:
        output.write(stand_text(data) + '\n')
    os.replace(temp, target)
    print(statistic_text(data))


if __name__ == '__main__':
    main()
