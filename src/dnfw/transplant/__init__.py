"""Move a routine from one user-supplied firmware into another, at apply time.

`spec` describes a transplant (guards, spans, relocation sites) without any
donor bytes; `plan.build` checks the two images and relocates in memory.
"""
