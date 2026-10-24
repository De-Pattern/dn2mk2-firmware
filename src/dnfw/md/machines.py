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
from . import pi                              # v0.24: P-I, the physical models

ORDER = ("TRX-BD", "TRX-B2", "TRX-SD", "TRX-XT", "TRX-CP", "TRX-RS", "TRX-CB", "TRX-CH",
         "TRX-OH", "TRX-CY", "TRX-MA", "TRX-CL", "TRX-XC", "TRX-S2",
         "EFM-BD", "EFM-SD", "EFM-XT", "EFM-CP", "EFM-RS", "EFM-CB", "EFM-HH", "EFM-CY",
         "GND-SN", "GND-NS", "GND-IM",              # PERC's order until v0.16, TRX-S2 added
         "PI-BD", "PI-SD", "PI-MT", "PI-ML", "PI-MA", "PI-RS", "PI-RC", "PI-CC", "PI-HH")   # v0.24
_ALL = {M.NAME: M for M in (*_TRX, *_EFM, *gnd.MACHINES, *pi.MACHINES)}
MACHINES = tuple(_ALL[n] for n in ORDER if n in _ALL)
NAMES = tuple(M.NAME for M in MACHINES)
BY_NAME = {M.NAME: M for M in MACHINES}

# the Machinedrum's own defaults for each machine's eight knobs (0..127), as its machine
# table holds them (docs/md.md)
DEFAULTS = {
    'GND-SN': (73, 96, 0, 0, 0, 0, 0, 0), 'GND-NS': (64, 0, 0, 0, 0, 0, 0, 0),
    'GND-IM': (64, 127, 0, 127, 0, 0, 0, 0), 'TRX-BD': (64, 64, 0, 0, 0, 0, 0, 0),
    'TRX-SD': (64, 32, 0, 64, 64, 64, 64, 0), 'TRX-XT': (64, 48, 48, 102, 64, 0, 0, 0),
    'TRX-CP': (64, 64, 127, 64, 64, 32, 32, 64), 'TRX-RS': (64, 32, 0, 0, 0, 0, 0, 0),
    'TRX-CB': (64, 64, 64, 0, 64, 64, 0, 0), 'TRX-CH': (32, 32, 64, 64, 64, 0, 0, 0),
    'TRX-OH': (64, 64, 64, 64, 64, 0, 0, 0), 'TRX-CY': (64, 64, 64, 64, 64, 64, 0, 0),
    'TRX-MA': (32, 32, 0, 0, 64, 64, 64, 64), 'TRX-CL': (64, 32, 64, 0, 64, 0, 0, 0),
    'TRX-XC': (64, 32, 32, 96, 0, 0, 0, 0), 'TRX-B2': (0, 64, 96, 64, 0, 0, 0, 0),
    'TRX-S2': (64, 32, 32, 96, 0, 0, 0, 0), 'EFM-BD': (36, 76, 64, 55, 64, 64, 32, 127),
    'EFM-SD': (64, 55, 64, 64, 64, 32, 44, 16), 'EFM-XT': (64, 64, 38, 87, 48, 84, 55, 127),
    'EFM-CP': (83, 41, 64, 36, 32, 64, 127, 32), 'EFM-RS': (64, 32, 64, 32, 64, 64, 44, 64),
    'EFM-CB': (64, 64, 64, 96, 64, 64, 64, 0), 'EFM-HH': (96, 32, 0, 0, 64, 64, 64, 127),
    'EFM-CY': (64, 72, 96, 127, 64, 32, 64, 0),
    # v0.24, P-I (the machine table's defaults)
    'PI-BD': (80, 26, 127, 96, 29, 122, 0, 0), 'PI-SD': (64, 64, 64, 16, 0, 127, 96, 0),
    'PI-MT': (22, 24, 127, 127, 127, 96, 96, 64), 'PI-ML': (64, 64, 127, 0, 0, 0, 0, 0),
    'PI-MA': (99, 0, 72, 96, 64, 0, 0, 0), 'PI-RS': (96, 48, 64, 64, 64, 64, 0, 0),
    'PI-RC': (64, 70, 96, 32, 127, 127, 64, 127), 'PI-CC': (64, 70, 96, 32, 127, 127, 64, 127),
    'PI-HH': (64, 70, 96, 32, 127, 127, 64, 127),
}
