// derived from irpina/digihealth (tools/digiusb.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project
//
// The USB probe panel, added at the foot of scripts/midi_live_page.html by
// tools/dn2live.py. It opens its own EventSource and listens for the named
// events dn2live sends -- state, backlog, probe, probe-status, probe-cost,
// probe-error, probe-lfo4, probe-watch, mark -- and never touches the MIDI view's code, only hides it
// when the MIDI view is switched off.
(() => {
"use strict";
const GRAPH_S = 60, KEEP_S = 75, LATE_BELOW = 1495;
const $ = id => document.getElementById(id);
const el = (tag, attrs = {}, html = "") => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (html) e.innerHTML = html;
  return e;
};
const fx = (v, nd = 1) => (v === null || v === undefined) ? "--" : Number(v).toFixed(nd);

// ---- the MIDI view gets a wrapper, so it can be hidden in one place ----------
const wrap = document.querySelector(".wrap");
const midiView = el("div", { id: "midi-view" });
{
  const bar = wrap.querySelector(".bar"), foot = wrap.querySelector("footer");
  let n = bar.nextSibling;
  while (n && n !== foot) { const next = n.nextSibling; midiView.appendChild(n); n = next; }
  wrap.insertBefore(midiView, foot);
}

// ---- the panel -------------------------------------------------------------
// the fourth window is the ColdFire -> SHARC USB-audio stream: the frame ISR zeroes it
// every frame unless USB audio streams in, so STILL is correct (docs/usbprobe.md)
const LINKS = ["SHARC reply", "control frame", "audio in", "USB audio → SHARC"];
const PIECES = ["on_save", "on_load", "memcpy", "memset", "refresh"];
// categorical slots 3-7 of the reference palette, dark steps (1-2 are the ISR lines);
// they overlap on one lane, so each also has a dash pattern and a direct label
const PIECE_COLOR = ["#199e70", "#c98500", "#d55181", "#9085e9", "#008300"];
const PIECE_DASH = [[], [6, 3], [2, 3], [8, 3, 2, 3], [1, 2]];
const panel = el("section", { id: "probe" }, `
  <h2>USB probe <span class="pill" id="p-pill">connecting</span></h2>
  <div class="bar">
    <button id="p-mark" title="Drop a labelled marker on the graph and in the log (key M)">Mark</button>
    <input type="text" id="p-label" value="save pressed" aria-label="Marker label">
    <span class="lab"><kbd>M</kbd> marks</span>
    <span class="sep"></span>
    <button id="p-midi" aria-pressed="true" title="Stop forwarding and drawing MIDI events, and allow faster polling">MIDI view on</button>
    <span class="sep"></span>
    <span class="lab">poll</span>
    <span id="p-rates"></span>
    <button id="p-cal" title="Poll at 5 Hz then 25 Hz for 5 s each and measure the context switches one request costs. Keep the instrument steady meanwhile.">Measure probe cost</button>
    <span class="rate" id="p-log">&nbsp;</span>
  </div>
  <div id="p-absent" hidden></div>
  <div id="p-live">
    <div class="grid" id="p-tiles"></div>
    <div class="links" id="p-links"></div>
    <div id="p-watch"><h2>Memory watches <span class="pill">PEEK after each STATS · read-only</span></h2>
      <div class="bar">
        <span class="lab">frame, track</span>
        <select id="p-w-track" aria-label="Track">${Array.from({ length: 16 }, (_, i) => `<option>${i + 1}</option>`).join("")}</select>
        <button id="p-w-frame" title="TUN1, WAV1, TBL1, TUN2 and the rest of the track's slot in the ColdFire → SHARC frame, with its note, level and machine">Watch frame</button>
        <span class="sep"></span>
        <input type="text" id="p-w-spec" value="0x800068e4+32" aria-label="Watch spec"
          title="ADDR+LEN[:u8|u16|s16|u32], or frame:T">
        <button id="p-w-add">Watch</button>
        <span class="rate" id="p-w-msg">&nbsp;</span>
      </div>
      <div id="p-w-list"></div></div>
    <div id="p-lfo4" hidden><h2>lfo4's pieces <span class="pill">PEEK after each STATS · µs of DTCN0</span></h2>
      <div class="scroll"><table><thead><tr><th>Piece</th><th>Calls / s</th><th>µs / s</th>
      <th>Peak µs (recent)</th><th>Peak µs (boot)</th><th>Calls since boot</th></tr></thead>
      <tbody id="p-lfo4-rows"></tbody></table></div>
      <div class="meta" id="p-lfo4-fast"></div></div>
    <div id="p-graph-wrap"><canvas id="p-graph" style="height:360px"></canvas><div id="p-tip"></div></div>
    <div class="legend">
      <span><span class="sw" style="background:var(--s-avg)"></span>ISR average</span>
      <span><span class="sw" style="background:var(--s-peak)"></span>ISR peak (per request)</span>
      <span><span class="sw" style="background:var(--ink)"></span>frames/s · context switches/s</span>
      <span><span class="sw dash"></span>100 % of a frame · 1500 and ${LATE_BELOW} frames/s</span>
      <span><span class="sw" style="background:var(--late)"></span>late: peak ≥ 100 %, an ISR over a frame, or frames/s &lt; ${LATE_BELOW}</span>
      <span id="p-leg-lfo4" hidden>lfo4 pieces: ${PIECES.map((p, i) => `<span class="sw" style="background:${PIECE_COLOR[i]}"></span>${p}`).join(' · ')}</span>
      <span><span class="sw" style="background:var(--amber)"></span>mark</span>
    </div>
    <div id="p-extra" hidden><h2>Fields this page does not know</h2>
      <div class="scroll"><table><thead><tr><th>Offset</th><th>Word</th><th>Value</th><th>Hex</th><th>Δ per reply</th></tr></thead>
      <tbody id="p-extra-rows"></tbody></table></div></div>
    <div id="p-note"></div>
  </div>`);
wrap.insertBefore(panel, wrap.querySelector("footer"));

const TILES = [
  ["frames", "Audio frames / s", "vs 1500"],
  ["isr", "Audio ISR avg", "% of a frame"],
  ["peak", "ISR peak, last 1 s", "% of a frame"],
  ["sw", "Context switches / s", ""],
  ["late", "Frames late / missed", ""],
  ["cpu", "CPU", ""],
  ["timer", "Timer", "DTCN0"],
  ["rtt", "Round trip", ""],
  ["over", "ISRs over a frame", "layout 2"],
  ["idle", "Idle task", "layout 2"],
];
const tiles = {};
for (const [k, name, meta] of TILES) {
  const c = el("div", { class: "cell" }, `<div class="id"><span>${name}</span><span class="tag"></span></div>
    <div class="val">--</div><div class="meta">${meta}</div>`);
  $("p-tiles").appendChild(c);
  tiles[k] = { el: c, val: c.querySelector(".val"), meta: c.querySelector(".meta"), tag: c.querySelector(".tag") };
  if (k === "over" || k === "idle") c.hidden = true;     // layout 2 only
}
const chips = LINKS.map(n => {
  const c = el("div", { class: "chip" }, `<span class="nm">${n}</span><span><span class="st waiting">--</span><span class="un"></span></span>`);
  $("p-links").appendChild(c);
  return { st: c.querySelector(".st"), un: c.querySelector(".un") };
});

// ---- state -----------------------------------------------------------------
let lfo4s = [];
const WATCH_S = 20;             // the sparkline's span
let watchNames = [], maxWatches = 8;
const watchData = {};           // name -> {last, hist: [[t, [words]]], box, rows}
let readings = [], marks = [], lastErr = null, status = {}, cost = null, midiOn = true;
let rates = [10, 25, 50], midiMaxHz = 10, dirty = true, hoverT = null;

function setRateButtons() {
  const box = $("p-rates");
  box.textContent = "";
  for (const hz of rates) {
    const b = el("button", { "aria-pressed": String(Number(status.rate_hz) === hz) }, hz + " Hz");
    if (midiOn && hz > midiMaxHz) {
      b.disabled = true;
      b.title = "switch the MIDI view off for more than " + midiMaxHz + " Hz";
    }
    b.onclick = () => fetch("/rate?hz=" + hz).then(r => r.json()).then(r => {
      if (r.message) $("p-log").textContent = r.message;
    });
    box.appendChild(b);
  }
}

function setMidi(on) {
  midiOn = on;
  midiView.hidden = !on;
  const b = $("p-midi");
  b.setAttribute("aria-pressed", String(on));
  b.textContent = on ? "MIDI view on" : "MIDI view off";
  setRateButtons();
}

function onState(s) {
  if (s.status && s.status.state) onStatus(s.status);
  if (s.cost) cost = s.cost;
  if (s.rates) rates = s.rates;
  if (s.midi_on_max_hz) midiMaxHz = s.midi_on_max_hz;
  setMidi(!!s.midi_on);
  if (s.watches) setWatches(s.watches, s.max_watches);
  if (s.log) $("p-log").textContent = "log " + s.log.replace(/^.*[\\/](out[\\/])/, "$1");
  if (s.log) $("p-log").title = s.log + "\n" + (s.jsonl || "");
  note();
}

function onStatus(s) {
  status = s;
  const pill = $("p-pill"), absent = $("p-absent");
  const who = s.tag ? `${s.tag} · protocol ${s.proto} · up ${s.boot_s} s at HELLO` : "";
  const txt = {
    searching: "looking for the probe (HELLO)",
    present: "answering · " + who + (s.calibrating ? " · measuring its cost" : ""),
    absent: "no probe on this firmware",
    lost: "the probe stopped answering",
  }[s.state] || s.state;
  pill.textContent = txt;
  panel.classList.toggle("absent", s.state === "absent" || s.state === "lost");
  absent.hidden = !(s.state === "absent" || s.state === "lost");
  if (s.state === "absent") {
    absent.innerHTML = "<b>No probe on this firmware</b>HELLO on the probe's channel (F0 00 20 3C 7D 00) " +
      "has had no answer. Stock firmware drops it, which is harmless; the MIDI view above keeps working. " +
      "On a usbprobe build, USB CONFIG must be USB MIDI or Overbridge. HELLO is retried every 3 s; after a " +
      "flash, press <i>Reopen port</i>.";
  } else if (s.state === "lost") {
    absent.innerHTML = "<b>The probe stopped answering</b>No STATS reply for 2 s: a reflash, a freeze, or the " +
      "cable. Looking for it again; press <i>Reopen port</i> after a flash.";
  }
  setRateButtons();
  $("p-cal").disabled = s.state !== "present" || !!s.calibrating;
  note();
}

function onProbe(r) {
  readings.push(r);
  const cut = r.t - KEEP_S;
  while (readings.length && readings[0].t < cut) readings.shift();
  render(r);
  dirty = true;
}

function onLfo4(e) {
  lfo4s.push(e);
  const cut = e.t - KEEP_S;
  while (lfo4s.length && lfo4s[0].t < cut) lfo4s.shift();
  renderLfo4();
  dirty = true;
}

function renderLfo4() {
  const last = lfo4s[lfo4s.length - 1];
  $("p-lfo4").hidden = !last;
  $("p-leg-lfo4").hidden = !last;
  if (!last) return;
  // per second: the sum over the replies of the last second
  const win = lfo4s.filter(e => e.t > last.t - 1);
  const span = win.length > 1 ? Math.max(0.1, last.t - win[0].t + (last.t - win[0].t) / (win.length - 1)) : 1;
  const tb = $("p-lfo4-rows");
  tb.textContent = "";
  PIECES.forEach((p, i) => {
    const n = win.reduce((a, e) => a + e.pieces[p].n, 0) / span;
    const us = win.reduce((a, e) => a + (e.pieces[p].us || 0), 0) / span;
    const q = last.pieces[p];
    const tr = el("tr");
    tr.appendChild(el("td", { class: "num" },
      `<span class="sw" style="display:inline-block;width:12px;height:3px;background:${PIECE_COLOR[i]};vertical-align:middle;margin-right:6px"></span>${p}`));
    for (const v of [fx(n, 0), fx(us, 1), fx(q.peak_us, 1), fx(q.max_us, 1), String(q.count)])
      tr.appendChild(el("td", { class: "num" }, v));
    tb.appendChild(tr);
  });
  const f = last.fast;
  $("p-lfo4-fast").textContent = "per reply: memcpy " + f.memcpy_calls + " · memset " + f.memset_calls +
    " · evaluator skips A " + f.skip_a + " / B " + f.skip_b + (last.clock ? "" : " · µs need DTCN0 running");
}

// ---- the watches -------------------------------------------------------------------
function setWatches(names, max) {
  watchNames = names;
  if (max) maxWatches = max;
  for (const n of Object.keys(watchData)) if (!names.includes(n)) { watchData[n].box.remove(); delete watchData[n]; }
  for (const n of names) if (!watchData[n]) watchData[n] = newWatch(n);
  $("p-w-add").disabled = $("p-w-frame").disabled = names.length >= maxWatches;
}

function newWatch(name) {
  const box = el("div", { class: "watch" }, `<div class="w-head"><span class="w-name"></span>
    <span class="w-age">waiting for a reading</span><button class="w-drop" title="Stop watching">×</button></div>
    <div class="scroll"><table><thead><tr><th>Field</th><th>Address</th><th>Word</th><th>Hex</th>
    <th>coarse.fine</th><th>Semitones</th><th>Last ${WATCH_S} s</th><th>Changed</th></tr></thead><tbody></tbody></table></div>`);
  box.querySelector(".w-name").textContent = name;
  box.querySelector(".w-drop").onclick = () => watchCall("drop=" + encodeURIComponent(name));
  $("p-w-list").appendChild(box);
  return { box, rows: null, last: null, hist: [], changedAt: {} };
}

function onWatch(e) {
  const w = watchData[e.name];
  if (!w) return;
  w.last = e;
  w.hist.push([e.t, e.values.map(v => v.word)]);
  while (w.hist.length && w.hist[0][0] < e.t - WATCH_S) w.hist.shift();
  for (const n of e.changed || []) w.changedAt[n] = e.t;
  renderWatch(w);
}

function renderWatch(w) {
  const e = w.last, tb = w.box.querySelector("tbody");
  if (!w.rows) {
    w.rows = e.values.map(v => {
      const tr = el("tr");
      const cells = Array.from({ length: 7 }, () => el("td", { class: "num" }));
      const spark = el("canvas", { class: "w-spark", width: "120", height: "18" });
      cells.splice(6, 0, el("td", {}));
      cells[6].appendChild(spark);
      cells.forEach(c => tr.appendChild(c));
      tb.appendChild(tr);
      return { tr, cells, spark };
    });
  }
  w.box.querySelector(".w-age").textContent = "t " + fx(e.t, 1) + " s";
  e.values.forEach((v, i) => {
    const r = w.rows[i];
    if (!r) return;
    const at = w.changedAt[v.name];
    const vals = [v.name, "0x" + v.addr.toString(16).padStart(8, "0"), String(v.word), v.hex,
      v.coarse_fine === undefined ? "" : fx(v.coarse_fine, 3),
      v.semitones === undefined ? "" : (v.semitones > 0 ? "+" : "") + fx(v.semitones, 2), null,
      at === undefined ? "" : fx(at - e.t, 1) + " s"];
    vals.forEach((t, k) => { if (t !== null && r.cells[k].textContent !== t) r.cells[k].textContent = t; });
    r.tr.classList.toggle("fresh", at !== undefined && e.t - at < 1.0);
    spark(r.spark, w.hist, i, e.t);
  });
}

function spark(cv, hist, i, t1) {
  const x = cv.getContext("2d"), W = cv.width, H = cv.height;
  x.clearRect(0, 0, W, H);
  if (hist.length < 2) return;
  const ys = hist.map(h => h[1][i]);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (lo === hi) { lo -= 1; hi += 1; }
  x.strokeStyle = css("--blue") || "#6FA8CF"; x.lineWidth = 1.5; x.beginPath();
  hist.forEach(([t, w], k) => {
    const X = W - (t1 - t) / WATCH_S * W, Y = H - 2 - (w[i] - lo) / (hi - lo) * (H - 4);
    k ? x.lineTo(X, Y) : x.moveTo(X, Y);
  });
  x.stroke();
}

function watchCall(q) {
  fetch("/watch?" + q).then(r => r.json()).then(r => {
    $("p-w-msg").textContent = r.message || "";
    onState(r);
  }).catch(() => {});
}
$("p-w-frame").onclick = () => watchCall("add=" + encodeURIComponent("frame:" + $("p-w-track").value));
$("p-w-add").onclick = () => watchCall("add=" + encodeURIComponent($("p-w-spec").value));
$("p-w-spec").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); $("p-w-add").click(); } });

