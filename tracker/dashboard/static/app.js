const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const COLOURS = { get productive() { return cssv("--productive"); }, get neutral() { return cssv("--neutral"); }, get distracting() { return cssv("--distracting"); }, get idle() { return cssv("--idle"); } };
const PRIMARY = () => cssv("--productive");
const CATS = ["productive", "neutral", "distracting"];

const state = { range: "7d", data: null, charts: {} };

const $ = (sel) => document.querySelector(sel);
const fmtTs = (iso) => iso ? iso.replace("T", " ").replace("Z", "") : "";
// Escape anything from the database before it goes into innerHTML: window titles
// come from web pages, so a page title like "<img onerror=...>" must not run.
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
const badge = (c) => `<span class="badge ${esc(c)}">${esc(c)}</span>`;
const scoreCls = (s) => s >= 70 ? "hi" : s >= 40 ? "mid" : "lo";

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.json()).error || res.statusText);
  return res.json();
}

function spark(vals, color) {
  if (vals.length < 2) return "";
  const max = Math.max(...vals, 1), min = Math.min(...vals, 0), r = max - min || 1;
  const pts = vals.map((v, i) => `${(100 * i / (vals.length - 1)).toFixed(1)},${(22 - 20 * (v - min) / r).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}
function mix(s) {
  const d = s.duration_min || 1;
  const part = (k, m) => `<span style="width:${(100 * m / d).toFixed(1)}%;background:${COLOURS[k]}" title="${k} ${m} min"></span>`;
  return `<div class="mix">${part("productive", s.productive_min)}${part("neutral", s.neutral_min)}${part("distracting", s.distracting_min)}${part("idle", s.idle_min)}</div>`;
}

function chart(id, config) {
  if (state.charts[id]) state.charts[id].destroy();
  Chart.defaults.font.family = '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = cssv("--muted");
  Chart.defaults.borderColor = cssv("--rule");
  Chart.defaults.maintainAspectRatio = false;          // the .chart-box sets the height
  Chart.defaults.plugins.legend.align = "start";
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.legend.labels.useBorderRadius = true;
  Chart.defaults.plugins.legend.labels.borderRadius = 3;
  Chart.defaults.plugins.tooltip.backgroundColor = cssv("--fg");
  Chart.defaults.plugins.tooltip.titleColor = cssv("--canvas");
  Chart.defaults.plugins.tooltip.bodyColor = cssv("--canvas");
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.elements.bar.borderRadius = 8;
  Chart.defaults.elements.line.borderWidth = 2;
  Chart.defaults.scale.grid.drawTicks = false;
  state.charts[id] = new Chart($(`#${id}`), config);
}

/* ---------- init ---------- */
async function init() {
  try {
    await api("/api/summary?range=today");   // fail early with a clear message if the database is down
  } catch (e) {
    $("#status").textContent = e.message;
    return;
  }

  $("#range").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $("#range .active").classList.remove("active"); b.classList.add("active");
    state.range = b.dataset.range; load();
  };
  $(".tabs").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll(".tabs button, .tab").forEach(el => el.classList.remove("active"));
    b.classList.add("active"); $(`#tab-${b.dataset.tab}`).classList.add("active");
    // Hidden scroll wheels can't be positioned: put them on the chosen length now.
    if (b.dataset.tab === "settings" && state.applyWheelLength) state.applyWheelLength();
  };
  $("#refresh").onclick = () => {
    const btn = $("#refresh");
    btn.classList.remove("is-spinning"); void btn.offsetWidth; btn.classList.add("is-spinning");
    load();
  };
  $("#goal-minus").onclick = () => stepGoal(-1);
  $("#goal-plus").onclick = () => stepGoal(1);
  load();
}

/* ---------- load + render ---------- */
async function load() {
  $("#status").textContent = "Loading…";
  try {
    const [summary, cats, procs, installed] = await Promise.all([
      api(`/api/summary?range=${state.range}`),
      api(`/api/categories`),
      api(`/api/processes?range=${state.range}`),
      // Installed apps (cached on the server) so blocked chips show friendly names.
      api(`/api/installed-apps`).catch(() => state.installed),
    ]);
    state.installed = installed;
    state.data = summary;
    renderOverview(summary);
    renderSessions(summary);
    renderApps(summary);
    renderProcesses(procs);
    renderSettings(cats);
    loadFocusHistory();
    loadSiteRules();
    loadTeach();
    $("#status").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    $("#status").textContent = e.message;
  }
}

const RANGE_WORDS = { today: "today", "7d": "in the last 7 days", "30d": "in the last 30 days", all: "so far" };

// Durations use a non-breaking space so "3 h" never splits across lines.
const NBSP = " ";

// Human-friendly duration from seconds: "40 s", "45 min", "2.4 hours"
function fmtDur(sec) {
  if (sec < 60) return `${Math.round(sec)}${NBSP}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}${NBSP}min`;
  return `${(sec / 3600).toFixed(1)}${NBSP}hours`;
}

// Compact duration for tight spots (the ring): "40 s", "45 min", "1.6 h"
function fmtShort(sec) {
  if (sec < 60) return `${Math.round(sec)}${NBSP}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}${NBSP}min`;
  return `${+(sec / 3600).toFixed(1)}${NBSP}h`;
}

/* ---------- daily goal (a per-browser preference, so localStorage is enough) ---------- */
const GOAL_STEPS = [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8];
const goalKey = () => "focusos.goalHours.1";   // key kept from the multi-user version, so a saved goal survives
function getGoal() {
  try { const v = parseFloat(localStorage.getItem(goalKey())); if (GOAL_STEPS.includes(v)) return v; } catch (_) { /* storage blocked */ }
  return 3;
}
function setGoal(h) {
  try { localStorage.setItem(goalKey(), String(h)); } catch (_) { /* storage blocked: keep for this page view */ }
  state.goalOverride = h;
}
const currentGoal = () => state.goalOverride ?? getGoal();
const fmtGoal = (h) => `${h % 1 ? h.toFixed(1) : h}${NBSP}h`;

