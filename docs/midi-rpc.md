# The device's MIDI RPC surface — reading the hardware instead of the file

> **PARKED 2026-09-12.** Recorded, not pursued. The DSP hunt needs a tooling
> answer first — we have no SHARC disassembler and no handle on the packing
> (`docs/ideas-backlog.md` §7) — so finding the image would not yet let us read
> it. This route is kept because it is the cheapest way to *settle* the question
> when the hunt resumes, and because steps 1–3 below are useful on their own.

The owner asked, in the middle of the DSP hunt: *"Why don't we go straight to the
Elektron transfer?"*

The instinct is right, and it opens a route this project had not considered.
**The DN2 exposes a large RPC surface over MIDI SysEx, including a raw
filesystem read API.** Everything the DSP hunt has been doing — entropy tests,
periodicity tests, guessing at packing — is static analysis of a file. This is
the option of asking the running instrument instead.

## What is there

Enumerated from the RTTI in MAIN OS 1.11 (`elektron::MidiRpc*`), ~90 request /
response pairs. Grouped:

| Group | Messages |
|---|---|
| **Raw filesystem** | `FsRawReadDir`, `FsRawOpenFileForRead`, `FsRawReadFileV1/V2`, `FsRawCloseFileReader`, `FsRawGetFileInfoFromPathV1/V2`, `FsRawGetFileInfoFromHashAndSize`, `FsRawCreateDir`, `FsRawDeleteDir`, `FsRawDeleteFile`, `FsRawRenameFile`, `FsRawOpenFileForWrite`, `FsRawWriteFileV1/V2`, `FsRawCloseFileWriter` |
| **Sample filesystem** | the same shape again under `FsSample*`, plus `FsSampleListRam`, `FsSampleClearRam`, `FsSampleAssign`, `FsSampleMemoryCompaction` |
| **Data objects** | `DataList`, `DataReadOpen`, `DataReadPartial`, `DataReadClose`, `DataWriteOpen/Partial/Close`, `DataClear`, `DataCopy`, `DataMove`, `DataSwap`, `DataRename`, `DataSetTags` |
| **Device** | `DeviceUID`, `SoftwareVersion`, `Ping`, `StorageSpace`, `Query`, `TempoRead`, `TempoWrite`, **`Screenshot`** |
| **OS upgrade** | `OsUpgradeStart`, `OsUpgradeWrite`, `OsUpgradeEnd` |
| **Generic** | `EnumerateFiles`, `ReadFile`, `WriteFile` |

Dispatch: `Midi::handleSysexRpc(const unsigned char*, int, midiInInterfaceID_t)`
→ `MidiRpcDispatcher::handleMessageAndCreateResponse(shared_ptr<MidiRpcMessage>)`.
A chunk-size limit is named in the strings as `rpc_file_chunk_size_max`.

## Why this matters here

**`FsRaw*` is a raw filesystem read API on the running device.** If the SHARC
boot image is stored as a file — on the eMMC, or in a region the filesystem
layer can address — it can be **listed and read off the hardware directly**,
rather than inferred from a static blob whose packing we cannot guess
(`docs/ideas-backlog.md` §7).

That would not merely shortcut the current hunt; it would settle it. A directory
listing either contains something DSP-shaped or it does not.

**And `Elektron Transfer` is the existing client for this protocol** — which is
exactly what the owner's question was pointing at. `FsSample*` is plainly what
Transfer drives on sampling devices; `FsRaw*`, `Data*` and `EnumerateFiles` are
the generic layer beneath it.

**DNX does not implement any of this.** Checked: the only match across the whole
DNX tree is a coincidence in `package-lock.json`. DNX reads *projects* from
`.dnx` backups; it does not speak the RPC. So this is new ground for both
projects, and anything built here would be useful to DNX too.

## What is not established

Stated plainly, because the temptation is to assume the good case:

- **Whether the DSP image is a file at all.** Firmware regions usually are not in
  the filesystem. `blob` ships inside the ELE3 container, which argues it is
  *not* a file the FS layer sees.
- **Whether `FsRaw*` is enabled on the DN2.** The DN2 does not sample, so the
  `FsSample*` half may be inert on this device; `FsRaw*` may or may not be.
- **The wire format.** Message ids, field layouts and the SysEx envelope are all
  unread. The RTTI gives names, not encodings.

## The next steps, cheapest first

1. **Read the dispatcher.** `MidiRpcDispatcher::handleMessageAndCreateResponse`
   resolves a message id to a handler; that table gives the **opcode for every
   name above**, which is the one thing needed before anything can be sent.
2. **Implement `Ping` and `SoftwareVersion`.** Two messages, no side effects, and
   they prove the envelope, framing and dispatch end to end. `SoftwareVersion`
   also answers a question left open earlier — the OS version is compiled-in
   integers with no string in the image (`docs/os-versions.md`), and this is how
   the device reports it.
3. **Then `Screenshot`.** Still read-only, still harmless, and a screenshot
   arriving on the desktop is unambiguous proof the whole stack works. A good
   milestone precisely because it cannot be misread.
4. **Then `FsRawReadDir` / `EnumerateFiles`.** Read-only. This is the step that
   answers the DSP question — and it also maps the device's storage, which
   `docs/hardware.md` lists as an open item.

**Write operations are out of scope and should stay out.** `FsRawWriteFile*`,
`FsRawDeleteFile`, `DataClear` and the `OsUpgrade*` trio can all destroy a
user's +Drive or brick the device. Nothing in this document needs them, and the
read half is where all the value is.

Recovery remains proven for the OS (`docs/flashing.md`), but **a wiped +Drive is
not recoverable** from anything this project holds — take a DNX backup before
the first RPC session regardless, since even a read API can be sent a malformed
message.
