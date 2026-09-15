"""Reading a firmware image from wherever it is kept, and loading one section.

Elektron ship OS files inside a `.zip` beside a readme, and that is how the
corpus in `00_Resources/` stores them. Accepting the zip directly means the
distributed file never has to be unpacked, so there is one less loose `.syx`
on disk to confuse with a build output.
"""

import pathlib
import zipfile

from ..firmware.load import load
from ..image.coldfire import LoadedImage


def read_image(path: pathlib.Path) -> bytes:
    """Read a `.syx`, or the single `.syx` inside a `.zip`."""
    if path.suffix.lower() != ".zip":
        return path.read_bytes()

    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".syx")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected exactly one .syx inside, found {len(names)}")
        return archive.read(names[0])


def load_section(path: pathlib.Path, section_id: int) -> LoadedImage:
    """One section of an image, at its load address, ready to disassemble.

    **Raw and compressed are both code.** `disasm` and `fn` each used to refuse
    a raw section as "stored raw, not code", conflating how a section is
    *stored* with what it *contains*. The updater (id 4) is ColdFire code that
    ships uncompressed, and that refusal is why the analysis in
    `docs/ideas-backlog.md` §6 was done with throwaway scripts instead of
    `dnfw fn callers` -- which covers more call forms than the throwaway did,
    and would have taken its `dest` from the section rather than from a wrong
    guess. The guard cost more than it saved.

    `Section.raw_payload` drops the 8-byte header where a raw section carries
    one, which is what makes the bytes line up with `dest`.
    """
    firmware = load(read_image(path))
    section = firmware.container.find(section_id)
    if section is None:
        raise ValueError(f"image has no section id={section_id}")
    content = section.unpack()
    if content is None:
        content = section.raw_payload
    return LoadedImage(dest=section.dest, content=content)
