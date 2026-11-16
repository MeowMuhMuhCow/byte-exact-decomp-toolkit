# Werkzeugkasten zur bytegleichen Rekonstruktion (Watcom C/C++ 10.6 & x86/DOS)

Eigenständiger, projektneutraler Werkzeugkasten zur **100 % bytegleichen Rekonstruktion von C/C++-Quelltext** aus unveränderten historischen Binärdateien (32-Bit Watcom C/C++ 10.6 `LE`/`OMF` DOS/4GW-Programme sowie 16-Bit `MZ`/`OMF`-Unterstützung) mit exaktem Compiler-Richter, modellübergreifendem Blind-Neubau, waagerechter Rekombination (Mischer & Phase R), senkrechtem Layern, bit-exaktem Compilermodell (`regforce`, `orakel`, zweistufigem ShellSort-Löser), Form-Ratschen-Entkrückung, schaltergesteuerten Bugfixes und urheberrechtsfreien `NDP2`-Binär-Patches.

Für die theoretischen Grundlagen und Messwerte („das Warum“) siehe die Methoden-Beschreibung.

---

## 1. Zweck & Clean-Room-Grundsätze

Ausgehend von einer unveränderten Original-EXE (`Original/TARGET.EXE`) und dem historischen Compiler (`Compiler/`) bildet dieser Werkzeugkasten die gesamten 13 Schritte des Verfahrens ab:
1. **Null fremde/proprietäre Bytes im Repository:** Keine Compiler-Binaries, keine Spiel-EXEs, keine `.OBJ`/`.LIB`-Dateien und keine projektspezifischen Tabellen.
2. **Zentrale Konfiguration (`project.json`):** Alle Skripte lesen Pfade, Binär-Offsets und Tabellen-Ausschlüsse aus einer einzigen Datei `project.json` (über `project_config.py`, überschreibbar per `DECOMP_PROJECT_CONFIG=/pfad/zu/project.json`).
3. **Exakte Prüfung auf jeder Stufe:** Generatoren bewerten sich nie selbst; statischer Pförtner (`pfoertner.py`), eingefrorener symbolbasierter OMF-Richter (`fstand.py`) und Gesamtbau-Relokationsprüfer (`bauen.py`) sichern regressionsfreie Schritte bis zur 100 % identischen Prüfsumme (MD5/SHA-256).

---

## 2. Installation & Voraussetzungen

- **Python 3.10+** (reine Standardbibliothek für Richter, Pförtner, Gesamtbau, Entkrücker, Binär-Prüfer und `NDP2`-Patcher).
- **Optionale Python-Pakete** für den In-Process-Compiler-Emulator (`01_werkzeugkette/` und `08_compilermodell/`):
  ```bash
  pip install -r requirements.txt
  ```
- **Node.js (`node`):** Standard-Laufzeitumgebung (keine npm-Pakete nötig) für den zweistufigen ShellSort-Löser (`08_compilermodell/watcom106_shellsort_solver.js`).
- **Systemwerkzeuge (vom Nutzer bereitzustellen):**
  - Historischer Compiler (z. B. Watcom C/C++ 10.6 `WPP386.EXE`, `WCC386.EXE`, `WASM.EXE`, `WLINK.EXE`) unter `Compiler/`.
  - `objdump` (GNU binutils) für die lineare Disassemblierung in `03_richter/` und `11_12_fixbau/`.
  - `dosbox` für den `WLINK`-Linklauf und Starttests.
  - `Ghidra` (optional) für den Headless-Erstexport in `02_basis/ghidra/`.

---

## 3. Konfiguration (`project.json`)

Alle Pfade und Binärparameter werden zentral in `project.json` eingetragen (oder per Umgebungsvariable `export DECOMP_PROJECT_CONFIG=/pfad/zu/meiner_config.json` übergeben).

---

## 4. Ablauf entlang der Kochrezept-Schritte (Ordner `01` – `13`)

### `01_werkzeugkette/` — Schritt 1: Originalwerkzeugkette bestimmen und im Emulator ausführen
- Compiler-ISOs entpacken (`iso.py`), Laufzeitbibliotheken `.LIB` gegen das Ziel-Binary abgleichen (`lib_version_match.py`), Watcom `WPP386.EXE` / `WCC386.EXE` deterministisch in Unicorn ausführen (`emu106.py`, `comp.py` in `2–4 s` je Einheit) und Compiler-Schalter je Einheit testen (`flag_sweep.py`).

