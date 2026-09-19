//! Print selache's view of a SHARC+ VISA region, one line per even offset:
//! `offset<TAB>length<TAB>text`. The region is read from the file named on the
//! command line, or from stdin, as stored in the firmware: 16-bit little-endian
//! parcels, most significant parcel first.

use std::io::{Read, Write};

use selinstr::{disasm, visa};

fn main() {
    let mut raw = Vec::new();
    match std::env::args().nth(1) {
        Some(path) => raw = std::fs::read(path).expect("cannot read region"),
        None => {
            std::io::stdin().read_to_end(&mut raw).expect("cannot read stdin");
        }
    }
    // selache reads parcels big-endian, as they sit in an ELF.
    let mut be = raw;
    for i in (0..be.len() & !1).step_by(2) {
        be.swap(i, i + 1);
    }
    let out = std::io::stdout();
    let mut out = std::io::BufWriter::new(out.lock());
    let mut off = 0usize;
    while off + 2 <= be.len() {
        let len = visa::instruction_len(&be, off);
        let end = (off + len).min(be.len());
        let lines = visa::disassemble_visa(&be[off..end], 0, disasm::decode_instruction);
        let text = lines.first().map(|l| l.text.replace(['\t', '\n'], " ")).unwrap_or_default();
        writeln!(out, "{off}\t{len}\t{text}").unwrap();
        off += 2;
    }
}