function onMark(m) {
  marks.push(m);
  const cut = m.t - KEEP_S * 4;
  while (marks.length && marks[0].t < cut) marks.shift();
  dirty = true;
}

// ---- the numbers -------------------------------------------------------------
function render(r) {
  const T = tiles;
  const fr = r.frames_s;
  T.frames.val.innerHTML = fx(fr, 1) + "<small>/ 1500</small>";
  T.frames.meta.textContent = (r.window_full ? "over 1 s" : "filling 1 s window") + " · clock " + r.clock;
  T.frames.el.classList.toggle("bad", r.window_full && fr !== null && fr < LATE_BELOW);

  T.isr.val.innerHTML = fx(r.isr_avg, 1) + "<small>%</small>";
  T.peak.val.innerHTML = fx(r.isr_peak_1s, 1) + "<small>%</small>";
  T.peak.meta.textContent = "this reply " + fx(r.isr_peak, 1) + " %";
  T.peak.el.classList.toggle("bad", r.isr_peak_1s !== null && r.isr_peak_1s >= 100);

  T.sw.val.textContent = fx(r.switches_s, 0);
  T.sw.meta.textContent = r.switches_probe !== undefined
    ? "≈ " + fx(r.switches_probe, 0) + " from the probe · net " + fx(r.switches_net, 0)
    : "probe's share: not measured";

  T.late.val.innerHTML = r.late ? "LATE" : "ok";
  T.late.el.classList.toggle("bad", !!r.late);
  T.late.meta.textContent = r.late_intervals + " late replies · " + r.low_episodes + " low-rate episodes";
  T.late.tag.textContent = r.late ? r.late_why : "";
  T.late.tag.className = "tag warn";

  // no layout so far fixes CPU; layout 2 adds the counters that say why it reads 100 %
  const cpuOk = r.reliable && r.reliable.cpu;
  T.cpu.val.innerHTML = fx(r.cpu, 1) + "<small>%</small>";
  T.cpu.el.classList.toggle("unrel", !cpuOk);
  T.cpu.tag.textContent = cpuOk ? "" : "unreliable";
  T.cpu.meta.textContent = cpuOk ? "1 − idle"
    : (r.cpu_verdict || (r.layout >= 2 ? "the idle counters need a second" : "reads 100 %; layout 2 says why"));

  const hasOver = r.isr_over !== undefined;
  T.over.el.hidden = !hasOver;
  if (hasOver) {
    T.over.val.innerHTML = fx(r.isr_over_s, 1) + "<small>/ s</small>";
    T.over.meta.textContent = r.isr_over_total + " since the first reply · this reply " + r.isr_over;
    T.over.el.classList.toggle("bad", r.isr_over > 0);
  }
  T.idle.el.hidden = !r.idle;
  if (r.idle) {
    const i = r.idle;
    T.idle.val.innerHTML = i.in_total + "<small>in</small>";
    T.idle.meta.textContent = "out " + i.out_total + " · off the spin " + i.offpc_total +
      (i.offpc_total ? " · last PC " + i.lastpc : "");
    T.idle.tag.textContent = i.in_total ? "" : "never ran";
  }

  T.timer.val.innerHTML = r.timer_mhz ? fx(r.timer_mhz, 3) + "<small>MHz</small>" : (r.timer ? "--" : "stopped");
  T.timer.meta.textContent = r.timer_mhz ? "measured against the host since the first reply" : "DTCN0 did not move";

  T.rtt.val.innerHTML = fx(r.rtt_med_ms, 1) + "<small>ms</small>";
  T.rtt.meta.textContent = fx(r.rate_hz, 1) + " of " + fx(r.rate_asked, 0) + " Hz · ceiling ≈ " +
    fx(r.rate_ceiling, 0) + " Hz · max " + fx(r.rtt_max_ms, 1) + " ms" +
    (r.lost_replies ? " · " + r.lost_replies + " lost" : "");

  (r.link || []).forEach((s, i) => {
    chips[i].st.textContent = s;
    // the USB-audio window is expected STILL: grey, not red, and said why
    chips[i].st.className = "st " + (i === 3 && s === "STILL" ? "waiting" : s);
    chips[i].un.textContent = (i === 3 && s === "STILL") ? "no USB audio in" : "";
  });

  const ex = r.extra || [];
  $("p-extra").hidden = !ex.length && !r.tail;
  if (ex.length || r.tail) {
    const tb = $("p-extra-rows");
    tb.textContent = "";
    for (const x of ex) {
      const tr = el("tr");
      for (const v of ["+" + x.offset, "word " + x.index, String(x.value),
                       "0x" + x.value.toString(16).padStart(8, "0"),
                       x.delta === null ? "--" : String(x.delta)]) {
        tr.appendChild(el("td", { class: "num" }, v));
      }
      tb.appendChild(tr);
    }
    if (r.tail) tb.appendChild(el("tr", {}, `<td class="num" colspan="5">trailing bytes: ${r.tail}</td>`));
  }
  if (r.layout_note !== (render.lastNote || null)) { render.lastNote = r.layout_note; note(); }
}

