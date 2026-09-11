/* Apply a names manifest to the current program.
 *
 * The manifest is written by `dnfw symbolmap --ghidra FILE`: tab-separated
 * lines `kind<TAB>address<TAB>name<TAB>note`, where kind is `function`, `data`
 * or `rtti`. `function` creates a function if none exists and names it; `data`
 * and `rtti` place a label, with the note as a plate comment. Lines starting
 * with `#` are comments.
 *
 * The data lives in the manifest, not here, so this one generic script seeds a
 * project of any size and carries no firmware itself. Run after auto-analysis:
 *   ghidra/analyze.bat <proj> <name> <bin> <base> -postScript ApplyNames.java <manifest>
 * or from the GUI Script Manager (it will prompt for the file).
 */

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

import java.io.BufferedReader;
import java.io.FileReader;

public class ApplyNames extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        java.io.File file = args.length >= 1 ? new java.io.File(args[0]) : askFile("Names manifest", "Apply");

        int functions = 0;
        int labels = 0;
        int skipped = 0;

        try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isEmpty() || line.charAt(0) == '#') {
                    continue;
                }
                String[] field = line.split("\t", -1);
                if (field.length < 3) {
                    continue;
                }
                String kind = field[0];
                Address address = toAddr(Long.decode(field[1]));
                String name = field[2];
                String note = field.length >= 4 ? field[3] : "";

                if (kind.equals("function")) {
                    if (nameFunction(address, name, note)) {
                        functions++;
                    } else {
                        skipped++;
                    }
                } else {
                    createLabel(address, name, true, SourceType.USER_DEFINED);
                    if (!note.isEmpty()) {
                        setPlateComment(address, note);
                    }
                    labels++;
                }
            }
        }

        println(String.format("ApplyNames: %d functions named, %d labels, %d skipped",
                functions, labels, skipped));
    }

    private boolean nameFunction(Address address, String name, String note) throws Exception {
        Function function = getFunctionContaining(address);
        if (function == null) {
            try {
                function = createFunction(address, name);
            } catch (Exception exc) {
                println("could not create function at " + address + ": " + exc.getMessage());
            }
        }
        if (function == null) {
            createLabel(address, name, true, SourceType.USER_DEFINED);
            if (!note.isEmpty()) {
                setPlateComment(address, note);
            }
            return false;
        }
        try {
            function.setName(name, SourceType.USER_DEFINED);
            if (!note.isEmpty()) {
                function.setComment(note);
            }
        } catch (Exception exc) {
            println("could not name function at " + address + ": " + exc.getMessage());
            return false;
        }
        return true;
    }
}