### `02_basis/` — Schritt 2: Reassemblierbare Ausgangsbasis, Schnitt & Ghidra-Headless-Export
- `LE`- (32-Bit) und `MZ`-Header (16-Bit) samt Relokationen parsen (`le.py`), flaches Speicherabbild bauen (`mkimg.py`), Funktions- und Einheitsgrenzen schneiden (`zerleg.py`, `zerleg2.py`, `grenzen.py`), symbolischen `WASM`-Basis-Assembler erzeugen (`genasm2.py`) und per Headless-Ghidra (`ghidra/TargetSetup.java`, `TargetParams.java`, `TargetDecomp.java`) `__watcall`-Signaturen und erste C-Rohentwürfe exportieren.

### `03_richter/` — Schritt 3: Eingefrorener Richter, Pförtner & Ratsche
- Statischer Vorfilter gegen Inline-ASM, Rohbytes, unerlaubte `#pragma aux`-Klauseln und geänderte Fremdprototypen (`pfoertner.py`, `schummel.py`).
- Symbolweiser OMF-Vergleich (`fstand.py` + `flach.py`), registerblinde Abschnitts-Lupe (`abschnitt.py` / `PROBE_ABSCHNITT=1`), Ursachen-Diagnose (`diagnose.py`), 3-Slot-Sperrwarteschlange mit SHA-256-Belegen (`probe_queue.py`) und abstandsgekoppelte Ratsche / Form-Ratsche (`uebernahmeschutz.py`, `sperre.py`, `uebernahme.py`).

### `04_trichter/` — Schritt 4: Arbeit aufteilen nach Kosten, Trichterstufe und Funktionsgröße
- Automatische Zuteilung nach `Core` und Befehlszahl (`verteiler.py`), Versuchsgedächtnis nach dem **Kreislauf der Frische** (`frisch.py`: jede Senkung des `Rest` macht die Funktion wieder frisch für alle Werkzeuge) und Echtzeit-Arbeiterübersicht (`laeuft.py`).

### `05_blind/` — Schritt 5: Gedächtnislose blinde Entwürfe vieler Modellfamilien
- Entfernt die defekte Zielfunktion aus der Arbeitskopie (`blind_template.py`) und startet modellneutrale Blind-Neubauten (`run_blind_draft.sh`) bzw. schlanke Einzelaufträge (`PROMPT_SLIM.txt`, `~4,6k` Zeichen ohne Altlasten-Akten), wobei alle Zwischenfassungen (`v001.cpp`, `v002.cpp`, ...) für den Mischer archiviert werden.

### `06_mischer_layern/` — Schritt 6: Waagerechte Rekombination (Mischer & Phase R) und senkrechtes Layern
- Kreuzt homologe Blöcke in Original-Befehlskoordinaten mit automatischer Übernahme fehlender Spender-Deklarationen und wählt per **Phase R** (Ridge-Regression, Log-Odds-Assoziation und Intervall-DP in `mischer_o14.py`) optimale überlappungsfreie Token-Hunks.
- Friert passende Abschnitte ein und schreibt einzelne fehlerhafte Fenster senkrecht neu (`layer_window.sh`).

### `07_mutator_schwestern/` — Schritt 7: Schwestern, Transplantat, Rosetta und Mutatoren
- Zwei komplementäre Schwestern-Maße (`aehnlich.py`: Befehlsfolge Metrik A; `aehnlich_b.py`: Aufrufe/Globale/Befehlsprofil Metrik B), mechanisches Körper-Transplantat (`transplant.py`), `Rosetta`-3-Befehls-Fenstersuche (`rsuch.py` / `ros.py`), Demo-Zuordnung (`demo_zuordnung.py`) sowie Mutator und Variantenmaschine (`mutator.py`, `vmasch.py`, `operatoren.py`, `beam.py`).

