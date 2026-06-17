const THEME_KEY = "nexus-theme";
const SKIN_KEY = "nexus-skin";

function initTheme() {
  const t = localStorage.getItem(THEME_KEY) || "light";
  document.documentElement.setAttribute("data-theme", t);
  // Single look ("fresh") — the old "classic" skin has been removed.
  document.documentElement.setAttribute("data-skin", "fresh");
  localStorage.setItem(SKIN_KEY, "fresh");
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem(THEME_KEY, next);
  const btn = document.getElementById("theme-btn");
  if (btn) btn.textContent = next === "dark" ? "Light" : "Dark";
}
function currentSkin() { return "fresh"; }
function toggleSkin() { /* removed: single look */ }
initTheme();

const NAV = [["/", "Dashboard"], ["/calendar", "Calendar"], ["/library", "Library"], ["/materials", "Materials"],
  ["/announcements", "Announcements"], ["/community", "Community"], ["/completed", "Completed"], ["/chat", "Chat"],
  ["/notifications", "Notifications"], ["/settings", "Settings"]];
const CAL_PREVIEW = 3;

const SOURCE_LABELS = {
  gmail: "Gmail",
  classroom: "Classroom",
  buzz: "Buzz",
  veracross: "Veracross",
  news: "News",
  activity: "Activity",
};

function sourceLabel(s) {
  if (!s) return "—";
  return SOURCE_LABELS[s] || s.charAt(0).toUpperCase() + s.slice(1);
}

function ensureNavChrome() {
  if (!document.getElementById("nav-toggle")) {
    const b = document.createElement("button");
    b.id = "nav-toggle";
    b.className = "nav-toggle";
    b.setAttribute("aria-label", "Toggle menu");
    b.innerHTML = "<span></span><span></span><span></span>";
    b.onclick = toggleNav;
    document.body.appendChild(b);
  }
  if (!document.getElementById("nav-backdrop")) {
    const d = document.createElement("div");
    d.id = "nav-backdrop";
    d.className = "nav-backdrop";
    d.onclick = closeNav;
    document.body.appendChild(d);
  }
}
function toggleNav() { document.body.classList.toggle("nav-open"); }
function closeNav() { document.body.classList.remove("nav-open"); }

function navLinkHtml(href, name, active) {
  const isActive = href === active;
  const badge = href === "/notifications"
    ? `<span class="nav-badge" id="nav-unread" hidden></span>` : "";
  return `<a href="${href}" class="${isActive ? "active" : ""}" onclick="closeNav()">` +
    `<span>${name}</span>${badge}</a>`;
}

// ----- Sidebar customization (per-device order + hidden tabs) -----
const NAV_ORDER_KEY = "nexus-nav-order";
const NAV_HIDDEN_KEY = "nexus-nav-hidden";
const NAV_LOCKED = new Set(["/settings"]); // never hideable (avoid lockout)
function navMap() { const m = {}; NAV.forEach(([h, n]) => (m[h] = n)); return m; }
function navOrder() {
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem(NAV_ORDER_KEY) || "[]"); } catch (e) { saved = []; }
  const valid = new Set(NAV.map(x => x[0]));
  const order = (saved || []).filter(h => valid.has(h));
  NAV.forEach(([h]) => { if (!order.includes(h)) order.push(h); });
  return order;
}
function navHidden() {
  let h = [];
  try { h = JSON.parse(localStorage.getItem(NAV_HIDDEN_KEY) || "[]"); } catch (e) { h = []; }
  return new Set((h || []).filter(x => !NAV_LOCKED.has(x)));
}
function setNavOrder(order) { localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(order)); }
function setNavHidden(set) { localStorage.setItem(NAV_HIDDEN_KEY, JSON.stringify([...set])); }
function renderSidebar(active) {
  const el = document.getElementById("sidebar");
  if (!el) return;
  ensureNavChrome();
  const cur = document.documentElement.getAttribute("data-theme");
  const label = cur === "dark" ? "Light" : "Dark";
  const m = navMap();
  const hidden = navHidden();
  const links = navOrder().filter(h => !hidden.has(h)).map(h => navLinkHtml(h, m[h], active)).join("");
  el.innerHTML = `<div class="brand">NEXUS</div><nav id="sidebar-nav">${links}</nav>` +
    `<div class="sidebar-footer">` +
      `<div class="acct-line" id="sidebar-acct"></div>` +
      `<div class="sidebar-controls">` +
        `<button id="theme-btn" onclick="toggleTheme()">${label}</button>` +
        `<a class="btn" href="/logout">Sign out</a>` +
      `</div>` +
    `</div>`;
  loadSidebarAccount(active);
  refreshNavUnread();
}
async function loadSidebarAccount(active) {
  try {
    const a = await getJSON("/api/account");
    const el = document.getElementById("sidebar-acct");
    if (el) {
      const who = (a && (a.email || a.username)) || "";
      el.textContent = who;
      el.title = who;
    }
    if (a && a.is_admin) {
      const nav = document.getElementById("sidebar-nav");
      if (nav && !document.getElementById("nav-platform")) {
        const link = document.createElement("a");
        link.id = "nav-platform";
        link.href = "/platform-config";
        link.className = active === "/platform-config" ? "active" : "";
        link.setAttribute("onclick", "closeNav()");
        link.innerHTML = "<span>Platform Config</span>";
        nav.appendChild(link);
      }
    }
  } catch (e) { /* not signed in */ }
}
async function refreshNavUnread() {
  try {
    const r = await getJSON("/api/notifications/unread");
    const badge = document.getElementById("nav-unread");
    if (!badge) return;
    const n = (r && r.count) || 0;
    if (n > 0) { badge.textContent = n > 99 ? "99+" : n; badge.hidden = false; }
    else { badge.hidden = true; }
  } catch (e) { /* ignore */ }
}

async function getJSON(url) { const r = await fetch(url); return r.json(); }
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: body != null ? { "Content-Type": "application/json" } : {},
    body: body != null ? JSON.stringify(body) : null,
  });
  if (!r.ok) {
    const err = await r.text();
    throw new Error(r.status + " " + r.statusText + (err ? ": " + err.slice(0, 120) : ""));
  }
  return r.json();
}
async function patchJSON(url) { const r = await fetch(url, { method: "PATCH" }); return r.json(); }

