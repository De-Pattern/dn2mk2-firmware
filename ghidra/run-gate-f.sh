#!/bin/sh
# Export a Ghidra disassembly of one span, so it can be checked against objdump.
#
# Runs inside WSL, where Ghidra and a JDK live on this machine. Produces the
# tab-separated listing that `dnfw validate-disasm --against ghidra --listing`
# reads.
#
#   ghidra/run-gate-f.sh <raw section .bin> <base addr> <start addr> <length> <out.txt>
#
# `-noanalysis` is deliberate. The auto-analyser would follow flow, propagate
# context and skip what it cannot make sense of; objdump does a flat linear
# sweep. Asking the two of them different questions would make any disagreement
# meaningless, so the script disassembles linearly and nothing else runs.
set -eu

GHIDRA="${GHIDRA_HOME:-$(ls -d /opt/ghidra_* 2>/dev/null | head -1)}"
[ -n "$GHIDRA" ] && [ -d "$GHIDRA" ] || {
    echo "Ghidra not found. Set GHIDRA_HOME, or install under /opt/ghidra_*." >&2
    exit 1
}

BIN="${1:?usage: run-gate-f.sh <raw.bin> <base> <start> <length> <out.txt>}"
BASE="${2:?}"
START="${3:?}"
LENGTH="${4:?}"
OUT="${5:?}"

# Ghidra's ColdFire variant. Whether it is any good is what Gate F decides.
PROCESSOR="${PROCESSOR:-68000:BE:32:Coldfire}"

PROJECT=$(mktemp -d)
SCRIPTS=$(cd "$(dirname "$0")" && pwd)

"$GHIDRA/support/analyzeHeadless" "$PROJECT" gatef \
    -import "$BIN" \
    -processor "$PROCESSOR" \
    -loader BinaryLoader \
    -loader-baseAddr "$BASE" \
    -noanalysis \
    -scriptPath "$SCRIPTS" \
    -postScript ExportDisassembly.java "$START" "$LENGTH" "$OUT" \
    -deleteProject

rm -rf "$PROJECT"
echo "wrote $OUT"
