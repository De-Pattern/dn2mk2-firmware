/* The extension table: open addressing, linear probing, no tombstones.
 *
 * Why no tombstones: the table is walked whole by every range operation, and a
 * probe that has to cross deleted slots cannot stop at the first free one. A
 * deletion instead shifts its cluster back (the standard backward shift), so a
 * free slot always ends a probe and `ext_key[i] != 0` always means a live
 * entry. The cost is that **a drop may move other entries**, which is why the
 * range operations copy keys and values out before dropping anything.
 *
 * Sizes are in `ext.h`. The table is BSS: the startup loader zeroes it before
 * `ext_init` runs (`csrc/runtime/loader.S`), and `ext_init` only has to set the
 * two bounds that are not zero.
 */
#include "ext.h"

#define MASK (EXT_SLOTS - 1u)
#define KNUTH 2654435761u              /* 2^32 / phi; one mulu.l on ColdFire */

u32 ext_key[EXT_SLOTS];
u16 ext_val[EXT_SLOTS][EXT_PARAMS];
u16 ext_default[EXT_PARAMS];

u32 ext_live, ext_lo, ext_hi, ext_generation;
u32 ext_inserts, ext_drops, ext_full, ext_overflow;

static u32 home(u32 key)
{
    return (key * KNUTH) >> (32 - EXT_SHIFT);
}

static u32 probe(u32 key)
{
    u32 i = home(key), steps = 0;

    while (ext_key[i]) {
        if (ext_key[i] == key)
            return i;
        i = (i + 1) & MASK;
        if (++steps == EXT_SLOTS)
            break;
    }
    return EXT_SLOTS;                  /* absent */
}

static void values(u32 to, const u16 *from)
{
    u32 p;

    for (p = 0; p < EXT_PARAMS; p++)
        ext_val[to][p] = from[p];
}

/* Remove the entry at `i`, then pull the rest of its cluster back so that no
 * free slot is left inside one. */
static void remove_at(u32 i)
{
    u32 j = i, k;

    ext_key[i] = 0;
    ext_live--;
    ext_drops++;
    ext_generation++;
    for (;;) {
        j = (j + 1) & MASK;
        if (!ext_key[j])
            return;
        k = home(ext_key[j]);
        if (((j - k) & MASK) < ((j - i) & MASK))
            continue;                  /* j sits at or before the hole: it must stay */
        ext_key[i] = ext_key[j];
        values(i, ext_val[j]);
        ext_key[j] = 0;
        i = j;
    }
}

void ext_init(void)
{
    ext_lo = 0xFFFFFFFFu;
    ext_hi = 0;
}

u16 *ext_find(u32 key)
{
    u32 i;

    if (!key || !ext_live)
        return 0;
    i = probe(key);
    return i == EXT_SLOTS ? 0 : ext_val[i];
}

u16 *ext_add(u32 key)
{
    u32 i;

    if (!key)
        return 0;
    i = probe(key);
    if (i != EXT_SLOTS)
        return ext_val[i];
    if (ext_live == EXT_SLOTS) {
        ext_full++;
        return 0;
    }
    i = home(key);
    while (ext_key[i])
        i = (i + 1) & MASK;
    ext_key[i] = key;
    values(i, ext_default);
    ext_live++;
    ext_inserts++;
    ext_generation++;
    if (key < ext_lo)
        ext_lo = key;
    if (key > ext_hi)
        ext_hi = key;
    return ext_val[i];
}

void ext_drop(u32 key)
{
    u32 i;

    if (!key || !ext_live)
        return;
    i = probe(key);
    if (i != EXT_SLOTS)
        remove_at(i);
}

/* Does [at, at + n) meet any byte any tracked object occupies? The bounds only
 * ever widen, so this is conservative -- and it is what keeps a large copy of
 * something that is not a sound (a frame buffer, a sample block) at two
 * compares. */
static int touches(u32 at, u32 n)
{
    return ext_live && at < ext_hi + EXT_SPAN && at + n > ext_lo;
}

/* The keys of every tracked object starting inside [at, at + n), with their
 * values if `out` is given. Returns how many; past EXT_BATCH the rest are
 * counted in `ext_overflow` and dropped rather than silently carried wrong. */
static u32 collect(u32 at, u32 n, u32 *keys, u16 (*out)[EXT_PARAMS])
{
    u32 i, p, found = 0;

    for (i = 0; i < EXT_SLOTS; i++) {
        u32 key = ext_key[i];

        if (!key || key < at || key - at >= n)
            continue;
        if (found == EXT_BATCH) {
            ext_overflow++;
            break;
        }
        keys[found] = key;
        if (out)
            for (p = 0; p < EXT_PARAMS; p++)
                out[found][p] = ext_val[i][p];
        found++;
    }
    return found;
}

void ext_copy(u32 dst, u32 src)
{
    u16 carried[EXT_PARAMS];
    const u16 *from = ext_find(src);
    u16 *to;
    u32 p;

    if (!from) {
        ext_drop(dst);                 /* the source has no entry: neither has the copy */
        return;
    }
    for (p = 0; p < EXT_PARAMS; p++)
        carried[p] = from[p];          /* an insert moves nothing, but do not depend on it */
    to = ext_add(dst);
    if (!to)
        return;
    for (p = 0; p < EXT_PARAMS; p++)
        to[p] = carried[p];
    ext_generation++;
}

void ext_carry(u32 dst, u32 src, u32 n)
{
    static u32 moved[EXT_BATCH], dead[EXT_BATCH];
    static u16 carried[EXT_BATCH][EXT_PARAMS];
    u32 i, p, taken = 0, gone;

    if (!touches(src, n) && !touches(dst, n))
        return;
    if (dst == src)
        return;
    if (touches(src, n))
        taken = collect(src, n, moved, carried);
    gone = touches(dst, n) ? collect(dst, n, dead, 0) : 0;
    for (i = 0; i < gone; i++)
        ext_drop(dead[i]);
    for (i = 0; i < taken; i++) {
        u16 *to = ext_add(dst + (moved[i] - src));

        if (!to)
            return;
        for (p = 0; p < EXT_PARAMS; p++)
            to[p] = carried[i][p];
    }
    ext_generation++;
}

void ext_clear(u32 at, u32 n)
{
    static u32 dead[EXT_BATCH];
    u32 i, gone;

    if (!touches(at, n))
        return;
    gone = collect(at, n, dead, 0);
    for (i = 0; i < gone; i++)
        ext_drop(dead[i]);
}

u16 ext_get(u32 key, u32 param)
{
    const u16 *v;

    if (param >= EXT_PARAMS)
        return 0;
    v = ext_find(key);
    return v ? v[param] : ext_default[param];
}

void ext_set(u32 key, u32 param, u16 value)
{
    u16 *v;

    if (param >= EXT_PARAMS)
        return;
    v = ext_add(key);
    if (v) {
        v[param] = value;
        ext_generation++;
    }
}