function srcClass(s) { return "src-" + s; }
function pClass(score) { return score >= 8 ? "p-high" : score >= 5 ? "p-med" : "p-low"; }
function esc(s) {
  return (s == null ? "" : String(s)).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function parseIsoDate(iso) {
  if (!iso) return null;
  const s = String(iso);
  const hasTz = /[Zz]$/.test(s) || /[+-]\d{2}:\d{2}$/.test(s);
  const d = new Date(hasTz ? s : s);
  return isNaN(d.getTime()) ? null : d;
}

function dueCalendarParts(iso, source) {
  const d = parseIsoDate(iso);
  if (!d) return null;
  const utc = source === "buzz" || /[Zz]$/.test(String(iso));
  return utc
    ? { y: d.getUTCFullYear(), m: d.getUTCMonth(), day: d.getUTCDate() }
    : { y: d.getFullYear(), m: d.getMonth(), day: d.getDate() };
}

function fmtDate(iso, source) {
  const d = parseIsoDate(iso);
  if (!d) return "—";
  const utcDue = source === "buzz" || /[Zz]$/.test(String(iso || ""));
  const opts = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" };
  if (utcDue) opts.timeZone = "UTC";
  return d.toLocaleString(undefined, opts);
}
function todayStr() {
  return new Date().toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}

// ---------- DASHBOARD ----------
let _tasks = [];
async function initDashboard() {
  renderSidebar("/");
  const td = document.getElementById("today");
  if (td) td.textContent = todayStr();
  loadStatus();
  loadCourses();
  loadUrgent();
  loadConflicts();
  await loadTasks();
  document.getElementById("f-source").onchange = () => { renderUndatedBoard(); renderTaskTable(); };
  document.getElementById("f-sort").onchange = renderTaskTable;
}

// ---------- CLASSES (per-course, deduped) ----------
let _courses = [];
async function loadCourses() {
  const root = document.getElementById("courses");
  if (!root) return;
  try {
    const data = await getJSON("/api/courses");
    _courses = data.courses || [];
  } catch (e) {
    _courses = [];
  }
  const badge = document.getElementById("courses-count");
  if (badge) badge.textContent = _courses.length;
  if (!_courses.length) {
    root.innerHTML = '<div class="muted">No classes yet. Connect Google + Veracross on your Account, then Sync All.</div>';
    return;
  }
  root.innerHTML = _courses.map(courseCard).join("");
}
function gradeClass(c) {
  const n = c.grade && c.grade.achieved ? parseFloat(c.grade.achieved) : null;
  if (n == null) return "";
  return n >= 90 ? "grade-a" : n >= 80 ? "grade-b" : n >= 70 ? "grade-c" : "grade-d";
}
function courseCard(c) {
  const grade = c.grade_display
    ? `<span class="course-grade ${gradeClass(c)}">${esc(c.grade_display)}</span>`
    : `<span class="course-grade muted">no grade</span>`;
  const srcDots = (c.sources || []).map(s =>
    `<span class="src-pill ${srcClass(s)}">${esc(sourceLabel(s))}</span>`).join("");
  const open = (c.tasks || []).filter(t => !t.is_completed);
  const taskRows = open.length
    ? open.map(t =>
        `<div class="course-task" ${typeof showCourseTask === "function" ? `onclick="showCourseTask(${t.id})"` : ""}>` +
          `<span class="ct-src ${srcClass(t.source)}">${esc(sourceLabel(t.source))}</span>` +
          `<span class="ct-title">${esc(t.title)}</span>` +
          `<span class="ct-due">${_hasDueDate(t) ? fmtDate(t.due_date, t.source) : "—"}</span>` +
        `</div>`).join("")
    : '<div class="muted course-empty">No open tasks. Nice.</div>';
  return `<details class="course-card">` +
    `<summary class="course-head" title="${esc(c.name)}">` +
      `<span class="course-name" title="${esc(c.name)}">${esc(c.name)}</span>` +
      `<span class="course-head-right">${grade}` +
      `<span class="course-open">${c.open_count} open</span></span>` +
    `</summary>` +
    `<div class="course-fullname">${esc(c.name)}</div>` +
    `<div class="course-body">` +
      `<div class="course-meta">${srcDots}` +
        (c.grade_source ? `<span class="muted"> · grade via ${esc(c.grade_source)}</span>` : "") +
        (c.done_count ? `<span class="muted"> · ${c.done_count} done</span>` : "") +
      `</div>` +
      `<div class="course-tasks">${taskRows}</div>` +
    `</div>` +
  `</details>`;
}
function showCourseTask(id) {
  const t = (_tasks || []).find(x => x.id === id) ||
    _courses.flatMap(c => c.tasks || []).find(x => x.id === id);
  if (!t) return;
  alert(`${t.title}\n\n${t.course_name || ""}\n${_hasDueDate(t) ? "Due " + fmtDate(t.due_date, t.source) : "No due date"}` +
    (t.description ? "\n\n" + t.description.slice(0, 400) : ""));
}
async function syncAll(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Syncing..."; }
  try {
    const r = await postJSON("/sync/all");
    const lines = Object.entries(r || {}).map(([src, info]) => {
      const count = typeof info === "object" ? info.count : info;
      const err = typeof info === "object" ? info.error : null;
      return err ? `${src}: failed (${err})` : `${src}: ${count} items`;
    });
    if (lines.length) alert("Sync complete\n\n" + lines.join("\n"));
  } catch (e) {
    alert("Sync failed: " + e.message);
  }
  location.reload();
}
async function loadStatus() {
  const s = await getJSON("/api/status");
  document.getElementById("status").innerHTML = ["gmail", "classroom", "buzz", "veracross"].map(k => {
    const c = s[k] || {};
    const dot = c.connected ? '<span class="dot on">●</span>' : '<span class="dot off">○</span>';
    return `<div class="status-cell"><div class="status-name ${srcClass(k)}">${sourceLabel(k)}</div>` +
      `<div>${dot} ${c.connected ? "connected" : "not connected"} (${c.count || 0} open` +
      `${c.completed_count ? ", " + c.completed_count + " done" : ""})</div>` +
      `<div class="status-time">sync: ${c.last_sync ? fmtDate(c.last_sync) : "never"}</div></div>`;
  }).join("");
}
async function loadUrgent() {
  const t = openTasksOnly(await getJSON("/api/tasks/urgent"));
  document.getElementById("urgent-count").textContent = t.length;
  document.getElementById("cards").innerHTML = t.map(taskCard).join("") ||
    '<div class="muted">No urgent tasks. Run Sync All.</div>';
}
function taskCard(t) {
  const dueMeta = _hasDueDate(t) ? fmtDate(t.due_date, t.source) : "No due date";
  return `<div class="card"><div class="src ${srcClass(t.source)}">${sourceLabel(t.source)}</div>` +
    `<div class="title">${esc(t.title)}</div><div class="meta">${esc(t.course_name || "—")}</div>` +
    `<div class="meta">${dueMeta}</div>` +
    `<div class="pscore ${pClass(t.priority_score)}">priority ${t.priority_score}</div></div>`;
}
async function loadConflicts() {
  const c = await getJSON("/api/conflicts");
  const el = document.getElementById("overload");
  if (c && c.length) { el.style.display = "block"; el.textContent = "OVERLOAD\n" + c.join("\n"); }
  else { el.style.display = "none"; }
}
function isAnnouncement(t) {
  return !!(t && (t.is_announcement || (t.external_id || "").includes(":ann:") ||
    (t.title || "").startsWith("Announcement:")));
}

function openTasksOnly(list) {
  return (list || []).filter(t => !t.is_completed && !isAnnouncement(t));
}

function openTasksOnly(list) {
  return (list || []).filter(t => !t.is_completed && !isAnnouncement(t));
}

function _hasDueDate(t) {
  return !!(t && t.due_date);
}

function _collectUndatedTasks(tasks) {
  return (tasks || []).filter(t => !t.is_completed && !isAnnouncement(t) && !_hasDueDate(t));
}

function _undatedRowHtml(t) {
  const detailFn = typeof showDetail === "function" ? `showDetail(${t.id})` : "";
  return `<div class="cal-overdue-row"${detailFn ? ` onclick="${detailFn}"` : ""}>` +
    `<span class="${srcClass(t.source)}">${esc(sourceLabel(t.source))}</span> ` +
    `<span class="cal-overdue-title">${esc(t.title)}</span>` +
    `<span class="muted"> · ${esc(t.course_name || "—")}</span></div>`;
}

function _renderUndatedStrip(el, tasks, { source = "", panelLink = false } = {}) {
  if (!el) return;
  let undated = _collectUndatedTasks(tasks);
  if (source) undated = undated.filter(t => t.source === source);
  undated.sort((a, b) => b.priority_score - a.priority_score);
  if (!undated.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  el.innerHTML =
    `<details class="cal-overdue-details cal-undated-details">` +
    `<summary>No due date (${undated.length}) — click to expand</summary>` +
    `<div class="cal-overdue-list">${undated.map(_undatedRowHtml).join("")}</div>` +
    `</details>` +
    (panelLink
      ? `<button type="button" class="cal-more" id="cal-undated-panel-btn" style="margin-top:6px" onclick="toggleUndatedPanel()">Show all in panel below</button>`
      : "");
}

async function loadTasks() {
  _tasks = openTasksOnly(await getJSON("/api/tasks?completed=false"));
  renderUndatedBoard();
  renderTaskTable();
}
function renderUndatedBoard() {
  const src = document.getElementById("f-source")?.value || "";
  _renderUndatedStrip(document.getElementById("dash-undated"), _tasks, { source: src });
  const badge = document.getElementById("undated-count");
  if (badge) {
    let undated = _collectUndatedTasks(_tasks);
    if (src) undated = undated.filter(t => t.source === src);
    badge.textContent = undated.length;
  }
}
function renderTaskTable() {
  const src = document.getElementById("f-source").value;
  const sort = document.getElementById("f-sort").value;
  let rows = openTasksOnly(_tasks.slice());
  if (src) rows = rows.filter(t => t.source === src);
  rows.sort((a, b) => {
    if (sort === "priority") return b.priority_score - a.priority_score;
    const da = a.due_date ? Date.parse(a.due_date) : Infinity;
    const db = b.due_date ? Date.parse(b.due_date) : Infinity;
    return da - db;
  });
  document.querySelector("#task-table tbody").innerHTML = rows.map(t =>
    `<tr>` +
    `<td>${esc(t.title)}</td><td>${esc(t.course_name || "—")}</td>` +
    `<td class="${srcClass(t.source)}">${sourceLabel(t.source)}</td>` +
    `<td>${_hasDueDate(t) ? fmtDate(t.due_date, t.source) : "No due date"}</td>` +
    `<td class="${pClass(t.priority_score)}">${t.priority_score}</td>` +
    `<td><input type="checkbox" onchange="toggleDone(${t.id})"></td></tr>`
  ).join("") || `<tr><td colspan="6" class="muted">No open tasks.</td></tr>`;
}
async function toggleDone(id) {
  await patchJSON(`/api/tasks/${id}/complete`);
  _tasks = _tasks.filter(t => t.id !== id);
  renderUndatedBoard();
  renderTaskTable();
  loadUrgent();
  loadConflicts();
}

// ---------- CALENDAR ----------
let _calDate = new Date();
let _calTasks = [];
let _calByDay = {};
let _calPanelMode = null;

function collapseCalPanel() {
  _calPanelMode = null;
  const title = document.getElementById("detail-title");
  const hint = document.getElementById("detail-hint");
  const body = document.getElementById("detail-body");
  const collapseBtn = document.getElementById("detail-collapse-btn");
  if (title) title.textContent = "DAY / TASK";
  if (hint) hint.textContent = "Click a day with +more or any task.";
  if (body) body.innerHTML = "";
  if (collapseBtn) collapseBtn.hidden = true;
  _updateUndatedPanelBtn();
}

function _updateUndatedPanelBtn() {
  const btn = document.getElementById("cal-undated-panel-btn");
  if (!btn) return;
  btn.textContent = _calPanelMode === "undated"
    ? "Hide panel below"
    : "Show all in panel below";
}

function toggleUndatedPanel() {
  if (_calPanelMode === "undated") {
    collapseCalPanel();
    return;
  }
  showUndatedPanel();
}

function _startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}
function _isOverdueTask(t, now = new Date()) {
  if (!t || !t.due_date) return false;
  const p = dueCalendarParts(t.due_date, t.source);
  if (!p) return false;
  const dueDay = new Date(p.y, p.m, p.day);
  return dueDay < _startOfDay(now);
}
function _collectOverdueTasks(tasks, now = new Date()) {
  return (tasks || []).filter(t => _isOverdueTask(t, now));
}
function _assignCalTasksByDay(tasks, viewYear, viewMonth) {
  const byDay = {};
  (tasks || []).forEach(t => {
    if (!t.due_date) return;
    const p = dueCalendarParts(t.due_date, t.source);
    if (!p || p.y !== viewYear || p.m !== viewMonth) return;
    (byDay[p.day] = byDay[p.day] || []).push(t);
  });
  return byDay;
}

// ---------- SCHOOL CALENDAR (fixed 2026/27 dates + colour map) ----------
const CAL_CATS = {
  na:   { label: "Non-Attendance", color: "#dc2626" },
  hol:  { label: "Holidays / Breaks", color: "#ca8a04" },
  imp:  { label: "Important School Dates", color: "#2563eb" },
  test: { label: "Testing Dates", color: "#ea580c" },
  evt:  { label: "Student Events", color: "#9333ea" },
};
const CAL_CAT_PRIORITY = ["na", "hol", "test", "imp", "evt"];
// [startISO, endISO|null, category, label]
const SCHOOL_EVENTS_RAW = [
  ["2026-09-01", null, "imp", "First Day of School for Students"],
  ["2026-09-03", null, "imp", "Picture Day (Studio)"],
  ["2026-09-10", null, "imp", "Parents Back to School Night"],
  ["2026-09-11", null, "hol", "La Diada (No School)"],
  ["2026-09-21", "2026-09-25", "test", "Fall MAP Testing Week"],
  ["2026-09-22", null, "evt", "Extracurricular & Athletics Fair"],
  ["2026-09-24", null, "hol", "La Mercé (No School)"],
  ["2026-09-29", null, "evt", "Grades 6-8 Movie Night"],
  ["2026-09-30", null, "evt", "Grades 9-10 Movie Night"],
  ["2026-10-01", null, "evt", "Grades 11-12 Movie Night"],
  ["2026-10-02", null, "evt", "Homecoming Dance & Pep Rally (Modified Schedule)"],
  ["2026-10-12", null, "hol", "La Hispanidad (No School)"],
  ["2026-10-30", null, "evt", "Halloween Party (Modified Schedule)"],
  ["2026-11-05", "2026-11-06", "na", "Student Parent Teacher Conferences (No School)"],
  ["2026-11-26", null, "hol", "Thanksgiving — Dinner at BHS 5-8 PM (No School)"],
  ["2026-11-27", null, "hol", "Thanksgiving (No School)"],
  ["2026-12-07", "2026-12-08", "hol", "La Inmaculada (No School)"],
  ["2026-12-18", null, "imp", "Half Day (ends 12 PM) · Winter Party 12-1 PM"],
  ["2026-12-21", "2026-12-31", "hol", "Winter Break (No School)"],
  ["2027-01-01", "2027-01-06", "hol", "Winter Break (No School)"],
  ["2027-01-07", null, "imp", "First Day Back After Winter Break"],
  ["2027-01-22", null, "imp", "Last Day to Submit Work"],
  ["2027-01-25", "2027-01-27", "test", "Final Exams (Modified Schedule)"],
  ["2027-01-28", "2027-01-29", "na", "Make-Up Exams & Professional Development (No School)"],
  ["2027-02-01", null, "imp", "First Day of New Semester"],
  ["2027-02-12", null, "evt", "Carnival Celebration at School"],
  ["2027-02-22", "2027-02-26", "hol", "Ski Week / Mid Winter Break (No School)"],
  ["2027-03-01", null, "hol", "Mid Winter Break (No School)"],
  ["2027-03-05", null, "evt", "Spring Dance"],
  ["2027-03-18", "2027-03-30", "hol", "Spring Break (No School)"],
  ["2027-04-12", "2027-04-14", "test", "Mock AP Exams"],
  ["2027-04-15", "2027-04-16", "na", "Student Parent Teacher Conferences (No School)"],
  ["2027-04-23", null, "evt", "Sant Jordi School Celebration"],
  ["2027-05-03", "2027-05-07", "imp", "Middle School Exploration Week"],
  ["2027-05-03", "2027-05-21", "test", "AP Examinations"],
  ["2027-05-17", null, "hol", "Pentecost (No School)"],
  ["2027-05-21", null, "imp", "Last Day of AP Classes"],
  ["2027-05-24", "2027-05-28", "test", "Spring MAP Testing Week"],
  ["2027-06-08", null, "imp", "Grade 12 Last Day of Classes"],
  ["2027-06-09", "2027-06-11", "test", "Grade 12 Final Exams"],
  ["2027-06-11", null, "imp", "Gr 12 Last Day of School · Gr 6-11 Last Day of Classes"],
  ["2027-06-14", "2027-06-16", "test", "Final Exams Grades 6-11"],
  ["2027-06-16", null, "imp", "Grades 6-11 Last Day of School"],
  ["2027-06-17", "2027-06-18", "na", "Make-Up Exams & Professional Development (No Classes)"],
];
let _schoolEvents = null;
function _isoOf(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function schoolEvents() {
  if (_schoolEvents) return _schoolEvents;
  const map = {};
  const add = (iso, cat, label) => { (map[iso] = map[iso] || []).push({ cat, label }); };
  for (const [start, end, cat, label] of SCHOOL_EVENTS_RAW) {
    if (!end) { add(start, cat, label); continue; }
    let d = new Date(start + "T00:00:00");
    const last = new Date(end + "T00:00:00");
    while (d <= last) { add(_isoOf(d), cat, label); d.setDate(d.getDate() + 1); }
  }
  _schoolEvents = map;
  return map;
}
function _tintCat(events) {
  for (const c of CAL_CAT_PRIORITY) if (events.some(e => e.cat === c)) return c;
  return "";
}
function renderCalLegend() {
  const el = document.getElementById("cal-legend");
  if (!el) return;
  el.innerHTML = Object.entries(CAL_CATS).map(([k, v]) =>
    `<span class="cal-legend-item"><span class="cal-legend-dot cat-${k}"></span>${esc(v.label)}</span>`).join("") +
    `<span class="cal-legend-item"><span class="cal-legend-dot cal-legend-weekend"></span>Weekend</span>`;
}

async function showYearOverview() {
  let data = {};
  try { data = await getJSON("/api/calendar/overview"); } catch (e) {}
  if (!data.available) {
    showInfoModal("Year overview", "No year-at-a-glance calendar has been uploaded yet. An administrator can add one on Platform Config.");
    return;
  }
  const isPdf = (data.file_url || "").toLowerCase().endsWith(".pdf") || data.file_url.includes("overview.pdf");
  const inner = isPdf
    ? `<iframe src="${esc(data.file_url)}" style="width:100%;height:70vh;border:1px solid var(--border)"></iframe>`
    : `<img src="${esc(data.file_url)}" alt="Year overview" style="max-width:100%;border:1px solid var(--border)">`;
  const back = _overlay(
    `<h3 class="modal-title">Year at a glance</h3>` + inner +
    `<div class="modal-actions"><a class="btn" href="${esc(data.file_url)}" target="_blank" rel="noopener">Open full size</a>` +
    `<button type="button" class="btn" data-ok>Close</button></div>`);
  back.querySelector("[data-ok]").onclick = () => back.remove();
}

async function initCalendar() {
  renderSidebar("/calendar");
  renderCalLegend();
  _calTasks = openTasksOnly(await getJSON("/api/tasks?completed=false"));
  renderCalendar();
}
function calMove(delta) { _calDate.setMonth(_calDate.getMonth() + delta); renderCalendar(); }

function _taskDetailHtml(t) {
  const overdue = _isOverdueTask(t);
  const dueLabel = !_hasDueDate(t)
    ? "No due date"
    : overdue
      ? `Overdue: ${fmtDate(t.due_date, t.source)}`
      : `Due: ${fmtDate(t.due_date, t.source)}`;
  return `<div class="cal-detail-item${overdue ? " cal-detail-overdue" : ""}"><div class="${srcClass(t.source)}">${sourceLabel(t.source)}</div>` +
    `<strong>${esc(t.title)}</strong><div class="muted">${esc(t.course_name || "—")}</div>` +
    `<div class="muted">${dueLabel} · Priority: ${t.priority_score}</div>` +
    (t.description ? `<p>${esc(t.description)}</p>` : "") + `</div>`;
}

function _calTaskHtml(t) {
  return `<span class="cal-task ${srcClass(t.source)}" onclick="event.stopPropagation();showDetail(${t.id})">` +
    `[${sourceLabel(t.source).toUpperCase()}] ${esc(t.title)}</span>`;
}

function _overdueRowHtml(t) {
  return `<div class="cal-overdue-row" onclick="showDetail(${t.id})">` +
    `<span class="${srcClass(t.source)}">${esc(sourceLabel(t.source))}</span> ` +
    `<span class="cal-overdue-title">${esc(t.title)}</span>` +
    `<span class="muted"> · ${fmtDate(t.due_date, t.source)}</span></div>`;
}

function renderOverdueStrip(tasks) {
  const el = document.getElementById("cal-overdue");
  if (!el) return;
  const overdue = _collectOverdueTasks(tasks).sort((a, b) => Date.parse(a.due_date) - Date.parse(b.due_date));
  if (!overdue.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  el.innerHTML =
    `<details class="cal-overdue-details">` +
    `<summary>Overdue (${overdue.length}) — click to expand</summary>` +
    `<div class="cal-overdue-list">${overdue.map(_overdueRowHtml).join("")}</div>` +
    `</details>`;
}

function renderUndatedStrip(tasks) {
  _renderUndatedStrip(document.getElementById("cal-undated"), tasks, { panelLink: true });
}

function showUndatedPanel() {
  const items = _collectUndatedTasks(_calTasks).sort((a, b) => b.priority_score - a.priority_score);
  const title = document.getElementById("detail-title");
  const hint = document.getElementById("detail-hint");
  const body = document.getElementById("detail-body");
  const collapseBtn = document.getElementById("detail-collapse-btn");
  if (title) title.textContent = "NO DUE DATE";
  if (hint) hint.textContent = `${items.length} open task${items.length === 1 ? "" : "s"} without a deadline`;
  if (body) {
    body.innerHTML = items.length
      ? items.map(_taskDetailHtml).join("")
      : '<div class="muted">No undated tasks.</div>';
  }
  _calPanelMode = "undated";
  if (collapseBtn) collapseBtn.hidden = false;
  _updateUndatedPanelBtn();
}

function showCalDay(y, m, day) {
  const items = _calByDay[day] || [];
  const iso = `${y}-${String(m + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const events = (schoolEvents()[iso] || []);
  const title = document.getElementById("detail-title");
  const hint = document.getElementById("detail-hint");
  const body = document.getElementById("detail-body");
  const collapseBtn = document.getElementById("detail-collapse-btn");
  if (title) title.textContent = new Date(y, m, day).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  if (hint) hint.textContent = `${events.length} school event${events.length === 1 ? "" : "s"} · ${items.length} task${items.length === 1 ? "" : "s"}`;
  const evHtml = events.map(e =>
    `<div class="cal-detail-item"><div class="cat-text cat-${e.cat}">${esc(CAL_CATS[e.cat].label)}</div>` +
    `<strong>${esc(e.label)}</strong></div>`).join("");
  if (body) body.innerHTML = (evHtml || "") + (items.length ? items.map(_taskDetailHtml).join("") : (evHtml ? "" : '<div class="muted">Nothing this day.</div>'));
  _calPanelMode = "day";
  if (collapseBtn) collapseBtn.hidden = false;
  _updateUndatedPanelBtn();
}

function showDetail(id) {
  const t = _calTasks.find(x => x.id === id);
  if (!t) return;
  const title = document.getElementById("detail-title");
  const hint = document.getElementById("detail-hint");
  const body = document.getElementById("detail-body");
  const collapseBtn = document.getElementById("detail-collapse-btn");
  if (title) title.textContent = "TASK";
  if (hint) {
    hint.textContent = !_hasDueDate(t)
      ? "No due date"
      : _isOverdueTask(t)
        ? `Overdue · ${fmtDate(t.due_date, t.source)}`
        : fmtDate(t.due_date, t.source);
  }
  if (body) body.innerHTML = _taskDetailHtml(t);
  _calPanelMode = "task";
  if (collapseBtn) collapseBtn.hidden = false;
  _updateUndatedPanelBtn();
}

function renderCalendar() {
  const y = _calDate.getFullYear(), m = _calDate.getMonth();
  const startDow = (new Date(y, m, 1).getDay() + 6) % 7;
  const days = new Date(y, m + 1, 0).getDate();
  const today = new Date();
  _calByDay = _assignCalTasksByDay(_calTasks, y, m);
  renderOverdueStrip(_calTasks);
  renderUndatedStrip(_calTasks);
  const evMap = schoolEvents();
  let cells = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(d => `<div class="dow">${d}</div>`).join("");
  for (let i = 0; i < startDow; i++) cells += `<div class="cal-cell empty"></div>`;
  for (let day = 1; day <= days; day++) {
    const iso = `${y}-${String(m + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const events = evMap[iso] || [];
    const dow = new Date(y, m, day).getDay();
    const weekend = dow === 0 || dow === 6;
    const all = _calByDay[day] || [];
    const evHtml = events.map(e =>
      `<span class="cal-ev cat-${e.cat}" title="${esc(e.label)}" onclick="event.stopPropagation();showCalDay(${y},${m},${day})">${esc(e.label)}</span>`).join("");
    const busy = all.length > CAL_PREVIEW;
    const preview = all.slice(0, CAL_PREVIEW);
    const taskHtml = preview.map(_calTaskHtml).join("");
    const more = busy
      ? `<button type="button" class="cal-more" onclick="event.stopPropagation();showCalDay(${y},${m},${day})">+${all.length - CAL_PREVIEW} more</button>`
      : "";
    const isToday = y === today.getFullYear() && m === today.getMonth() && day === today.getDate();
    const tint = _tintCat(events);
    const clickable = busy || events.length;
    const cellClass = "cal-cell" + (busy ? " cal-busy" : "") + (isToday ? " cal-today" : "") +
      (weekend ? " cal-weekend" : "") + (tint ? " cat-" + tint : "");
    const openDay = clickable ? `onclick="showCalDay(${y},${m},${day})"` : "";
    cells += `<div class="${cellClass}" ${openDay}><span class="num">${day}</span>${evHtml}${taskHtml}${more}</div>`;
  }
  document.getElementById("cal-grid").innerHTML = cells;
  document.getElementById("cal-title").textContent =
    _calDate.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

// ---------- ANNOUNCEMENTS ----------
let _announcements = [];
let _news = [];
let _activityFeed = [];
let _annTab = "announcements";

async function initAnnouncements() {
  renderSidebar("/announcements");
  document.querySelectorAll("[data-ann-tab]").forEach(btn => {
    btn.onclick = () => {
      _annTab = btn.dataset.annTab;
      document.querySelectorAll("[data-ann-tab]").forEach(b =>
        b.classList.toggle("active", b.dataset.annTab === _annTab));
      renderAnnouncements();
    };
  });
  await loadAnnouncementFeeds();
}

async function loadAnnouncementFeeds() {
  const [ann, news, act] = await Promise.all([
    getJSON("/api/announcements"),
    getJSON("/api/news"),
    getJSON("/api/activity"),
  ]);
  _announcements = ann || [];
  _news = news || [];
  _activityFeed = act || [];
  renderAnnouncements();
}

function _feedRows() {
  if (_annTab === "news") return _news;
  if (_annTab === "activity") return _activityFeed;
  return _announcements;
}

function renderAnnouncements() {
  const root = document.getElementById("announcements-root");
  if (!root) return;
  const rows = _feedRows();
  const empty = {
    announcements: "No Classroom announcements. Run Sync All.",
    news: "No BHS News emails yet. Sync All (needs Google connected).",
    activity: "No Buzz activity stream items. Run Sync All.",
  };
  if (!rows.length) {
    root.innerHTML = `<div class="muted">${empty[_annTab] || empty.announcements}</div>`;
    return;
  }
  root.innerHTML = rows.map(t => {
    let body = (t.description || "").trim();
    if (_annTab === "announcements") {
      body = body || (t.title || "").replace(/^Announcement:\s*/i, "");
    }
    const when = t.due_date ? fmtDate(t.due_date, t.source) : fmtDate(t.created_at, t.source);
    return `<article class="announcement-card">` +
      `<div class="announcement-meta"><span class="${srcClass(t.source)}">${esc(sourceLabel(t.source))}</span>` +
      ` · ${esc(t.course_name || "—")} · ${when}</div>` +
      `<h3 class="announcement-title">${esc(t.title)}</h3>` +
      (body ? `<p class="announcement-body">${esc(body)}</p>` : "") +
      `</article>`;
  }).join("");
}

// ---------- CHAT ----------
let _history = [];
let _convId = null;
let _convs = [];

async function initChat() {
  renderSidebar("/chat");
  document.getElementById("send-btn").onclick = sendChat;
  document.getElementById("chat-text").addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); sendChat(); }
  });
  const fileInp = document.getElementById("chat-file");
  if (fileInp) {
    fileInp.onchange = () => {
      const el = document.getElementById("file-name");
      if (el) el.textContent = fileInp.files[0] ? fileInp.files[0].name : "";
    };
  }
  document.querySelectorAll(".quick button").forEach(b => b.onclick = () => {
    document.getElementById("chat-text").value = b.textContent; sendChat();
  });
  const newBtn = document.getElementById("new-chat-btn");
  if (newBtn) newBtn.onclick = newConversation;
  await loadConversations();
  // Open the most recent conversation, or start fresh.
  if (_convs.length) await openConversation(_convs[0].id);
  else resetChatView();
}

function resetChatView() {
  _history = [];
  const box = document.getElementById("messages");
  if (box) box.innerHTML = "";
  const welcome = document.createElement("div");
  welcome.className = "msg assistant chat-md";
  welcome.innerHTML = renderChatMarkdown(
    "Nexus ready — I remember this conversation. Ask about deadlines, workload, or math. " +
    "Set your profile in **Settings → AI & Profile** so I can tailor help."
  );
  typesetChat(welcome);
  if (box) box.appendChild(welcome);
}

async function loadConversations() {
  try {
    const r = await getJSON("/api/chat/conversations");
    _convs = r.conversations || [];
  } catch (e) { _convs = []; }
  renderConversations();
}

function renderConversations() {
  const el = document.getElementById("conv-list");
  if (!el) return;
  if (!_convs.length) { el.innerHTML = `<div class="muted">No conversations yet.</div>`; return; }
  el.innerHTML = _convs.map(c =>
    `<div class="conv-item${c.id === _convId ? " active" : ""}" onclick="openConversation(${c.id})">` +
    `<span class="conv-title">${esc(c.title || "New chat")}</span>` +
    `<button type="button" class="link-btn conv-del" onclick="event.stopPropagation();deleteConversation(${c.id})">✕</button>` +
    `</div>`).join("");
}

async function newConversation() {
  try {
    const r = await postJSON("/api/chat/conversations/new");
    _convId = r.conversation ? r.conversation.id : null;
    await loadConversations();
    resetChatView();
  } catch (e) { /* ignore */ }
}

async function openConversation(id) {
  _convId = id;
  renderConversations();
  const box = document.getElementById("messages");
  if (box) box.innerHTML = "";
  _history = [];
  try {
    const r = await getJSON(`/api/chat/conversations/${id}`);
    const msgs = r.messages || [];
    if (!msgs.length) { resetChatView(); return; }
    msgs.forEach(m => addMsg(m.role, m.content));
  } catch (e) { resetChatView(); }
}

async function deleteConversation(id) {
  if (!confirm("Delete this conversation?")) return;
  try { await postJSON(`/api/chat/conversations/${id}/delete`); } catch (e) {}
  if (_convId === id) _convId = null;
  await loadConversations();
  if (_convs.length) await openConversation(_convs[0].id);
  else { _convId = null; resetChatView(); }
}

function renderChatMarkdown(text) {
  if (!text) return "";
  if (typeof marked === "undefined") return esc(text);
  let src = String(text);
  const math = [];
  const stash = (block) => {
    math.push(block);
    return `%%MATH${math.length - 1}%%`;
  };
  src = src.replace(/\\\[([\s\S]*?)\\\]/g, (_, m) => stash(`\\[${m}\\]`));
  src = src.replace(/\\\(([\s\S]*?)\\\)/g, (_, m) => stash(`\\(${m}\\)`));
  src = src.replace(/\$\$([\s\S]*?)\$\$/g, (_, m) => stash(`$$${m}$$`));
  src = src.replace(/(^|[^\$])\$(?!\$)([^\$\n]+?)\$(?!\$)/g, (_, pre, m) => pre + stash(`$${m}$`));
  let html = marked.parse(src, { breaks: true, gfm: true });
  math.forEach((block, i) => {
    html = html.split(`%%MATH${i}%%`).join(block);
  });
  if (typeof DOMPurify !== "undefined") {
    html = DOMPurify.sanitize(html, {
      ADD_TAGS: ["mjx-container", "math", "semantics", "mrow", "mi", "mo", "mn"],
      ADD_ATTR: ["class", "style", "xmlns", "display"],
    });
  }
  return html;
}

function typesetChat(el) {
  if (!el || typeof renderMathInElement !== "function") return;
  renderMathInElement(el, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "\\[", right: "\\]", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
    ],
    throwOnError: false,
  });
}