function greetingFor(date) {
  const h = date.getHours();
  return h < 5 ? "Up late" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

// The Today panel: greeting, streak, and the goal ring. Always about today,
// whatever range is selected.
function renderToday(d) {
  const today = d.today || { tracked_s: 0, productive_s: 0, distracting_s: 0 };
  const goalH = currentGoal(), goalS = goalH * 3600;
  const prod = today.productive_s || 0;
  $("#greeting").textContent = greetingFor(new Date());

  let title;
  if (prod <= 0) title = today.tracked_s > 0 ? "No focused work yet today. One good session changes that." : "Nothing tracked yet today. Start the tracker when you sit down.";
  else if (prod >= goalS) title = `Goal reached! ${fmtShort(prod)} of focused work today.`;
  else title = `${fmtShort(prod)} of focused work so far. ${fmtShort(goalS - prod)} to your goal.`;
  $("#today-title").textContent = title;

  const streak = d.streak_days || 0;
  $("#streak").classList.toggle("is-on", streak > 0);
  $("#streak-text").textContent = streak > 0 ? `${streak}-day streak` : "Start a streak today";
  $("#today-dist").textContent = `${fmtShort(today.distracting_s || 0)} distracted today`;

  const pct = Math.min(prod / goalS, 1);
  const C = 2 * Math.PI * 84;
  requestAnimationFrame(() => { $("#ring-fill").style.strokeDashoffset = (C * (1 - pct)).toFixed(2); });
  $(".ring-wrap").classList.toggle("is-done", prod >= goalS);
  $("#ring-value").textContent = fmtShort(prod);
  $("#ring-label").textContent = `of ${fmtGoal(goalH)} goal`;
  $("#goal-text").textContent = `Goal ${fmtGoal(goalH)}`;
  $("#goal-minus").disabled = goalH <= GOAL_STEPS[0];
  $("#goal-plus").disabled = goalH >= GOAL_STEPS[GOAL_STEPS.length - 1];
}

function stepGoal(dir) {
  const i = GOAL_STEPS.indexOf(currentGoal());
  const next = GOAL_STEPS[Math.max(0, Math.min(GOAL_STEPS.length - 1, i + dir))];
  setGoal(next);
  if (state.data) renderToday(state.data);
}

const RANGE_TITLES = { today: "Today", "7d": "Your last 7 days", "30d": "Your last 30 days", all: "All time" };

// The time-split ribbon for the selected range.
function renderHero(t) {
  const when = RANGE_WORDS[state.range] || "";
  const ribbon = $("#ribbon"), legend = $("#ribbon-legend");
  ribbon.innerHTML = "";
  legend.innerHTML = "";
  $("#range-title").textContent = RANGE_TITLES[state.range] || "Your stats";

  if (!t.tracked_s) {
    $("#hero-title").textContent = `Nothing tracked ${when}. Start the tracker, then refresh.`;
    ribbon.classList.add("is-empty");
    return;
  }
  ribbon.classList.remove("is-empty");
  const pct = Math.round(100 * t.productive_s / t.tracked_s);
  $("#hero-title").textContent = `Where your time went: ${pct}% productive`;

  const parts = [["productive", t.productive_s, "Productive"], ["neutral", t.neutral_s, "Neutral"], ["distracting", t.distracting_s, "Distracting"]];
  const segs = [];
  for (const [cls, h, name] of parts) {
    if (h <= 0) continue;
    const seg = document.createElement("span");
    seg.className = cls;
    seg.title = `${name}: ${fmtDur(h)}`;
    ribbon.appendChild(seg);
    segs.push([seg, h]);
    const li = document.createElement("li");
    li.innerHTML = `<i class="${cls}"></i><b>${esc(fmtDur(h))}</b> ${esc(name.toLowerCase())}`;
    legend.appendChild(li);
  }
  // The page's one animation: grow the ribbon in on the next frame.
  requestAnimationFrame(() => segs.forEach(([seg, s]) => { seg.style.width = `${(100 * s / t.tracked_s).toFixed(2)}%`; }));
}

function renderOverview(d) {
  const t = d.totals;
  renderToday(d);
  renderHero(t);
  $("#m-tracked").textContent = fmtDur(t.tracked_s);
  $("#m-prod").textContent = fmtDur(t.productive_s);
  $("#m-dist").textContent = fmtDur(t.distracting_s);
  $("#m-focus").textContent = t.sessions ? t.avg_focus.toFixed(0) : "–";
  $("#m-sessions").textContent = `${t.sessions} session${t.sessions === 1 ? "" : "s"}`;
  $("#m-prod-pct").textContent = t.tracked_s ? `${(100 * t.productive_s / t.tracked_s).toFixed(0)}% of tracked time` : " ";
  $("#m-dist-pct").textContent = t.tracked_s ? `${(100 * t.distracting_s / t.tracked_s).toFixed(0)}% of tracked time` : " ";

  const dates = [...new Set(d.daily.map(r => r.date))].sort();
  const daySum = (cats) => dates.map(dt => d.daily.filter(r => r.date === dt && cats.includes(r.category)).reduce((a, r) => a + r.minutes, 0));
  $("#s-tracked").innerHTML = spark(daySum(CATS), cssv("--fg"));
  $("#s-prod").innerHTML = spark(daySum(["productive"]), COLOURS.productive);
  $("#s-dist").innerHTML = spark(daySum(["distracting"]), COLOURS.distracting);
  const byTime = [...d.sessions].sort((a, b) => a.start_time.localeCompare(b.start_time));
  $("#s-focus").innerHTML = spark(byTime.map(s => s.focus_score), COLOURS.productive);

  renderDaily(d);
  renderDayparts(d.sessions);
  renderTrend(d.sessions);
}

// "2 h 10 min", "35 min", "40 s" from minutes
function fmtHM(min) {
  if (min < 1) return `${Math.round(min * 60)}${NBSP}s`;
  const m = Math.round(min);
  return m >= 60 ? `${Math.floor(m / 60)}${NBSP}h${m % 60 ? ` ${m % 60}${NBSP}min` : ""}` : `${m}${NBSP}min`;
}
const utcDate = (ts) => new Date(ts.replace(" ", "T").replace(/Z?$/, "Z"));   // DB times are UTC
const dayLabel = (ymd) => new Date(`${ymd}T12:00:00Z`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });

/* How your days went: one stacked bar per day, with the answer written above it. */
function renderDaily(d) {
  const dates = [...new Set(d.daily.map(r => r.date))].sort();
  const minsOf = (dt, c) => d.daily.find(r => r.date === dt && r.category === c)?.minutes ?? 0;
  const totals = dates.map(dt => CATS.reduce((a, c) => a + minsOf(dt, c), 0));
  const useHours = Math.max(0, ...totals) >= 120;           // big days read better in hours
  const unit = useHours ? 60 : 1;

  const take = $("#daily-takeaway");
  if (!dates.length) {
    take.textContent = "Nothing tracked in this range yet. Start the tracker and come back.";
  } else {
    const best = dates.reduce((bi, dt, i) => minsOf(dt, "productive") > minsOf(dates[bi], "productive") ? i : bi, 0);
    const prod = minsOf(dates[best], "productive"), tot = totals[best];
    const share = tot ? Math.round(100 * prod / tot) : 0;
    take.textContent = dates.length === 1
      ? `${dayLabel(dates[0])}: ${fmtHM(prod)} in work apps out of ${fmtHM(tot)} (${share}%).`
      : `Your best day was ${dayLabel(dates[best])}: ${fmtHM(prod)} in work apps, ${share}% of that day.`;
  }

  chart("chart-daily", {
    type: "bar",
    data: {
      labels: dates.map(dayLabel),
      datasets: CATS.map(c => ({
        label: { productive: "Work apps", neutral: "Neutral", distracting: "Distracting" }[c],
        backgroundColor: COLOURS[c],
        data: dates.map(dt => +(minsOf(dt, c) / unit).toFixed(2)),
        maxBarThickness: 44, borderSkipped: false, borderWidth: { top: 2 }, borderColor: cssv("--surface") || "#fff",
      })),
    },
    options: {
      plugins: {
        legend: { position: "top" },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const min = ctx.raw * unit, tot = totals[ctx.dataIndex];
              return ` ${ctx.dataset.label}: ${fmtHM(min)} (${tot ? Math.round(100 * min / tot) : 0}%)`;
            },
            footer: (items) => `Total: ${fmtHM(totals[items[0].dataIndex])}`,
          },
        },
      },
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: { stacked: true, border: { display: false }, title: { display: true, text: useHours ? "Hours" : "Minutes" },
             ticks: { maxTicksLimit: 5 } },
      },
    },
  });
}

/* When you focus best: four parts of the day as a ranked meter list. */
const DAYPARTS = [
  { key: "morning", name: "Morning", span: "5 am – 12 pm", from: 5, to: 12 },
  { key: "afternoon", name: "Afternoon", span: "12 – 5 pm", from: 12, to: 17 },
  { key: "evening", name: "Evening", span: "5 – 9 pm", from: 17, to: 21 },
  { key: "night", name: "Night", span: "9 pm – 5 am", from: 21, to: 29 },
];
function renderDayparts(sessions) {
  const groups = DAYPARTS.map(p => ({ ...p, scores: [] }));
  for (const s of sessions) {
    let h = utcDate(s.start_time).getHours();
    if (h < 5) h += 24;
    groups.find(g => h >= g.from && h < g.to)?.scores.push(s.focus_score);
  }
  groups.forEach(g => { g.avg = g.scores.length ? g.scores.reduce((a, b) => a + b, 0) / g.scores.length : null; });
  const withData = groups.filter(g => g.avg != null);
  const best = withData.reduce((b, g) => (b == null || g.avg > b.avg ? g : b), null);

  const take = $("#daypart-takeaway");
  if (!best) take.textContent = "No sessions in this range yet.";
  else {
    const n = best.scores.length;
    take.textContent = `You focus best in the ${best.name.toLowerCase()}: an average score of ${Math.round(best.avg)} over ${n} session${n === 1 ? "" : "s"}.` +
      (sessions.length < 5 ? " A few more sessions will make this more reliable." : "");
  }

  $("#daypart-list").innerHTML = groups.map(g => {
    const n = g.scores.length;
    const val = g.avg == null ? "–" : Math.round(g.avg);
    return `<li class="${g === best ? "is-best" : ""}${g.avg == null ? " is-empty" : ""}">
      <span class="ml-name">${esc(g.name)}<span class="ml-span">${esc(g.span)}</span></span>
      <span class="ml-track" aria-hidden="true"><span class="ml-fill" style="width:${g.avg == null ? 0 : Math.max(2, g.avg)}%"></span></span>
      <span class="ml-value">${val}<span class="ml-count">${n ? `${n} session${n === 1 ? "" : "s"}` : "no sessions"}</span></span>
    </li>`;
  }).join("");
}

