// TargetSetup.java - Pre-Script: Datenblock abtrennen, Funktionen aus funktionen.tsv anlegen
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import java.io.*;
import java.util.*;

public class TargetSetup extends GhidraScript {
    public void run() throws Exception {
        String tsv = getScriptArgs()[0];
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        MemoryBlock b = mem.getBlock(sp.getAddress(0x10000));
        mem.split(b, sp.getAddress(0x1A0000));
        MemoryBlock code = mem.getBlock(sp.getAddress(0x10000));
        MemoryBlock data = mem.getBlock(sp.getAddress(0x1A0000));
        code.setName("CODE"); code.setRead(true); code.setWrite(false); code.setExecute(true);
        data.setName("DATA"); data.setRead(true); data.setWrite(true); data.setExecute(false);
        BufferedReader r = new BufferedReader(new FileReader(tsv));
        String line = r.readLine(); int n = 0;
        SymbolTable st = currentProgram.getSymbolTable();
        while ((line = r.readLine()) != null) {
            String[] f = line.split("\t", -1);
            long va = Long.parseLong(f[0], 16), end = Long.parseLong(f[1], 16);
            Address a = sp.getAddress(va);
            AddressSet body = new AddressSet(a, sp.getAddress(end - 1));
            new DisassembleCommand(a, body, true).applyTo(currentProgram, monitor);
            String nm = String.format("F_%06X", va);
            if (f.length > 5 && !f[5].isEmpty()) nm = "lib_" + f[5].replaceAll("[^A-Za-z0-9_]", "_") + String.format("_%06X", va);
            CreateFunctionCmd c = new CreateFunctionCmd(nm, a, null, SourceType.USER_DEFINED);
            if (!c.applyTo(currentProgram, monitor)) {
                println("kein Funktionsanlegen bei " + f[0] + ": " + c.getStatusMsg());
            }
            n++;
        }
        r.close();
        println("TargetSetup: " + n + " Funktionen");
    }
}
