#define WR_PAGES 2
static const unsigned short wr_ids[WR_PAGES][8] = {
 {238, 242, 254, 241, 256, 257, 260, 240},
 {239, 246, 250, 244, 243, 258, 253, 252}
};
static const char wr_labels[WR_PAGES][8][6] = {
 {"-", "-", "-", "-", "-", "-", "-", "-"},
 {"-", "-", "-", "-", "-", "-", "-", "-"}
};
#define WR_NAMED 25
static const unsigned short wr_named_ids[WR_NAMED] = {238, 239, 240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 250, 251, 252, 253, 254, 255, 256, 257, 258, 259, 260, 261, 262};
#define WR_KINDS 9
static const char *const wr_named_long[WR_KINDS][WR_NAMED] = {{0, "Amp Mod Depth", 0, 0, 0, "Filter Base", "EQ Gain", "Unused", "Amp Mod Rate", "Unused", "Unused", "Unused", "EQ Freq", "Unused", "Perc Type", "Filter Q", 0, "Unused", 0, 0, "Filter Width", "Unused", 0, "Unused", "Unused"}, {"Pulse Width", "Unused", "Tune", "Waveform", "PW Sweep", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "PW Restart", "Unused", "Modulation", "Mod Source", "Unused", "Unused", "Mod Freq", "Unused", "Unused"}, {"Waveform", "Unused", "Tune", "WP Restart", "Wave Position", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "WP Mod", "Unused", "Sync", "Sync Freq", "Unused", "Unused", "Unused", "Unused", "Unused"}, {"Tune", "Start", "Unused", "Sample Level", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Play Mode", "Unused", "Sample Slot", "Loop Pos", "Length", "Unused", "Unused", "Unused", "Unused"}, {"Tune", "Unused", "Bars", "Sample Level", "Segment Size", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Play Mode", "Segment Mode", "Sample Slot", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused"}, {"Tune", "Start", "Bars", "Sample Level", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Play Mode", "Unused", "Sample Slot", "Unused", "Length", "Unused", "Unused", "Unused", "Unused"}, {"Unused", "Start", "Bars", "Sample Level", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Play Mode", "Unused", "Sample Slot", "Unused", "Length", "Unused", "Unused", "Unused", "Unused"}, {"Tune", "Slice Grid", "Unused", "Sample Level", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Play Mode", "Unused", "Sample Slot", "Slice Select", "Unused", "Unused", "Slice Length", "Unused", "Unused"}, {"Tune", "Unused", "Unused", "Sample Level", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused", "Play Mode", "Unused", "Sample Slot", "Slice Select", "Unused", "Unused", "Slice Length", "Unused", "Unused"}};
static const char *const wr_named_short[WR_KINDS][WR_NAMED] = {{0, "AMD", 0, 0, 0, "FLTF", "EQG", "-", "AMF", "-", "-", "-", "EQF", "-", "TYPE", "FLTQ", 0, "-", 0, 0, "FLTW", "-", 0, "-", "-"}, {"PW", "-", "TUNE", "WAVE", "PWAD", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "PWRS", "-", "MOD", "MSRC", "-", "-", "MFRQ", "-", "-"}, {"WAVE", "-", "TUNE", "WPRS", "WP", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "WPM", "-", "SYNC", "SFRQ", "-", "-", "-", "-", "-"}, {"TUNE", "STRT", "-", "LEV", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "PLAY", "-", "SAMP", "LOOP", "LEN", "-", "-", "-", "-"}, {"TUNE", "-", "BARS", "LEV", "SEG", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "PLAY", "MODE", "SAMP", "-", "-", "-", "-", "-", "-"}, {"TUNE", "STRT", "BARS", "LEV", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "PLAY", "-", "SAMP", "-", "LEN", "-", "-", "-", "-"}, {"-", "STRT", "BARS", "LEV", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "PLAY", "-", "SAMP", "-", "LEN", "-", "-", "-", "-"}, {"TUNE", "GRID", "-", "LEV", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "PLAY", "-", "SAMP", "SLCE", "-", "-", "LEN", "-", "-"}, {"TUNE", "-", "-", "LEV", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "PLAY", "-", "SAMP", "SLCE", "-", "-", "LEN", "-", "-"}};
#define PERC_N 34
#define PERC_TYPE_ID 252
static const char perc_machine[PERC_N][7] = {"TRX-BD", "TRX-B2", "TRX-SD", "TRX-XT", "TRX-CP", "TRX-RS", "TRX-CB", "TRX-CH", "TRX-OH", "TRX-CY", "TRX-MA", "TRX-CL", "TRX-XC", "TRX-S2", "EFM-BD", "EFM-SD", "EFM-XT", "EFM-CP", "EFM-RS", "EFM-CB", "EFM-HH", "EFM-CY", "GND-SN", "GND-NS", "GND-IM", "PI-BD", "PI-SD", "PI-MT", "PI-ML", "PI-MA", "PI-RS", "PI-RC", "PI-CC", "PI-HH"};
static const char perc_what[PERC_N][12] = {"Bass Drum", "Bass Drum 2", "Snare", "Tom", "Clap", "Rimshot", "Cowbell", "Closed Hat", "Open Hat", "Cymbal", "Maracas", "Claves", "Conga", "Snare 2", "Bass Drum", "Snare", "Tom", "Clap", "Rimshot", "Cowbell", "Hi-Hat", "Cymbal", "Sine", "Noise", "Impulse", "Bass Drum", "Snare", "Tom", "Metallica", "Maracas", "Rimshot", "Ride", "Crash", "Hi-Hat"};
static const unsigned short perc_param_ids[8] = {238, 242, 254, 241, 256, 257, 260, 240};
static const char perc_short[PERC_N][8][5] = {
 {"PTCH", "DEC", "RAMP", "RDEC", "STRT", "NOIS", "HARM", "CLIP"},
 {"PTCH", "DEC", "RAMP", "HOLD", "TICK", "NOIS", "DIRT", "DIST"},
 {"PTCH", "DEC", "BUMP", "BENV", "SNAP", "TONE", "TUNE", "CLIP"},
 {"PTCH", "DEC", "RAMP", "RDEC", "DAMP", "DIST", "DTYP", "-"},
 {"CLPY", "TONE", "HARD", "RICH", "RATE", "ROOM", "RSIZ", "RTUN"},
 {"PTCH", "DEC", "DIST", "-", "-", "-", "-", "-"},
 {"PTCH", "DEC", "ENH", "DAMP", "TONE", "BUMP", "-", "-"},
 {"GAP", "DEC", "HPF", "LPF", "MTAL", "-", "-", "-"},
 {"GAP", "DEC", "HPF", "LPF", "MTAL", "-", "-", "-"},
 {"RICH", "DEC", "TOP", "TTUN", "SIZE", "PEAK", "-", "-"},
 {"ATT", "SUS", "REV", "DAMP", "RATL", "RTYP", "TONE", "HARD"},
 {"PTCH", "DEC", "DUAL", "ENH", "TUNE", "CLIC", "-", "-"},
 {"PTCH", "DEC", "RAMP", "RDEC", "DAMP", "DIST", "DTYP", "-"},
 {"PTCH", "DEC", "NOIS", "NDEC", "POWR", "TUNE", "NTUN", "NTYP"},
 {"PTCH", "DEC", "RAMP", "RDEC", "MOD", "MFRQ", "MDEC", "MFB"},
 {"PTCH", "DEC", "NOIS", "NDEC", "MOD", "MFRQ", "MDEC", "HPF"},
 {"PTCH", "DEC", "RAMP", "RDEC", "MOD", "MFRQ", "MDEC", "CLIC"},
 {"PTCH", "DEC", "CLPS", "CDEC", "MOD", "MFRQ", "MDEC", "HPF"},
 {"PTCH", "DEC", "MOD", "HPF", "SNAR", "SPTC", "SDEC", "SMOD"},
 {"PTCH", "DEC", "SNAP", "FB", "MOD", "MFRQ", "MDEC", "-"},
 {"PTCH", "DEC", "TREM", "TFRQ", "MOD", "MFRQ", "MDEC", "FB"},
 {"PTCH", "DEC", "FB", "HPF", "MOD", "MFRQ", "MDEC", "-"},
 {"PTCH", "DEC", "RAMP", "RDEC", "-", "-", "-", "-"},
 {"DEC", "-", "-", "-", "-", "-", "-", "-"},
 {"UP", "UVAL", "DOWN", "DVAL", "-", "-", "-", "-"},
 {"PTCH", "DEC", "HARD", "HAMR", "TENS", "DAMP", "-", "-"},
 {"PTCH", "DEC", "HARD", "RING", "TENS", "RVOL", "RDEC", "-"},
 {"PTCH", "DEC", "HARD", "HAMR", "TUNE", "DAMP", "SIZE", "POS"},
 {"PTCH", "DEC", "HARD", "TENS", "-", "-", "-", "-"},
 {"GRNS", "DEC", "GLEN", "SIZE", "HARD", "-", "-", "-"},
 {"PTCH", "DEC", "HARD", "RING", "RVOL", "RDEC", "-", "-"},
 {"PTCH", "DEC", "HARD", "RING", "AG", "AU", "BR", "GRAB"},
 {"PTCH", "DEC", "HARD", "RING", "AG", "AU", "BR", "GRAB"},
 {"PTCH", "DEC", "CLSN", "RING", "AG", "AU", "BR", "CLOS"}
};
static const char *const perc_longs[76] = {"Attack", "Bump", "Bump Env", "Clap Decay", "Claps", "Click", "Clip", "Close Time", "Closeness", "Damping", "Decay", "Dirt", "Dist Type", "Distortion", "Down", "Down Value", "Dual", "Enhance", "Feedback", "Gap", "Grab", "Grain Length", "Grains", "Hammer", "Hardness", "Harmonics", "High-Pass", "Highs Down", "Highs Up", "Hold", "Low-Pass", "Lows", "Metal", "Mod Amount", "Mod Decay", "Mod Feedback", "Mod Freq", "Noise", "Noise Decay", "Noise Tune", "Noise Type", "Peak", "Pitch", "Position", "Power", "Ramp", "Ramp Decay", "Rate", "Rattle", "Rattle Type", "Rattle Vol", "Reverse", "Richness", "Ring", "Room", "Room Size", "Room Tune", "Size", "Snap", "Snare", "Snare Decay", "Snare Mod", "Snare Pitch", "Start", "Sustain", "Tension", "Tick", "Tone", "Top", "Top Tune", "Trem Freq", "Tremolo", "Tune", "Unused", "Up", "Up Value"};
static const unsigned char perc_long[PERC_N][8] = {
 {42, 10, 45, 46, 63, 37, 25, 6},
 {42, 10, 45, 29, 66, 37, 11, 13},
 {42, 10, 1, 2, 58, 67, 72, 6},
 {42, 10, 45, 46, 9, 13, 12, 73},
 {4, 67, 24, 52, 47, 54, 55, 56},
 {42, 10, 13, 73, 73, 73, 73, 73},
 {42, 10, 17, 9, 67, 1, 73, 73},
 {19, 10, 26, 30, 32, 73, 73, 73},
 {19, 10, 26, 30, 32, 73, 73, 73},
 {52, 10, 68, 69, 57, 41, 73, 73},
 {0, 64, 51, 9, 48, 49, 67, 24},
 {42, 10, 16, 17, 72, 5, 73, 73},
 {42, 10, 45, 46, 9, 13, 12, 73},
 {42, 10, 37, 38, 44, 72, 39, 40},
 {42, 10, 45, 46, 33, 36, 34, 35},
 {42, 10, 37, 38, 33, 36, 34, 26},
 {42, 10, 45, 46, 33, 36, 34, 5},
 {42, 10, 4, 3, 33, 36, 34, 26},
 {42, 10, 33, 26, 59, 62, 60, 61},
 {42, 10, 58, 18, 33, 36, 34, 73},
 {42, 10, 71, 70, 33, 36, 34, 18},
 {42, 10, 18, 26, 33, 36, 34, 73},
 {42, 10, 45, 46, 73, 73, 73, 73},
 {10, 73, 73, 73, 73, 73, 73, 73},
 {74, 75, 14, 15, 73, 73, 73, 73},
 {42, 10, 24, 23, 65, 9, 73, 73},
 {42, 10, 24, 53, 65, 50, 46, 73},
 {42, 10, 24, 23, 72, 9, 57, 43},
 {42, 10, 24, 65, 73, 73, 73, 73},
 {22, 10, 21, 57, 24, 73, 73, 73},
 {42, 10, 24, 53, 50, 46, 73, 73},
 {42, 10, 24, 53, 28, 27, 31, 20},
 {42, 10, 24, 53, 28, 27, 31, 20},
 {42, 10, 8, 53, 28, 27, 31, 7}
};
#define MDUI_KNOB 8
#define MDUI_CLIP 52
#define MDUI_PTR 84
#define MDUI_FONT 1876
#define MDUI_FONT_BYTES 1537
#define MDUI_FONT_STRIDE 16
#define MDUI_MACH 6487
#define MDUI_MACH_BYTES 10
#define MDUI_KNOB_COLS 11
#define MDUI_CLIP_COLS 8
#define MDUI_PTR_COLS 7
#define MDUI_VERSION 1
#define MDUI_LOAD 0x46ae0000u
#define MD_FX_NIBBLES 0x31313311u
#define TRACK_LEVEL_ID 10
static const char perc_what_upper[PERC_N][12] = {"BASS DRUM", "BASS DRUM 2", "SNARE", "TOM", "CLAP", "RIMSHOT", "COWBELL", "CLOSED HAT", "OPEN HAT", "CYMBAL", "MARACAS", "CLAVES", "CONGA", "SNARE 2", "BASS DRUM", "SNARE", "TOM", "CLAP", "RIMSHOT", "COWBELL", "HI-HAT", "CYMBAL", "SINE", "NOISE", "IMPULSE", "BASS DRUM", "SNARE", "TOM", "METALLICA", "MARACAS", "RIMSHOT", "RIDE", "CRASH", "HI-HAT"};
#define SMP_KIND0 4
#define SMP_N 6
#define WR_TYPES_LAST 13
static const unsigned short smp_ids[SMP_N][8] = {
 {238, 254, 0, 256, 239, 258, 257, 241},
 {238, 254, 0, 256, 242, 255, 240, 241},
 {238, 254, 0, 256, 239, 258, 240, 241},
 {0, 254, 0, 256, 239, 258, 240, 241},
 {238, 254, 0, 256, 257, 260, 239, 241},
 {238, 254, 0, 256, 257, 260, 0, 241}
};
static const char smp_machine[SMP_N][8] = {"ONESHOT", "WERP", "STRETCH", "REPITCH", "GRID", "SLICE"};
#define SMP_PLAY_ID 254
#define SMP_SAMP_ID 256
#define SMP_STRT_ID 239
#define SMP_LEN_ID 258
#define SMP_LOOP_ID 257
#define SMP_GRID_ID 239
#define SMP_SLICE_ID 257
#define SMP_SLEN_ID 260
#define SMP_GRID_KIND 8
#define SMP_WERP_KIND 5
#define SMP_SLICE_KIND 9
#define SMP_STRETCH_KIND 6
#define SMP_REPITCH_KIND 7
#define SMP_BARS_ID 240
#define SMP_SEG_ID 242
#define SMP_MODE_ID 255
static const unsigned short smp_rec_ids[8] = {252, 259, 0, 243, 248, 253, 251, 247};
#define SMP_RSRC_ID 252
#define SMP_RCHAN_ID 259
#define SMP_RTHR_ID 243
#define SMP_RDST_ID 248
#define SMP_RLEN_ID 253
#define SMP_RSTRT_ID 251
#define SMP_ARM_ID 247
#define SMP_REC_FIRST 123
#define SMP_REC_SECONDS10 660
#define SMP_REC_SOURCES 20
static const char smp_rec_chan[3][4] = {"L+R", "L", "R"};
static const char smp_rec_src[20][8] = {"EXT L+R", "EXT L", "EXT R", "MAIN", "TRK1", "TRK2", "TRK3", "TRK4", "TRK5", "TRK6", "TRK7", "TRK8", "TRK9", "TRK10", "TRK11", "TRK12", "TRK13", "TRK14", "TRK15", "TRK16"};
static const char smp_bars[8][4] = {"1", "2", "4", "8", "8", "8", "8", "8"};
static const unsigned char smp_bars_steps[7] = {13, 38, 63, 255, 255, 255, 255};
static const unsigned char smp_seg_steps[7] = {40, 80, 255, 255, 255, 255, 255};
static const char smp_play[4][5] = {"REV", "REVL", "FWDL", "FWD"};
static const unsigned char smp_grids[5] = {4, 8, 16, 32, 64};
#define SMP_WAVE_W 100
#define SMP_WAVE_AMP 11
#define W_NONE 0
#define W_BIPOLAR 1
#define W_PLAY 2
#define W_EMPTY 3
#define W_SAMP 4
#define W_KNOB 5
#define W_FADER 6
#define W_SEG 7
#define W_BARS 8
#define SMP_WIDGETS 11
static const unsigned short smp_widget_ids[SMP_WIDGETS] = {238, 239, 240, 241, 242, 254, 255, 256, 257, 258, 260};
static const unsigned char smp_widget_kind[SMP_WIDGETS] = {1, 5, 8, 6, 7, 2, 2, 4, 5, 5, 5};
static const char smp_glyph_chars[] = "0123456789AB/-YES";
static const unsigned char smp_glyph[17][5] = {{7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}, {7, 1, 7, 4, 7}, {7, 1, 7, 1, 7}, {5, 5, 7, 1, 1}, {7, 4, 7, 1, 7}, {7, 4, 7, 5, 7}, {7, 1, 1, 1, 1}, {7, 5, 7, 5, 7}, {7, 5, 7, 1, 7}, {2, 5, 7, 5, 5}, {6, 5, 6, 5, 6}, {1, 1, 2, 4, 4}, {0, 0, 7, 0, 0}, {5, 5, 2, 2, 2}, {7, 4, 6, 4, 7}, {3, 4, 2, 1, 6}};
static const unsigned char smp_test_wave[4][SMP_WAVE_W] = {{10, 9, 9, 9, 9, 9, 9, 8, 8, 6, 8, 6, 7, 7, 7, 7, 5, 7, 5, 6, 6, 4, 6, 6, 3, 5, 5, 4, 5, 5, 4, 3, 5, 5, 3, 4, 4, 4, 2, 4, 4, 4, 2, 4, 4, 3, 2, 3, 3, 3, 1, 3, 3, 3, 1, 2, 3, 3, 2, 2, 3, 3, 2, 1, 2, 2, 2, 1, 2, 2, 2, 1, 1, 2, 2, 1, 1, 2, 2, 2, 1, 1, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1}, {10, 9, 9, 8, 8, 7, 8, 6, 8, 7, 6, 7, 5, 5, 5, 6, 5, 5, 5, 5, 4, 3, 4, 3, 4, 3, 4, 3, 2, 3, 3, 3, 2, 3, 3, 3, 2, 3, 2, 2, 2, 2, 2, 1, 2, 1, 1, 2, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}, {7, 8, 8, 4, 6, 7, 6, 8, 7, 6, 5, 4, 6, 4, 4, 5, 5, 5, 4, 4, 3, 4, 2, 3, 3, 3, 2, 3, 2, 2, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 2, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}, {8, 8, 7, 6, 5, 5, 4, 0, 0, 0, 0, 0, 7, 5, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 8, 6, 4, 3, 2, 2, 7, 4, 2, 1, 0, 0, 7, 5, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 8, 8, 7, 6, 5, 5, 4, 0, 0, 0, 0, 0, 7, 5, 2, 1, 0, 0, 8, 8, 7, 6, 6, 5, 5, 8, 6, 4, 3, 2, 2, 1, 0, 0, 0, 0, 0, 7, 5, 2, 1, 0, 0, 7, 6, 3, 1, 0, 0, 0}};
struct smp_q { unsigned char types, slot, n, th[17], rep[18]; };
struct smp_qs { unsigned char types, slot, step, lo, hi; };
#define SMP_NQ 5
static const struct smp_q smp_q[SMP_NQ] = {
 {63, 41, 4, {32, 64, 96, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255}, {0, 32, 64, 127, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}},
 {2, 42, 4, {32, 64, 96, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255}, {0, 32, 64, 127, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}},
 {14, 29, 4, {13, 38, 63, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255}, {0, 25, 50, 75, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}},
 {2, 31, 3, {44, 84, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255}, {24, 64, 104, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}},
 {16, 26, 5, {24, 48, 72, 96, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255}, {0, 24, 48, 72, 96, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}
};
#define SMP_NQS 2
static const struct smp_qs smp_qs[SMP_NQS] = {
 {48, 44, 2, 0, 127},
 {48, 47, 2, 0, 127}
};
#define SMP_PLAY_REC 254
#define SMP_MODE_REC 255
#define SMP_BARS_REC 240
#define SMP_SEG_REC 242
#define SMP_GRID_REC 239
#define SMP_SAMP_REC 256
#define SMP_SEG_LO 4
#define SMP_SEG_SLOT 31
#define SMP_SOUNDS 4
static const char smp_sound[SMP_SOUNDS][6] = {"KICK", "SNARE", "HAT", "BEAT"};
#define MNM_N 2
/* is_wr's kind -> the Monomachine machine's index, -1 for any other kind */
static inline int mnm_index(int kind)
{
    if (kind == 2) return 0;
    if (kind == 3) return 1;
    return -1;
}
#define MNM_WAVES 32
static const char mnm_labels[MNM_N][8][6] = {{"PW", "PWAD", "PWRS", "WAVE", "MOD", "MSRC", "MFRQ", "TUNE"}, {"WAVE", "WP", "WPM", "WPRS", "SYNC", "SFRQ", "-", "TUNE"}};
static const unsigned char mnm_lo[8] = {4, 4, 0, 0, 0, 0, 0, 0};
static const unsigned char mnm_top[8] = {120, 120, 127, 127, 127, 127, 127, 100};
static const unsigned char mnm_choices[MNM_N][8] = {{0, 0, 2, 5, 4, 2, 0, 0}, {32, 0, 0, 2, 3, 0, 0, 0}};
static const unsigned char mnm_choice_at[MNM_N][8] = {{0, 0, 0, 2, 7, 11, 0, 0}, {0, 0, 0, 13, 15, 0, 0, 0}};
static const char mnm_choice_names[18][5] = {"OFF", "ON", "TRI", "SAW", "PULS", "MIX", "NOIS", "OFF", "RING", "SYNC", "R+S", "MFRQ", "PRCH", "OFF", "ON", "OFF", "SFRQ", "PRCH"};
#define PING_SETS 3
static const signed char ping_filters[PING_SETS] = {6, 7, 8};
#define PING_NAMED 10
static const unsigned short ping_named_ids[PING_NAMED] = {36, 37, 38, 44, 45, 46, 47, 48, 49, 51};
static const char *const ping_named_long[PING_SETS][PING_NAMED] = {{0, "Ring Time", "Ping Type", "Ping Drive", 0, 0, "Env. Curve", "Strike", 0, 0}, {"Shift", "Shift Feedback", "Shift Mode", "Shift Drive", 0, 0, "Shift Mix", "Unused", 0, 0}, {"Grain Size", "Grain Density", "Grain Mode", "Grain Drive", "Grain Feedback", "Unused", "Grain Mix", "Unused", "Grain Spread", "Unused"}};
static const char *const ping_named_short[PING_SETS][PING_NAMED] = {{0, "RING", "TYPE", "DRIV", 0, 0, "CURV", "STRK", 0, 0}, {"SHFT", "FDBK", "MODE", "DRIV", 0, 0, "MIX", "-", 0, 0}, {"SIZE", "DENS", "MODE", "DRIV", "FDBK", "-", "MIX", "-", "SPRD", "-"}};
#define PING_TYPE_ID 38
static const unsigned char ping_type_count[PING_SETS] = {4, 3, 4};
static const char ping_type_text[PING_SETS][4][5] = {{"SVF", "LADR", "VCFQ", "LPG"}, {"UP", "DOWN", "BOTH"}, {"NORM", "UP", "DOWN", "REV"}};
