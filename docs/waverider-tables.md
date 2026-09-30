# Waverider's tables: loaded from the +Drive, the way Tonverk loads them

**The goal (owner, 2026-10-01):** tables and samples sit on the +Drive and are managed through DNX. The firmware carries the code and a few fallback tables only. **The procedure follows Tonverk's (owner, 2026-10-01).**

## How Tonverk does it

Read from the Tonverk User Manual, OS 1.4.1 (`00_Resources/06_Manuals_Text/`), §5.2.5, §5.2.6, §6.13.3 and §A.2.5. This is a summary in our own words; the manual is the authority.

1. **A wavetable is an ordinary audio file,** in the same formats as samples, divided into equal-length waves:
   - up to 64 waves; from a file with more, Tonverk takes 64 evenly spaced waves;
   - each wave a power of two from 64 to 4096 samples. The default is 2048, or the filename gives the size with a `_wt<size>` suffix (e.g. `name_wt1024.wav`);
   - a trailing `r` (e.g. `name_wt128r.wav`) turns interpolation between waves off.

   So tables made by other tools, or even plain samples, load unchanged.
2. **Each project has a wavetable pool:** 127 slots in RAM, separate from the 1,023-slot sample pool. Files go into the pool from the card, through the sample browser or straight from the machine's slot parameter.
3. **The oscillator's slot parameter picks a pool entry,** and it can be p-locked per step. To load from the machine: turn the slot knob to an empty slot, press YES to open a browser on the card, pick one or more files, and press YES again. A loaded table is picked by turning the knob. FUNC + YES opens the browser where a table's file lives.
4. **The pool is managed from the browser's wavetable view:** replace a table, unload tables, or select the ones no pattern uses.

## The same procedure on the Digitone II

| Tonverk | Waverider |
|---|---|
| the SD card | the **+Drive**; DNX puts the files there |
| an audio file with `_wt<size>` / `r` naming | **the same convention**, so a Tonverk-style table works as it is |
| a per-project pool, 127 slots, in RAM | a per-project pool in SHARC memory (DDR). Its size is set by measurement, not assumed |
| SLOT picks a pool entry, p-lockable | **TBL** picks a pool entry, p-lockable |
| load from the slot knob, or the browser | load from TBL (an empty slot, then YES, then browse); pool management later |

**Proposed split of the work (for the owner and DNX to decide):**
- **Tonverk parses and resamples the WAV on the device.** For the DN2, DNX would do that conversion on the computer: it accepts Tonverk-convention files and writes a ready-to-play table to the +Drive. The instrument then only copies it into the pool.
- **What the user sees stays Tonverk's; the heavy work stays off the Digitone.**
- The file format DNX writes, and how the project refers to its pool, are to be agreed with the DNX session (`docs/drive-storage-research.md` has the +Drive groundwork).

## What it constrains now

- **M7 (the pages):** TBL's record must not assume today's two baked tables. Its range comes from the pool, with the fallback tables as the entries a project gets without any loaded.
- **M8 (the waveform):** the display draws from the table TBL points at, wherever it was loaded, not from a separate baked copy.
- **The SHARC loop:** reads a table through the directory (it already does, `dnfw.waverider.dsp.directory`), so a loaded table is one more directory entry.
- **Table geometry:** today's baked tables are 16 frames of 512 points (`dnfw.waverider.reduce`). Tonverk plays up to 64 waves of up to 4096 samples. Which geometry the pool uses is a memory and CPU question, to be measured with `tools/dn2sharc_load.py --idle`.
