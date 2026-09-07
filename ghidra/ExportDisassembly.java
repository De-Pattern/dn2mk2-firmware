/* Export a linear disassembly of one span, for Gate F.
 *
 * Ghidra is the tool we actually want for this firmware -- decompiler, cross
 * references, types -- but nothing it says is trusted until it has been checked
 * against objdump. This script produces the listing that check compares.
 *
 * The sweep is deliberately LINEAR and does not follow flow, because that is
 * what `objdump -D` does and a comparison is only fair if both sides were asked
 * the same question. Following flow would let Ghidra skip the bytes it cannot
 * make sense of, which is exactly the disagreement worth finding.
 *
 * Output is one instruction per line: address, hex bytes, text, tab separated.
 * `dnfw validate-disasm --against ghidra` reads it.
 *
 * Headless usage (see ghidra/run-gate-f.sh):
 *   analyzeHeadless <project dir> <name> -import <raw.bin> \
 *     -processor <languageId> -loader BinaryLoader -loader-baseAddr 0x40000400 \
 *     -postScript ExportDisassembly.java <start> <length> <out.txt>
 */

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;

import java.io.PrintWriter;

public class ExportDisassembly extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 3) {
            println("usage: ExportDisassembly <startAddress> <length> <outputFile>");
            return;
        }

        long start = Long.decode(args[0]);
        long length = Long.decode(args[1]);
        String outputPath = args[2];

        Address address = toAddr(start);
        Address end = toAddr(start + length - 1);
        Listing listing = currentProgram.getListing();

        int decoded = 0;
        int skipped = 0;

        try (PrintWriter out = new PrintWriter(outputPath, "UTF-8")) {
            while (address.compareTo(end) <= 0) {
                Instruction insn = listing.getInstructionAt(address);

                if (insn == null) {
                    /* followFlow = false: one instruction at this address only. */
                    DisassembleCommand cmd = new DisassembleCommand(address, null, false);
                    cmd.applyTo(currentProgram, monitor);
                    insn = listing.getInstructionAt(address);
                }

                if (insn == null) {
                    /* Ghidra could not decode here. Advance one halfword, which
                     * is the same assumption Capstone makes and the one that
                     * causes desynchronisation -- recorded, not hidden.
                     * getBytes() is FlatProgramAPI's; do not redeclare it. */
                    out.printf("%s\t%s\t%s%n", address, hex(getBytes(address, 2)), "; undecodable");
                    address = address.add(2);
                    skipped++;
                    continue;
                }

                out.printf("%s\t%s\t%s%n", insn.getAddress(), hex(insn.getBytes()), insn.toString());
                address = address.add(insn.getLength());
                decoded++;
            }
        }

        println(String.format("ExportDisassembly: %d instructions, %d undecodable -> %s",
                decoded, skipped, outputPath));
    }

    private static String hex(byte[] bytes) {
        StringBuilder text = new StringBuilder();
        for (byte b : bytes) {
            text.append(String.format("%02x", b));
        }
        return text.toString();
    }
}