function note() {
  const bits = [];
  const last = readings[readings.length - 1];
  if (last && last.layout_note) bits.push(last.layout_note + " (an assumption: a later layout appends to layout 1)");
  if (last && last.reliable && !last.reliable.cpu)
    bits.push("CPU is not trusted on any layout so far (it read 100 % playing and stopped); layout 2 does not correct it but its idle counters say why. “USB audio → SHARC” STILL is correct: the frame ISR zeroes that window unless USB audio streams in");
  if (cost && cost.per_request !== null && cost.per_request !== undefined)
    bits.push(`probe cost: ≈ ${cost.per_request} context switches per request (${cost.switches_low}/s at ${cost.low_hz} Hz, ${cost.switches_high}/s at ${cost.high_hz} Hz)`);
  else if (cost) bits.push("probe cost: the measurement did not settle; try again with the instrument steady");
  if (lastErr) bits.push("last probe error: " + lastErr);
  if (last && last.layout >= 2)
    bits.push("the ISR's own time and time lost to nested interrupts cannot be split with the probe's hooks (docs/usbprobe.md): the peak is wall time, nesting included");
  bits.push("per-second figures use the device's own timer (DTCN0), not the host clock; the ISR peak is per request, so a faster poll shows shorter spikes");
  $("p-note").innerHTML = bits.map(b => "· " + b).join("<br>");
}

