/* Decompile the function at an address, or the function that references a
 * given string, and print the C. For reading a routine after Gate F has
 * cleared the disassembler -- never before.
 *
 * Two ways to name the target, because an address is not always known yet:
 *   -postScript DecompileFunction.java 0x80012a1c
 *   -postScript DecompileFunction.java "RECEIVING..."     (string it references)
 *
 * A quoted string argument decompiles every function that references that
 * string literal, which is how you get from a message on the screen to the
 * code that prints it. An address decompiles just that one function.
 *
 * Run after auto-analysis (no -noanalysis), so references and functions exist.
 * Output goes to stdout; redirect it.
 */

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;

import java.util.LinkedHashSet;
import java.util.Set;

public class DecompileFunction extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("usage: DecompileFunction <address> | \"<string it references>\"");
            return;
        }

        Set<Function> targets = new LinkedHashSet<>();
        String arg = args[0];
        boolean looksLikeAddress = arg.startsWith("0x") || arg.matches("[0-9a-fA-F]{6,}");

        if (looksLikeAddress) {
            Address a = toAddr(Long.decode(arg.startsWith("0x") ? arg : "0x" + arg));
            Function f = getFunctionContaining(a);
            if (f != null) targets.add(f);
            else println("; no function contains " + a);
        } else {
            for (Function f : functionsReferencing(arg)) targets.add(f);
            if (targets.isEmpty()) println("; no function references the string " + arg);
        }

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        try {
            for (Function f : targets) {
                println("");
                println("/* " + f.getName() + " @ " + f.getEntryPoint()
                        + "  (" + f.getBody().getNumAddresses() + " bytes) */");
                DecompileResults r = decomp.decompileFunction(f, 60, monitor);
                if (r.decompileCompleted()) {
                    println(r.getDecompiledFunction().getC());
                } else {
                    println("; decompile failed: " + r.getErrorMessage());
                }
            }
        } finally {
            decomp.dispose();
        }
    }

    /* Every function holding a reference to the address of a NUL-terminated
     * string equal to `text`. Ghidra has already made the string into Data and
     * recorded who points at it, so this is a lookup, not a scan. */
    private Set<Function> functionsReferencing(String text) {
        Set<Function> out = new LinkedHashSet<>();
        Listing listing = currentProgram.getListing();
        ReferenceManager refs = currentProgram.getReferenceManager();
        for (Data d : listing.getDefinedData(true)) {
            Object value = d.getValue();
            if (!(value instanceof String) || !text.equals(value)) continue;
            for (Reference ref : refs.getReferencesTo(d.getAddress())) {
                Function f = getFunctionContaining(ref.getFromAddress());
                if (f != null) out.add(f);
            }
        }
        return out;
    }
}