/* Is your focus getting better? Score per session with "great" and "low" zones. */
const scoreZones = {
  id: "scoreZones",
  beforeDatasetsDraw(c) {
    const { ctx, chartArea: a, scales: { y } } = c;
    if (!a) return;
    const zone = (from, to, colour, label) => {
      const top = y.getPixelForValue(to), bottom = y.getPixelForValue(from);
      ctx.save();
      ctx.globalAlpha = 0.1;
      ctx.fillStyle = colour;
      ctx.fillRect(a.left, top, a.right - a.left, bottom - top);
      ctx.globalAlpha = 1;
      ctx.fillStyle = cssv("--muted");
      ctx.font = '600 11px "IBM Plex Sans", system-ui, sans-serif';
      ctx.textAlign = "left"; ctx.textBaseline = "middle";
      ctx.fillText(label, a.right + 8, (top + bottom) / 2);       // in the right margin, clear of the dots
      ctx.restore();
    };
    zone(70, 100, COLOURS.productive, "Great");
    zone(0, 40, COLOURS.distracting, "Low");
  },
};
function renderTrend(sessions) {
  const sess = [...sessions].sort((a, b) => a.start_time.localeCompare(b.start_time));
  const scores = sess.map(s => s.focus_score);
  const avg = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;

  const take = $("#trend-takeaway");
  if (scores.length < 2) take.textContent = "Finish a couple of sessions to see how your focus changes.";
  else if (scores.length < 6) take.textContent = `Your average score so far is ${Math.round(avg(scores))} out of 100.`;
  else {
    const recent = avg(scores.slice(-5)), before = avg(scores.slice(-10, -5));
    const diff = Math.round(recent - before);
    take.textContent = diff >= 5 ? `Getting better: your last 5 sessions averaged ${Math.round(recent)}, up ${diff} from the 5 before.`
      : diff <= -5 ? `Slipping a little: your last 5 sessions averaged ${Math.round(recent)}, down ${-diff} from the 5 before.`
      : `Holding steady: your last 5 sessions averaged ${Math.round(recent)}, about the same as before.`;
  }

  const brand = cssv("--brand") || PRIMARY();
  // Sessions all within ~2 days: label them by time, not by the same date over and over.
  const sameFewDays = sess.length > 1 && utcDate(sess[sess.length - 1].start_time) - utcDate(sess[0].start_time) < 2 * 864e5;
  const when = (s) => utcDate(s.start_time).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  chart("chart-trend", {
    type: "line",
    data: {
      labels: sess.map(s => sameFewDays
        ? utcDate(s.start_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : utcDate(s.start_time).toLocaleDateString([], { day: "numeric", month: "short" })),
      datasets: [{ label: "Focus score", data: scores, borderColor: brand, backgroundColor: brand,
                   cubicInterpolationMode: "monotone", pointRadius: 4, pointHoverRadius: 6, pointBorderColor: cssv("--surface") || "#fff", pointBorderWidth: 2 }],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      layout: { padding: { right: 44 } },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => when(sess[items[0].dataIndex]),
            label: (ctx) => {
              const v = ctx.raw;
              return ` Score ${Math.round(v)}: ${v >= 70 ? "great" : v >= 40 ? "OK" : "low"}`;
            },
            afterLabel: (ctx) => {
              const s = sess[ctx.dataIndex];
              return ` ${fmtHM(s.duration_min)} long, ${fmtHM(s.productive_min)} in work apps${s.focus_mode ? ", focus mode" : ""}`;
            },
          },
        },
      },
      scales: {
        y: { min: 0, max: 100, border: { display: false }, afterBuildTicks: (ax) => { ax.ticks = [0, 40, 70, 100].map(v => ({ value: v })); } },
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
      },
    },
    plugins: [scoreZones],
  });
}

state.sessionFilter = "all";        // "all" | "focus"

// The Focus column: "25 min · Completed", or "–" for a normal session.
function focusCell(s) {
  if (!s.focus_mode) return `<span class="muted">–</span>`;
  const plan = s.planned_minutes ? `${esc(fmtMin(Math.round(s.planned_minutes)))} ` : "";
  const o = s.outcome || "finished";
  return `${plan}<span class="outcome ${esc(o.replace(" ", "-"))}">${esc(OUTCOME_TEXT[o] || o)}</span>`;
}

function renderSessions(d) {
  const tb = $("#sessions-table tbody");
  const rows = state.sessionFilter === "focus" ? d.sessions.filter(s => s.focus_mode) : d.sessions;
  if (!rows.length) {
    const msg = state.sessionFilter === "focus"
      ? "No focus sessions in this range. Start one from the Focus mode tab."
      : "No sessions in this range. Try a longer range.";
    tb.innerHTML = `<tr><td colspan="12" class="empty">${msg}</td></tr>`; return;
  }
  tb.innerHTML = rows.map(s => `
    <tr class="clickable${s.session_id === state.selectedSessionId ? " selected" : ""}" data-id="${esc(s.session_id)}">
      <td>${esc(s.session_id)}</td><td>${esc(fmtTs(s.start_time))}</td><td>${s.duration_min} min</td><td>${mix(s)}</td>
      <td>${s.productive_min}</td><td>${s.neutral_min}</td><td>${s.distracting_min}</td><td>${s.idle_min}</td>
      <td>${s.switches}</td><td>${focusCell(s)}</td><td>${s.focus_mode ? esc(s.blocks) : ""}</td>
      <td class="score ${scoreCls(s.focus_score)}">${s.focus_score}</td>
    </tr>`).join("");
  tb.onclick = (e) => {
    const tr = e.target.closest("tr[data-id]"); if (!tr) return;
    tb.querySelectorAll("tr").forEach(r => r.classList.remove("selected")); tr.classList.add("selected");
    showSession(+tr.dataset.id);
  };
}

function setSessionFilter(f) {
  state.sessionFilter = f;
  document.querySelectorAll("#session-filter button").forEach(x => {
    const on = x.dataset.filter === f;
    x.classList.toggle("active", on); x.setAttribute("aria-checked", on);
  });
  if (state.data) renderSessions(state.data);
}

// Draw activity/idle segments proportionally across a .timeline element.
// `until` (ms) stretches the scale to a later time, e.g. "now" for a live session.
function renderTimeline(tl, segments, from = null, until = null) {
  tl.innerHTML = "";
  if (!segments.length) return;
  const t0 = from ?? Date.parse(segments[0].start);
  const t1 = Math.max(until ?? 0, ...segments.map(s => Date.parse(s.end)));
  const span = Math.max(t1 - t0, 1);
  for (const s of segments) {
    const el = document.createElement("div");
    el.className = `seg ${s.kind}`;
    el.style.left = `${100 * (Date.parse(s.start) - t0) / span}%`;
    el.style.width = `${100 * (Date.parse(s.end) - Date.parse(s.start)) / span}%`;
    el.title = `${s.label}  ${fmtTs(s.start)} → ${fmtTs(s.end)}${s.title ? "\n" + s.title : ""}`;
    tl.appendChild(el);
  }
}