// ---- the graph ------------------------------------------------------------------
const cv = $("p-graph"), ctx = cv.getContext("2d");
const G = { L: 78, R: 14, T: 24, B: 26, gap: 16 };
const BASE_LANES = [
  { key: "isr", label: "ISR %", lo: 0, hi: 125, h: 0.44 },
  { key: "frames", label: "frames/s", lo: 1480, hi: 1510, h: 0.26 },
  { key: "sw", label: "switches/s", lo: 0, hi: 1600, h: 0.30 },
];
// lanes that appear with their data: layout 2's over-a-frame count, a profiling build's lfo4
const OVER_LANE = { key: "over", label: "ISR>frame", lo: 0, hi: 4, h: 0.16 };
const LFO4_LANE = { key: "lfo4", label: "lfo4 µs", lo: 0, hi: 200, h: 0.30 };
let LANES = BASE_LANES;
function lanes() {
  const L = [...BASE_LANES];
  if (readings.some(r => r.isr_over !== undefined)) L.push(OVER_LANE);
  if (lfo4s.length) L.push(LFO4_LANE);
  return L;
}
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function laneBoxes() {
  LANES = lanes();
  const want = 360 + (LANES.length - 3) * 110 + "px";
  if (cv.style.height !== want) cv.style.height = want;
  const total = LANES.reduce((a, l) => a + l.h, 0);
  LANES = LANES.map(l => ({ ...l, h: l.h / total }));
  const H = cssH() - G.T - G.B - G.gap * (LANES.length - 1);
  let y = G.T;
  return LANES.map(l => { const b = { ...l, y0: y, y1: y + H * l.h }; y = b.y1 + G.gap; return b; });
}
let clock = null;   // [server t, performance.now()] from the last event that carried a t
function stamp(t) { if (typeof t === "number") clock = [t, performance.now()]; }
function nowT() {
  if (clock) return clock[0] + (performance.now() - clock[1]) / 1000;
  return readings.length ? readings[readings.length - 1].t : 0;
}

