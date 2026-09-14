/* List every instruction that references an address inside a range, with the
 * containing function. For finding who reads a table when the table was found
 * by inspecting bytes rather than by following code.
 *
 *   -postScript FindDataRefs.java 0x401f7fc8 0x401fcac8
 *
 * Ghidra's reference model only sees a reference it managed to build, so an
 * address computed at runtime will not appear here. Absence is weak evidence;
 * presence is strong. Run --control against a range known to be referenced
 * before believing a zero.
 *
 * ## [FIXED 2026-09-14] This script never worked, and its zero was quoted
 *
 * The first version did:
 *
 *     ReferenceIterator it = rm.getReferenceIterator(toAddr(lo));
 *     while (it.hasNext()) {
 *         Reference r = it.next();
 *         if (r.getToAddress().getOffset() > hi) break;
 *         ...
 *     }
 *
 * Two faults, either one fatal:
 *
 *  1. `getReferenceIterator(addr)` walks references ordered by their **from**
 *     address, starting at `addr`. Passing `lo` -- an address in the DATA
 *     region -- means every reference originating in the CODE region below it
 *     is never visited at all. It was iterating the wrong axis.
 *
 *  2. The `break` compares the **to** address against `hi` while iterating by
 *     **from** address, so the first reference pointing anywhere above the
 *     range ends the loop. In practice that is immediately.
 *
 * It therefore returned `total 0` for everything. `docs/modulation-mask.md`
 * quoted that zero for the parameter table and explained it as "a property of
 * the reference model", which is a true statement about Ghidra attached to a
 * result that came from a broken loop. The parameter table has 44 `lea` sites
 * against its base (`docs/version-anchors.md`) and a working scan finds them.
 *
 * The fix walks the destination axis -- `getReferenceDestinationIterator` over
 * the range, then `getReferencesTo` each destination -- which is what "who
 * points at this?" actually asks.
 */

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressIterator;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;

import java.util.TreeMap;

public class FindDataRefs extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: FindDataRefs <lo> <hi> [maxPrint]");
            return;
        }
        long lo = Long.decode(args[0]);
        long hi = Long.decode(args[1]);
        int maxPrint = args.length > 2 ? Integer.decode(args[2]) : 200;

        ReferenceManager rm = currentProgram.getReferenceManager();
        AddressSet set = new AddressSet(toAddr(lo), toAddr(hi));

        // The destination axis: every address IN the range that something
        // points at. This is the question the script name asks.
        AddressIterator dests = rm.getReferenceDestinationIterator(set, true);

        TreeMap<String, Integer> byFunction = new TreeMap<>();
        int n = 0, printed = 0;
        while (dests.hasNext() && !monitor.isCancelled()) {
            Address to = dests.next();
            for (Reference r : rm.getReferencesTo(to)) {
                Address from = r.getFromAddress();
                Function f = getFunctionContaining(from);
                Instruction ins = getInstructionAt(from);
                String fname = f == null ? "(no function)"
                        : f.getName() + "@" + f.getEntryPoint();
                byFunction.merge(fname, 1, Integer::sum);
                if (printed < maxPrint) {
                    println(String.format("%s -> %s  %-38s  %s",
                            from, to,
                            ins == null ? "(data)" : ins.toString(), fname));
                    printed++;
                }
                n++;
            }
        }
        if (n > printed) {
            println("... " + (n - printed) + " more not printed");
        }
        println("");
        println("referencing functions, by count:");
        byFunction.entrySet().stream()
                .sorted((a, b) -> b.getValue() - a.getValue())
                .limit(40)
                .forEach(e -> println(String.format("  %5d  %s",
                        e.getValue(), e.getKey())));
        println("total " + n);
    }
}
