const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const COLOURS = { get productive() { return cssv("--productive"); }, get neutral() { return cssv("--neutral"); }, get distracting() { return cssv("--distracting"); }, get idle() { return cssv("--idle"); } };
const PRIMARY = () => cssv("--productive");
const CATS = ["productive", "neutral", "distracting"];

const state = { user: null, range: "7d", data: null, charts: {} };

const $ = (sel) => document.querySelector(sel);
const fmtH = (h) => `${h.toFixed(1)} h`;
const fmtTs = (iso) => iso ? iso.replace("T", " ").replace("Z", "") : "";
const badge = (c) => `<span class="badge ${c}">${c}</span>`;
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
  const css = getComputedStyle(document.documentElement);
  Chart.defaults.font.family = "Inter, Helvetica, Arial, sans-serif";
  Chart.defaults.color = css.getPropertyValue("--muted").trim();
  Chart.defaults.borderColor = css.getPropertyValue("--rule").trim();
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.labels.boxHeight = 8;
  Chart.defaults.elements.bar.borderRadius = 0;
  Chart.defaults.elements.line.borderWidth = 2;
  state.charts[id] = new Chart($(`#${id}`), config);
}

/* ---------- init ---------- */
async function init() {
  try {
    const users = await api("/api/users");
    const sel = $("#user");
    sel.innerHTML = users.map(u => `<option value="${u.user_id}">${u.name} (id ${u.user_id})</option>`).join("");
    state.user = users[0]?.user_id ?? 1;
    sel.onchange = () => { state.user = +sel.value; load(); };
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
  $("#refresh").onclick = load;
  load();
}

/* ---------- load + render ---------- */
async function load() {
  $("#status").textContent = "Loading…";
  try {
    const [summary, cats] = await Promise.all([
      api(`/api/summary?user=${state.user}&range=${state.range}`),
      api(`/api/categories?user=${state.user}`),
    ]);
    state.data = summary;
    renderOverview(summary);
    renderSessions(summary);
    renderApps(summary);
    renderSettings(cats);
    $("#status").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    $("#status").textContent = e.message;
  }
}

function renderOverview(d) {
  const t = d.totals;
  $("#m-tracked").textContent = fmtH(t.tracked_h);
  $("#m-prod").textContent = fmtH(t.productive_h);
  $("#m-dist").textContent = fmtH(t.distracting_h);
  $("#m-focus").textContent = t.avg_focus.toFixed(0);
  $("#m-prod-pct").textContent = t.tracked_h ? `${(100 * t.productive_h / t.tracked_h).toFixed(0)}% of time` : "";
  $("#m-dist-pct").textContent = t.tracked_h ? `${(100 * t.distracting_h / t.tracked_h).toFixed(0)}% of time` : "";

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
    options: { plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 100 }, x: { grid: { display: false }, title: { display: true, text: "start hour (UTC)" } } } },
  });

  chart("chart-daily", {
    type: "bar",
    data: {
      labels: dates,
      datasets: CATS.map(c => ({
        label: c, backgroundColor: COLOURS[c],
        data: dates.map(dt => d.daily.find(r => r.date === dt && r.category === c)?.minutes ?? 0),
      })),
    },
    options: { responsive: true, scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: "minutes" } } } },
  });

  chart("chart-pie", {
    type: "doughnut",
    data: { labels: CATS, datasets: [{ data: [t.productive_h, t.neutral_h, t.distracting_h], backgroundColor: CATS.map(c => COLOURS[c]), borderWidth: 2, borderColor: cssv("--bg") }] },
    options: { cutout: "72%", plugins: { legend: { position: "bottom" } } },
  });

  const sess = [...d.sessions].sort((a, b) => a.start_time.localeCompare(b.start_time));
  chart("chart-trend", {
    type: "line",
    data: { labels: sess.map(s => fmtTs(s.start_time)), datasets: [{ label: "focus score", data: sess.map(s => s.focus_score), borderColor: PRIMARY(), backgroundColor: PRIMARY(), tension: 0, pointRadius: 2 }] },
    options: { scales: { y: { min: 0, max: 100 } } },
  });
}

function renderSessions(d) {
  const tb = $("#sessions-table tbody");
  if (!d.sessions.length) { tb.innerHTML = `<tr><td colspan="11" class="empty">No sessions in this range. Try a longer range.</td></tr>`; return; }
  tb.innerHTML = d.sessions.map(s => `
    <tr class="clickable" data-id="${s.session_id}">
      <td>${s.session_id}</td><td>${fmtTs(s.start_time)}</td><td>${s.duration_min} min</td><td>${mix(s)}</td>
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
    data: { labels: d.top_apps.map(a => a.process_name), datasets: [{ label: "minutes", data: d.top_apps.map(a => a.minutes), backgroundColor: d.top_apps.map(a => COLOURS[a.category]) }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } } },
  });
  const tb = $("#recent-table tbody");
  tb.innerHTML = d.recent.length ? d.recent.map(r => `
    <tr><td>${fmtTs(r.start_time)}</td><td><code>${r.process_name}</code></td>
    <td class="title" title="${r.window_title ?? ""}">${r.window_title ?? ""}</td>
    <td>${badge(r.category)}</td><td>${Math.round(r.seconds)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">Nothing recorded yet.</td></tr>`;
}

function renderSettings(cats) {
  const tb = $("#cat-table tbody");
  tb.innerHTML = cats.map(c => `
    <tr data-app="${c.app_id}">
      <td><code>${c.process_name}</code></td><td>${badge(c.default_category)}</td>
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
  $("#focus-cmd").textContent = `focus_tracker.exe --db focus.db --user ${state.user} --focus`;
}

init();