function cssW() { return cv.clientWidth || 800; }
function cssH() { return cv.clientHeight || 360; }
function draw() {
  // drawn in CSS pixels at the screen's density, so text stays the page's size
  const dpr = window.devicePixelRatio || 1, W = cssW(), H = cssH(), x = ctx;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  }
  x.setTransform(dpr, 0, 0, dpr, 0, 0);
  const c = { grid: css("--grid"), dim: css("--dim"), faint: css("--faint"), ink: css("--ink"),
              avg: css("--s-avg"), peak: css("--s-peak"), late: css("--late"), amber: css("--amber") };
  x.clearRect(0, 0, W, H);
  const t1 = nowT(), t0 = t1 - GRAPH_S;
  const px = t => G.L + ((t - t0) / GRAPH_S) * (W - G.L - G.R);
  const boxes = laneBoxes();
  const swMax = Math.max(1600, ...readings.filter(r => r.t >= t0).map(r => r.switches_s || 0)) * 1.05;
  boxes[2].hi = Math.ceil(swMax / 200) * 200;
  const bOver = boxes.find(b => b.key === "over"), bLfo = boxes.find(b => b.key === "lfo4");
  if (bOver) bOver.hi = Math.max(4, ...readings.filter(r => r.t >= t0).map(r => r.isr_over || 0));
  if (bLfo) {
    const m = Math.max(10, ...lfo4s.filter(e => e.t >= t0).flatMap(e => PIECES.map(p => e.pieces[p].us || 0)));
    bLfo.hi = Math.ceil(m * 1.1 / 10) * 10;
  }
  x.font = '500 11px "IBM Plex Mono", monospace';
  x.textBaseline = "middle";

  for (let s = 0; s <= GRAPH_S; s += 10) {
    const gx = G.L + (s / GRAPH_S) * (W - G.L - G.R);
    x.strokeStyle = c.grid; x.lineWidth = 1;
    x.beginPath(); x.moveTo(gx, G.T); x.lineTo(gx, H - G.B); x.stroke();
    x.fillStyle = c.faint; x.textAlign = "center";
    x.fillText("-" + (GRAPH_S - s) + "s", gx, H - G.B + 14);
  }
  for (const b of boxes) {
    const py = v => b.y1 - (Math.min(Math.max(v, b.lo), b.hi) - b.lo) / (b.hi - b.lo) * (b.y1 - b.y0);
    b.py = py;
    x.fillStyle = c.dim; x.textAlign = "right";
    x.fillText(b.label, G.L - 8, (b.y0 + b.y1) / 2);
    x.fillStyle = c.faint; x.font = '400 10px "IBM Plex Mono", monospace';
    x.fillText(String(b.hi), G.L - 8, b.y0 + 5); x.fillText(String(b.lo), G.L - 8, b.y1 - 5);
    x.font = '500 11px "IBM Plex Mono", monospace';
    x.strokeStyle = c.grid; x.strokeRect(G.L, b.y0, W - G.L - G.R, b.y1 - b.y0);
    const refs = b.key === "isr" ? [100] : b.key === "frames" ? [1500, LATE_BELOW] : [];
    for (const v of refs) {
      x.strokeStyle = v === LATE_BELOW ? c.late : c.dim; x.setLineDash([7, 6]); x.lineWidth = 1.5;
      x.beginPath(); x.moveTo(G.L, py(v)); x.lineTo(W - G.R, py(v)); x.stroke(); x.setLineDash([]);
      x.fillStyle = c.faint; x.textAlign = "right"; x.font = '400 10px "IBM Plex Mono", monospace';
      x.fillText(b.key === "isr" ? "100 %" : String(v), W - G.R - 4, py(v) + (v === LATE_BELOW ? 8 : -7));
      x.font = '500 11px "IBM Plex Mono", monospace';
    }
  }
  const vis = readings.filter(r => r.t >= t0 - 1);
  const line = (b, key, color, width) => {
    x.strokeStyle = color; x.lineWidth = width; x.lineJoin = "round"; x.beginPath();
    let pen = false;
    for (const r of vis) {
      const v = r[key];
      if (v === null || v === undefined) { pen = false; continue; }
      const X = px(r.t), Y = b.py(v);
      pen ? x.lineTo(X, Y) : x.moveTo(X, Y); pen = true;
    }
    x.stroke();
  };
  x.save(); x.beginPath();
  x.rect(G.L, G.T, W - G.L - G.R, H - G.T - G.B); x.clip();
  line(boxes[0], "isr_peak", c.peak, 2);
  line(boxes[0], "isr_avg", c.avg, 2);
  line(boxes[1], "frames_s", c.ink, 2);
  line(boxes[2], "switches_s", c.ink, 2);
  if (bOver) {                      // one bar per reply that had an ISR over a frame
    x.fillStyle = c.late;
    for (const r of vis) if (r.isr_over) {
      const Y = bOver.py(r.isr_over);
      x.fillRect(px(r.t) - 1.5, Y, 3, bOver.y1 - Y);
    }
  }
  if (bLfo) {
    const lv = lfo4s.filter(e => e.t >= t0 - 1);
    PIECES.forEach((p, i) => {
      x.strokeStyle = PIECE_COLOR[i]; x.lineWidth = 2; x.setLineDash(PIECE_DASH[i]); x.beginPath();
      let pen = false, lastXY = null, any = false;
      for (const e of lv) {
        const v = e.pieces[p] && e.pieces[p].us;
        if (v === null || v === undefined) { pen = false; continue; }
        const X = px(e.t), Y = bLfo.py(v);
        pen ? x.lineTo(X, Y) : x.moveTo(X, Y); pen = true; lastXY = [X, Y]; any = any || v > 0;
      }
      x.stroke(); x.setLineDash([]);
      if (lastXY && any) {           // direct label at the line's end, for a piece that ran
        x.fillStyle = c.ink; x.textAlign = "right"; x.font = '500 10px "IBM Plex Mono", monospace';
        x.fillText(p, lastXY[0] - 4, Math.max(bLfo.y0 + 6, lastXY[1] - 7));
        x.font = '500 11px "IBM Plex Mono", monospace';
      }
    });
  }
  // late replies: a red tick at the top of the ISR lane
  x.fillStyle = c.late;
  for (const r of vis) if (r.late) x.fillRect(px(r.t) - 1.5, boxes[0].y0, 3, 8);
  // clipped peaks (over the lane's top): a marker, so a spike off the scale is not lost
  for (const r of vis) if (r.isr_peak !== null && r.isr_peak > boxes[0].hi) {
    x.beginPath(); x.arc(px(r.t), boxes[0].y0 + 13, 3, 0, 6.283); x.fill();
  }
  x.restore();
  // marks: across every lane, labelled at the top
  for (const m of marks) {
    if (m.t < t0 || m.t > t1 + 0.5) continue;
    const X = px(Math.min(m.t, t1));
    x.strokeStyle = c.amber; x.lineWidth = 2; x.setLineDash([]);
    x.beginPath(); x.moveTo(X, G.T - 6); x.lineTo(X, H - G.B); x.stroke();
    x.fillStyle = c.amber; x.textAlign = X > W - 200 ? "right" : "left";
    x.font = '600 11px "IBM Plex Mono", monospace';
    x.fillText(m.label, X + (x.textAlign === "left" ? 6 : -6), G.T - 10);
    x.font = '500 11px "IBM Plex Mono", monospace';
  }
  if (!readings.length) {
    x.fillStyle = c.faint; x.textAlign = "left"; x.font = '400 13px "IBM Plex Sans", sans-serif';
    x.fillText("no probe readings yet", G.L + 10, G.T + 20);
  }
  // hover crosshair
  if (hoverT !== null && vis.length) {
    const r = nearest(hoverT);
    if (r) {
      const X = px(r.t);
      x.strokeStyle = c.dim; x.lineWidth = 1;
      x.beginPath(); x.moveTo(X, G.T); x.lineTo(X, H - G.B); x.stroke();
    }
  }
}