function addMsg(role, content) {
  _history.push({ role, content });
  const m = document.createElement("div");
  m.className = "msg " + role + (role === "assistant" ? " chat-md" : "");
  if (role === "assistant") {
    m.innerHTML = renderChatMarkdown(content);
    typesetChat(m);
  } else {
    m.textContent = content;
  }
  const box = document.getElementById("messages");
  box.appendChild(m);
  box.scrollTop = box.scrollHeight;
}
async function sendChat() {
  const inp = document.getElementById("chat-text");
  const fileInp = document.getElementById("chat-file");
  const text = inp.value.trim();
  const file = fileInp && fileInp.files[0];
  if (!text && !file) return;
  inp.value = "";
  const hist = _history.slice(-10);
  const userLabel = text || `[file: ${file.name}]`;
  addMsg("user", userLabel);
  const thinking = document.createElement("div");
  thinking.className = "msg assistant";
  thinking.textContent = "…";
  document.getElementById("messages").appendChild(thinking);
  try {
    const fd = new FormData();
    fd.append("message", text);
    fd.append("history", JSON.stringify(hist));
    if (_convId) fd.append("conversation_id", _convId);
    if (file) fd.append("file", file);
    const r = await fetch("/ai/chat", { method: "POST", body: fd });
    if (!r.ok) throw new Error(r.status + " " + r.statusText);
    const data = await r.json();
    thinking.remove();
    addMsg("assistant", data.response || "(no response)");
    const badge = document.getElementById("model-badge");
    if (badge && data.tier) badge.textContent = "model: " + data.tier;
    if (fileInp) { fileInp.value = ""; const fn = document.getElementById("file-name"); if (fn) fn.textContent = ""; }
    if (data.conversation_id && data.conversation_id !== _convId) {
      _convId = data.conversation_id;
    }
    if (typeof loadConversations === "function") loadConversations();
  } catch (e) {
    thinking.remove();
    addMsg("assistant", "Error: " + e);
  }
}

// ---------- SIGN IN / REGISTER (auth gate) ----------
let _authMode = "login";
function initLogin() {
  initTheme();
  const tabs = document.querySelectorAll("[data-auth-tab]");
  tabs.forEach(btn => btn.onclick = () => setAuthMode(btn.dataset.authTab));
  const form = document.getElementById("auth-form");
  if (form) form.onsubmit = (e) => { e.preventDefault(); submitAuth(); };
  const forgot = document.getElementById("forgot-link");
  if (forgot) forgot.onclick = (e) => {
    e.preventDefault();
    const help = document.getElementById("forgot-help");
    if (help) help.style.display = help.style.display === "none" ? "block" : "none";
  };
  showLoginOAuthBanner();
  setAuthMode("login");
}
function showLoginOAuthBanner() {
  const banner = document.getElementById("oauth-banner");
  if (!banner) return;
  const params = new URLSearchParams(location.search);
  if (params.get("oauth_error")) {
    banner.className = "oauth-banner err";
    banner.style.display = "block";
    banner.textContent = "Google sign-in failed: " + params.get("oauth_error");
  } else if (params.get("oauth") === "ok") {
    banner.className = "oauth-banner ok";
    banner.style.display = "block";
    banner.textContent = "Google connected. Signing you in…";
  } else {
    return;
  }
  history.replaceState(null, "", location.pathname);
}
function setAuthMode(mode) {
  _authMode = mode === "register" ? "register" : "login";
  document.querySelectorAll("[data-auth-tab]").forEach(b =>
    b.classList.toggle("active", b.dataset.authTab === _authMode));
  const nameRow = document.getElementById("auth-name-row");
  if (nameRow) nameRow.style.display = _authMode === "register" ? "block" : "none";
  const submit = document.getElementById("auth-submit");
  if (submit) submit.textContent = _authMode === "register" ? "Create account" : "Sign in";
  const status = document.getElementById("auth-status");
  if (status) status.textContent = "";
}
async function submitAuth() {
  const status = document.getElementById("auth-status");
  const email = (document.getElementById("auth-email").value || "").trim();
  const password = document.getElementById("auth-password").value || "";
  const name = (document.getElementById("auth-name")?.value || "").trim();
  if (!email || !password) { if (status) status.textContent = "Enter your email and password."; return; }
  status.textContent = _authMode === "register" ? "Creating account…" : "Signing in…";
  const url = _authMode === "register" ? "/api/auth/register" : "/api/auth/login";
  try {
    const r = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    });
    const data = await r.json();
    if (!r.ok) { status.textContent = data.error || "Failed."; return; }
    location.href = data.redirect || "/";
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

// ---------- ACCOUNT (services + per-user credentials) ----------
let _loginFields = [];
let _adminFields = [];

function renderAccountStatus(a) {
  const el = document.getElementById("account-status");
  if (!el) return;
  const row = (label, ok, extra) =>
    `<div class="acct-status-row"><span class="status-name">${label}</span>` +
    `<span>${ok ? '<span class="dot on">●</span> ' + (extra || "linked")
                 : '<span class="dot off">○</span> ' + (extra || "not linked")}</span></div>`;
  const gbtn = a.google_connected ? "Switch Google account" : "Connect Google";
  el.innerHTML =
    `<div class="acct-status-row"><span class="status-name">Google (Gmail + Classroom)</span>` +
      `<span class="row-actions"><a class="btn" href="/auth/google">${gbtn}</a>` +
      (a.google_connected ? `<button type="button" class="btn" onclick="disconnectGoogle()">Disconnect</button>` : "") +
      `</span></div>` +
    `<div class="muted acct-email">${a.email ? ("Signed in as " + esc(a.email)) : "Email/password account. Connect Google to pull Gmail + Classroom."}</div>` +
    row("Veracross", a.veracross_linked, a.veracross_linked ? "linked" : "add below") +
    row("Accelerate / Buzz", a.buzz_linked, a.buzz_linked ? "linked" : "optional") +
    row("Phone (SMS / WhatsApp)", a.phone_linked, a.phone_linked ? "linked" : "optional");
}

function initAccountPassword() {
  const btn = document.getElementById("password-save-btn");
  if (!btn) return;
  btn.onclick = async () => {
    const status = document.getElementById("password-status");
    const pw = document.getElementById("new-password").value || "";
    if (pw.length < 8) { status.textContent = "Password must be at least 8 characters."; return; }
    status.textContent = "Updating…";
    try {
      await postJSON("/api/auth/change-password", { new_password: pw });
      status.textContent = "Password updated.";
      document.getElementById("new-password").value = "";
    } catch (e) {
      status.textContent = "Error: " + e;
    }
  };
}

async function initAccount() {
  renderSidebar("/account");
  const [data, account] = await Promise.all([
    getJSON("/api/settings"),
    getJSON("/api/account"),
  ]);
  renderAccountStatus(account);
  _loginFields = data.fields || [];
  const form = document.getElementById("login-form");
  const groups = [
    { title: "Veracross — grades & classes", keys: ["VERACROSS_URL", "VERACROSS_USERNAME", "VERACROSS_PASSWORD"] },
    { title: "Phone — SMS / WhatsApp notifications", keys: ["USER_DISPLAY_NAME", "YOUR_PHONE_NUMBER"] },
    { title: "Accelerate / Buzz", keys: ["BUZZ_DOMAIN", "BUZZ_USERNAME", "BUZZ_PASSWORD"] },
  ];
  form.innerHTML = groups.map(g => {
    const fields = _loginFields.filter(f => g.keys.includes(f.key));
    if (!fields.length) return "";
    return `<div class="cred-group"><div class="section-h">${g.title}</div>` +
      fields.map(f => credFieldHtml(f)).join("") + `</div>`;
  }).join("");

  document.getElementById("save-btn").onclick = saveLogin;
  const tb = document.getElementById("test-btn");
  if (tb) tb.onclick = testLogins;

  const adminLink = document.getElementById("admin-platform-link");
  if (adminLink) adminLink.style.display = account.is_admin ? "block" : "none";
}

