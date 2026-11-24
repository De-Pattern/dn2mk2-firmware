/* v0.68 (owner, 2026-11-21): MACHINE SEL's left pane shows the machine under the cursor.
 *
 * Stock's draw (0x4005b7d4) shows, in the SRC column (+424 == 0), a wave bitmap
 * (0x401157fc at 0x4005b8ac) and "SYN" (its pea 0x40210800 at 0x4005b8c8, centred by the
 * text call that follows). For the mod's machines (dnfw.msicons.TYPE_ICON) the pane shows
 * that machine's icon and label instead; the stock machines and the FLTR column keep
 * stock's. The machine under the cursor is 0x4005b162(view), as colsw reads it.
 * (docs/machine-icons.md; the art: src/dnfw/msicons.py -> msicon_art.h) */
#include "msicon_art.h"

#define SET_PIXEL ((void (*)(void *, int, int, int))0x40113B90)
#define ROW_TYPE ((int (*)(void *))0x4005B162)
#define STOCK_LABEL ((const char *)0x40210800)          /* "SYN" */

#define PANE_CX 25                       /* the stock wave's centre: x 8..42, panel rows 18..36 */
#define PANE_CY 27

static int pane_icon(void *view)
{
    if (*(int *)((char *)view + 424) != 0)
        return -1;
    return msi_of(ROW_TYPE(view));
}

/* 1: drawn (stock's bitmap skipped); 0: stock draws its own */
int ms_icon_c(void *screen, void *view)
{
    int i = pane_icon(view);
    if (i < 0)
        return 0;
    int w = msi_w[i], h = msi_h[i];
    int x0 = PANE_CX - w / 2, y0 = PANE_CY - h / 2;
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++)
            if (msi_bits[i][y][x >> 5] & (0x80000000u >> (x & 31)))
                SET_PIXEL(screen, x0 + x, 63 - (y0 + y), 1);   /* the panel's y counts from the bottom */
    }
    return 1;
}

const char *ms_label_c(void *view)
{
    extern const char *sc_list_label(unsigned int);
    if (*(int *)((char *)view + 424) == 0) {
        const char *label = sc_list_label(ROW_TYPE(view));
        if (label) return label;
    }
    int i = pane_icon(view);
    return i < 0 ? STOCK_LABEL : msi_label[i];
}