function nearest(t) {
  let best = null, d = Infinity;
  for (const r of readings) { const e = Math.abs(r.t - t); if (e < d) { d = e; best = r; } }
  return best;
}

cv.addEventListener("mousemove", e => {
  const rect = cv.getBoundingClientRect(), sx = 1;
  const X = (e.clientX - rect.left) * sx;
  const t1 = nowT(), t0 = t1 - GRAPH_S;
  if (X < G.L || X > cssW() - G.R || !readings.length) { hoverT = null; $("p-tip").style.display = "none"; dirty = true; return; }
  hoverT = t0 + (X - G.L) / (cssW() - G.L - G.R) * GRAPH_S;
  const r = nearest(hoverT), tip = $("p-tip");
  const near = marks.filter(m => Math.abs(m.t - r.t) < 0.6).map(m => "mark: " + m.label);
  tip.innerHTML = [
    `<span class="k">t</span> ${fx(r.t - t1, 2)} s (${fx(r.t, 2)})`,
    `<span class="k">ISR avg</span> ${fx(r.isr_avg, 1)} %  <span class="k">peak</span> ${fx(r.isr_peak, 1)} %`,
    `<span class="k">frames/s</span> ${fx(r.frames_s, 1)}  <span class="k">switches/s</span> ${fx(r.switches_s, 0)}`,
    r.late ? `<span style="color:var(--late)">late: ${r.late_why}</span>` : "",
    ...near,
  ].filter(Boolean).join("<br>");
  tip.style.display = "block";
  const left = e.clientX - rect.left + 14;
  tip.style.left = Math.min(left, rect.width - tip.offsetWidth - 4) + "px";
  tip.style.top = (e.clientY - rect.top + 14) + "px";
  dirty = true;
});
cv.addEventListener("mouseleave", () => { hoverT = null; $("p-tip").style.display = "none"; dirty = true; });

