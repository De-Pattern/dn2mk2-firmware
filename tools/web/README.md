# DN2 Sample Import (browser)

`index.html` is the whole tool: one page, no server, no packages. It does what
`tools/dn2samples.py send` does, with a window: pick the Digitone II's MIDI ports, drop or
browse WAVs, see which slot each goes to and how much memory is used, sent and left, and
send them over USB (SysEx, sample link 4; firmware v0.22 or later).

- **Run it:** open `index.html` in Chrome or Edge (from disk works), or host it on any
  static site (GitHub Pages from a public repo). Allow MIDI with SysEx when asked.
- **What a send does:** your samples on the instrument are replaced by the list, in its
  order (SAMP 1, 2, ...); recordings stay. The samples go to the +Drive, then into the DSP,
  and load at every power-on.
- **Memory:** 368 MB for yours when the instrument's power-on RAM check passed, else 96 MB
  (`docs/sampler.md`, "400 MB, and a RAM check"). The 32 MB recordings area is skipped.
- `test/test_web_tool.py` runs the page's core under node and checks it builds the same
  image and SysEx as `dn2samples.py`, byte for byte.

## Icon

The page carries its own favicon (embedded in `index.html`, so it shows even when the
file is opened on its own). `icons/` holds the same mark for a desktop shortcut:

- **Windows:** right-click the desktop, **New > Shortcut**, point it at Chrome or Edge with
  the page, e.g. `"C:\Program Files\Google\Chrome\Application\chrome.exe" --app="file:///C:/path/to/tools/web/index.html"`,
  then **Properties > Change Icon...** and pick `icons/dn2-import.ico`.
- `icons/dn2-import-512.png` and `icons/dn2-import-180.png` for anything else (macOS, a
  home-screen icon).
