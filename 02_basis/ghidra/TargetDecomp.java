// TargetDecomp.java - Post-Script: alle Funktionen vorueberetzen, je Bau-Einheit eine .c-Datei
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.*;

public class TargetDecomp extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        String tsv = a[0], units = a[1], outdir = a[2];
        // Einheiten: name lo hi (TSV)
        List<long[]> ur = new ArrayList<>(); List<String> un = new ArrayList<>();
        BufferedReader r = new BufferedReader(new FileReader(units)); String line;
        while ((line = r.readLine()) != null) { String[] f = line.split("\t"); un.add(f[0]); ur.add(new long[]{Long.parseLong(f[1]), Long.parseLong(f[2])}); }
        r.close();
        Map<String, StringBuilder> out = new LinkedHashMap<>();
        PrintWriter idx = new PrintWriter(new FileWriter(outdir + "/index.tsv"));
        idx.println("va\teinheit\tstatus\tzeilen\tname");
        DecompInterface di = new DecompInterface();
        DecompileOptions op = new DecompileOptions(); di.setOptions(op);
        di.toggleCCode(true); di.toggleSyntaxTree(false); di.setSimplificationStyle("decompile");
        di.openProgram(currentProgram);
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        r = new BufferedReader(new FileReader(tsv)); r.readLine();
        int n = 0, ok = 0;
        while ((line = r.readLine()) != null) {
            String[] f = line.split("\t", -1);
            if (f.length > 5 && !f[5].isEmpty()) continue;  // Watcom-Bibliothek ueberspringen
            long va = Long.parseLong(f[0], 16);
            String unit = "_ohne_einheit";
            for (int i = 0; i < ur.size(); i++) if (va >= ur.get(i)[0] && va < ur.get(i)[1]) { unit = un.get(i); break; }
            Function fn = getFunctionAt(sp.getAddress(va));
            String st, txt;
            if (fn == null) { st = "keine_funktion"; txt = "/* keine Funktion */\n"; }
            else {
                DecompileResults res = di.decompileFunction(fn, 60, monitor);
                if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) { st = "ok"; txt = res.getDecompiledFunction().getC(); ok++; }
                else { st = "fehler"; txt = "/* Fehler: " + (res == null ? "null" : res.getErrorMessage()) + " */\n"; }
            }
            StringBuilder sb = out.computeIfAbsent(unit, k -> new StringBuilder("/* Ghidra-Rohentwurf, Einheit " + k + " - nicht bytegleich, nur Vorlage */\n\n"));
            sb.append("/* ==== ").append(f[0]).append("-").append(f[1]).append("  ").append(f[3]).append("  ").append(f[4]).append(" ==== */\n").append(txt).append("\n");
            idx.println(f[0] + "\t" + unit + "\t" + st + "\t" + txt.split("\n").length + "\t" + (fn == null ? "" : fn.getName()));
            n++;
            if (n % 250 == 0) { println("Fortschritt: " + n + " (ok " + ok + ")"); idx.flush(); }
        }
        r.close(); idx.close(); di.dispose();
        for (Map.Entry<String, StringBuilder> e : out.entrySet()) {
            try (PrintWriter w = new PrintWriter(new FileWriter(outdir + "/" + e.getKey() + ".c"))) { w.print(e.getValue()); }
        }
        println("TargetDecomp: " + n + " Funktionen, ok " + ok + ", Dateien " + out.size());
    }
}
