"""TRX: the Machinedrum's analog-modelled machines (docs/md.md), in two halves."""

from __future__ import annotations

MACHINES: tuple = ()
try:
    from . import trx1
    MACHINES += trx1.MACHINES
except ImportError:                           # pragma: no cover
    pass
try:
    from . import trx2
    MACHINES += trx2.MACHINES
except ImportError:                           # pragma: no cover
    pass
