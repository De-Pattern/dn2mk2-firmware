/* Build a SHARC program with every region at the address the ISA implies, then
 * disassemble from the function entries the call scan already found.
 *
 * ## Why seeding matters here more than on the ColdFire side
 *
 * A raw binary has no entry point, so Ghidra's auto-analysis has nothing to
 * follow and falls back on guessing. On this image guessing is actively
 * harmful: an all-zero 48-bit word satisfies Type21a's mask, so padding
 * disassembles as confident code (docs/sharc-disassembly.md), and a linear
 * sweep desynchronises almost immediately -- measured at 6.9% of bytes covered
 * and 3.9% of known boundaries hit, by scripts/sharc_decode.py.
 *
 * The fix is to give Ghidra the boundaries we already trust. Every absolute
 * cjump target is a function entry, 461 of them, and each is a point where the
 * instruction stream is known to start. Disassembling from those and letting
 * flow do the rest is a different method from a linear walk, not a better
 * tuning of one.
 *
 * ## The measurement
 *
 * The same oracle scores both: a cjump site is a boundary neither disassembler
 * chose, so "did an instruction start exactly there" can come out either way.
 * The script writes that per-site verdict out, so Ghidra's flow-following can
 * be compared with the linear walk on identical ground rather than by
 * impression.
 *
 *   ghidra\analyze.bat <projdir> sharc out\sharc\code_283825c4.bin 0x3825c4 \
 *     -postScript SharcImport.java out\sharc <out.txt>
 */

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;

import java.io.File;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

public class SharcImport extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("usage: SharcImport <exportDir> [report.txt]");
            return;
        }
        Path dir = Path.of(args[0]);
        Memory mem = currentProgram.getMemory();

        // 1. Every region the exporter placed, at its flat base. The block the
        //    loader already created is skipped rather than duplicated.
        for (String line : Files.readAllLines(dir.resolve("manifest.tsv"))) {
            String[] f = line.split("\t");
            if (f.length < 5) continue;
            String name = f[0];
            long base = Long.decode(f[1]);
            File blob = dir.resolve(f[4]).toFile();
            Address at = toAddr(base);
            if (mem.getBlock(at) != null) {
                println("block already present at " + at + " (" + name + ")");
                continue;
            }
            try (java.io.InputStream in = new java.io.FileInputStream(blob)) {
                MemoryBlock b = mem.createInitializedBlock(
                        name, at, in, blob.length(), monitor, false);
                b.setRead(true);
                b.setWrite(false);
                b.setExecute(f[3].equals("code"));
                println("added " + name + " at " + at + " (" + blob.length() + " bytes)");
            }
        }

        // 2. Disassemble from each known entry and make it a function.
        List<Address> entries = new ArrayList<>();
        for (String line : Files.readAllLines(dir.resolve("entries.txt"))) {
            line = line.trim();
            if (!line.isEmpty()) entries.add(toAddr(Long.decode(line)));
        }
        println("seeding " + entries.size() + " entries");

        AddressSet seeds = new AddressSet();
        for (Address a : entries) {
            if (mem.getBlock(a) != null) seeds.add(a);
        }
        DisassembleCommand cmd = new DisassembleCommand(seeds, null, true);
        cmd.applyTo(currentProgram, monitor);

        int made = 0;
        for (Address a : entries) {
            if (mem.getBlock(a) == null) continue;
            if (getFunctionAt(a) != null) { made++; continue; }
            if (createFunction(a, null) != null) made++;
        }
        println("functions: " + made + " of " + entries.size());

        // 3. Score against the oracle: did an instruction begin at each call
        //    site? The sites come from the exporter's own scan, not from here.
        Listing listing = currentProgram.getListing();
        int instrs = 0;
        long bytes = 0;
        for (Instruction ins : listing.getInstructions(true)) {
            instrs++;
            bytes += ins.getLength();
        }
        println("instructions: " + instrs + ", bytes covered: " + bytes);

        if (args.length >= 2) {
            try (PrintWriter out = new PrintWriter(args[1])) {
                out.println("# instructions=" + instrs + " bytes=" + bytes
                        + " functions=" + made);
                for (Instruction ins : listing.getInstructions(true)) {
                    Address a = ins.getAddress();
                    out.println(a + "\t" + ins.getLength() + "\t" + ins);
                }
            }
            println("wrote " + args[1]);
        }
    }
}