let lastDraw = 0;
function loop(ts) {
  // the time axis moves on its own, so redraw at ~30 fps whether or not a reading came
  if (dirty || ts - lastDraw > 33) { dirty = false; lastDraw = ts; draw(); }
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);

// ---- controls -----------------------------------------------------------------
function mark() {
  const label = $("p-label").value || "mark";
  fetch("/mark?label=" + encodeURIComponent(label)).catch(() => {});
  const b = $("p-mark"); b.textContent = "marked"; setTimeout(() => { b.textContent = "Mark"; }, 700);
}
$("p-mark").onclick = mark;
$("p-label").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); mark(); } });
document.addEventListener("keydown", e => {
  if (e.key !== "m" && e.key !== "M") return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target && e.target.tagName;
  if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT") return;
  e.preventDefault(); mark();
});
$("p-midi").onclick = () => fetch("/midi?on=" + (midiOn ? "0" : "1")).then(r => r.json()).then(onState);
$("p-cal").onclick = () => fetch("/calibrate").then(r => r.json()).then(r => { $("p-log").textContent = r.message; });

// ---- the stream -----------------------------------------------------------------
// Its own connection, not the page's `es`: the server sends `state` and `backlog`
// the instant a stream opens, before this script has loaded and could listen on
// the page's. The MIDI messages on it are ignored here (no listener for them).
const src = new EventSource("/events");
const on = (name, fn) => src.addEventListener(name, m => { const d = JSON.parse(m.data); stamp(d.t !== undefined ? d.t : d.now); fn(d); });
on("state", onState);
on("backlog", b => {
  readings = []; marks = []; lfo4s = [];
  for (const ev of b.events) {
    if (ev.type === "probe") readings.push(ev);
    else if (ev.type === "mark") marks.push(ev);
    else if (ev.type === "probe-cost") cost = ev;
    else if (ev.type === "probe-lfo4") lfo4s.push(ev);
    else if (ev.type === "probe-watch") onWatch(ev);
  }
  if (readings.length) render(readings[readings.length - 1]);
  dirty = true; note();
});
on("probe", onProbe);
on("probe-lfo4", onLfo4);
on("probe-watch", onWatch);
on("probe-status", onStatus);
on("mark", onMark);
on("probe-cost", c => { cost = c; note(); });
on("probe-error", e => {
  lastErr = e.error; note();
  if (watchNames.some(n => e.error.includes("(" + n + ","))) $("p-w-msg").textContent = e.error;
});
setMidi(true);
})();
