/* List every instruction that references an address inside a range, with the
 * containing function. For finding who reads a table when the table was found
 * by inspecting bytes rather than by following code.
 *
 *   -postScript FindDataRefs.java 0x401f8784 0x401fcac8
 *
 * Ghidra's reference model only sees a reference it managed to build, so an
 * address computed at runtime will not appear here. Absence is not evidence;
 * presence is.
 */

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;

public class FindDataRefs extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: FindDataRefs <lo> <hi>");
            return;
        }
        long lo = Long.decode(args[0]);
        long hi = Long.decode(args[1]);

        ReferenceManager rm = currentProgram.getReferenceManager();
        AddressSet set = new AddressSet(toAddr(lo), toAddr(hi));
        ReferenceIterator it = rm.getReferenceIterator(toAddr(lo));

        int n = 0;
        while (it.hasNext()) {
            Reference r = it.next();
            Address to = r.getToAddress();
            if (to.getOffset() > hi) {
                break;
            }
            if (!set.contains(to)) {
                continue;
            }
            Address from = r.getFromAddress();
            Function f = getFunctionContaining(from);
            Instruction ins = getInstructionAt(from);
            println(String.format("%s -> %s  %-40s  %s",
                    from, to,
                    ins == null ? "(data)" : ins.toString(),
                    f == null ? "(no function)" : f.getName() + "@" + f.getEntryPoint()));
            n++;
        }
        println("total " + n);
    }
}