async function initAdminCredentials() {
  try {
    const data = await getJSON("/api/admin/credentials");
    _adminFields = data.fields || [];
    const form = document.getElementById("admin-creds-form");
    if (!form) return;
    const groups = [
      { title: "Twilio (SMS + WhatsApp)", keys: ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM", "TWILIO_WHATSAPP_FROM"] },
      { title: "Public webhook (for inbound replies)", keys: ["PUBLIC_WEBHOOK_BASE"] },
      { title: "Cerebras AI", keys: ["CEREBRAS_API_KEY"] },
      { title: "Google OAuth app", keys: ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"] },
      { title: "Optional: Telegram", keys: ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"] },
    ];
    form.innerHTML = groups.map(g => {
      const fields = _adminFields.filter(f => g.keys.includes(f.key));
      if (!fields.length) return "";
      return `<div class="cred-group"><div class="section-h">${g.title}</div>` +
        fields.map(f => credFieldHtml(f, "admin-creds-form")).join("") + `</div>`;
    }).join("");
    const saveBtn = document.getElementById("admin-save-btn");
    if (saveBtn) saveBtn.onclick = saveAdminCredentials;
  } catch (e) {
    const status = document.getElementById("admin-creds-status");
    if (status) status.textContent = "Could not load admin credentials: " + e;
  }
}

function credFieldHtml(f, formId = "login-form") {
  const type = f.type === "password" ? "password" : "text";
  const val = f.secret ? "" : esc(f.value);
  const ph = f.secret && f.value ? "(saved — leave blank to keep)" : "";
  return `<label class="cred-field"><span>${esc(f.label)}</span>` +
    `<input name="${f.key}" type="${type}" value="${val}" placeholder="${ph}" autocomplete="off" form="${formId}">` +
    `</label>`;
}

async function saveAdminCredentials() {
  const status = document.getElementById("admin-creds-status");
  const values = {};
  _adminFields.forEach(f => {
    const inp = document.querySelector(`#admin-creds-form [name="${f.key}"]`);
    if (!inp) return;
    const v = inp.value.trim();
    if (f.secret && !v) return;
    if (v) values[f.key] = v;
  });
  status.textContent = "Saving…";
  try {
    const r = await postJSON("/api/admin/credentials", { values });
    status.textContent = r.updated && r.updated.length
      ? "Saved: " + r.updated.join(", ") : "Nothing changed.";
    await initAdminCredentials();
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

async function saveLogin() {
  const status = document.getElementById("login-status");
  const values = {};
  _loginFields.forEach(f => {
    const inp = document.querySelector(`#login-form [name="${f.key}"]`);
    if (!inp) return;
    const v = inp.value.trim();
    if (f.secret && !v) return;
    if (v) values[f.key] = v;
  });
  status.textContent = "Saving…";
  try {
    const r = await postJSON("/api/settings", { values });
    status.textContent = r.updated && r.updated.length
      ? "Saved: " + r.updated.join(", ") : "Nothing changed.";
    await initAccount();
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

async function testLogins() {
  const status = document.getElementById("login-status");
  status.textContent = "Testing logins…";
  try {
    const r = await postJSON("/api/settings/test-login");
    const parts = [];
    parts.push(r.buzz.ok ? "Buzz: OK" : "Buzz: " + (r.buzz.error || "failed"));
    parts.push(r.veracross.ok ? "Veracross: OK" : "Veracross: " + (r.veracross.error || "failed"));
    status.textContent = parts.join(" · ");
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

// ---------- SETTINGS (merged: Connections + Messages + AI/Profile) ----------
let _setStatus = {};
let _setAccount = {};
let _setMsg = {};
let _setPrefs = {};
let _settingsTab = "connections";

function _field(key) { return (_loginFields || []).find(f => f.key === key) || {}; }
function _fieldVal(key) { const f = _field(key); return f.secret ? "" : (f.value || ""); }
function _fieldPlaceholder(key) { const f = _field(key); return (f.secret && f.value) ? "(saved — leave blank to keep)" : ""; }

function _settingsBanner() {
  const params = new URLSearchParams(location.search);
  const banner = document.getElementById("oauth-banner");
  if (!banner) return;
  if (params.get("oauth") === "ok" && params.get("scopes") !== "missing") {
    banner.style.display = "block"; banner.className = "oauth-banner ok";
    banner.textContent = "Google connected successfully.";
  } else if (params.get("oauth") === "ok" && params.get("scopes") === "missing") {
    banner.style.display = "block"; banner.className = "oauth-banner err";
    banner.textContent = "Google connected, but some Classroom permissions were not granted. Disconnect, then Connect again and accept ALL checkboxes.";
  } else if (params.get("oauth_error")) {
    banner.style.display = "block"; banner.className = "oauth-banner err";
    banner.textContent = "Google OAuth failed: " + params.get("oauth_error");
  } else if (_setStatus.google_needs_reconnect) {
    banner.style.display = "block"; banner.className = "oauth-banner err";
    banner.textContent = "Missing Google Classroom permissions. Disconnect Google, then Connect again and accept ALL permission checkboxes.";
  }
}

async function initSettings() {
  renderSidebar("/settings");
  const [s, account, sett, msg, prefs] = await Promise.all([
    getJSON("/api/status"),
    getJSON("/api/account"),
    getJSON("/api/settings"),
    getJSON("/api/messaging/status"),
    getJSON("/api/notifications/prefs"),
  ]);
  _setStatus = s || {}; _setAccount = account || {};
  _loginFields = sett.fields || []; _setMsg = msg || {}; _setPrefs = prefs || {};
  _settingsBanner();
  document.querySelectorAll("[data-settings-tab]").forEach(btn => {
    btn.onclick = () => {
      _settingsTab = btn.dataset.settingsTab;
      document.querySelectorAll("[data-settings-tab]").forEach(b =>
        b.classList.toggle("active", b.dataset.settingsTab === _settingsTab));
      renderSettingsTab();
    };
  });
  renderSettingsTab();
}

function renderSettingsTab() {
  const root = document.getElementById("settings-root");
  if (!root) return;
  if (_settingsTab === "messages") root.innerHTML = settingsMessagesHtml();
  else if (_settingsTab === "profile") root.innerHTML = settingsProfileHtml();
  else if (_settingsTab === "sidebar") root.innerHTML = settingsSidebarHtml();
  else if (_settingsTab === "support") root.innerHTML = settingsSupportHtml();
  else root.innerHTML = settingsConnectionsHtml();
  wireSettingsTab();
}

// ----- Sidebar customization tab -----
function settingsSidebarHtml() {
  const m = navMap(); const hidden = navHidden(); const order = navOrder();
  const rows = order.map(h => {
    const locked = NAV_LOCKED.has(h);
    return `<li class="nav-edit-item" draggable="true" data-href="${esc(h)}">` +
      `<span class="nav-drag" aria-hidden="true">⠿</span>` +
      `<span class="nav-edit-name">${esc(m[h])}</span>` +
      (locked
        ? `<span class="muted nav-edit-lock">always shown</span>`
        : `<label class="nav-edit-hide"><input type="checkbox" data-hide="${esc(h)}" ${hidden.has(h) ? "" : "checked"}> visible</label>`) +
      `</li>`;
  }).join("");
  return `<div class="section-h">SIDEBAR</div>` +
    `<p class="muted">Drag the handle to reorder tabs. Untick to hide one. Saved on this device.</p>` +
    `<ul class="nav-edit-list" id="nav-edit-list">${rows}</ul>` +
    `<div class="login-actions"><button type="button" class="btn" onclick="resetSidebar()">Reset to default</button></div>`;
}
function _dragAfter(list, y) {
  const els = [...list.querySelectorAll(".nav-edit-item:not(.dragging)")];
  let best = { offset: -Infinity, el: null };
  for (const child of els) {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > best.offset) best = { offset, el: child };
  }
  return best.el;
}
function persistNavFromDom() {
  const list = document.getElementById("nav-edit-list");
  if (!list) return;
  const order = [...list.querySelectorAll(".nav-edit-item")].map(li => li.getAttribute("data-href"));
  setNavOrder(order);
  renderSidebar("/settings");
}
function resetSidebar() {
  localStorage.removeItem(NAV_ORDER_KEY);
  localStorage.removeItem(NAV_HIDDEN_KEY);
  renderSidebar("/settings");
  renderSettingsTab();
}
function wireSidebarEditor() {
  const list = document.getElementById("nav-edit-list");
  if (!list) return;
  let dragEl = null;
  list.querySelectorAll(".nav-edit-item").forEach(li => {
    li.addEventListener("dragstart", () => { dragEl = li; li.classList.add("dragging"); });
    li.addEventListener("dragend", () => { li.classList.remove("dragging"); dragEl = null; persistNavFromDom(); });
  });
  list.addEventListener("dragover", e => {
    e.preventDefault();
    if (!dragEl) return;
    const after = _dragAfter(list, e.clientY);
    if (after == null) list.appendChild(dragEl);
    else list.insertBefore(dragEl, after);
  });
  list.querySelectorAll("[data-hide]").forEach(cb => cb.onchange = () => {
    const hidden = navHidden();
    const h = cb.getAttribute("data-hide");
    if (cb.checked) hidden.delete(h); else hidden.add(h);
    setNavHidden(hidden);
    renderSidebar("/settings");
  });
}

// ----- Support tab -----
const SUPPORT_FAQ = [
  ["How do I connect my school accounts?", "Open Settings → Connections. Connect Google for Gmail + Classroom, and enter your Veracross and Accelerate username and password, then press Sync."],
  ["Why don't I see grades for a class?", "Grades come from Veracross — make sure your Veracross login is saved and synced. Tasks come from Classroom and Accelerate."],
  ["How do notifications work?", "The Notifications page shows your in-app feed with an unread badge. For SMS, WhatsApp or Telegram reminders, set your channel in Settings → Messages."],
  ["How do I use Telegram for free instead of SMS?", "In Settings → Messages: create a bot with @BotFather, paste the bot token and your chat ID (from @userinfobot), pick Telegram as your channel, then Send test. It does not use Twilio."],
  ["How do I join a club?", "Go to Community → Clubs, open a club card and enter the access code given by the club leader or teacher."],
  ["Does the AI chat remember our conversation?", "Yes — every conversation is saved and listed in Chat. Fill in Settings → AI & Profile so answers are tailored to you."],
  ["How do I reorder or hide sidebar tabs?", "Settings → Sidebar. Drag to reorder and untick to hide. Settings always stays visible."],
  ["How is the school calendar colour-coded?", "Calendar shows weekends shaded and official dates coloured: red = non-attendance, yellow = holidays/breaks, blue = important dates, orange = testing, purple = student events. Use ‘Year overview’ for the full-year image."],
];
function settingsSupportHtml() {
  const faq = SUPPORT_FAQ.map(([q, a]) =>
    `<details class="faq-item"><summary>${esc(q)}</summary><p>${esc(a)}</p></details>`).join("");
  return `<div class="section-h">SUPPORT · FAQ</div>${faq}` +
    `<div class="section-h" style="margin-top:20px">DIDN'T FIND AN ANSWER?</div>` +
    `<p class="muted">Email us — we're happy to help.</p>` +
    `<div id="support-admins" class="support-emails muted">Loading…</div>`;
}
async function loadSupportAdmins() {
  try {
    const r = await getJSON("/api/admins");
    const el = document.getElementById("support-admins");
    if (!el) return;
    const list = r.admins || [];
    el.innerHTML = list.length
      ? list.map(e => `<a class="btn support-email" href="mailto:${esc(e)}">${esc(e)}</a>`).join("")
      : "No admin contacts configured yet.";
  } catch (e) { /* ignore */ }
}

// ----- Connections -----
function _connRow(key, label, type) {
  const t = type || "text";
  return `<label class="cred-field"><span>${esc(label)}</span>` +
    `<input data-set="${key}" type="${t}" value="${esc(_fieldVal(key))}" placeholder="${esc(_fieldPlaceholder(key))}" autocomplete="off"></label>`;
}
function _statusLine(k) {
  const c = _setStatus[k] || {};
  return `${c.connected ? '<span class="dot on">●</span>' : '<span class="dot off">○</span>'} ` +
    `${c.count || 0} items · sync: ${c.last_sync ? fmtDate(c.last_sync) : "never"}`;
}
function settingsConnectionsHtml() {
  const s = _setStatus, a = _setAccount;
  const g = s.gmail && s.gmail.connected;
  const gEmail = a.email
    ? "Signed in as " + esc(a.email) + ((a.google_missing_scopes && a.google_missing_scopes.length) ? " · missing permissions — reconnect" : "")
    : (g ? "Connected" : "Not connected. Connect to pull Gmail + Classroom.");
  return `<div class="section-h">CONNECTIONS</div>` +
    // Google combined
    `<div class="settings-row"><div class="row-head">` +
      `<div><div class="status-name">Google · Gmail + Classroom</div>` +
      `<div class="muted">${g ? '<span class="dot on">●</span> Connected' : '<span class="dot off">○</span> Not connected'} · ${gEmail}</div>` +
      `<div class="muted">Gmail: ${_statusLine("gmail")} &nbsp;|&nbsp; Classroom: ${_statusLine("classroom")}</div></div>` +
      `<div class="row-actions">` +
        `<a class="btn" href="/auth/google">${g ? "Switch account" : "Connect Google"}</a>` +
        (g ? `<button type="button" class="btn" onclick="disconnectGoogle()">Disconnect</button>` : "") +
        `<button type="button" class="btn" id="sync-google-btn" onclick="syncGoogle(this)">Sync Google</button>` +
      `</div>` +
    `</div></div>` +
    // Veracross
    `<div class="settings-row"><div class="row-head" style="align-items:flex-start">` +
      `<div style="flex:1;min-width:240px"><div class="status-name src-veracross">Veracross · grades</div>` +
      `<div class="muted" style="margin-bottom:8px">${_statusLine("veracross")}</div>` +
      _connRow("VERACROSS_USERNAME", "Veracross username") +
      _connRow("VERACROSS_PASSWORD", "Veracross password", "password") + `</div>` +
      `<div class="row-actions"><button type="button" class="btn" onclick="saveConnections(this)">Save</button>` +
      `<button type="button" class="btn" onclick="syncOne('veracross', this)">Sync</button></div>` +
    `</div></div>` +
    // Accelerate / Buzz
    `<div class="settings-row"><div class="row-head" style="align-items:flex-start">` +
      `<div style="flex:1;min-width:240px"><div class="status-name src-buzz">Accelerate / Buzz · tasks</div>` +
      `<div class="muted" style="margin-bottom:8px">${_statusLine("buzz")}</div>` +
      _connRow("BUZZ_USERNAME", "Accelerate username") +
      _connRow("BUZZ_PASSWORD", "Accelerate password", "password") + `</div>` +
      `<div class="row-actions"><button type="button" class="btn" onclick="saveConnections(this)">Save</button>` +
      `<button type="button" class="btn" onclick="syncOne('buzz', this)">Sync</button></div>` +
    `</div></div>` +
    `<div id="conn-status" class="login-status muted"></div>` +
    // Advanced
    `<details class="admin-creds"><summary class="muted">Advanced — portal URLs (defaults are pre-filled)</summary>` +
      `<div class="cred-group" style="margin-top:10px">` +
      _connRow("VERACROSS_URL", "Veracross portal URL") +
      _connRow("BUZZ_DOMAIN", "Accelerate / Buzz domain") +
      `<button type="button" class="btn" onclick="saveConnections(this)">Save advanced</button></div>` +
    `</details>` +
    (a.is_admin ? `<div class="settings-row" style="margin-top:14px"><div class="row-head">` +
      `<div class="muted">Shared server credentials &amp; community controls.</div>` +
      `<a class="btn" href="/platform-config">Open Platform Config</a></div></div>` : "");
}

// ----- Messages -----
function settingsMessagesHtml() {
  const m = _setMsg, p = _setPrefs;
  const ch = p.notification_channel || "sms";
  const opt = (v, lbl) => `<option value="${v}"${ch === v ? " selected" : ""}>${lbl}</option>`;
  return `<div class="section-h">MESSENGER</div>` +
    `<div class="settings-row"><div class="muted">` +
      `Channel readiness — SMS: ${m.sms_ready ? "ready" : "not set"} · WhatsApp: ${m.whatsapp_ready ? "ready" : "not set"} · Telegram: ${m.telegram_ready ? "ready" : "not set"}` +
    `</div></div>` +
    `<div class="cred-group">` +
      _connRow("USER_DISPLAY_NAME", "Your first name (used in messages)") +
      _connRow("YOUR_PHONE_NUMBER", "Your mobile (E.164, e.g. +34…)") +
      `<label class="cred-field"><span>Preferred channel</span>` +
        `<select id="set-channel">${opt("sms", "SMS")}${opt("whatsapp", "WhatsApp")}${opt("telegram", "Telegram (free, recommended)")}</select></label>` +
      `<div class="muted channel-hint" id="set-channel-hint"></div>` +
    `</div>` +
    `<div class="cred-group" id="telegram-group">` +
      `<div class="section-h">TELEGRAM (direct, no Twilio)</div>` +
      `<div class="muted" style="margin-bottom:8px">Create a bot with <code>@BotFather</code>, paste the token, then message your bot and put your chat ID below. ` +
      `Get the chat ID from <code>@userinfobot</code>.</div>` +
      _connRow("TELEGRAM_BOT_TOKEN", "Telegram bot token", "password") +
      _connRow("TELEGRAM_CHAT_ID", "Telegram chat ID") +
    `</div>` +
    `<div class="cred-group">` +
      `<div class="section-h">REMINDERS &amp; UPDATES</div>` +
      `<label class="cred-check"><input type="checkbox" id="chatbot_enabled"${p.chatbot_enabled ? " checked" : ""}> Reply with the AI assistant when I message the bot</label>` +
      `<label class="cred-check"><input type="checkbox" id="daily_digest_enabled"${p.daily_digest_enabled ? " checked" : ""}> Morning task summary</label>` +
      `<label class="cred-field"><span>Digest hour (0–23)</span><input type="number" id="daily_digest_hour" min="0" max="23" value="${p.daily_digest_hour ?? 7}"></label>` +
      `<label class="cred-check"><input type="checkbox" id="reminders_enabled"${p.reminders_enabled ? " checked" : ""}> Reminders before deadlines</label>` +
      `<label class="cred-field"><span>Remind within (hours)</span><input type="number" id="reminder_hours_before" min="1" max="72" value="${p.reminder_hours_before ?? 2}"></label>` +
      `<label class="cred-check"><input type="checkbox" id="background_sync_enabled"${p.background_sync_enabled ? " checked" : ""}> Background sync</label>` +
    `</div>` +
    `<div class="login-actions">` +
      `<button type="button" class="btn" onclick="saveMessages(this)">Save</button>` +
      `<button type="button" class="btn" onclick="testMessage(this)">Send test</button>` +
    `</div>` +
    `<div id="msg-status" class="login-status muted"></div>`;
}

// ----- AI & Profile -----
function settingsProfileHtml() {
  return `<div class="section-h">YOUR STUDENT PROFILE</div>` +
    `<p class="muted">Nexus AI uses this to personalise help — favourite and disliked subjects, learning style, goals, exams coming up. It is private to your account.</p>` +
    `<div class="cred-group">` +
      `<label class="cred-field"><span>About you</span>` +
      `<textarea id="ai-profile" rows="8" placeholder="e.g. I love Physics and Maths, dislike essay writing. I learn best with worked examples. Targeting a 5 in AP Calculus. Native Spanish speaker.">${esc(_fieldVal("AI_PROFILE"))}</textarea></label>` +
    `</div>` +
    `<div class="login-actions"><button type="button" class="btn" onclick="saveProfile(this)">Save profile</button></div>` +
    `<div id="profile-status" class="login-status muted"></div>` +
    `<details class="admin-creds account-password" style="margin-top:18px"><summary class="muted">Change password</summary>` +
      `<label class="cred-field"><span>New password (min 8 chars)</span><input id="new-password" type="password" autocomplete="new-password"></label>` +
      `<div class="login-actions"><button type="button" class="btn" id="password-save-btn">Update password</button></div>` +
      `<div id="password-status" class="login-status muted"></div>` +
    `</details>`;
}

function wireSettingsTab() {
  if (_settingsTab === "messages") {
    const sel = document.getElementById("set-channel");
    const hint = document.getElementById("set-channel-hint");
    const upd = () => { if (hint) hint.textContent = CHANNEL_HINTS[sel.value] || ""; };
    if (sel) { sel.onchange = upd; upd(); }
  } else if (_settingsTab === "profile") {
    initAccountPassword();
  } else if (_settingsTab === "sidebar") {
    wireSidebarEditor();
  } else if (_settingsTab === "support") {
    loadSupportAdmins();
  }
}

function _collectSetInputs() {
  const values = {};
  document.querySelectorAll("[data-set]").forEach(inp => {
    const key = inp.getAttribute("data-set");
    const v = (inp.value || "").trim();
    const f = _field(key);
    if (f.secret && !v) return;     // keep saved secret
    if (v !== "" || !f.secret) values[key] = v;
  });
  return values;
}

async function saveConnections(btn) {
  const status = document.getElementById("conn-status");
  if (status) status.textContent = "Saving…";
  try {
    await postJSON("/api/settings", { values: _collectSetInputs() });
    if (status) status.textContent = "Saved.";
    const sett = await getJSON("/api/settings");
    _loginFields = sett.fields || [];
  } catch (e) { if (status) status.textContent = "Error: " + e; }
}

async function saveMessages(btn) {
  const status = document.getElementById("msg-status");
  if (status) status.textContent = "Saving…";
  try {
    await postJSON("/api/settings", { values: _collectSetInputs() });
    const body = { notification_channel: document.getElementById("set-channel").value };
    ["chatbot_enabled", "daily_digest_enabled", "reminders_enabled", "background_sync_enabled"].forEach(id => {
      const el = document.getElementById(id); if (el) body[id] = el.checked;
    });
    ["daily_digest_hour", "reminder_hours_before"].forEach(id => {
      const el = document.getElementById(id); if (el) body[id] = parseInt(el.value, 10);
    });
    await postJSON("/api/notifications/prefs", body);
    _setPrefs = Object.assign(_setPrefs, body);
    const sett = await getJSON("/api/settings"); _loginFields = sett.fields || [];
    _setMsg = await getJSON("/api/messaging/status");
    if (status) status.textContent = "Saved.";
  } catch (e) { if (status) status.textContent = "Error: " + e; }
}

async function testMessage(btn) {
  const status = document.getElementById("msg-status");
  if (status) status.textContent = "Sending test…";
  try {
    const r = await postJSON("/api/notifications/test");
    if (status) status.textContent = (r.ok ? "Sent via " + (r.channel || "channel") + ". " : "Failed: ") + (r.detail || "");
  } catch (e) { if (status) status.textContent = "Error: " + e; }
}

async function saveProfile(btn) {
  const status = document.getElementById("profile-status");
  const val = document.getElementById("ai-profile").value;
  if (status) status.textContent = "Saving…";
  try {
    await postJSON("/api/settings", { values: { AI_PROFILE: val } });
    const sett = await getJSON("/api/settings"); _loginFields = sett.fields || [];
    if (status) status.textContent = "Saved. Nexus AI will use this in chat.";
  } catch (e) { if (status) status.textContent = "Error: " + e; }
}

async function syncGoogle(btn) {
  const o = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Syncing…"; }
  let lines = [];
  for (const src of ["gmail", "classroom"]) {
    try {
      const r = await postJSON("/sync/" + src);
      const info = r && r[src];
      lines.push(`${src}: ${info && info.error ? "failed (" + info.error + ")" : "synced " + ((info && info.count) ?? 0)}`);
    } catch (e) { lines.push(`${src}: ${e.message}`); }
  }
  if (btn) { btn.disabled = false; btn.textContent = o; }
  alert("Google sync\n\n" + lines.join("\n"));
  initSettings();
}

async function syncOne(src, btn) {
  const o = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "…"; }
  try {
    const r = await postJSON("/sync/" + src);
    const info = r && r[src];
    if (info && info.error) alert(`${src} sync failed: ${info.error}`);
    else if (info) alert(`${src}: synced ${info.count ?? info} items`);
  } catch (e) {
    alert(`${src} sync failed: ${e.message}`);
  }
  if (btn) { btn.disabled = false; btn.textContent = o; }
  if (location.pathname === "/materials" && typeof loadMaterials === "function") await loadMaterials();
  else if (location.pathname === "/settings") initSettings();
}

async function disconnectGoogle() {
  if (!confirm("Disconnect Google and clear synced Gmail, Classroom, and news tasks?")) return;
  try {
    await postJSON("/auth/google/disconnect");
    location.href = "/settings";
  } catch (e) {
    alert("Disconnect failed: " + e.message);
  }
}

// ---------- COMPLETED ----------
let _completedTasks = [];

async function initCompleted() {
  renderSidebar("/completed");
  await loadCompleted();
  document.getElementById("f-source").onchange = renderCompletedTable;
}

async function loadCompleted() {
  const all = await getJSON("/api/tasks?completed=true");
  _completedTasks = (all || []).filter(t => t.is_completed);
  renderCompletedTable();
}

function renderCompletedTable() {
  const src = document.getElementById("f-source").value;
  let rows = _completedTasks.filter(t => t.is_completed);
  if (src) rows = rows.filter(t => t.source === src);
  document.querySelector("#task-table tbody").innerHTML = rows.map(t =>
    `<tr>` +
    `<td>${esc(t.title)}</td><td>${esc(t.course_name || "—")}</td>` +
    `<td class="${srcClass(t.source)}">${sourceLabel(t.source)}</td><td>${fmtDate(t.due_date, t.source)}</td>` +
    `<td class="${pClass(t.priority_score)}">${t.priority_score}</td>` +
    `<td><input type="checkbox" checked onchange="reopenTask(${t.id})"></td></tr>`
  ).join("") || `<tr><td colspan="6" class="muted">No completed tasks yet.</td></tr>`;
}

async function reopenTask(id) {
  await patchJSON(`/api/tasks/${id}/complete`);
  await loadCompleted();
}

// ---------- NOTIFICATIONS ----------
const NOTIFY_IDS = [
  "chatbot_enabled", "daily_digest_enabled", "daily_digest_hour", "daily_digest_minute",
  "reminders_enabled", "reminder_check_minutes", "reminder_hours_before",
  "background_sync_enabled", "background_sync_hours",
];

const CHANNEL_HINTS = {
  sms: "Twilio SMS: set TWILIO_SMS_FROM and YOUR_PHONE_NUMBER on Account login. Webhook: /sms/incoming",
  whatsapp: "Twilio WhatsApp sandbox or Business API. Webhook: /whatsapp/incoming",
  telegram: "Create a bot via @BotFather, set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, then register webhook to /telegram/webhook",
};

function updateChannelHint() {
  const sel = document.getElementById("notification_channel");
  const hint = document.getElementById("channel-hint");
  if (sel && hint) hint.textContent = CHANNEL_HINTS[sel.value] || "";
}

let _notifCategory = "";
async function initNotifications() {
  renderSidebar("/notifications");
  await loadNotificationFeed();
  document.querySelectorAll("[data-notif-tab]").forEach(btn => {
    btn.onclick = () => {
      _notifCategory = btn.dataset.notifTab;
      document.querySelectorAll("[data-notif-tab]").forEach(b =>
        b.classList.toggle("active", b.dataset.notifTab === _notifCategory));
      loadNotificationFeed();
    };
  });
  const markBtn = document.getElementById("notif-mark-all");
  if (markBtn) markBtn.onclick = async () => {
    await postJSON("/api/notifications/read", { all: true });
    await loadNotificationFeed();
    refreshNavUnread();
  };
}

// ---------- LIBRARY ----------
function _bookCard(b, suggested) {
  const topics = (b.topics || []).map(t => `<span class="library-tag">${esc(t)}</span>`).join("");
  const matched = (b.matched_courses || []).length
    ? `<div class="library-match">Matches your work in: ${esc(b.matched_courses.join(", "))}</div>`
    : "";
  const badge = suggested ? `<span class="library-badge">Suggested</span>` : "";
  return `<article class="library-card${suggested ? " library-suggested" : ""}">` +
    `<div class="library-card-head">${badge}<h3>${esc(b.title)}</h3></div>` +
    `<div class="library-meta"><strong>Author:</strong> ${esc(b.author)}</div>` +
    `<div class="library-meta"><strong>Location:</strong> ${esc(b.location)}</div>` +
    `<div class="library-topics">${topics}</div>` +
    matched +
    `</article>`;
}

async function initLibrary() {
  renderSidebar("/library");
  const data = await getJSON("/api/library");
  const sug = document.getElementById("library-suggested");
  const all = document.getElementById("library-all");
  const suggested = data.suggested || [];
  if (sug) {
    sug.innerHTML = suggested.length
      ? suggested.map(b => _bookCard(b, true)).join("")
      : '<div class="muted">Sync assignments first — suggestions appear when we see open work by class.</div>';
  }
  if (all) {
    all.innerHTML = (data.books || []).map(b => _bookCard(b, false)).join("") ||
      '<div class="muted">No books in catalog.</div>';
  }
}

function fmtMaterialDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function _materialLinksHtml(links, alternate) {
  const items = (links || []).map(l =>
    `<a class="material-attachment" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.title || "Open link")}</a>`
  );
  if (alternate) {
    items.push(
      `<a class="material-attachment material-classroom" href="${esc(alternate)}" target="_blank" rel="noopener noreferrer">Open in Classroom</a>`
    );
  }
  if (!items.length) return "";
  return `<div class="material-attachments">${items.join("")}</div>`;
}

function _materialBooksHtml(books) {
  if (!books || !books.length) {
    return '<div class="material-no-books muted">No library match yet — browse the full <a href="/library">Library</a>.</div>';
  }
  return `<div class="material-books">` + books.map(b =>
    `<div class="material-book-link">` +
    `<strong>${esc(b.title)}</strong>` +
    `<span class="muted"> · ${esc(b.author)} · ${esc(b.location)}</span>` +
    `</div>`
  ).join("") + `</div>`;
}

function materialCard(m) {
  const body = (m.description || "").trim();
  const posted = fmtMaterialDate(m.posted_at || m.created_at);
  return `<article class="material-card">` +
    `<div class="material-head">` +
    `<span class="${srcClass(m.source)}">${esc(sourceLabel(m.source))}</span>` +
    `<span class="muted"> · ${esc(m.course_name || "—")}</span>` +
    `<span class="muted"> · Posted ${esc(posted)}</span>` +
    `</div>` +
    `<h3 class="material-title">${esc(m.title)}</h3>` +
    (body ? `<p class="material-body">${esc(body)}</p>` : "") +
    _materialLinksHtml(m.material_links, m.alternate_link) +
    `<div class="material-books-label">Suggested books</div>` +
    _materialBooksHtml(m.books) +
    `</article>`;
}

function _materialsQuery() {
  const course = document.getElementById("m-course")?.value || "";
  const sort = document.getElementById("m-sort")?.value || "date_desc";
  const params = new URLSearchParams();
  if (course) params.set("course", course);
  if (sort && sort !== "date_desc") params.set("sort", sort);
  const q = params.toString();
  return q ? `?${q}` : "";
}

function _populateMaterialsCourses(courses, selected) {
  const el = document.getElementById("m-course");
  if (!el) return;
  el.innerHTML = `<option value="">All classes</option>` +
    (courses || []).map(c =>
      `<option value="${esc(c.id)}">${esc(c.name)} (${c.count})</option>`
    ).join("");
  el.value = selected || "";
}

function renderMaterialsList(data) {
  const list = document.getElementById("materials-list");
  if (!list) return;
  const rows = data.materials || [];
  const course = data.course_id || document.getElementById("m-course")?.value || "";
  const total = data.total_count || 0;
  if (!rows.length) {
    let msg = "No Classroom materials synced yet. Connect Google on Settings, allow the Materials permission, then run Sync Classroom.";
    if (total > 0 && course) {
      msg = "No materials in this class.";
    } else if (total > 0) {
      msg = "No materials match the current filters.";
    }
    list.innerHTML = `<div class="muted">${msg}</div>`;
    return;
  }
  list.innerHTML = `<div class="materials-list">${rows.map(materialCard).join("")}</div>`;
}

async function loadMaterials() {
  const sortEl = document.getElementById("m-sort");
  const courseEl = document.getElementById("m-course");
  const params = new URLSearchParams(location.search);
  const course = courseEl?.value || params.get("course") || "";
  const sort = sortEl?.value || params.get("sort") || "date_desc";
  if (sortEl) sortEl.value = sort;
  const qs = new URLSearchParams();
  if (course) qs.set("course", course);
  if (sort) qs.set("sort", sort);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const data = await getJSON(`/api/materials${suffix}`);
  _populateMaterialsCourses(data.courses, course || data.course_id || "");
  history.replaceState(null, "", `/materials${_materialsQuery()}`);
  renderMaterialsList(data);
}

async function initMaterials() {
  renderSidebar("/materials");
  const root = document.getElementById("materials-root");
  if (!root) return;
  const params = new URLSearchParams(location.search);
  root.innerHTML =
    `<div class="filters materials-toolbar">` +
    `<select id="m-course" aria-label="Class"><option value="">All classes</option></select>` +
    `<select id="m-sort" aria-label="Sort materials">` +
    `<option value="date_desc">Sort: Newest first</option>` +
    `<option value="date_asc">Sort: Oldest first</option>` +
    `<option value="title">Sort: Title (A–Z)</option>` +
    `</select>` +
    `</div>` +
    `<div id="materials-list"><div class="muted">Loading materials…</div></div>`;
  document.getElementById("m-sort").value = params.get("sort") || "date_desc";
  document.getElementById("m-course").onchange = loadMaterials;
  document.getElementById("m-sort").onchange = loadMaterials;
  await loadMaterials();
}

// ===================================================================
// SHARED: modal / overlay helpers
// ===================================================================
function _overlay(innerHtml) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal-card">${innerHtml}</div>`;
  document.body.appendChild(back);
  back.addEventListener("click", (e) => { if (e.target === back) back.remove(); });
  return back;
}
function showInfoModal(title, message) {
  const back = _overlay(
    `<h3 class="modal-title">${esc(title)}</h3>` +
    `<p class="modal-msg">${esc(message)}</p>` +
    `<div class="modal-actions"><button type="button" class="btn" data-ok>OK</button></div>`);
  back.querySelector("[data-ok]").onclick = () => back.remove();
  return back;
}
function showProfanityWarning(message) {
  const back = _overlay(
    `<h3 class="modal-title" style="color:var(--priority-high)">Message blocked</h3>` +
    `<p class="modal-msg">${esc(message || "Your behavior is noted and will be reported")}</p>` +
    `<div class="modal-actions"><button type="button" class="btn" data-ok>Understood</button></div>`);
  back.querySelector("[data-ok]").onclick = () => back.remove();
}
function ensureChatUsername(suggested) {
  return new Promise((resolve) => {
    const back = _overlay(
      `<h3 class="modal-title">Pick a chat username</h3>` +
      `<p class="modal-msg">A username is required to post in chats. It will be shown next to your messages.</p>` +
      `<input id="uname-input" type="text" placeholder="username" value="${esc(suggested || "")}" maxlength="120">` +
      `<div class="modal-err muted" id="uname-err"></div>` +
      `<div class="modal-actions"><button type="button" class="btn" data-cancel>Cancel</button>` +
      `<button type="button" class="btn" data-save>Save</button></div>`);
    const input = back.querySelector("#uname-input");
    input.focus();
    back.querySelector("[data-cancel]").onclick = () => { back.remove(); resolve(null); };
    back.querySelector("[data-save]").onclick = async () => {
      const v = (input.value || "").trim();
      if (v.length < 2) { back.querySelector("#uname-err").textContent = "At least 2 characters."; return; }
      try {
        const r = await postJSON("/api/community/profile", { username: v });
        back.remove();
        resolve(r.username || v);
      } catch (e) { back.querySelector("#uname-err").textContent = "Error: " + e; }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") back.querySelector("[data-save]").click(); });
  });
}
function fmtWhen(iso) {
  const d = parseIsoDate(iso);
  if (!d) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// ===================================================================
// NOTIFICATIONS — in-app feed
// ===================================================================
const NOTIF_CAT_LABELS = {
  task: "Task", grade: "Grade", announcement: "Announcement",
  club: "Club", chat: "Chat", other: "Other", news: "News",
};
async function loadNotificationFeed() {
  const root = document.getElementById("notif-feed");
  if (!root) return;
  const q = _notifCategory ? `?category=${encodeURIComponent(_notifCategory)}` : "";
  const data = await getJSON(`/api/notifications/feed${q}`);
  const rows = data.notifications || [];
  if (!rows.length) {
    root.innerHTML = `<div class="muted">No notifications${_notifCategory ? " in this category" : ""} yet. They appear after you Sync.</div>`;
    return;
  }
  root.innerHTML = rows.map(n =>
    `<article class="notif-item${n.is_read ? "" : " notif-unread"}">` +
      `<div class="notif-meta"><span class="notif-cat notif-cat-${esc(n.category)}">${esc(NOTIF_CAT_LABELS[n.category] || n.category)}</span>` +
      ` · ${esc(fmtWhen(n.created_at))}${n.source ? " · " + esc(sourceLabel(n.source)) : ""}</div>` +
      `<div class="notif-title">${esc(n.title)}</div>` +
      (n.body ? `<div class="notif-body">${esc(n.body)}</div>` : "") +
      (n.link ? `<a class="notif-link" href="${esc(n.link)}">Open →</a>` : "") +
    `</article>`).join("");
}

// ===================================================================
// COMMUNITY — landing
// ===================================================================
async function initCommunity() {
  renderSidebar("/community");
  const root = document.getElementById("community-root");
  if (!root) return;
  let data = {};
  try { data = await getJSON("/api/community/overview"); } catch (e) { data = {}; }
  const tiles = [
    { href: "/community/news", title: "BHS News", desc: "Latest video from the school's YouTube channel." },
    { href: "/community/journal", title: "BHS Journal", desc: data.journal && data.journal.available ? "Read the latest issue." : "No issue uploaded yet." },
    { href: "/community/clubs", title: "Clubs", desc: `${data.clubs_count || 0} club${(data.clubs_count || 0) === 1 ? "" : "s"} — join with an access code.` },
  ];
  if (data.school_chat_enabled) {
    tiles.push({ href: "/community/chat", title: "School Chat", desc: "Talk with the whole school or your grade." });
  }
  root.innerHTML = tiles.map(t =>
    `<a class="community-tile" href="${t.href}">` +
    `<div class="community-tile-title">${esc(t.title)}</div>` +
    `<div class="muted">${esc(t.desc)}</div></a>`).join("");
}

// ===================================================================
// COMMUNITY — BHS News (YouTube)
// ===================================================================
async function initCommunityNews() {
  renderSidebar("/community");
  const root = document.getElementById("news-root");
  if (!root) return;
  root.innerHTML = `<div class="muted">Loading latest video…</div>`;
  let data = {};
  try { data = await getJSON("/api/community/news"); } catch (e) {}
  renderNews(root, data);
  const btn = document.getElementById("news-refresh");
  if (btn) btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "Refreshing…";
    try { data = await getJSON("/api/community/news?refresh=1"); renderNews(root, data); }
    catch (e) {}
    btn.disabled = false; btn.textContent = "Refresh";
  };
}
function renderNews(root, data) {
  if (data && data.embed_url) {
    const watch = data.watch_url || data.channel_url || "";
    root.innerHTML = `<div class="video-wrap"><iframe src="${esc(data.embed_url)}" title="BHS News" ` +
      `referrerpolicy="strict-origin-when-cross-origin" ` +
      `allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div>` +
      `<div class="muted" style="margin-top:10px">` +
      (watch ? `<a href="${esc(watch)}" target="_blank" rel="noopener">Watch on YouTube →</a> · ` : "") +
      `<a href="${esc(data.channel_url)}" target="_blank" rel="noopener">Visit the channel →</a></div>`;
  } else {
    root.innerHTML = `<div class="muted">Could not load the latest video automatically. ` +
      `An admin can pin a video on <a href="/platform-config">Platform Config</a>, then click Refresh. ` +
      (data && data.channel_url ? `<a href="${esc(data.channel_url)}" target="_blank" rel="noopener">Open the channel →</a>` : "") + `</div>`;
  }
}

function clubImgHtml(url, className) {
  if (!url) return "";
  return `<img class="${className}" src="${esc(url)}" alt="" loading="lazy">`;
}

async function uploadClubImage(clubId, file) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`/api/clubs/${clubId}/image`, { method: "POST", body: fd });
  if (!r.ok) {
    const err = await r.text();
    throw new Error(r.status + " " + (err || r.statusText).slice(0, 120));
  }
  return r.json();
}

async function deleteClub(clubId) {
  const c = _findClub(clubId) || _club;
  const label = (c && c.name) || "this club";
  if (!confirm(`Permanently delete "${label}"? This cannot be undone.`)) return;
  await postJSON(`/api/clubs/${clubId}/delete`);
  if (location.pathname.includes("/community/club")) location.href = "/community/clubs";
  else await loadClubs();
}

async function renderJournalPdf(fileUrl, root) {
  root.innerHTML =
    `<div class="pdf-toolbar">` +
    `<button type="button" class="btn" id="pdf-prev" disabled>Previous</button>` +
    `<span id="pdf-page-info" class="muted">Loading…</span>` +
    `<button type="button" class="btn" id="pdf-next" disabled>Next</button>` +
    `<a class="btn" href="${esc(fileUrl)}" target="_blank" rel="noopener">Open in new tab</a>` +
    `</div>` +
    `<div class="pdf-canvas-wrap"><canvas id="pdf-canvas"></canvas></div>`;
  const pdfjs = window.pdfjsLib;
  if (!pdfjs) {
    root.innerHTML = `<div class="muted">PDF viewer failed to load. <a href="${esc(fileUrl)}" target="_blank" rel="noopener">Open the journal in a new tab →</a></div>`;
    return;
  }
  pdfjs.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  let pdf = null;
  let pageNum = 1;
  let rendering = false;
  const canvas = document.getElementById("pdf-canvas");
  const ctx = canvas.getContext("2d");
  const info = document.getElementById("pdf-page-info");
  const prevBtn = document.getElementById("pdf-prev");
  const nextBtn = document.getElementById("pdf-next");
  async function renderPage() {
    if (!pdf || rendering) return;
    rendering = true;
    const page = await pdf.getPage(pageNum);
    const viewport = page.getViewport({ scale: 1.35 });
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await page.render({ canvasContext: ctx, viewport }).promise;
    info.textContent = `Page ${pageNum} of ${pdf.numPages}`;
    prevBtn.disabled = pageNum <= 1;
    nextBtn.disabled = pageNum >= pdf.numPages;
    rendering = false;
  }
  prevBtn.onclick = () => { if (pageNum > 1) { pageNum--; renderPage(); } };
  nextBtn.onclick = () => { if (pdf && pageNum < pdf.numPages) { pageNum++; renderPage(); } };
  try {
    pdf = await pdfjs.getDocument({ url: fileUrl, withCredentials: true }).promise;
    await renderPage();
  } catch (e) {
    root.innerHTML = `<div class="muted">Could not render the PDF inline (${esc(String(e))}). ` +
      `<a href="${esc(fileUrl)}" target="_blank" rel="noopener">Open in new tab →</a></div>`;
  }
}

// ===================================================================
// COMMUNITY — BHS Journal (PDF)
// ===================================================================
async function initCommunityJournal() {
  renderSidebar("/community");
  const root = document.getElementById("journal-root");
  if (!root) return;
  let data = {};
  try { data = await getJSON("/api/community/journal"); } catch (e) {}
  const title = document.getElementById("journal-title");
  if (title) title.textContent = data.title || "BHS Journal";
  if (data.available && data.file_url) {
    await renderJournalPdf(data.file_url, root);
  } else {
    root.innerHTML = `<div class="muted">No journal has been uploaded yet.` +
      (data.is_admin ? ` Upload one on <a href="/platform-config">Platform Config</a>.` : "") + `</div>`;
  }
}

// ===================================================================
// COMMUNITY — Clubs dashboard
// ===================================================================
let _clubsData = null;
async function initClubs() {
  renderSidebar("/community");
  await loadClubs();
  const createBtn = document.getElementById("club-create-btn");
  if (createBtn) createBtn.onclick = openCreateClub;
}
async function loadClubs() {
  const data = await getJSON("/api/clubs");
  _clubsData = data;
  const adminBar = document.getElementById("club-admin-bar");
  if (adminBar) adminBar.hidden = !data.is_admin;
  renderClubSection("club-manage", data.manage, "manage");
  renderClubSection("club-joined", data.joined, "joined");
  renderClubSection("club-all", data.all, "all");
  const manageWrap = document.getElementById("club-manage-wrap");
  if (manageWrap) manageWrap.hidden = !(data.manage && data.manage.length);
}
function renderClubSection(id, clubs, mode) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!clubs || !clubs.length) {
    el.innerHTML = `<div class="muted">${mode === "all" ? "No clubs yet." : mode === "joined" ? "You haven't joined any clubs yet." : ""}</div>`;
    return;
  }
  el.innerHTML = clubs.map(c => clubCard(c, mode)).join("");
}
function _truncate(text, n) {
  if (!text) return "";
  return text.length > n ? text.slice(0, n).trim() + "…" : text;
}
function clubCard(c, mode) {
  const portal = (mode === "joined" || mode === "manage" || c.is_member || c.is_manager);
  const img = clubImgHtml(c.image_url, "club-card-img");
  const desc = (c.description || "").length > 150
    ? `<span class="club-desc-short">${esc(_truncate(c.description, 150))} <button type="button" class="link-btn" onclick="event.stopPropagation();openClubPreview(${c.id})">more</button></span>`
    : esc(c.description || "No description.");
  const tag = c.is_manager ? `<span class="club-tag">Leader / Teacher</span>` : (c.is_member ? `<span class="club-tag">Member</span>` : "");
  const del = (_clubsData && _clubsData.can_delete_clubs)
    ? `<button type="button" class="link-btn club-del-btn" onclick="event.stopPropagation();deleteClub(${c.id})">Delete</button>` : "";
  const onclick = portal ? `onclick="location.href='/community/club?id=${c.id}'"` : `onclick="openClubPreview(${c.id})"`;
  return `<article class="club-card" ${onclick}>` +
    img +
    `<div class="club-card-body">` +
    `<div class="club-card-head"><span class="club-card-name">${esc(c.name)}</span>${tag}${del}</div>` +
    `<div class="club-card-desc">${desc}</div>` +
    `<div class="muted club-card-meta">${c.member_count} member${c.member_count === 1 ? "" : "s"}` +
    (portal ? ` · click to enter` : ` · click to join`) + `</div>` +
    `</div></article>`;
}
function _findClub(id) {
  if (!_clubsData) return null;
  return (_clubsData.all || []).find(c => c.id === id);
}
function openClubPreview(id) {
  const c = _findClub(id);
  if (!c) return;
  const img = clubImgHtml(c.image_url, "club-preview-img");
  const emails = [];
  if (c.leader_email) emails.push("leader " + c.leader_email);
  if (c.teacher_email) emails.push("teacher " + c.teacher_email);
  const help = emails.length
    ? `Don't have a code? Write the ${emails.map(esc).join(", ")}.`
    : `Don't have a code? Ask the club leadership.`;
  const back = _overlay(
    img +
    `<h3 class="modal-title">${esc(c.name)}</h3>` +
    `<p class="modal-msg">${esc(c.description || "No description.")}</p>` +
    `<input id="club-code-input" type="text" placeholder="Enter access code" maxlength="64">` +
    `<div class="modal-err muted" id="club-code-err"></div>` +
    `<p class="muted">${help}</p>` +
    `<div class="modal-actions"><button type="button" class="btn" data-cancel>Close</button>` +
    `<button type="button" class="btn" data-join>Join club</button></div>`);
  back.querySelector("[data-cancel]").onclick = () => back.remove();
  back.querySelector("[data-join]").onclick = async () => {
    const code = (back.querySelector("#club-code-input").value || "").trim();
    try {
      await postJSON(`/api/clubs/${id}/join`, { code });
      back.remove();
      location.href = `/community/club?id=${id}`;
    } catch (e) {
      back.querySelector("#club-code-err").textContent = String(e).replace(/^Error:\s*/, "").replace(/^\d+\s+\w+:\s*/, "");
    }
  };
}
function openCreateClub() {
  const back = _overlay(
    `<h3 class="modal-title">Create a club</h3>` +
    `<label class="cred-field"><span>Club name *</span><input id="cc-name" type="text"></label>` +
    `<label class="cred-field"><span>Description</span><input id="cc-desc" type="text"></label>` +
    `<label class="cred-field"><span>Club image (PNG/JPG)</span><input id="cc-file" type="file" accept="image/png,image/jpeg,image/webp,image/gif"></label>` +
    `<label class="cred-field"><span>Or image URL (optional)</span><input id="cc-img" type="text" placeholder="https://…"></label>` +
    `<label class="cred-field"><span>Leader email</span><input id="cc-leader" type="text"></label>` +
    `<label class="cred-field"><span>Teacher email (optional)</span><input id="cc-teacher" type="text"></label>` +
    `<label class="cred-field"><span>Initial access code</span><input id="cc-code" type="text"></label>` +
    `<label class="cred-field"><span>Schedule (e.g. Every Wed 15:00 at AP Hub)</span><input id="cc-sched" type="text"></label>` +
    `<div class="modal-err muted" id="cc-err"></div>` +
    `<div class="modal-actions"><button type="button" class="btn" data-cancel>Cancel</button>` +
    `<button type="button" class="btn" data-create>Create</button></div>`);
  back.querySelector("[data-cancel]").onclick = () => back.remove();
  back.querySelector("[data-create]").onclick = async () => {
    const payload = {
      name: back.querySelector("#cc-name").value.trim(),
      description: back.querySelector("#cc-desc").value.trim(),
      image_url: back.querySelector("#cc-img").value.trim(),
      leader_email: back.querySelector("#cc-leader").value.trim(),
      teacher_email: back.querySelector("#cc-teacher").value.trim(),
      access_code: back.querySelector("#cc-code").value.trim(),
      schedule: back.querySelector("#cc-sched").value.trim(),
    };
    if (!payload.name) { back.querySelector("#cc-err").textContent = "Name is required."; return; }
    try {
      const r = await postJSON("/api/clubs/create", payload);
      const imgFile = back.querySelector("#cc-file").files[0];
      if (imgFile && r.club && r.club.id) await uploadClubImage(r.club.id, imgFile);
      back.remove();
      await loadClubs();
    }
    catch (e) { back.querySelector("#cc-err").textContent = "Error: " + e; }
  };
}

// ===================================================================
// COMMUNITY — Club portal
// ===================================================================
let _club = null;
let _clubChatLast = 0;
let _clubChatTimer = null;
function _clubId() {
  return parseInt(new URLSearchParams(location.search).get("id"), 10);
}
async function initClubPortal() {
  renderSidebar("/community");
  const id = _clubId();
  const root = document.getElementById("club-root");
  if (!root || !id) return;
  let data;
  try {
    data = await getJSON(`/api/clubs/${id}`);
  } catch (e) {
    root.innerHTML = `<div class="muted">You need to join this club to view it. <a href="/community/clubs">Back to clubs →</a></div>`;
    return;
  }
  _club = data;
  renderClubPortal(root, data);
  _clubChatLast = 0;
  await loadClubChat(true);
  if (_clubChatTimer) clearInterval(_clubChatTimer);
  _clubChatTimer = setInterval(() => loadClubChat(false), 4000);
}
function renderClubPortal(root, c) {
  const emails = [];
  if (c.teacher_email) emails.push(`<div><strong>Teacher:</strong> ${esc(c.teacher_email)}</div>`);
  if (c.leader_email) emails.push(`<div><strong>Leader:</strong> ${esc(c.leader_email)}</div>`);
  const sched = c.schedule ? `<div><strong>Schedule:</strong> ${esc(c.schedule)}</div>` : "";
  const manageBtn = c.can_manage ? `<button type="button" class="btn" onclick="openClubManage()">Manage club</button>` : "";
  const delBtn = c.can_delete_clubs ? `<button type="button" class="btn" onclick="deleteClub(${c.id})">Delete club</button>` : "";
  const postBtn = c.can_manage ? `<button type="button" class="btn" onclick="openClubPost()">Post update</button>` : "";
  root.innerHTML =
    `<div class="topbar"><div class="breadcrumb">CLUB / ${esc(c.name).toUpperCase()}</div>` +
    `<div class="row-actions">${manageBtn}${delBtn}<a class="btn" href="/community/clubs">All clubs</a></div></div>` +
    `<div class="club-portal">` +
      `<div class="club-info">` +
        `<div class="section-h">CLUB DETAILS</div>` +
        `<div class="club-details">${emails.join("") || '<div class="muted">No contacts listed.</div>'}${sched}</div>` +
      `</div>` +
      `<div class="club-news-col">` +
        `<div class="section-h">NEWS & UPDATES ${postBtn}</div>` +
        `<div id="club-news-list"></div>` +
      `</div>` +
      `<div class="club-chat-col">` +
        `<div class="section-h">CLUB CHAT</div>` +
        `<div class="chat-box" id="club-messages"></div>` +
        `<div class="chat-input"><input type="text" id="club-chat-text" placeholder="Message the club…" autocomplete="off">` +
        `<button type="button" id="club-chat-send">Send</button></div>` +
      `</div>` +
    `</div>`;
  renderClubNews(c.news || []);
  const sendBtn = document.getElementById("club-chat-send");
  const inp = document.getElementById("club-chat-text");
  if (sendBtn) sendBtn.onclick = sendClubChat;
  if (inp) inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); sendClubChat(); } });
}
function renderClubNews(news) {
  const el = document.getElementById("club-news-list");
  if (!el) return;
  if (!news.length) { el.innerHTML = `<div class="muted">No updates yet.</div>`; return; }
  el.innerHTML = news.map(n => {
    const del = (_club && _club.can_manage)
      ? `<button type="button" class="link-btn" onclick="deleteClubNews(${n.id})">remove</button>` : "";
    const imgs = [];
    if (n.image_url) imgs.push(`<img class="club-news-img" src="${esc(n.image_url)}" alt="">`);
    (n.images || []).forEach(im => imgs.push(`<img class="club-news-img" src="${esc(im.url)}" alt="${esc(im.name || "")}">`));
    const files = (n.files || []).map(f =>
      `<a class="material-attachment" href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.name || "file")}</a>`).join("");
    return `<article class="club-news-item">` +
      `<div class="notif-meta">${esc(n.author_name || "Leadership")} · ${esc(fmtWhen(n.created_at))} ${del}</div>` +
      (n.title ? `<h3 class="club-news-title">${esc(n.title)}</h3>` : "") +
      imgs.join("") +
      `<div class="club-news-body chat-md">${renderChatMarkdown(n.body || "")}</div>` +
      (files ? `<div class="material-attachments">${files}</div>` : "") +
      `</article>`;
  }).join("");
  el.querySelectorAll(".chat-md").forEach(typesetChat);
}
async function deleteClubNews(nid) {
  if (!confirm("Remove this update?")) return;
  await postJSON(`/api/clubs/${_club.id}/news/${nid}/delete`);
  const data = await getJSON(`/api/clubs/${_club.id}`);
  _club = data;
  renderClubNews(data.news || []);
}
function openClubPost() {
  const back = _overlay(
    `<h3 class="modal-title">Post an update</h3>` +
    `<label class="cred-field"><span>Title (optional)</span><input id="cn-title" type="text"></label>` +
    `<label class="cred-field"><span>Body — Markdown & LaTeX ($…$) supported</span>` +
    `<textarea id="cn-body" rows="6"></textarea></label>` +
    `<label class="cred-field"><span>Images (browse — PNG/JPG/WEBP/GIF, multiple)</span>` +
    `<input id="cn-images" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple></label>` +
    `<label class="cred-field"><span>Attachments (PDF, DOCX, PPTX, XLSX… multiple)</span>` +
    `<input id="cn-files" type="file" accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.csv,.zip" multiple></label>` +
    `<label class="cred-field"><span>Or image URL (optional)</span><input id="cn-img" type="text" placeholder="https://…"></label>` +
    `<div class="modal-err muted" id="cn-err"></div>` +
    `<div class="modal-actions"><button type="button" class="btn" data-cancel>Cancel</button>` +
    `<button type="button" class="btn" data-post>Post</button></div>`);
  back.querySelector("[data-cancel]").onclick = () => back.remove();
  back.querySelector("[data-post]").onclick = async () => {
    const title = back.querySelector("#cn-title").value.trim();
    const body = back.querySelector("#cn-body").value.trim();
    const imgUrl = back.querySelector("#cn-img").value.trim();
    const images = back.querySelector("#cn-images").files;
    const files = back.querySelector("#cn-files").files;
    if (!title && !body && !images.length && !files.length && !imgUrl) {
      back.querySelector("#cn-err").textContent = "Write something or attach a file."; return;
    }
    const fd = new FormData();
    fd.append("title", title);
    fd.append("body", body);
    if (imgUrl) fd.append("image_url", imgUrl);
    for (const f of images) fd.append("images", f);
    for (const f of files) fd.append("files", f);
    const btn = back.querySelector("[data-post]");
    btn.disabled = true; btn.textContent = "Posting…";
    try {
      const r = await fetch(`/api/clubs/${_club.id}/news`, { method: "POST", body: fd });
      if (!r.ok) throw new Error((await r.text()).slice(0, 160));
      back.remove();
      const data = await getJSON(`/api/clubs/${_club.id}`);
      _club = data; renderClubNews(data.news || []);
    } catch (e) {
      btn.disabled = false; btn.textContent = "Post";
      back.querySelector("#cn-err").textContent = "Error: " + e;
    }
  };
}
function openClubManage() {
  const c = _club;
  const back = _overlay(
    `<h3 class="modal-title">Manage ${esc(c.name)}</h3>` +
    `<label class="cred-field"><span>Description</span><input id="cm-desc" type="text" value="${esc(c.description || "")}"></label>` +
    `<label class="cred-field"><span>Leader email</span><input id="cm-leader" type="email" value="${esc(c.leader_email || "")}"></label>` +
    `<label class="cred-field"><span>Teacher email</span><input id="cm-teacher" type="email" value="${esc(c.teacher_email || "")}"></label>` +
    `<label class="cred-field"><span>Schedule</span><input id="cm-sched" type="text" value="${esc(c.schedule || "")}"></label>` +
    `<label class="cred-field"><span>Upload club image</span><input id="cm-file" type="file" accept="image/png,image/jpeg,image/webp,image/gif"></label>` +
    (c.image_url ? `<div class="muted">Current: ${clubImgHtml(c.image_url, "club-manage-preview")}</div>` : "") +
    `<label class="cred-field"><span>Or external image URL</span><input id="cm-img" type="text" placeholder="https://…"></label>` +
    `<label class="cred-field"><span>Access code</span><input id="cm-code" type="text" value="${esc(c.access_code || "")}"></label>` +
    `<div class="modal-err muted" id="cm-err"></div>` +
    `<div class="modal-actions"><button type="button" class="btn" data-cancel>Cancel</button>` +
    `<button type="button" class="btn" data-save>Save</button></div>`);
  back.querySelector("[data-cancel]").onclick = () => back.remove();
  back.querySelector("[data-save]").onclick = async () => {
    const payload = {
      description: back.querySelector("#cm-desc").value,
      leader_email: back.querySelector("#cm-leader").value.trim(),
      teacher_email: back.querySelector("#cm-teacher").value.trim(),
      schedule: back.querySelector("#cm-sched").value,
      image_url: back.querySelector("#cm-img").value.trim(),
      access_code: back.querySelector("#cm-code").value,
    };
    try {
      const r = await postJSON(`/api/clubs/${c.id}/update`, payload);
      const imgFile = back.querySelector("#cm-file").files[0];
      if (imgFile) await uploadClubImage(c.id, imgFile);
      _club = Object.assign(_club, r.club, { can_manage: true, access_code: payload.access_code, news: _club.news });
      back.remove();
      renderClubPortal(document.getElementById("club-root"), _club);
    } catch (e) { back.querySelector("#cm-err").textContent = "Error: " + e; }
  };
}
async function loadClubChat(initial) {
  const box = document.getElementById("club-messages");
  if (!box) return;
  let data;
  try { data = await getJSON(`/api/clubs/${_club.id}/chat?after=${_clubChatLast}`); }
  catch (e) { return; }
  const msgs = data.messages || [];
  if (!msgs.length && initial) { box.innerHTML = `<div class="muted">No messages yet. Say hello.</div>`; return; }
  if (initial) box.innerHTML = "";
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  msgs.forEach(m => { box.appendChild(chatBubble(m)); _clubChatLast = Math.max(_clubChatLast, m.id); });
  if (initial || atBottom) box.scrollTop = box.scrollHeight;
}
function chatBubble(m) {
  const el = document.createElement("div");
  el.className = "chat-bubble" + (m.is_teacher ? " chat-teacher" : "");
  const tag = m.is_teacher ? `<span class="teacher-badge">Teacher</span>` : "";
  el.innerHTML = `<div class="chat-bubble-head"><span class="chat-user">${esc(m.username)}</span>${tag}` +
    `<span class="chat-time">${esc(fmtWhen(m.created_at))}</span></div>` +
    `<div class="chat-bubble-body">${esc(m.content)}</div>`;
  return el;
}
async function sendClubChat() {
  const inp = document.getElementById("club-chat-text");
  const text = (inp.value || "").trim();
  if (!text) return;
  try {
    const r = await postJSON(`/api/clubs/${_club.id}/chat/send`, { content: text });
    inp.value = "";
    if (r.message) {
      const box = document.getElementById("club-messages");
      const empty = box.querySelector(".muted");
      if (empty) empty.remove();
      box.appendChild(chatBubble(r.message));
      _clubChatLast = Math.max(_clubChatLast, r.message.id);
      box.scrollTop = box.scrollHeight;
    }
  } catch (e) {
    await handleChatError(e);
  }
}