async function showSession(id) {
  state.selectedSessionId = id;
  let d;
  try { d = await api(`/api/session/${id}`); } catch (_) { return; }
  const m = state.data.sessions.find(s => s.session_id === id);
  $("#session-detail").hidden = false;
  $("#detail-id").textContent = id;
  const out = $("#detail-outcome");
  out.hidden = !d.focus_mode;
  if (d.focus_mode) {
    out.textContent = `Focus · ${OUTCOME_TEXT[d.outcome] || d.outcome}`;
    out.className = `outcome ${d.outcome.replace(" ", "-")}`;
  }
  const planned = d.planned_minutes ? `, planned ${d.planned_minutes}${NBSP}min` : "";
  $("#detail-when").textContent = `${fmtWhen(d.start)}${planned}`;

  renderTimeline($("#timeline"), d.segments);
  $("#detail-apps").innerHTML = d.apps.length
    ? d.apps.map(a => `<li><span class="proc">${esc(a.process_name)}</span><span>${badge(a.category)} <span class="muted">${esc(fmtShort(a.seconds))}</span></span></li>`).join("")
    : `<li class="fs-empty">No app activity was saved.</li>`;
  $("#detail-blocked").innerHTML = d.blocked_apps.length
    ? d.blocked_apps.map(b => `<li><span class="proc">${esc(b.process_name)}</span><span class="muted">${esc(describeActions(b))}</span></li>`).join("")
    : `<li class="fs-empty">${d.focus_mode ? "No blocked app tried to open." : "Focus mode was off, so nothing was blocked."}</li>`;
  if (m) $("#formula-values").textContent =
    `T_productive = ${m.productive_min} min, T_session = ${m.duration_min} min, T_idle = ${m.idle_min} min, ` +
    `S = ${m.switches} switches, S_max = ${state.data.s_max}/h  →  score ${m.focus_score}`;
  $("#session-detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

// Jump from the Focus tab to Sessions, filtered to focus sessions, with one opened.
function openInSessions(id) {
  document.querySelector('.tabs button[data-tab="sessions"]').click();
  setSessionFilter("focus");
  if (id && state.data?.sessions.some(s => s.session_id === id)) showSession(id);
}

function renderApps(d) {
  chart("chart-apps", {
    type: "bar",
    data: { labels: d.top_apps.map(a => a.process_name), datasets: [{ label: "minutes", data: d.top_apps.map(a => a.minutes), backgroundColor: d.top_apps.map(a => COLOURS[a.category]), maxBarThickness: 26 }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } } },
  });
  const tb = $("#recent-table tbody");
  tb.innerHTML = d.recent.length ? d.recent.map(r => `
    <tr><td>${esc(fmtTs(r.start_time))}</td><td><span class="proc">${esc(r.process_name)}</span></td>
    <td class="title" title="${esc(r.window_title)}">${esc(r.window_title)}</td>
    <td>${badge(r.category)}${r.category_source === "default" ? "" : ` <span class="small">(${esc(r.category_source)})</span>`}</td><td>${Math.round(r.seconds)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">Nothing recorded yet.</td></tr>`;
}

const fmtBytes = (b) => b == null ? "" : b >= 2 ** 30 ? `${(b / 2 ** 30).toFixed(1)} GB` : `${Math.round(b / 2 ** 20)} MB`;
const num = (v, d = 1) => v == null ? "" : (+v).toFixed(d);

function renderProcesses(p) {
  const bg = p.background;
  chart("chart-bg-cpu", {
    type: "bar",
    data: { labels: bg.map(r => r.process_name),
            datasets: [{ label: "CPU seconds while in background", data: bg.map(r => r.background_cpu_seconds), backgroundColor: cssv("--brand"), maxBarThickness: 26 }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: "CPU seconds" } } } },
  });

  const fgBody = $("#fgcpu-table tbody");
  fgBody.innerHTML = p.foreground_vs_cpu.length ? p.foreground_vs_cpu.map(r => {
    const fgMin = (r.foreground_seconds || 0) / 60;
    const perMin = fgMin > 0 ? num(r.cpu_seconds / fgMin, 2) : "never in front";
    return `<tr><td><span class="proc">${esc(r.process_name)}</span></td><td>${num(fgMin)}</td><td>${num(r.cpu_seconds, 2)}</td>
      <td>${esc(perMin)}</td><td>${num(r.peak_cpu_percent, 2)}</td><td>${fmtBytes(r.peak_working_set_bytes)}</td></tr>`;
  }).join("") : `<tr><td colspan="6" class="empty">No process snapshots in this range. Run the tracker with --proc.</td></tr>`;

  const bgBody = $("#bg-table tbody");
  bgBody.innerHTML = bg.length ? bg.map(r => `
    <tr><td><span class="proc">${esc(r.process_name)}</span></td><td>${num(r.background_cpu_seconds, 2)}</td><td>${num(r.peak_cpu_percent, 2)}</td>
    <td>${num(r.max_threads, 0)}</td><td>${esc(r.priority_class)}</td><td>${fmtBytes(r.peak_working_set_bytes)}</td></tr>`).join("")
    : `<tr><td colspan="6" class="empty">No background CPU use recorded.</td></tr>`;
}

function renderSettings(cats) {
  const tb = $("#cat-table tbody");
  tb.innerHTML = cats.map(c => `
    <tr data-app="${esc(c.app_id)}">
      <td><span class="proc">${esc(c.process_name)}</span></td><td>${badge(c.default_category)}</td>
      <td><select class="cat-select">${CATS.map(x => `<option ${x === c.effective_category ? "selected" : ""}>${x}</option>`).join("")}</select></td>
      <td>${c.overridden ? `<button class="reset">Reset</button>` : ""}</td>
    </tr>`).join("");
  tb.onchange = async (e) => {
    if (!e.target.classList.contains("cat-select")) return;
    const app_id = +e.target.closest("tr").dataset.app;
    await api("/api/categories", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_id, label: e.target.value }) });
    load();
  };
  tb.onclick = async (e) => {
    if (!e.target.classList.contains("reset")) return;
    const app_id = +e.target.closest("tr").dataset.app;
    await api("/api/categories", { method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_id }) });
    load();
  };
  const blocked = cats.filter(c => c.effective_category === "distracting").map(c => c.process_name);
  $("#blocked-list").textContent = blocked.join(", ") || "none";
  syncFocusSetup();
  renderBlocked(cats);
}

/* ---------- blocked apps ---------- */
const jsonPost = (path, body, method = "POST") =>
  api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

state.installed = [];        // [{name, exe, source, blocked}] from /api/installed-apps
state.cats = [];

const installedByExe = () => new Map(state.installed.map(a => [a.exe, a]));

// A stable, friendly colour per app for the letter avatar.
const AVATAR_COLOURS = ["#6C4CF5", "#14B87A", "#FF5C7A", "#FFB020", "#2E90FA", "#9B51E0", "#F2994A", "#0EA5A4"];
function avatarColour(text) {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLOURS[h % AVATAR_COLOURS.length];
}

function renderBlocked(cats) {
  state.cats = cats;
  const byExe = installedByExe();
  const blocked = cats.filter(c => c.effective_category === "distracting");
  const list = $("#blocked-chips");
  list.innerHTML = blocked.length
    ? blocked.map(c => {
        const app = byExe.get(c.process_name);
        const label = app ? app.name : c.process_name;
        const missing = state.installed.length && !app;
        return `<li data-app="${esc(c.app_id)}" class="${missing ? "not-installed" : ""}" title="${esc(c.process_name)}">${esc(label)}${missing ? ' <span class="chip-sub">not installed</span>' : ""}<button type="button" aria-label="Stop blocking ${esc(label)}" title="Stop blocking">×</button></li>`;
      }).join("")
    : `<li class="empty-chip">Nothing blocked yet. Add the apps that pull you away.</li>`;
  state.activeBlocked = blocked.filter(c => !state.installed.length || byExe.has(c.process_name)).length;
  updateFocusNote();
}

// The note under Start focus: how many apps, and what happens to them.
function updateFocusNote() {
  const n = state.activeBlocked ?? 0;
  const el = $("#focus-note");
  el.classList.remove("is-error");
  if (!n) { el.textContent = "Your block list is empty, so nothing will be stopped."; return; }
  const apps = `${n} app${n === 1 ? "" : "s"}`;
  el.textContent = state.onBlock === "minimise"
    ? `${apps} will be minimised as soon as ${n === 1 ? "it opens" : "they open"}, with a notification.`
    : `${apps} will be closed as soon as ${n === 1 ? "it opens" : "they open"}, with a notification. Save your work in ${n === 1 ? "it" : "them"} first.`;
}

function setFormMsg(text, isError = false) {
  const el = $("#add-app-msg");
  el.textContent = text;
  el.classList.toggle("is-error", isError);
}

async function loadInstalled(refresh = false) {
  try {
    state.installed = await api(`/api/installed-apps${refresh ? "?refresh=1" : ""}`);
  } catch (err) {
    state.installed = [];
    setFormMsg(err.message, true);
  }
}

