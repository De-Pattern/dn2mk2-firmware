"""Porting the mod from stock OS 1.11 to stock OS 1.12 (docs/os112-port.md).

The source stays written in 1.11's addresses; `addrmap` translates each one to 1.12 and says
how it knows: the code around it matched in both images, or the code that references it
(an absolute operand) matched and its operand is read from 1.12."""
