"""P-I: the Machinedrum's physical-model machines (v0.24, docs/md.md), one module a group
(pi_<group>.py, each with its MACHINES)."""

from __future__ import annotations

import importlib

MACHINES: tuple = ()
for _g in ("pi_bd", "pi_mt", "pi_sd", "pi_rs", "pi_ml", "pi_ma", "pi_rc", "pi_cc", "pi_hh"):
    try:
        MACHINES += importlib.import_module(f".{_g}", __package__).MACHINES
    except ImportError:                       # pragma: no cover (the family arrives one by one)
        pass
