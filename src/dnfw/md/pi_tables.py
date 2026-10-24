"""P-I's ROM tables (v0.24): each machine's module lists the DSP2 words it reads, in a
file of its own (pi_<group>_tables.py, a dict TABLES: name -> (DSP2 address, words)), so
rom.py can take them without importing the machines."""

from __future__ import annotations

import importlib

TABLES: dict = {}
for _g in ("pi_bd", "pi_mt", "pi_sd", "pi_rs", "pi_ml", "pi_ma", "pi_rc", "pi_cc", "pi_hh"):
    try:
        TABLES.update(importlib.import_module(f".{_g}_tables", __package__).TABLES)
    except ImportError:                       # pragma: no cover
        pass
