# The front panel's LEDs (OS 1.11), and the recorder trigs on the [TRIG] LEDs (v0.45)

Read from the disassembly in 2026-11. The layout was checked against the emulator snapshot.
Grades: [D] disassembly, [M] measured in the snapshot, [I] inferred.

## The stock path

- **The LEDs live on the front-panel microcontroller**, reached over UART8 [D]. Transmit goes
  through a 4 KB ring: pointer `0x4058d5c4`, write index `0x4058d5d4`, routine `0x4000220c`.
- **`0x40132148(id, value)` is the driver** [D].
  - It maps a logical id to a physical one through `0x401f3604`: n goes to n − 1, and id 0 has no LED.
  - It keeps the last value sent for each LED at `0x466b7420[phys]` (54 bytes).
  - It sends `[0xB9, phys, value]`, and only when the value has changed.
  - Blinking: `0x40131f60`, timer `0x40131ede`.
- **`LedManager`** is a singleton [D, layout M]. Its pointer is at `0x446478e0` and its getter is `0x4018aabc`.
  - Modes are at `+40 + 4·id`, values at `+256 + 4·id`.
  - `0x4002c318(lm, id, mode, value)` is the only route to the driver.
  - **It returns at once if the LED already has a mode this refresh: the first write wins.**
- **The refresh is `0x4002c854(x)`, with screen = x + 64** [D]. It runs when the screen's `+33` is set:
  1. clears both arrays (`0x4002c3c6`);
  2. walks the views with `jsr 0x4011d3b2(screen)` at `0x4002c880`; each view's virtual +8 claims the LEDs it sets;
  3. sets every LED nobody claimed to mode 1, value 1 (unlit/backlight) and flushes (`0x4002c3ee`).

  `0x4011d314(screen)` marks the screen's LEDs dirty; `View::ledsDirty` (`0x4011c7f2`) reaches it.
- **The trig keys are logical ids 26..41** [M]. The vector at `0x4059cda4` holds them.

## Colours

The value is a **palette index**. At init the palette is uploaded with `[0xB5, idx, r, g, b]` [D],
in three sets, one per LED INTENSITY setting.

- **0** off.
- **1** the backlight white.
- **Eight hues, 16 levels each, brightest last:**
  - red 2..17
  - green 18..33
  - blue 34..49
  - yellow 50..65
  - cyan 66..81
  - magenta 82..97
  - white 98..113
  - orange 114..129
- **130..135** special colours: 132 and 133 light blue, 134 warm white.

Modes: 1 unlit (forced to value 1), 2 steady, 3 and 4 blinking (4 faster).

## v0.45: recorder trigs on the [TRIG] LEDs (`csrc/sampler/rec.c` `bn_led_walk`, `bn_led_poll`)

The owner, 2026-11-07: "a different color for rec trigs ... only visible when rec window is open".

**The hook.** `LED_SITE` = `0x4002c880`. The compose's `jsr 0x4011d3b2(screen)` becomes `jsr bn_led_walk`:
- While the BOUNCE REC panel is up (`bn_active()`), it first claims the 16 trig LEDs, then runs stock's walk.
  Because the first write wins, no stock view can light them.
- When the panel is closed it only runs stock's walk.

**What each step shows:**

| step | colour | mode, palette index |
|---|---|---|
| recorder trig | red | 2, 17 |
| one-shot armed | yellow | 2, 65 |
| one-shot spent | dim yellow | 2, 54 |
| the playing step | white | 2, 113 |
| empty, or past the pattern's length | unlit | 1, 1 |

**Keeping them current.** `bn_led_poll`, called from `rt_poll` on every UI pass, marks the screen's LEDs dirty whenever what they should show changes:
- the panel opens or closes;
- a trig is placed;
- the page turns;
- the playhead moves.

So they follow at once, and go back to stock's the moment the panel closes.

**The gate.** `rectrig`, in the panel section:
- [TRIG 3]'s LED is red and the other trig LEDs are unlit;
- removed, it is unlit again;
- closed, all 16 equal stock's from before the panel opened, and nothing more is claimed.

Not verified on hardware: the colours as seen. The LED INTENSITY sets scale them.
