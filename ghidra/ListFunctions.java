/* List the functions in an address range, with size and callees.
 *
 *   -postScript ListFunctions.java 0x40025000 0x40028000
 *
 * WHY THIS EXISTS. `dnfw fn entry` attributes an address to whichever
 * directly-called function precedes it, and says so: functions reached only
 * through a vtable or a `jsr %aN@` are not call targets, so the attribution is
 * a guess. On 2026-09-15 that guess made a 44-byte function at 0x40025e0a look
 * like a 6 KB interrupt handler containing the trig handler, the modulation
 * apply and the frame builder, and a whole afternoon was spent reasoning about
 * "the big ISR" that does not exist.
 *
 * Ghidra with real flow analysis has real boundaries -- but only since the
 * ColdfireEMAC language, because stock Ghidra stopped at every `movclr` and
 * never reached most of this region. See docs/mainos-image.md.
 *
 * Callees are listed from the reference manager, so indirect calls Ghidra has
 * resolved appear too; ones it has not are still invisible, and this script
 * does not pretend otherwise.
 */

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.RefType;

import java.util.ArrayList;
import java.util.List;
import java.util.TreeSet;

public class ListFunctions extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: ListFunctions.java <startAddr> <endAddr>");
            return;
        }
        Address lo = parse(args[0]);
        Address hi = parse(args[1]);

        List<Function> found = new ArrayList<>();
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(lo, true);
        while (it.hasNext()) {
            Function f = it.next();
            if (f.getEntryPoint().compareTo(hi) > 0) break;
            found.add(f);
        }

        println(String.format("%d functions in %s..%s", found.size(), lo, hi));
        for (Function f : found) {
            long size = f.getBody().getNumAddresses();
            TreeSet<String> callees = new TreeSet<>();
            for (Reference r : currentProgram.getReferenceManager()
                    .getReferenceIterator(f.getEntryPoint())) {
                if (r.getFromAddress().compareTo(f.getBody().getMaxAddress()) > 0) break;
                RefType t = r.getReferenceType();
                if (t.isCall()) {
                    Function c = getFunctionAt(r.getToAddress());
                    callees.add(c != null ? c.getName() : r.getToAddress().toString());
                }
            }
            println(String.format("%s  %6d B  %-34s -> %s",
                    f.getEntryPoint(), size, f.getName(),
                    callees.isEmpty() ? "(no resolved calls)" : String.join(" ", callees)));
        }
    }

    private Address parse(String s) {
        return currentProgram.getAddressFactory().getAddress(s.replaceFirst("^0x", ""));
    }
}
