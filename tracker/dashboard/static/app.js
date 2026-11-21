const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const COLOURS = { get productive() { return cssv("--productive"); }, get neutral() { return cssv("--neutral"); }, get distracting() { return cssv("--distracting"); }, get idle() { return cssv("--idle"); } };
const PRIMARY = () => cssv("--productive");
const CATS = ["productive", "neutral", "distracting"];

const state = { user: null, range: "7d", data: null, charts: {} };

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
    const users = await api("/api/users");
    const sel = $("#user");
    sel.innerHTML = users.map(u => `<option value="${esc(u.user_id)}">${esc(u.name)} (id ${esc(u.user_id)})</option>`).join("");
    state.user = users[0]?.user_id ?? 1;
    sel.onchange = () => { state.user = +sel.value; state.goalOverride = undefined; load(); };
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
      api(`/api/summary?user=${state.user}&range=${state.range}`),
      api(`/api/categories?user=${state.user}`),
      api(`/api/processes?user=${state.user}&range=${state.range}`),
      // Installed apps (cached on the server) so blocked chips show friendly names.
      api(`/api/installed-apps?user=${state.user}`).catch(() => state.installed),
    ]);
    state.installed = installed;
    state.data = summary;
    renderOverview(summary);
    renderSessions(summary);
    renderApps(summary);
    renderProcesses(procs);
    renderSettings(cats);
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
const goalKey = () => `focusos.goalHours.${state.user}`;
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
  const name = $("#user").selectedOptions[0]?.textContent.replace(/\s*\(id \d+\)$/, "") || "";

  $("#greeting").textContent = name && name !== "default" ? `${greetingFor(new Date())}, ${name}` : greetingFor(new Date());

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

  const hrs = Array.from({ length: 24 }, () => []);
  d.sessions.forEach(s => hrs[+s.start_time.slice(11, 13)].push(s.focus_score));
  const hAvg = hrs.map(a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
  chart("chart-hour", {
    type: "bar",
    data: { labels: hrs.map((_, h) => String(h).padStart(2, "0")), datasets: [{ label: "avg focus score", data: hAvg.map(v => +v.toFixed(0)),
      backgroundColor: hAvg.map((v, h) => !hrs[h].length ? COLOURS.idle : v < 40 ? COLOURS.distracting : COLOURS.productive) }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 100, border: { display: false } }, x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }, title: { display: true, text: "Hour the session started (UTC)" } } } },
  });

  chart("chart-daily", {
    type: "bar",
    data: {
      labels: dates,
      datasets: CATS.map(c => ({
        label: c[0].toUpperCase() + c.slice(1), backgroundColor: COLOURS[c],
        data: dates.map(dt => d.daily.find(r => r.date === dt && r.category === c)?.minutes ?? 0),
        maxBarThickness: 44,
      })),
    },
    options: { scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, border: { display: false }, title: { display: true, text: "Minutes" } } } },
  });

  const sess = [...d.sessions].sort((a, b) => a.start_time.localeCompare(b.start_time));
  const jade = PRIMARY();
  chart("chart-trend", {
    type: "line",
    data: { labels: sess.map(s => fmtTs(s.start_time)), datasets: [{ label: "Focus score", data: sess.map(s => s.focus_score),
      borderColor: jade, backgroundColor: /^#[0-9a-f]{6}$/i.test(jade) ? `${jade}1f` : jade, fill: true, tension: 0.25, pointRadius: 3, pointBackgroundColor: jade }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 100, border: { display: false } }, x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } } } },
  });
}

function renderSessions(d) {
  const tb = $("#sessions-table tbody");
  if (!d.sessions.length) { tb.innerHTML = `<tr><td colspan="11" class="empty">No sessions in this range. Try a longer range.</td></tr>`; return; }
  tb.innerHTML = d.sessions.map(s => `
    <tr class="clickable" data-id="${esc(s.session_id)}">
      <td>${esc(s.session_id)}</td><td>${esc(fmtTs(s.start_time))}</td><td>${s.duration_min} min</td><td>${mix(s)}</td>
      <td>${s.productive_min}</td><td>${s.neutral_min}</td><td>${s.distracting_min}</td><td>${s.idle_min}</td>
      <td>${s.switches}</td><td>${s.focus_mode ? "on" : "off"}</td>
      <td class="score ${scoreCls(s.focus_score)}">${s.focus_score}</td>
    </tr>`).join("");
  tb.onclick = (e) => {
    const tr = e.target.closest("tr[data-id]"); if (!tr) return;
    tb.querySelectorAll("tr").forEach(r => r.classList.remove("selected")); tr.classList.add("selected");
    showSession(+tr.dataset.id);
  };
}

async function showSession(id) {
  const { segments } = await api(`/api/session/${id}?user=${state.user}`);
  const m = state.data.sessions.find(s => s.session_id === id);
  $("#session-detail").hidden = false;
  $("#detail-id").textContent = id;

  const tl = $("#timeline"); tl.innerHTML = "";
  if (segments.length) {
    const t0 = Date.parse(segments[0].start);
    const t1 = Math.max(...segments.map(s => Date.parse(s.end)));
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
  $("#formula-values").textContent =
    `T_productive = ${m.productive_min} min, T_session = ${m.duration_min} min, T_idle = ${m.idle_min} min, ` +
    `S = ${m.switches} switches, S_max = ${state.data.s_max}/h  →  score ${m.focus_score}`;
  $("#session-detail").scrollIntoView({ behavior: "smooth", block: "start" });
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
      body: JSON.stringify({ user: state.user, app_id, label: e.target.value }) });
    load();
  };
  tb.onclick = async (e) => {
    if (!e.target.classList.contains("reset")) return;
    const app_id = +e.target.closest("tr").dataset.app;
    await api("/api/categories", { method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: state.user, app_id }) });
    load();
  };
  const blocked = cats.filter(c => c.effective_category === "distracting").map(c => c.process_name);
  $("#blocked-list").textContent = blocked.join(", ") || "none";
  $("#focus-cmd").textContent = `focus_tracker.exe --user ${state.user} --focus --minutes ${state.focusMinutes}`;
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
  const active = blocked.filter(c => !state.installed.length || byExe.has(c.process_name)).length;
  $("#focus-note").textContent = active
    ? `${active} app${active === 1 ? "" : "s"} will be minimised as soon as ${active === 1 ? "it opens" : "they open"}.`
    : "Your block list is empty, so nothing will be minimised.";
}

