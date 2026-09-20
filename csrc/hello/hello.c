/* Step 0 of LFO4 (docs/lfo4-build-plan.md §8): the smallest C that proves the
 * chain -- compiled, linked at its run address, carried in a CODE chunk,
 * copied by the loader, initialised after the BSS clear, reached from a hook
 * with the hooked routine's own arguments, and calling a firmware routine.
 *
 * It watches memcpy, the routine step 1 will carry the extension table
 * through: every call is counted, the last size kept, and whole-sound copies
 * (1,163 bytes) counted apart.
 */
#include "dn2_111.h"

#define SOUND_BYTES 1163u

volatile u32 hello_ready;           /* 'HELO' once init has run */
volatile u32 hello_calls;
volatile u32 hello_last_n;
volatile u32 hello_sound_copies;
u8 hello_marker[16];                /* filled by the firmware's own memset */

void hello_init(void)
{
    dn2_memset(hello_marker, 0xA5, sizeof hello_marker);
    hello_ready = 0x48454C4Fu;
}

void hello_on_memcpy(void *dst, const void *src, u32 n)
{
    (void)dst;
    (void)src;
    hello_calls++;
    hello_last_n = n;
    if (n == SOUND_BYTES)
        hello_sound_copies++;
}