// ===================================================================
// COMMUNITY — School chat
// ===================================================================
let _scRoom = "all";
let _scLast = 0;
let _scTimer = null;
let _scQuery = "";
async function initSchoolChat() {
  renderSidebar("/community");
  const root = document.getElementById("school-chat-root");
  if (!root) return;
  let data;
  try { data = await getJSON("/api/school-chat?room=all"); } catch (e) { data = {}; }
  if (data.enabled === false) {
    root.innerHTML = `<div class="muted">School chat is currently turned off by an administrator.</div>`;
    return;
  }
  const rooms = data.rooms || ["all"];
  root.innerHTML =
    `<div class="chat-rooms" id="sc-rooms">` +
    rooms.map(r => `<button type="button" class="ann-tab${r === "all" ? " active" : ""}" data-room="${esc(r)}">${r === "all" ? "Whole school" : "Grade " + esc(r)}</button>`).join("") +
    `</div>` +
    `<div class="chat-search"><input type="text" id="sc-search" placeholder="Search messages…" autocomplete="off"></div>` +
    `<div class="chat-box" id="sc-messages"></div>` +
    `<div class="chat-input"><input type="text" id="sc-text" placeholder="Message…" autocomplete="off">` +
    `<button type="button" id="sc-send">Send</button></div>`;
  document.querySelectorAll("#sc-rooms [data-room]").forEach(b => b.onclick = () => {
    _scRoom = b.dataset.room;
    document.querySelectorAll("#sc-rooms [data-room]").forEach(x => x.classList.toggle("active", x === b));
    _scLast = 0;
    loadSchoolChat(true);
  });
  const search = document.getElementById("sc-search");
  search.addEventListener("input", () => { _scQuery = search.value.trim(); _scLast = 0; loadSchoolChat(true); });
  document.getElementById("sc-send").onclick = sendSchoolChat;
  document.getElementById("sc-text").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); sendSchoolChat(); } });
  await loadSchoolChat(true);
  if (_scTimer) clearInterval(_scTimer);
  _scTimer = setInterval(() => { if (!_scQuery) loadSchoolChat(false); }, 4000);
}
async function loadSchoolChat(initial) {
  const box = document.getElementById("sc-messages");
  if (!box) return;
  const qs = new URLSearchParams({ room: _scRoom, after: String(_scLast) });
  if (_scQuery) qs.set("q", _scQuery);
  let data;
  try { data = await getJSON(`/api/school-chat?${qs.toString()}`); } catch (e) { return; }
  const msgs = data.messages || [];
  if (initial) box.innerHTML = msgs.length ? "" : `<div class="muted">${_scQuery ? "No matching messages." : "No messages yet."}</div>`;
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  msgs.forEach(m => { box.appendChild(chatBubble(m)); if (!_scQuery) _scLast = Math.max(_scLast, m.id); });
  if (initial || atBottom) box.scrollTop = box.scrollHeight;
}
async function sendSchoolChat() {
  const inp = document.getElementById("sc-text");
  const text = (inp.value || "").trim();
  if (!text) return;
  try {
    const r = await postJSON("/api/school-chat/send", { room: _scRoom, content: text });
    inp.value = "";
    if (r.message && !_scQuery) {
      const box = document.getElementById("sc-messages");
      const empty = box.querySelector(".muted");
      if (empty) empty.remove();
      box.appendChild(chatBubble(r.message));
      _scLast = Math.max(_scLast, r.message.id);
      box.scrollTop = box.scrollHeight;
    }
  } catch (e) {
    await handleChatError(e);
  }
}