function renderPicker() {
  const q = $("#picker-search").value.trim().toLowerCase();
  // Match the app's name anywhere (word starts rank first), or its file name from the start.
  const score = (a) => {
    if (!q) return 1;
    const name = a.name.toLowerCase();
    if (name.startsWith(q)) return 3;
    if (name.split(/[\s()&.-]+/).some(w => w.startsWith(q))) return 2;
    if (name.includes(q) || a.exe.startsWith(q)) return 1;
    return 0;
  };
  const items = state.installed.map(a => [a, score(a)]).filter(([, s]) => s > 0)
    // Best match first; with no search, blocked apps first; then alphabetical.
    .sort(([a, sa], [b, sb]) => (sb - sa) || (q ? 0 : b.blocked - a.blocked) || a.name.localeCompare(b.name))
    .map(([a]) => a);
  $("#picker-list").innerHTML = items.length
    ? items.map(a => `
      <li>
        <span class="app-avatar" style="background:${avatarColour(a.exe)}" aria-hidden="true">${esc(a.name.trim()[0]?.toUpperCase() || "?")}</span>
        <span class="app-meta"><span class="app-name">${esc(a.name)}</span><span class="app-exe">${esc(a.exe)}${a.source === "store" ? ", Microsoft Store" : ""}</span></span>
        <button type="button" class="app-toggle ${a.blocked ? "is-blocked" : ""}" data-exe="${esc(a.exe)}" aria-pressed="${a.blocked}">${a.blocked ? "Blocked" : "Block"}</button>
      </li>`).join("")
    : `<li class="picker-empty">${state.installed.length ? `No installed app matches “${esc(q)}”.` : "Looking for installed apps…"}</li>`;
}

async function openPicker() {
  const dlg = $("#app-picker");
  $("#picker-search").value = "";
  renderPicker();
  dlg.showModal();
  $("#picker-search").focus();
  await loadInstalled();
  renderPicker();
}

async function togglePickerApp(e) {
  const btn = e.target.closest("button.app-toggle");
  if (!btn) return;
  const app = state.installed.find(a => a.exe === btn.dataset.exe);
  if (!app) return;
  btn.disabled = true;
  try {
    if (app.blocked) {
      const row = state.cats.find(c => c.process_name === app.exe);
      if (row) await jsonPost("/api/blocked", { app_id: row.app_id }, "DELETE");
      app.blocked = false;
      setFormMsg(`Unblocked ${app.name}.`);
    } else {
      await jsonPost("/api/blocked", { process_name: app.exe });
      app.blocked = true;
      setFormMsg(`Blocked ${app.name}.`);
    }
  } catch (err) {
    setFormMsg(err.message, true);
  }
  renderPicker();
  await load();                // refresh chips, categories and the focus note
}

async function removeBlocked(e) {
  const btn = e.target.closest("button");
  if (!btn) return;
  const li = btn.closest("li[data-app]");
  const label = li.firstChild.textContent;
  try {
    await jsonPost("/api/blocked", { app_id: +li.dataset.app }, "DELETE");
    setFormMsg(`Unblocked ${label}.`);
    const app = state.installed.find(a => a.exe === li.title);
    if (app) app.blocked = false;
    await load();
  } catch (err) {
    setFormMsg(err.message, true);
  }
}

/* ---------- teach the AI (active learning) ---------- */
async function loadTeach() {
  let items = [], ai = null;
  try { [items, ai] = await Promise.all([api(`/api/teach`), api("/api/ai")]); } catch (_) { return; }
  $("#teach-list").innerHTML = items.length
    ? items.map(it => `
      <li data-title="${esc(it.title)}">
        <span class="teach-title" title="${esc(it.title)}">${esc(it.title)}</span>
        <span class="teach-guess">${it.guess ? `AI guesses ${esc(it.guess)} (${Math.round(it.confidence * 100)}% sure)` : "AI has no guess yet"}, ${esc(fmtShort(it.seconds))} on it</span>
        <span class="teach-buttons">
          <button class="productive" data-label="productive">Productive</button>
          <button class="neutral" data-label="neutral">Neutral</button>
          <button class="distracting" data-label="distracting">Distracting</button>
        </span>
      </li>`).join("")
    : `<li class="teach-empty">Nothing to label right now. Browse a bit with the tracker running, then come back.</li>`;
  renderTeachStatus(ai);
}

function renderTeachStatus(ai) {
  if (!ai) return;
  const m = ai.metrics || {};
  const labels = ai.labels || { user: 0, demo: 0 };
  const score = m.unseen_sites_f1 != null
    ? ` Current model: known sites ${m.known_sites_f1.toFixed(2)}, unseen sites ${m.unseen_sites_f1.toFixed(2)} (macro-F1).` : "";
  $("#teach-status").textContent = ai.training
    ? "Retraining… this takes about half a minute."
    : `${labels.user} of your own labels, ${labels.demo} demo labels.${score}${ai.training_message ? " " + ai.training_message : ""}`;
  $("#retrain-btn").disabled = !!ai.training;
}

async function labelTitle(e) {
  const btn = e.target.closest("button[data-label]"); if (!btn) return;
  const li = btn.closest("li[data-title]");
  try {
    await jsonPost("/api/training-samples", { title: li.dataset.title, label: btn.dataset.label });
    li.classList.add("done");
    li.querySelector(".teach-guess").textContent = `Labelled ${btn.dataset.label}. Press Retrain to teach the model.`;
  } catch (err) { $("#teach-status").textContent = err.message; }
}

async function retrainModel() {
  $("#retrain-btn").disabled = true;
  try { renderTeachStatus(await jsonPost("/api/ai/retrain", {})); } catch (err) { $("#teach-status").textContent = err.message; return; }
  const poll = setInterval(async () => {
    const ai = await api("/api/ai").catch(() => null);
    renderTeachStatus(ai);
    if (ai && !ai.training) { clearInterval(poll); loadTeach(); load(); }
  }, 3000);
}

/* ---------- website rules + AI status ---------- */
async function loadSiteRules() {
  let rules = [];
  try { rules = await api(`/api/site-rules`); } catch (_) { return; }
  const mine = rules.filter(r => !r.builtin), builtin = rules.filter(r => r.builtin);
  $("#my-rules").innerHTML = mine.length
    ? mine.map(r => `<li class="${esc(r.category)}" data-rule="${esc(r.rule_id)}">“${esc(r.pattern)}” → ${esc(r.category)}<button type="button" aria-label="Remove rule ${esc(r.pattern)}" title="Remove">×</button></li>`).join("")
    : `<li class="rules-empty">No rules of your own yet. The built-in ones below still apply.</li>`;
  $("#builtin-summary").textContent = `Built-in rules (${builtin.length})`;
  $("#builtin-rules").innerHTML = builtin.map(r => `<li class="builtin ${esc(r.category)}">“${esc(r.pattern)}” → ${esc(r.category)}</li>`).join("");
  try {
    const ai = await api("/api/ai");
    $("#ai-line").textContent = ai.available
      ? `AI: ${ai.model_name}. It labels new browser tabs every minute${ai.last_run ? ` (last run ${ai.last_run})` : ""}.`
      : `AI is off (${ai.last_message}). Website rules still apply.`;
  } catch (_) { /* leave the line empty */ }
}

function setRuleMsg(text, isError = false) {
  const el = $("#rule-msg");
  el.textContent = text;
  el.classList.toggle("is-error", isError);
}

async function addSiteRule(e) {
  e.preventDefault();
  const pattern = $("#rule-pattern").value.trim(), category = $("#rule-category").value;
  if (!pattern) { setRuleMsg("Type part of the tab title first, for example youtube shorts", true); return; }
  try {
    let r;
    if (/^https?:\/\//i.test(pattern)) {
      // A link: FocusOs only sees tab titles, so look up the video's title.
      setRuleMsg("Looking up that video's title…");
      r = await jsonPost("/api/site-rules/from-link", { url: pattern, category });
      setRuleMsg(`“${r.video_title}” now counts as ${r.category} whenever it's open.`);
    } else {
      r = await jsonPost("/api/site-rules", { pattern, category });
      setRuleMsg(`Tabs containing “${r.pattern}” now count as ${r.category}.`);
    }
    $("#rule-pattern").value = "";
    await loadSiteRules();
    load();                                   // categories change everywhere at once
  } catch (err) { setRuleMsg(err.message, true); }
}

async function removeSiteRule(e) {
  const btn = e.target.closest("button"); if (!btn) return;
  const li = btn.closest("li[data-rule]");
  try {
    await jsonPost("/api/site-rules", { rule_id: +li.dataset.rule }, "DELETE");
    setRuleMsg("Rule removed.");
    await loadSiteRules();
    load();
  } catch (err) { setRuleMsg(err.message, true); }
}

/* ---------- focus session ---------- */
state.focusMinutes = 25;
state.focus = { running: false };

