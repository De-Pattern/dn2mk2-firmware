/* apopt: the optimal parse for dnfw's aPLib variant (v0.65, docs/packer.md).
 *
 * The format, the cost model and the limits are codec/aplibpack.py's (ported there from
 * mischa85/elektron-firmware-tool's compress.c): a literal is 9 bits; a match is a 0 bit, the
 * offset (2 bits when it reuses the last one, else gamma((offset + 767) >> 8) and a byte) and
 * the length (2 bits up to base 3, else 2 + gamma(base - 2)); offsets past 3328 take one more
 * byte of length and a minimum of 3. No match reaches further back than MAX_OFFSET (inside
 * Elektron's 1 MiB window, codec/limits.py) or copies more than MAX_MATCH bytes.
 *
 * What differs from aplibpack.pack is only the CHOICE of tokens: a forward dynamic program over
 * every position (the least bits to reach each byte, the last offset carried along its best
 * path) instead of greedy matching with one step of lookahead. The tokens are written by
 * aplibpack's own _Writer, so the bit stream is the same code's.
 *
 * Lives beside codec/aplibopt.py, which compiles it (natively) or loads apopt.wasm (built from
 * it by scripts/build_apopt_wasm.py). Built twice from this one file: natively (a shared library, called through ctypes) and for
 * wasm32 (the in-browser patcher, under Pyodide). Integer arithmetic on fixed-width types only,
 * no libc, no floating point, so both give the same tokens (test/test_apopt.py checks it).
 *
 * Memory: the caller gives one region of apopt_need(n) bytes with the n input bytes at its
 * start; apopt_plan returns the token count, and the tokens (u32 offset, u32 length; offset 0 a
 * literal) start at apopt_tokens(n). */
typedef unsigned int u32;
typedef int s32;
typedef unsigned char u8;

#define OFFSET_BIAS 767u
#define FAR_THRESHOLD 3328u
#define MIN_MATCH 2u
#define MAX_MATCH 2048u
#define MAX_OFFSET (1048576u - 4096u)
#define LITERAL_BITS 9u
#define HEADS 65536u
#define NONE 0xFFFFFFFFu

static u32 bitlen(u32 v) { u32 n = 0; while (v) { n++; v >>= 1; } return n; }
static u32 gcost(u32 v) { return 2u * (bitlen(v) - 1u); }
static u32 len_cost(u32 off, u32 len)
{
    u32 base = len - 1u - (off > FAR_THRESHOLD ? 1u : 0u);
    return base <= 3u ? 2u : 2u + gcost(base - 2u);
}
static u32 off_cost(u32 off, u32 last)
{
    return 1u + (off == last ? 2u : gcost((off + OFFSET_BIAS) >> 8) + 8u);
}
static u32 min_match(u32 off) { return off > FAR_THRESHOLD ? MIN_MATCH + 1u : MIN_MATCH; }

static u32 al(u32 x) { return (x + 7u) & ~7u; }
/* the region: input | cost | from | moff | last | prev | head | tokens */
#define O_COST(n) al((n) + 8u)
#define O_FROM(n) (O_COST(n) + al(4u * ((n) + 1u)))
#define O_MOFF(n) (O_FROM(n) + al(4u * ((n) + 1u)))
#define O_LAST(n) (O_MOFF(n) + al(4u * ((n) + 1u)))
#define O_PREV(n) (O_LAST(n) + al(4u * ((n) + 1u)))
#define O_HEAD(n) (O_PREV(n) + al(4u * ((n) + 1u)))
#define O_TOK(n) (O_HEAD(n) + 4u * HEADS)

u32 apopt_need(u32 n) { return O_TOK(n) + 8u * (n + 1u); }
u32 apopt_tokens(u32 n) { return O_TOK(n); }

u32 apopt_plan(u8 *base, u32 n, u32 depth)
{
    const u8 *d = base;
    u32 *cost = (u32 *)(base + O_COST(n));
    u32 *from = (u32 *)(base + O_FROM(n));
    u32 *moff = (u32 *)(base + O_MOFF(n));
    u32 *last = (u32 *)(base + O_LAST(n));
    u32 *prev = (u32 *)(base + O_PREV(n));
    u32 *head = (u32 *)(base + O_HEAD(n));
    u32 *tok = (u32 *)(base + O_TOK(n));

    for (u32 i = 0; i <= n; i++) cost[i] = NONE;
    for (u32 k = 0; k < HEADS; k++) head[k] = NONE;
    cost[0] = 0; last[0] = 1; from[0] = 0; moff[0] = 0;

#define RELAX(j, c, fr, o) do { if ((c) < cost[j]) { cost[j] = (c); from[j] = (fr); moff[j] = (o); last[j] = (o) ? (o) : lo; } } while (0)

    for (u32 i = 0; i < n; i++) {
        u32 c0 = cost[i];
        u32 lo = last[i];
        u32 cap = n - i < MAX_MATCH ? n - i : MAX_MATCH;
        RELAX(i + 1u, c0 + LITERAL_BITS, i, 0u);
        if (lo > 0u && lo <= i && lo <= MAX_OFFSET) {           /* the last offset again */
            u32 L = 0;
            while (L < cap && d[i - lo + L] == d[i + L]) L++;
            for (u32 l = min_match(lo); l <= L; l++)
                RELAX(i + l, c0 + off_cost(lo, lo) + len_cost(lo, l), i, lo);
        }
        if (i + 2u <= n) {                                      /* the chain, nearest first */
            u32 key = (u32)d[i] << 8 | d[i + 1u];
            u32 cand = head[key];
            u32 got = 1u;                                       /* each length takes the */
            u32 left = depth;                                   /* nearest offset reaching it */
            while (cand != NONE && left) {
                left--;
                u32 off = i - cand;
                if (off > MAX_OFFSET) break;
                if (got < cap && d[cand + got] == d[i + got]) {
                    u32 L = 0;
                    while (L < cap && d[cand + L] == d[i + L]) L++;
                    if (L > got) {
                        u32 s = got + 1u > min_match(off) ? got + 1u : min_match(off);
                        for (u32 l = s; l <= L; l++)
                            RELAX(i + l, c0 + off_cost(off, lo) + len_cost(off, l), i, off);
                        got = L;
                        if (got >= cap) break;
                    }
                }
                cand = prev[cand];
            }
            prev[i] = head[key];
            head[key] = i;
        }
    }
    u32 cnt = 0;
    for (u32 j = n; j > 0u; j = from[j]) cnt++;
    u32 k = cnt;
    for (u32 j = n; j > 0u; j = from[j]) {
        k--;
        tok[2u * k] = moff[j];
        tok[2u * k + 1u] = j - from[j];
    }
    return cnt;
}