// Shared: handle 422 profanity + 400 need_username from chat sends.
async function handleChatError(e) {
  const msg = String(e && e.message || e);
  // postJSON throws with status + body text; detect our flags in the body.
  if (msg.includes("422") || msg.toLowerCase().includes("noted and will be reported")) {
    showProfanityWarning("Your behavior is noted and will be reported");
    return;
  }
  if (msg.includes("need_username") || msg.includes("Set a chat username")) {
    let suggested = "";
    try { const p = await getJSON("/api/community/profile"); suggested = p.suggested || ""; } catch (_) {}
    const name = await ensureChatUsername(suggested);
    if (name) showInfoModal("Username set", "Your username is set. Send your message again.");
    return;
  }
  showInfoModal("Could not send", msg);
}

// ===================================================================
// PLATFORM CONFIG (admin)
// ===================================================================
async function initPlatformConfig() {
  renderSidebar("/platform-config");
  const root = document.getElementById("platform-root");
  if (!root) return;
  let acct = {};
  try { acct = await getJSON("/api/account"); } catch (e) {}
  if (!acct.is_admin) {
    root.innerHTML = `<div class="muted">This page is for administrators only.</div>`;
    return;
  }
  let cfg = {};
  try { cfg = await getJSON("/api/platform/config"); } catch (e) {}
  renderPlatformConfig(root, cfg);
  await initAdminCredentials();
}
function renderPlatformConfig(root, cfg) {
  const j = cfg.journal || {};
  root.innerHTML =
    `<div class="section-h">COMMUNITY CONTROLS</div>` +
    `<div class="settings-row"><div class="row-head">` +
    `<label class="cred-check"><input type="checkbox" id="pc-chat" ${cfg.school_chat_enabled ? "checked" : ""}> School chat enabled</label>` +
    `<button type="button" class="btn" id="pc-chat-save">Save</button></div></div>` +

    `<div class="cred-group"><div class="section-h">TEACHER IDENTITY</div>` +
    `<label class="cred-field"><span>Teacher email domain (messages from this domain are highlighted)</span>` +
    `<input id="pc-domain" type="text" value="${esc(cfg.teacher_email_domain || "")}"></label>` +
    `<button type="button" class="btn" id="pc-domain-save">Save domain</button></div>` +

    `<div class="cred-group"><div class="section-h">BHS NEWS (YOUTUBE)</div>` +
    `<label class="cred-field"><span>Channel URL</span><input id="pc-channel" type="text" value="${esc(cfg.bhs_news_channel_url || "")}"></label>` +
    `<label class="cred-field"><span>Pin a specific video (URL or ID — optional, overrides latest)</span>` +
    `<input id="pc-video" type="text" value="${esc(cfg.bhs_news_video_manual || "")}"></label>` +
    `<div class="muted">Current video: ${cfg.news && cfg.news.video_id ? esc(cfg.news.video_id) : "none resolved"}</div>` +
    `<div class="row-actions" style="margin-top:8px"><button type="button" class="btn" id="pc-news-save">Save</button>` +
    `<button type="button" class="btn" id="pc-news-refresh">Refresh latest</button></div></div>` +

    `<div class="cred-group"><div class="section-h">BHS JOURNAL (PDF)</div>` +
    `<div class="muted">${j.available ? "A journal is uploaded." : "No journal uploaded."} ${j.available ? `<a href="${esc(j.file_url)}" target="_blank" rel="noopener">View →</a>` : ""}</div>` +
    `<label class="cred-field"><span>Title</span><input id="pc-journal-title" type="text" value="${esc(j.title || "BHS Journal")}"></label>` +
    `<label class="cred-field"><span>Upload PDF</span><input id="pc-journal-file" type="file" accept="application/pdf,.pdf"></label>` +
    `<button type="button" class="btn" id="pc-journal-save">Save journal</button>` +
    `<div class="muted" id="pc-journal-status"></div></div>` +

    // Year-at-a-glance calendar overview image
    `<div class="cred-group"><div class="section-h">CALENDAR · YEAR OVERVIEW</div>` +
    `<div class="muted">${(cfg.calendar_overview && cfg.calendar_overview.available) ? `Uploaded. <a href="${esc(cfg.calendar_overview.file_url)}" target="_blank" rel="noopener">View →</a>` : "No year overview uploaded."} Shown on the Calendar via the “Year overview” button.</div>` +
    `<label class="cred-field"><span>Upload image or PDF (year-at-a-glance)</span><input id="pc-cal-file" type="file" accept="image/png,image/jpeg,image/webp,image/gif,application/pdf,.pdf"></label>` +
    `<button type="button" class="btn" id="pc-cal-save">Save overview</button>` +
    `<div class="muted" id="pc-cal-status"></div></div>` +

    // Admin management — owner only
    (cfg.is_owner ? (
      `<div class="cred-group"><div class="section-h">ADMINISTRATORS</div>` +
      `<p class="muted">Only you (the platform owner) can add or remove admins. Admins can manage community settings; they cannot manage admins or wipe data.</p>` +
      `<div id="pc-admin-list">${_adminListHtml(cfg.admins || [])}</div>` +
      `<label class="cred-field"><span>Add admin by email</span><input id="pc-admin-email" type="email" placeholder="name@example.com"></label>` +
      `<button type="button" class="btn" id="pc-admin-add">Add admin</button>` +
      `<div class="muted" id="pc-admin-status"></div></div>`
    ) : "") +

    `<div id="admin-creds-section" class="admin-creds-panel">` +
    `<div class="section-h">ADMIN — SHARED SERVER CREDENTIALS</div>` +
    `<p class="muted" id="admin-creds-note">Twilio, Cerebras, Google OAuth app and webhook (admin only).</p>` +
    `<div id="admin-creds-status" class="login-status muted"></div>` +
    `<form id="admin-creds-form" class="cred-form"></form>` +
    `<div class="login-actions"><button type="button" class="btn" id="admin-save-btn">Save admin credentials</button></div></div>` +

    // Danger zone — owner only
    (cfg.is_owner ? (
      `<div class="cred-group danger-zone"><div class="section-h">DANGER ZONE</div>` +
      `<p class="muted">Permanently delete <strong>all</strong> clubs, club news & chats, school chat, in-app notifications and AI conversations for <strong>every</strong> user. This cannot be undone and is available only to you.</p>` +
      `<button type="button" class="btn danger-btn" id="pc-wipe-btn">Clear all clubs, chats & notifications</button>` +
      `<div class="muted" id="pc-wipe-status"></div></div>`
    ) : "");

  document.getElementById("pc-chat-save").onclick = async () => {
    await postJSON("/api/platform/config", { school_chat_enabled: document.getElementById("pc-chat").checked });
    showInfoModal("Saved", "School chat setting updated.");
  };
  document.getElementById("pc-domain-save").onclick = async () => {
    await postJSON("/api/platform/config", { teacher_email_domain: document.getElementById("pc-domain").value.trim() });
    showInfoModal("Saved", "Teacher domain updated.");
  };
  document.getElementById("pc-news-save").onclick = async () => {
    await postJSON("/api/platform/config", {
      bhs_news_channel_url: document.getElementById("pc-channel").value.trim(),
      bhs_news_video_manual: document.getElementById("pc-video").value.trim(),
      refresh_news: true,
    });
    const c = await getJSON("/api/platform/config");
    renderPlatformConfig(root, c); await initAdminCredentials();
  };
  document.getElementById("pc-news-refresh").onclick = async () => {
    await postJSON("/api/platform/config", { refresh_news: true });
    const c = await getJSON("/api/platform/config");
    renderPlatformConfig(root, c); await initAdminCredentials();
  };
  document.getElementById("pc-journal-save").onclick = async () => {
    const st = document.getElementById("pc-journal-status");
    const fd = new FormData();
    fd.append("title", document.getElementById("pc-journal-title").value.trim());
    const f = document.getElementById("pc-journal-file").files[0];
    if (f) fd.append("file", f);
    st.textContent = "Saving…";
    try {
      const r = await fetch("/api/community/journal/upload", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      st.textContent = "Saved.";
    } catch (e) { st.textContent = "Error: " + e; }
  };
  const calSave = document.getElementById("pc-cal-save");
  if (calSave) calSave.onclick = async () => {
    const st = document.getElementById("pc-cal-status");
    const f = document.getElementById("pc-cal-file").files[0];
    if (!f) { st.textContent = "Choose a file first."; return; }
    const fd = new FormData(); fd.append("file", f);
    st.textContent = "Saving…";
    try {
      const r = await fetch("/api/calendar/overview/upload", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      st.textContent = "Saved. Visible on the Calendar → Year overview.";
    } catch (e) { st.textContent = "Error: " + e; }
  };
  const adminAdd = document.getElementById("pc-admin-add");
  if (adminAdd) adminAdd.onclick = () => addAdmin();
  const wipeBtn = document.getElementById("pc-wipe-btn");
  if (wipeBtn) wipeBtn.onclick = () => wipeEverything();
}

function _adminListHtml(admins) {
  if (!admins.length) return `<div class="muted">No admins.</div>`;
  return `<ul class="admin-list">` + admins.map((e, i) =>
    `<li class="admin-list-item"><span>${esc(e)}${i === 0 ? ' <span class="club-tag">Owner</span>' : ""}</span>` +
    (i === 0 ? "" : `<button type="button" class="link-btn" onclick="removeAdmin('${esc(e)}')">remove</button>`) +
    `</li>`).join("") + `</ul>`;
}
async function _refreshAdminList() {
  try {
    const r = await getJSON("/api/platform/config");
    const el = document.getElementById("pc-admin-list");
    if (el) el.innerHTML = _adminListHtml(r.admins || []);
  } catch (e) { /* ignore */ }
}
async function addAdmin() {
  const inp = document.getElementById("pc-admin-email");
  const st = document.getElementById("pc-admin-status");
  const email = (inp.value || "").trim();
  if (!email) { st.textContent = "Enter an email."; return; }
  st.textContent = "Adding…";
  try {
    await postJSON("/api/platform/admins", { action: "add", email });
    inp.value = ""; st.textContent = "Added " + email + ".";
    await _refreshAdminList();
  } catch (e) { st.textContent = "Error: " + e; }
}
async function removeAdmin(email) {
  if (!confirm("Remove admin " + email + "?")) return;
  const st = document.getElementById("pc-admin-status");
  try {
    await postJSON("/api/platform/admins", { action: "remove", email });
    if (st) st.textContent = "Removed " + email + ".";
    await _refreshAdminList();
  } catch (e) { if (st) st.textContent = "Error: " + e; }
}
async function wipeEverything() {
  const st = document.getElementById("pc-wipe-status");
  if (!confirm("DANGER (1/3): Permanently delete ALL clubs, club news & chats, school chat, notifications and AI conversations for EVERY user?")) return;
  if (!confirm("Are you absolutely sure? (2/3) This cannot be undone.")) return;
  const back = _overlay(
    `<h3 class="modal-title" style="color:var(--priority-high)">Final confirmation (3/3)</h3>` +
    `<p class="modal-msg">Type <strong>WIPE</strong> to permanently clear all community data for every user.</p>` +
    `<input id="wipe-input" type="text" placeholder="WIPE" autocomplete="off">` +
    `<div class="modal-err muted" id="wipe-err"></div>` +
    `<div class="modal-actions"><button type="button" class="btn" data-cancel>Cancel</button>` +
    `<button type="button" class="btn danger-btn" data-go>Wipe everything</button></div>`);
  back.querySelector("[data-cancel]").onclick = () => back.remove();
  back.querySelector("[data-go]").onclick = async () => {
    const val = (back.querySelector("#wipe-input").value || "").trim();
    if (val.toUpperCase() !== "WIPE") { back.querySelector("#wipe-err").textContent = 'Type "WIPE" exactly.'; return; }
    try {
      const r = await postJSON("/api/platform/wipe", { confirm: val });
      back.remove();
      const cleared = r.cleared || {};
      const total = Object.values(cleared).reduce((a, b) => a + (b || 0), 0);
      if (st) st.textContent = `Done. Removed ${total} records.`;
      showInfoModal("Wiped", "All community data has been cleared for every user.");
      refreshNavUnread();
    } catch (e) { back.querySelector("#wipe-err").textContent = "Error: " + e; }
  };
}