const pad2 = (n) => String(n).padStart(2, "0");
// 25:00, or 1:30:00 for sessions of an hour or more
const fmtClock = (s) => s >= 3600
  ? `${Math.floor(s / 3600)}:${pad2(Math.floor(s / 60) % 60)}:${pad2(Math.floor(s % 60))}`
  : `${pad2(Math.floor(s / 60))}:${pad2(Math.floor(s % 60))}`;
const fmtMin = (m) => m >= 60 ? `${Math.floor(m / 60)}${NBSP}h${m % 60 ? ` ${m % 60}${NBSP}min` : ""}` : `${m}${NBSP}min`;

/* ---------- focus setup: length, breaks, plan preview ---------- */
// Same rule as the tracker (BreakSchedule) and focus_control.break_plan:
// focus `every` min, break `len` min, repeat; a break with no focus after it is skipped.
function focusPlan(minutes, every, len) {
  if (!every || !len) return [{ kind: "focus", start: 0, end: minutes }];
  const out = [];
  let t = 0;
  while (t < minutes) {
    const focusEnd = Math.min(t + every, minutes);
    out.push({ kind: "focus", start: t, end: focusEnd });
    if (focusEnd + len >= minutes) { out[out.length - 1].end = minutes; break; }
    out.push({ kind: "break", start: focusEnd, end: focusEnd + len });
    t = focusEnd + len;
  }
  return out;
}

state.breaks = { on: true, every: 50, len: 10 };
try { Object.assign(state.breaks, JSON.parse(localStorage.getItem("focusos.breaks") || "{}")); } catch (_) { /* storage blocked */ }

/* Timer wheels: a scroll-snap column per unit. Scroll, drag, tap a number,
   or focus it and use the arrow keys / Page Up / Page Down. */
const WHEEL_ITEM = 40;   // px, must match .wheel li height
function makeWheel(el, max, onChange) {
  const ul = el.querySelector("ul");
  ul.innerHTML = Array.from({ length: max + 1 }, (_, i) => `<li data-v="${i}">${i}</li>`).join("");
  let value = 0, settle = 0;
  const mark = () => {
    ul.querySelectorAll("li").forEach(li => li.classList.toggle("on", +li.dataset.v === value));
    el.setAttribute("aria-valuenow", value);
    el.setAttribute("aria-valuetext", `${value} ${el.getAttribute("aria-label").toLowerCase()}`);
  };
  const set = (v, smooth = true, notify = true) => {
    value = Math.min(max, Math.max(0, v));
    el.scrollTo({ top: value * WHEEL_ITEM, behavior: smooth ? "smooth" : "auto" });
    mark();
    if (notify) onChange();
  };
  el.addEventListener("scroll", () => {
    const v = Math.min(max, Math.max(0, Math.round(el.scrollTop / WHEEL_ITEM)));
    if (v !== value) { value = v; mark(); onChange(); }
    clearTimeout(settle);
    settle = setTimeout(() => { if (Math.abs(el.scrollTop - value * WHEEL_ITEM) > 1) set(value, true, false); }, 140);
  }, { passive: true });
  ul.addEventListener("click", (e) => { const li = e.target.closest("li"); if (li) set(+li.dataset.v); });
  el.addEventListener("keydown", (e) => {
    const step = { ArrowUp: -1, ArrowDown: 1, PageUp: -5, PageDown: 5 }[e.key];
    if (e.key === "Home") { e.preventDefault(); set(0); }
    else if (e.key === "End") { e.preventDefault(); set(max); }
    else if (step) { e.preventDefault(); set(value + step); }
  });
  return { get value() { return value; }, set };
}

let wheelH = null, wheelM = null;

// What will actually be sent: length, and breaks only if they fit.
function focusSetup() {
  const minutes = wheelH ? wheelH.value * 60 + wheelM.value : 25;
  const valid = minutes >= 1 && minutes <= 480;
  const b = state.breaks;
  const fits = b.every + b.len < minutes;
  const useBreaks = valid && b.on && fits;
  return { minutes, valid, fits, useBreaks, every: useBreaks ? b.every : 0, len: useBreaks ? b.len : 0 };
}

function renderPlan(el, plan) {
  el.innerHTML = plan.map(p => {
    const len = p.end - p.start;
    const label = p.kind === "break" ? `${len}` : fmtMin(len);
    return `<span class="plan-seg ${p.kind}" style="flex-grow:${len}" title="${esc(p.kind === "break" ? "Break" : "Focus")}: ${esc(fmtMin(len))}"><span>${esc(label)}</span></span>`;
  }).join("");
}

