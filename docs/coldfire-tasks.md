# The ColdFire's tasks, the scheduler, and their stacks (DN2 1.11)

Read on the instrument on 2026-09-30, using the USB probe's read-only PEEK (`tools/dn2probe.py`), on `waverider-m6b-usbprobe` and `-usbprobe3`. The task list comes from the image. **[V]** marks a fact read on the instrument, **[D]** one read from the disassembly.

## The scheduler

- **The context switch** is at `0x40000410..0x40000458`. It saves every register at TCB `+12` and stores the resume frame's SP at `+72`. It then takes the next TCB from `**[0x4058d15c]`, stores it in `0x4664acdc` (the running task) and returns with `rte`. **[D]**
- **The ready table** is at `0x4664ac9c`: one list head per priority, `0x4664ac9c + 4 * prio`. A TCB's word at `+8` points at its own slot, set by `TASK_CREATE` (below). All 11 running tasks matched. **[V]**
- **Higher numbers run first.** The MIDI task, which answers the probe, is prio 7. It was the running task in every read, and `[0x4058d15c]` pointed at its slot. **[V]**
- **Prio 0 never runs.** Prio 0 (`0x424388ac`) and prio 1 (`0x4243c900`) were both ready in 60 of 60 reads, so prio 0 never gets the CPU; on probe protocol 2, `idle_in` stayed 0. **[V]**
- **Prio 1 is the real idle loop.** Its entry is `0x400cec98`. It runs the boot's setup and then parks at `bra.s *` `0x400cf0e2`; either branch of its last test lands there. Its saved PC was that spin in 200 of 200 reads. **[V]**
- **The probe times prio 1** from protocol 3 on, and its CPU figure is now correct (`docs/usbprobe.md`).

## `TASK_CREATE(tcb, entry, prio, stack, size)`, `0x400012c8`

The TCB keeps no record of its stack. The call sets the initial SP to `stack + (size & ~3) - 12`, with a frame that enters `entry`. Every call site pushes its arguments as constants, except one at `0x400f2220`, which passes registers. **[D]**

## The tasks, and how much of each stack has been used

Stacks start zeroed, so the deepest non-zero word is the high-water mark. This is a lower bound: a deepest word that was written as 0 is missed. Interrupts run on the current task's stack, so every figure includes the audio ISR's frame. Read after a busy pattern, a Waverider note and a save. **[V]**

| TCB | entry | prio | stack | size | used | peak | note |
|---|---|---|---|---|---|---|---|
| `0x4058d604` | `0x40002a46` | 10 | `0x4058d658` | 2,048 | 556 | **27 %** | the fullest; a small stack |
| `0x4058bee4` | `0x40000ea0` | 9 | `0x4058bf38` | 4,096 | 564 | 14 % | |
| `0x46678e7c` | `0x4012a9a8` | 8 | `0x44617484` | 16,384 | 536 | 3 % | |
| `0x445e6764` | `0x40120722` | 7 | `0x445e67b8` | 32,768 | 756 | 2 % | MIDI input: the probe answers here |
| `0x42c45624` | `0x400d3d86` | 7 | `0x42c41624` | 16,384 | 700 | 4 % | the boot intro |
| `0x4059d1c0` | `0x4002ed34` | 6 | `0x4059da34` | 163,840 | 2,416 | 1.5 % | the main application |
| `0x4461eb74` | `0x40131a2a` | 6 | `0x4461ebc8` | 16,384 | 0 | -- | not created this session |
| `0x446235f4` | `0x401334e4` | 5 | `0x44635a68` | 32,768 | 120 | 0.4 % | |
| `0x44623580` | `0x40133638` | 4 | `0x4462ca68` | 32,768 | 124 | 0.4 % | |
| `0x4462350c` | `0x4013375e` | 4 | `0x44623a68` | 32,768 | 124 | 0.4 % | |
| `0x445ef420` | `0x40122676` | 3 | `0x445ef474` | 32,768 | 0 | -- | not created this session |
| `0x40385e48` | `0x400cd48e` | 2 | `0x40385e9c` | 16,384 | 0 | -- | not created this session |
| `0x4243c900` | `0x400cec98` | 1 | `0x4243c954` | 16,384 | 3,796 | 23 % | **the idle loop** |
| `0x424388ac` | `0x400cebb4` | 0 | `0x42438900` | 16,384 | 48 | 0.3 % | never runs |

"Not created this session" means the TCB's `+8` slot is 0 and the stack is untouched. The tasks behind `0x400f2220` (register arguments) are not in the table.

## The ColdFire's CPU, from the probe (protocol 3)

| state | CPU | audio ISR (peak) |
|---|---|---|
| stopped | 60.5 % | 56 % (64 %) |
| a Waverider pattern | 58-61 % | 54 % (63-72 %) |
| a busy pattern | 59 % | 55 % (75-83 %) |
| SAVE PROJECT | 100 % for about 1 s, then 77-83 % for about 3 s | 57-61 % (76 %) |

- **The average barely moves.** The load is mostly the audio ISR, which runs every frame whatever plays.
- **What a pattern raises is the ISR's worst frame.** That peak is the ColdFire's headroom.
- **During the save,** nothing was late.
