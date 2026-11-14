# Test builds

Builds from feature branches, gated exactly like a release (`CLEARED TO FLASH` on that exact
file, its `.gate.json` beside it), but **not releases**: flash one only to test its feature, and go
back to the latest release for everyday use. Each one's notes, tests and known issues are in its
branch's own `FIRMWARE.md`.

| build | branch | what it tests |
|---|---|---|
| `v0.54-t1-STEREO/` | `stereo` | stereo samples in true stereo (FIRMWARE.md on `stereo`, "v0.54-t1 — STEREO") |
