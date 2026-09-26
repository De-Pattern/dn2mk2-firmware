"""Move a routine from one user-supplied firmware into another, at apply time.

`spec` describes a transplant (guards, spans, relocation sites) without any
donor bytes; `plan.build` checks the two images and relocates in memory;
`oneshot_dt2.SPEC` is the Digitakt II 1.16 ONESHOT render into Digitone II 1.11.
"""
