// TargetParams.java - Watcom-Parameter je Funktion aus der Registernutzung ableiten und Signatur __watcall fest setzen
// Regel (byteweise: AL/AH/AX/EAX): EAX, EDX, EBX, ECX werden in dieser Reihenfolge belegt. Gelesen-vor-geschrieben (linear, Sicherungs-push
// im Prolog ausgenommen) zaehlt als Parameter; Anzahl = hoechster benutzter Index + 1. Stapelparameter aus "ret N".
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.lang.*;
import ghidra.program.model.data.*;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class TargetParams extends GhidraScript {
    static final String[] R = {"EAX", "EDX", "EBX", "ECX"};
    int idx(Register r) {
        if (r == null) return -1;
        Register b = r.getBaseRegister();
        for (int i = 0; i < 4; i++) if (b.getName().equals(R[i])) return i;
        return -1;
    }
    int bm(Register r) {
        int lsb = r.getLeastSignificantBitInBaseRegister(), len = r.getBitLength();
        return (((1 << (len / 8)) - 1) << (lsb / 8)) & 0xF;
    }
    public void run() throws Exception {
        Listing L = currentProgram.getListing();
        int n = 0, cnt[] = new int[9];
        Map<Function,Integer> regs = new HashMap<>(), stk = new HashMap<>();
        for (int pass = 0; pass < 6; pass++) {
          int changed = 0;
          for (Function f : L.getFunctions(true)) {
            if (f.getName().startsWith("lib_")) continue;
            int[] written = new int[4]; int maxi = -1; int stackArgs = 0; boolean prolog = true;
            for (Instruction ins : L.getInstructions(f.getBody(), true)) {
                String m = ins.getMnemonicString().toLowerCase();
                if (prolog && !m.equals("push")) prolog = false;
                if (m.equals("ret") && ins.getNumOperands() == 1) {
                    Scalar s = ins.getScalar(0); if (s != null) stackArgs = Math.max(stackArgs, (int) (s.getUnsignedValue() / 4));
                }
                boolean selfZero = (m.equals("xor") || m.equals("sub")) && ins.getNumOperands() == 2
                        && ins.getRegister(0) != null && ins.getRegister(0).equals(ins.getRegister(1));
                if (!(prolog && m.equals("push")) && !selfZero) {
                    for (Object o : ins.getInputObjects()) if (o instanceof Register) {
                        Register r = (Register) o; int i = idx(r); if (i >= 0 && (written[i] & bm(r)) != bm(r)) maxi = Math.max(maxi, i);
                    }
                }
                for (Object o : ins.getResultObjects()) if (o instanceof Register) {
                    Register r = (Register) o; int i = idx(r);
                    // geschriebene Bytes merken (AL, AH, AX, EAX); gelesen-vor-geschrieben byteweise
                    if (i >= 0) written[i] |= bm(r);
                }
                if (m.startsWith("call") || m.equals("jmp")) {
                    // Aufruf/Endsprung liest die Registerparameter des Ziels (Fixpunkt ueber alle Funktionen)
                    for (ghidra.program.model.symbol.Reference rf : ins.getReferencesFrom()) {
                        if (!rf.getReferenceType().isFlow()) continue;
                        Function g = getFunctionAt(rf.getToAddress());
                        if (g == null || g == f || !regs.containsKey(g)) continue;
                        for (int i = 0; i < regs.get(g); i++) if (written[i] != 0xF) maxi = Math.max(maxi, i);
                    }
                }
                if (m.startsWith("call")) written[0] = 0xF;   // Rueckgabe in EAX
            }
            Integer old = regs.get(f);
            if (old == null || old != maxi + 1) { regs.put(f, maxi + 1); changed++; }
            stk.put(f, stackArgs);
          }
          println("TargetParams Durchgang " + pass + ": geaendert " + changed);
          if (changed == 0) break;
        }
        for (Function f : regs.keySet()) {
            int np = regs.get(f) + stk.get(f);
            List<Variable> ps = new ArrayList<>();
            for (int k = 0; k < np; k++) ps.add(new ParameterImpl("p" + (k + 1), Undefined4DataType.dataType, currentProgram));
            f.updateFunction("__watcall", null, ps, Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, true, SourceType.ANALYSIS);
            cnt[Math.min(np, 8)]++; n++;
        }
        println("TargetParams: " + n + " Funktionen, Parameterzahl 0..8+: " + Arrays.toString(cnt));
    }
}