function setFormMsg(text, isError = false) {
  const el = $("#add-app-msg");
  el.textContent = text;
  el.classList.toggle("is-error", isError);
}

async function loadInstalled(refresh = false) {
  try {
    state.installed = await api(`/api/installed-apps?user=${state.user}${refresh ? "&refresh=1" : ""}`);
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
      if (row) await jsonPost("/api/blocked", { user: state.user, app_id: row.app_id }, "DELETE");
      app.blocked = false;
      setFormMsg(`Unblocked ${app.name}.`);
    } else {
      await jsonPost("/api/blocked", { user: state.user, process_name: app.exe });
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
    await jsonPost("/api/blocked", { user: state.user, app_id: +li.dataset.app }, "DELETE");
    setFormMsg(`Unblocked ${label}.`);
    const app = state.installed.find(a => a.exe === li.title);
    if (app) app.blocked = false;
    await load();
  } catch (err) {
    setFormMsg(err.message, true);
  }
}

/* ---------- focus session ---------- */
state.focusMinutes = 25;
state.focus = { running: false };

const pad2 = (n) => String(n).padStart(2, "0");
const fmtClock = (s) => `${pad2(Math.floor(s / 60))}:${pad2(Math.floor(s % 60))}`;

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
    startBtn.disabled = false;
  }

  if (f.running) {
    if (live) {
      $("#countdown").textContent = fmtClock(f.remaining_s);
      const done = 1 - f.remaining_s / (f.minutes * 60);
      $("#live-bar-fill").style.width = `${(100 * Math.min(Math.max(done, 0), 1)).toFixed(1)}%`;
      $("#live-note").textContent = "Changes to blocked apps apply to your next session.";
    } else {
      $("#countdown").textContent = "On";
      $("#live-bar-fill").style.width = "100%";
      $("#live-note").textContent = "The tracker was started outside the dashboard. You can still end it here.";
    }
  }

  const chip = $("#today-focus");
  chip.classList.toggle("is-live", f.running);
  $("#today-focus-text").textContent = f.running ? (live ? `Focusing, ${fmtClock(f.remaining_s)} left` : "Tracker running") : "Start focus";
}

function setFocusNote(text, isError = false) {
  const el = $("#focus-note");
  el.textContent = text;
  el.classList.toggle("is-error", isError);
}

async function refreshFocus() {
  try { state.focus = await api("/api/focus"); } catch (_) { state.focus = { running: false }; }
  renderFocus();
}

// One timer: ticks the countdown every second, re-syncs with the server every 10 s.
let focusTick = 0;
setInterval(() => {
  const f = state.focus;
  if (f.running && f.remaining_s != null) {
    f.remaining_s = Math.max(0, f.remaining_s - 1);
    renderFocus();
    if (f.remaining_s === 0) setTimeout(async () => { await refreshFocus(); load(); }, 2500);
  }
  if (++focusTick % 10 === 0) refreshFocus();
}, 1000);

async function startFocus() {
  const btn = $("#focus-start");
  btn.disabled = true;
  setFocusNote("Starting…");
  try {
    state.focus = await jsonPost("/api/focus/start", { user: state.user, minutes: state.focusMinutes });
    renderFocus();
    setFocusNote("");
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
  load();
}

function initFocus() {
  $("#durations").onclick = (e) => {
    const b = e.target.closest("button[data-min]"); if (!b) return;
    document.querySelectorAll("#durations button").forEach(x => { x.classList.toggle("active", x === b); x.setAttribute("aria-checked", x === b); });
    state.focusMinutes = +b.dataset.min;
    $("#focus-cmd").textContent = `focus_tracker.exe --user ${state.user} --focus --minutes ${state.focusMinutes}`;
  };
  $("#focus-start").onclick = startFocus;
  $("#focus-stop").onclick = stopFocus;
  $("#blocked-chips").onclick = removeBlocked;
  $("#open-picker").onclick = openPicker;
  $("#close-picker").onclick = () => $("#app-picker").close();
  $("#picker-search").oninput = renderPicker;
  $("#picker-list").onclick = togglePickerApp;
  // Click on the dimmed backdrop closes the dialog.
  $("#app-picker").addEventListener("click", (e) => { if (e.target.id === "app-picker") e.target.close(); });
  // The Today chip: jump to the Focus tab (or show the running session there).
  $("#today-focus").onclick = () => document.querySelector('.tabs button[data-tab="settings"]').click();
  refreshFocus();
}

initFocus();
init();