### `08_compilermodell/` — Schritt 8: Compiler-Entscheidungen modellieren, `regforce` / `orakel` und Geister-Löser
- Wenn der strukturelle Kern steht (`Core = 0`) und nur noch Register-, Stapel- oder Befehlsreihenfolge-Gleichstände („Wachs“) offen sind:
  - **`regforce.py` (Registerbelegung im Emulator erzwingen):** Hängt sich in `WPP386.EXE` und `WCC386.EXE` direkt an `GiveBestReg` (`0x93BC8` / `0x61488`) und `CountRegMoves` (`0x93744` / `0x61004`). Ohne Schalter protokolliert es für jeden Konfliktknoten alle Kandidatenregister, deren Move-Savings-Punkte und Gleichstände. Mit `--zwing K REG` (z. B. `--zwing 3 ECX`, um beim 3. Aufruf einen Tabellenindex von `EDX` nach `ECX` zu zwingen) überschreibt es die Bewertung im Emulator und misst sofort mit `fstand.py`, ob der Befehlsabstand `Rest` fällt oder `0` (`GLEICH`) erreicht. Mit `--alle` (bzw. `--alle --weit`) probiert es alle Alternativen parallel durch.
  - **`orakel.py` (Listen-Orakel für Stapel & Konflikte):** Erzwingt alternative Stapel- (`--stapel`) oder Konfliktlisten-Reihenfolgen (`--register`) im Emulator und berechnet rückwärts, welche Einzel- oder Paarzüge (`WEG`, `DAZU`, `SCHIEBEN`) an der Rohliste unter Watcoms instabilem ShellSort genau die Soll-Folge erzeugen.
  - **`schedforce.py` / `tiediag.py` / `savdiag.py` / `slotdiag.py` / `latepick106.py`:** Diagnose und Erzwingung am Instruktions-Scheduler (`ScheduleIns`), an Konflikt-Gewichten (`savings`), Stapelplätzen und der `LatePick`-Rotation.
  - **`watcom106_shellsort_solver.js`:** Eigenständiger Node.js-Simulator und **zweistufiger `{1, 2, 3} -> {3, 4, 5}`-ShellSort-Löser** zum Wegrechnen von `volatile`-Geistervariablen.

### `09_gesamtbau/` — Schritt 9: Gesamtbau, Relokations- und Aufrufprüfung
- Übersetzt alle Einheiten frisch, prüft sämtliche 32-Bit-Relokationen gegen das unmaskierte Original-Abbild (deckt den blinden Fleck des Einzelvergleichs auf), prüft die 512-Byte-Fixup-Seitenordnung, linkt mit `WLINK 10.6` und verifiziert die 100 % identische Prüfsumme (`bauen.py`).

### `10_entkruecker/` — Schritt 10: Halbierungs-Entkrücker und stripp-geprüfte Kommentare
- Entfernt künstliche Suchkrücken per binärer Chunk-Halbierung (`zusammen2.py` + `muster.py`, max. 8 native Messungen je Einheit) und setzt Katalog-Beschreibungen als C-Blockkommentare ein, wobei vor dem Speichern bewiesen wird, dass der Quelltext ohne Kommentare zeichengleich bleibt (`sprache_einsetzen.py`).

### `11_12_fixbau/` — Schritte 11 & 12: Schalter-Bugfixes und Prüfung längenverschobener Binaries
- Erzeugt mehrstufige Bugfix-Schalterheader (`mkfix.py` für `FIX_BUGS = 0 / 1 / 2`), beweist statisch die `#else`-Zeichengleichheit bei `FIX_BUGS=0` (`basis_check.py`), prüft längenverschobene `LE`-Binaries (`ΔLänge != 0`) auf Zeiger mitten in Funktionen (`zeiger_check.py`), verschobene `rel32`-Aufrufe (`call_check.py`, `kreuz_check.py`) und Datensegment-Gleichheit (`daten_check.py`) und teilt geänderte Einheiten zur Bisektion (`bisect_units.py`).

### `13_release/` — Schritt 13: Bau-Paket-Generator, `NDP2`-Patch & 64-Byte-Rechteprüfung
- Erzeugt das Clean-Room-Baupaket (`mk_baupaket.py`), kodiert verschobene Ziel-EXEs als kompakte `NDP2`-Patches (`mkpatch.py`), prüft alle gleitenden 64-Byte-Fenster gegen das Original-Binary (`pruefe_patch_rechte.py`), wendet Patches ohne Compiler an (`patchen.py` / `patchen.ps1`) und prüft die Repository-Hygiene (`check_repo_hygiene.py`).

---

## 5. Eigenständiges Mini-Beispiel (`beispiel/`)

Um den Werkzeugkasten ohne fremde Spieldaten auszuprobieren, führst du `beispiel/run_example.py` mit deinem lokalen `WPP386.EXE` aus:

```bash
W106_EXE=/pfad/zu/WPP386.EXE W106_H=/pfad/zu/H python3 beispiel/run_example.py
```

---

## 6. Lizenz

Veröffentlicht unter der **MIT-Lizenz** (siehe `LICENSE`, Copyright (c) 2026 MeowMuhMuhCow). Optionale Drittpakete (`unicorn`, `capstone`) sind in `THIRD_PARTY.md` dokumentiert und werden separat über `requirements.txt` installiert.
