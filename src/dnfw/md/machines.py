"""Every ported Machinedrum machine, in the order TYPE offers them (docs/md.md)."""

from __future__ import annotations

from . import gnd

try:                                          # the families arrive one by one
    from . import trx
    _TRX = trx.MACHINES
except ImportError:                           # pragma: no cover
    _TRX = ()
try:
    from . import efm
    _EFM = efm.MACHINES
except ImportError:                           # pragma: no cover
    _EFM = ()

MACHINES = (*_TRX, *_EFM, *gnd.MACHINES)
NAMES = tuple(M.NAME for M in MACHINES)
BY_NAME = {M.NAME: M for M in MACHINES}