function syncFocusSetup() {
  const f = focusSetup();
  const hint = $("#length-hint");
  hint.textContent = f.minutes > 480 ? "The longest session is 8 hours." : f.minutes < 1 ? "Turn a wheel to pick a length." : "";
  hint.classList.toggle("is-error", !f.valid);
  document.querySelectorAll("#durations button").forEach(x => x.classList.toggle("active", +x.dataset.min === f.minutes));

  // Break cards: the chosen one is marked; ones that don't fit this length are greyed.
  const b = state.breaks;
  const chosen = b.on ? `${b.every}-${b.len}` : "off";
  document.querySelectorAll("#break-options button").forEach(x => {
    const on = x.dataset.break === chosen;
    const [every, len] = x.dataset.break.split("-").map(Number);
    const tooShort = x.dataset.break !== "off" && every + len >= f.minutes;
    x.classList.toggle("active", on);
    x.classList.toggle("too-short", tooShort);
    x.setAttribute("aria-checked", on);
    x.tabIndex = on ? 0 : -1;
    x.title = tooShort ? `Needs a session longer than ${fmtMin(every + len)}` : "";
  });
  const note = $("#break-note");
  note.textContent = !f.valid ? "" : b.on && !f.fits
    ? `No break needed in a ${fmtMin(f.minutes)} session. Breaks start once a session is longer than ${fmtMin(b.every + b.len)}.`
    : b.on ? "Blocked apps are allowed during a break. You'll get a notification when it starts and ends." : "";

  const plan = focusPlan(f.minutes, f.every, f.len);
  $("#plan").hidden = !f.valid || !f.useBreaks;
  if (f.valid) renderPlan($("#plan"), plan);
  const nBreaks = plan.filter(p => p.kind === "break").length;
  const focusMin = plan.filter(p => p.kind === "focus").reduce((a, p) => a + p.end - p.start, 0);
  const ends = new Date(Date.now() + f.minutes * 60000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  $("#plan-text").textContent = !f.valid ? "" : nBreaks
    ? `${fmtMin(focusMin)} of focus and ${nBreaks} break${nBreaks === 1 ? "" : "s"}. Ends around ${ends}.`
    : `${fmtMin(f.minutes)} of focus. Ends around ${ends}.`;

  if (!state.focus.running && state.focus.supported !== false && state.focus.tracker_found !== false)
    $("#focus-start").disabled = !f.valid;
  $("#focus-cmd").textContent = `focus_tracker.exe --focus --minutes ${f.minutes}` +
    (f.useBreaks ? ` --break-every ${f.every} --break ${f.len}` : "");
}

function saveBreaks() {
  try { localStorage.setItem("focusos.breaks", JSON.stringify(state.breaks)); } catch (_) { /* storage blocked */ }
  syncFocusSetup();
}

// The session as a ring, like a kitchen timer: the coloured part is what's
// left (focus white, breaks amber) and shrinks clockwise as time passes.
function renderRing(plan, total, elapsedMin) {
  const R = 108, C = 2 * Math.PI * R, GAP = plan.length > 1 ? 1.2 : 0;   // GAP in % of the circle
  const arc = (from, to, cls) => {
    const len = Math.max(0, (to - from) - GAP);
    if (len <= 0) return "";
    return `<circle class="${cls}" cx="120" cy="120" r="${R}" pathLength="100"
      stroke-dasharray="${len.toFixed(3)} ${(100 - len).toFixed(3)}" stroke-dashoffset="${(-from - GAP / 2).toFixed(3)}"/>`;
  };
  let out = `<circle class="timer-track" cx="120" cy="120" r="${R}"/>`;
  for (const p of plan) {
    const a = 100 * p.start / total, b = 100 * p.end / total, now = 100 * elapsedMin / total;
    if (now < b) out += arc(Math.max(a, now), b, `timer-seg ${p.kind}`);
  }
  $("#timer-ring").innerHTML = `<g transform="rotate(-90 120 120)">${out}</g>`;
  void C;
}

function renderFocus() {
  const f = state.focus;
  const live = !!(f.running && f.focus && f.remaining_s != null);
  $("#focus-hero").classList.toggle("is-live", f.running);
  $("#focus-idle").hidden = f.running;
  $("#focus-live").hidden = !f.running;

  const startBtn = $("#focus-start");
  if (f.supported === false) {
    startBtn.disabled = true;
    setFocusNote(f.message || "Focus sessions need Windows.", true);
  } else if (f.tracker_found === false) {
    startBtn.disabled = true;
    setFocusNote("Build the tracker first (tracker\\build\\focus_tracker.exe), then refresh.", true);
  } else {
    startBtn.disabled = !focusSetup().valid;
  }

  let onBreak = false;
  if (f.running) {
    if (live) {
      $("#countdown").textContent = fmtClock(f.remaining_s);
      $("#live-note").textContent = "Changes to blocked apps apply to your next session.";
      const elapsedS = f.minutes * 60 - f.remaining_s;
      const nowMin = elapsedS / 60;
      const plan = (f.plan || [{ kind: "focus", start_min: 0, end_min: f.minutes }])
        .map(p => ({ kind: p.kind, start: p.start_min, end: p.end_min }));
      const cur = plan.find(p => p.start <= nowMin && nowMin < p.end);
      onBreak = cur?.kind === "break";
      renderRing(plan, f.minutes, nowMin);
      const next = plan.find(p => p.kind === "break" && p.start > nowMin);
      const left = cur ? Math.max(0, Math.round(cur.end * 60 - elapsedS)) : 0;
      $("#phase-line").textContent = onBreak
        ? `Break, ${fmtClock(left)} left`
        : next ? `Break in ${fmtClock(Math.max(0, Math.round(next.start * 60 - elapsedS)))}`
               : plan.length > 1 ? "Last stretch" : "";
      const ends = new Date(Date.now() + f.remaining_s * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      $("#timer-ends").textContent = `Ends ${ends}`;
      if (onBreak) $("#live-note").textContent = "Your blocked apps are allowed until the break ends.";
    } else {
      $("#countdown").textContent = "On";
      renderRing([{ kind: "focus", start: 0, end: 1 }], 1, 0);
      $("#phase-line").textContent = "";
      $("#timer-ends").textContent = "";
      $("#live-note").textContent = "The tracker was started outside the dashboard. You can still end it here.";
    }
  }
  $("#live-heading").textContent = onBreak ? "On a break" : "Focusing";
  $("#focus-hero").classList.toggle("is-break", onBreak);

  const chip = $("#today-focus");
  chip.classList.toggle("is-live", f.running);
  $("#today-focus-text").textContent = f.running
    ? (live ? `${onBreak ? "On a break" : "Focusing"}, ${fmtClock(f.remaining_s)} left` : "Tracker running") : "Start focus";
}

function setFocusNote(text, isError = false) {
  const el = $("#focus-note");
  el.textContent = text;
  el.classList.toggle("is-error", isError);
}

async function refreshFocus() {
  const wasRunning = state.focus.running;
  try { state.focus = await api("/api/focus"); } catch (_) { state.focus = { running: false }; }
  renderFocus();
  // A session just ended (time up or stopped elsewhere): show its summary.
  if (wasRunning && !state.focus.running) { state.selectedFocusId = null; loadFocusHistory(); }
}

/* ---------- focus session details: live stats, summary, history ---------- */
state.focusHistory = [];
state.selectedFocusId = null;     // reserved: always show the latest finished session

const OUTCOME_TEXT = { completed: "Completed", "ended early": "Ended early", running: "In progress", finished: "Finished" };
const pctOf = (part, whole) => whole > 0 ? Math.round(100 * part / whole) : 0;

function fmtWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

async function loadFocusHistory() {
  try {
    state.focusHistory = await api(`/api/focus/sessions`);
  } catch (_) {
    state.focusHistory = [];
  }
  const live = state.focusHistory.find(s => s.live);
  const pick = state.selectedFocusId ?? (state.focusHistory.find(s => !s.live) || null)?.session_id;
  if (live && state.focus.running) loadLiveDetail(live.session_id);
  if (pick) loadFocusSummary(pick); else $("#focus-summary").hidden = true;
}

// "closed 2×, minimised 1×" (force-closes count as closed, marked "forced")
function describeActions(b) {
  const a = b.actions || {};
  const parts = [];
  const closed = (a.closed || 0) + (a.terminated || 0);
  if (closed) parts.push(`closed ${closed}×${a.terminated ? ` (${a.terminated} forced)` : ""}`);
  if (a.minimised) parts.push(`minimised ${a.minimised}×`);
  return parts.length ? parts.join(", ") : `${b.count}×`;
}

// Live stats inside the violet "Focusing" panel.
async function loadLiveDetail(id) {
  let d;
  try { d = await api(`/api/focus/session/${id}`); } catch (_) { return; }
  if (!d.live) return;
  $("#ls-prod").textContent = fmtShort(d.productive_s);
  $("#ls-dist").textContent = fmtShort(d.distracting_s);
  $("#ls-blocks").textContent = d.blocks;
  $("#ls-now").textContent = d.last_app ? d.last_app.process_name : "Saving first data…";
  $("#ls-now").title = d.last_app ? d.last_app.title : "";
  renderTimeline($("#live-timeline"), d.segments, Date.parse(d.start), Date.now());

  // Apps used so far, one row per app (Chrome tabs in different categories are
  // merged; the dot shows where most of its time went). Longest first; the
  // app in front right now is marked.
  const nowApp = d.last_app?.process_name;
  const merged = new Map();
  for (const a of d.apps) {
    const m = merged.get(a.process_name) || { process_name: a.process_name, seconds: 0, best: 0, category: a.category };
    m.seconds += a.seconds;
    if (a.seconds > m.best) { m.best = a.seconds; m.category = a.category; }
    merged.set(a.process_name, m);
  }
  const liveApps = [...merged.values()].sort((x, y) => y.seconds - x.seconds);
  $("#live-apps").innerHTML = liveApps.length
    ? liveApps.map(a => `<li class="${a.process_name === nowApp ? "is-now" : ""}" title="${esc(a.category)}">
        <span class="ll-dot ${esc(a.category)}" aria-hidden="true"></span>
        <span class="ll-name">${esc(a.process_name)}</span>
        ${a.process_name === nowApp ? '<span class="ll-now">now</span>' : ""}
        <span class="ll-time">${esc(fmtShort(a.seconds))}</span></li>`).join("")
    : `<li class="ll-empty">Waiting for the first app…</li>`;
  $("#live-blocked").innerHTML = d.blocked_apps.length
    ? d.blocked_apps.map(b => `<li><span class="ll-name">${esc(b.process_name)}</span><span class="ll-time">${esc(describeActions(b))}</span></li>`).join("")
    : `<li class="ll-empty">None so far.</li>`;
}

async function loadFocusSummary(id) {
  let d;
  try { d = await api(`/api/focus/session/${id}`); } catch (_) { return; }
  const card = $("#focus-summary");
  card.hidden = false;
  const isLatest = state.focusHistory.find(s => !s.live)?.session_id === id;
  $("#fs-title").textContent = isLatest ? "Your last focus session" : `Focus session ${d.session_id}`;
  $("#fs-see-all").dataset.id = d.session_id;
  const out = $("#fs-outcome");
  out.textContent = OUTCOME_TEXT[d.outcome] || d.outcome;
  out.className = `outcome ${d.outcome.replace(" ", "-")}`;
  const planned = d.planned_minutes ? `, planned ${d.planned_minutes}${NBSP}min` : "";
  $("#fs-when").textContent = `${fmtWhen(d.start)}${planned}`;
  $("#fs-score").textContent = Math.round(d.focus_score);
  $("#fs-score").className = `fs-value score ${scoreCls(d.focus_score)}`;
  $("#fs-length").textContent = fmtShort(d.duration_s);
  $("#fs-prod").textContent = fmtShort(d.productive_s);
  $("#fs-dist").textContent = fmtShort(d.distracting_s);
  $("#fs-blocks").textContent = d.blocks;
  $("#fs-switches").textContent = d.switches;
  renderTimeline($("#fs-timeline"), d.segments, Date.parse(d.start), d.end ? Date.parse(d.end) : null);
  $("#fs-apps").innerHTML = d.apps.length
    ? d.apps.map(a => `<li><span class="proc">${esc(a.process_name)}</span><span>${badge(a.category)} <span class="muted">${esc(fmtShort(a.seconds))}</span></span></li>`).join("")
    : `<li class="fs-empty">No app activity was saved.</li>`;
  $("#fs-blocked").innerHTML = d.blocked_apps.length
    ? d.blocked_apps.map(b => `<li><span class="proc">${esc(b.process_name)}</span><span class="muted">${esc(describeActions(b))}</span></li>`).join("")
    : `<li class="fs-empty">No blocked app tried to open. Nice.</li>`;
}

// One timer: ticks the countdown every second, re-syncs with the server
// every 10 s, and refreshes the live stats every 5 s while focusing.
let focusTick = 0;
setInterval(() => {
  const f = state.focus;
  if (f.running && f.remaining_s != null) {
    f.remaining_s = Math.max(0, f.remaining_s - 1);
    renderFocus();
    if (f.remaining_s === 0) setTimeout(async () => { await refreshFocus(); load(); }, 2500);
  }
  focusTick++;
  if (focusTick % 10 === 0) refreshFocus();
  if (f.running && focusTick % 5 === 0) {
    const live = state.focusHistory.find(s => s.live);
    if (live) loadLiveDetail(live.session_id); else loadFocusHistory();
  }
}, 1000);

async function startFocus() {
  const btn = $("#focus-start");
  btn.disabled = true;
  setFocusNote("Starting…");
  try {
    const setup = focusSetup();
    try { localStorage.setItem("focusos.minutes", String(setup.minutes)); } catch (_) { /* storage blocked */ }
    state.focus = await jsonPost("/api/focus/start", { minutes: setup.minutes, on_block: state.onBlock,
                                                       break_every: setup.every, break_min: setup.len });
    renderFocus();
    setFocusNote("");
    loadFocusHistory();
  } catch (err) {
    btn.disabled = false;
    setFocusNote(err.message, true);
  }
}

async function stopFocus() {
  const btn = $("#focus-stop");
  btn.disabled = true;
  btn.textContent = "Saving your session…";
  try {
    state.focus = await jsonPost("/api/focus/stop", {});
  } catch (err) {
    $("#live-note").textContent = err.message;
  }
  btn.disabled = false;
  btn.textContent = "End now";
  renderFocus();
  state.selectedFocusId = null;
  await loadFocusHistory();
  $("#focus-summary").scrollIntoView({ behavior: "smooth", block: "start" });
  load();
}

function initFocus() {
  // Timer wheels, starting at the last length used (25 min the first time).
  let last = 25;
  try { last = +localStorage.getItem("focusos.minutes") || 25; } catch (_) { /* storage blocked */ }
  wheelH = makeWheel($("#wheel-h"), 8, syncFocusSetup);
  wheelM = makeWheel($("#wheel-m"), 59, syncFocusSetup);
  const setLength = (min, smooth) => { wheelH.set(Math.floor(min / 60), smooth, false); wheelM.set(min % 60, smooth, false); syncFocusSetup(); };
  // The wheels only have a size once the Focus tab is visible: position them then.
  state.applyWheelLength = () => setLength(focusSetup().minutes || last, false);
  setLength(last, false);
  $("#durations").onclick = (e) => {
    const b = e.target.closest("button[data-min]"); if (b) setLength(+b.dataset.min, true);
  };
  const pickBreak = (key) => {
    if (key === "off") state.breaks.on = false;
    else { const [every, len] = key.split("-").map(Number); Object.assign(state.breaks, { on: true, every, len }); }
    saveBreaks();
  };
  $("#break-options").onclick = (e) => { const b = e.target.closest("button[data-break]"); if (b) pickBreak(b.dataset.break); };
  $("#break-options").addEventListener("keydown", (e) => {
    const dir = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key]; if (!dir) return;
    e.preventDefault();
    const btns = [...document.querySelectorAll("#break-options button")];
    const i = btns.findIndex(x => x.classList.contains("active"));
    const nxt = btns[(i + dir + btns.length) % btns.length];
    pickBreak(nxt.dataset.break); nxt.focus();
  });
  syncFocusSetup();
  // Close or minimise blocked apps (remembered in this browser).
  try { state.onBlock = localStorage.getItem("focusos.onBlock") === "minimise" ? "minimise" : "close"; } catch (_) { state.onBlock = "close"; }
  const syncOnBlock = () => {
    document.querySelectorAll(".on-block button").forEach(x => {
      const on = x.dataset.action === state.onBlock;
      x.classList.toggle("active", on);
      x.setAttribute("aria-checked", on);
      x.tabIndex = on ? 0 : -1;                // radio group: Tab reaches the chosen option only
    });
    updateFocusNote();
  };
  // Arrow keys move between the options, like a native radio group.
  document.querySelector(".on-block").addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    e.preventDefault();
    state.onBlock = state.onBlock === "close" ? "minimise" : "close";
    try { localStorage.setItem("focusos.onBlock", state.onBlock); } catch (_) { /* storage blocked */ }
    syncOnBlock();
    document.querySelector(`.on-block button[data-action="${state.onBlock}"]`).focus();
  });
  document.querySelector(".on-block").onclick = (e) => {
    const b = e.target.closest("button[data-action]"); if (!b) return;
    state.onBlock = b.dataset.action;
    try { localStorage.setItem("focusos.onBlock", state.onBlock); } catch (_) { /* storage blocked */ }
    syncOnBlock();
  };
  syncOnBlock();
  $("#focus-start").onclick = startFocus;
  $("#focus-stop").onclick = stopFocus;
  $("#blocked-chips").onclick = removeBlocked;
  // Theme switch: glass (default) <-> classic, remembered in this browser.
  const syncThemeButton = () => {
    const glass = document.documentElement.dataset.style === "glass";
    $("#theme-name").textContent = glass ? "Glass" : "Classic";
    $("#theme-toggle").setAttribute("aria-label", `Theme: ${glass ? "glass" : "classic"}. Switch theme`);
  };
  $("#theme-toggle").onclick = () => {
    const next = document.documentElement.dataset.style === "glass" ? "classic" : "glass";
    document.documentElement.dataset.style = next;
    try { localStorage.setItem("focusos.theme", next); } catch (_) { /* storage blocked */ }
    syncThemeButton();
    if (state.data) load();                    // charts read colours when drawn: redraw them
  };
  syncThemeButton();

  // Light / dark: Auto (follow Windows) -> Light -> Dark -> Auto ...
  const MODES = ["auto", "light", "dark"];
  const MODE_NAMES = { auto: "Auto", light: "Light", dark: "Dark" };
  const currentMode = () => document.documentElement.dataset.theme || "auto";
  const syncModeButton = () => {
    const m = currentMode();
    $("#mode-toggle").dataset.mode = m;
    $("#mode-name").textContent = MODE_NAMES[m];
    $("#mode-toggle").setAttribute("aria-label", `Colour mode: ${MODE_NAMES[m]}. Switch mode`);
  };
  $("#mode-toggle").onclick = () => {
    const next = MODES[(MODES.indexOf(currentMode()) + 1) % MODES.length];
    if (next === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    try { localStorage.setItem("focusos.mode", next); } catch (_) { /* storage blocked */ }
    syncModeButton();
    if (state.data) load();                    // charts take their colours when drawn
  };
  // In Auto, follow Windows switching between light and dark while the page is open.
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (currentMode() === "auto" && state.data) load();
  });
  syncModeButton();
  $("#rule-form").onsubmit = addSiteRule;
  $("#teach-list").onclick = labelTitle;
  $("#retrain-btn").onclick = retrainModel;
  $("#my-rules").onclick = removeSiteRule;
  $("#open-picker").onclick = openPicker;
  $("#close-picker").onclick = () => $("#app-picker").close();
  $("#picker-search").oninput = renderPicker;
  $("#picker-list").onclick = togglePickerApp;
  // Click on the dimmed backdrop closes the dialog.
  $("#app-picker").addEventListener("click", (e) => { if (e.target.id === "app-picker") e.target.close(); });
  // The Today chip: jump to the Focus tab (or show the running session there).
  $("#today-focus").onclick = () => document.querySelector('.tabs button[data-tab="settings"]').click();
  $("#fs-see-all").onclick = (e) => { e.preventDefault(); openInSessions(+e.currentTarget.dataset.id); };
  $("#session-filter").onclick = (e) => {
    const b = e.target.closest("button[data-filter]"); if (b) setSessionFilter(b.dataset.filter);
  };
  refreshFocus();
}

initFocus();
init();