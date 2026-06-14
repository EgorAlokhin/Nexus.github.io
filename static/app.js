const THEME_KEY = "nexus-theme";
const SKIN_KEY = "nexus-skin";

function initTheme() {
  const t = localStorage.getItem(THEME_KEY) || "light";
  document.documentElement.setAttribute("data-theme", t);
  const skin = localStorage.getItem(SKIN_KEY) || "fresh";
  document.documentElement.setAttribute("data-skin", skin);
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem(THEME_KEY, next);
  const btn = document.getElementById("theme-btn");
  if (btn) btn.textContent = next === "dark" ? "Light" : "Dark";
}
function currentSkin() {
  return document.documentElement.getAttribute("data-skin") || "fresh";
}
function toggleSkin() {
  const next = currentSkin() === "fresh" ? "classic" : "fresh";
  document.documentElement.setAttribute("data-skin", next);
  localStorage.setItem(SKIN_KEY, next);
  const btn = document.getElementById("skin-btn");
  if (btn) btn.textContent = next === "fresh" ? "Classic look" : "Fresh look";
}
initTheme();

const NAV = [["/", "Dashboard"], ["/calendar", "Calendar"], ["/library", "Library"], ["/materials", "Materials"],
  ["/announcements", "Announcements"], ["/completed", "Completed"], ["/chat", "Chat"], ["/notifications", "Notifications"],
  ["/account", "Account"], ["/settings", "Settings"]];
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

function renderSidebar(active) {
  const el = document.getElementById("sidebar");
  if (!el) return;
  ensureNavChrome();
  const cur = document.documentElement.getAttribute("data-theme");
  const label = cur === "dark" ? "Light" : "Dark";
  const links = NAV.map(([href, name]) =>
    `<a href="${href}" class="${href === active ? "active" : ""}" onclick="closeNav()">${name}</a>`).join("");
  el.innerHTML = `<div class="brand">NEXUS</div><nav>${links}</nav>` +
    `<div class="sidebar-footer">` +
      `<div class="acct-line" id="sidebar-acct"></div>` +
      `<div class="sidebar-controls">` +
        `<button id="theme-btn" onclick="toggleTheme()">${label}</button>` +
        `<a class="btn" href="/logout">Sign out</a>` +
      `</div>` +
    `</div>`;
  loadSidebarAccount();
}
async function loadSidebarAccount() {
  try {
    const a = await getJSON("/api/account");
    const el = document.getElementById("sidebar-acct");
    if (!el) return;
    const who = (a && (a.email || a.username)) || "";
    el.textContent = who;
    el.title = who;
  } catch (e) { /* not signed in */ }
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
    `<summary class="course-head">` +
      `<span class="course-name">${esc(c.name)}</span>` +
      `<span class="course-head-right">${grade}` +
      `<span class="course-open">${c.open_count} open</span></span>` +
    `</summary>` +
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

async function initCalendar() {
  renderSidebar("/calendar");
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
  const title = document.getElementById("detail-title");
  const hint = document.getElementById("detail-hint");
  const body = document.getElementById("detail-body");
  const collapseBtn = document.getElementById("detail-collapse-btn");
  if (title) title.textContent = new Date(y, m, day).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  if (hint) hint.textContent = `${items.length} task${items.length === 1 ? "" : "s"}`;
  if (body) body.innerHTML = items.length ? items.map(_taskDetailHtml).join("") : '<div class="muted">No tasks this day.</div>';
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
  let cells = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(d => `<div class="dow">${d}</div>`).join("");
  for (let i = 0; i < startDow; i++) cells += `<div class="cal-cell empty"></div>`;
  for (let day = 1; day <= days; day++) {
    const all = _calByDay[day] || [];
    const busy = all.length > CAL_PREVIEW;
    const preview = all.slice(0, CAL_PREVIEW);
    const taskHtml = preview.map(_calTaskHtml).join("");
    const more = busy
      ? `<button type="button" class="cal-more" onclick="event.stopPropagation();showCalDay(${y},${m},${day})">+${all.length - CAL_PREVIEW} more</button>`
      : "";
    const isToday = y === today.getFullYear() && m === today.getMonth() && day === today.getDate();
    const cellClass = "cal-cell" + (busy ? " cal-busy" : "") + (isToday ? " cal-today" : "");
    const openDay = busy ? `onclick="showCalDay(${y},${m},${day})"` : "";
    cells += `<div class="${cellClass}" ${openDay}><span class="num">${day}</span>${taskHtml}${more}</div>`;
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
function initChat() {
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
  const welcome = document.querySelector("#messages .msg.assistant");
  if (welcome) {
    welcome.classList.add("chat-md");
    welcome.innerHTML = renderChatMarkdown(
      "Nexus ready. Attach a file or ask about deadlines, workload, or math. " +
      "Model: **GPT-OSS (quick)** → **GPT-OSS (deep)** → **GLM-4.7 (advanced)**."
    );
    typesetChat(welcome);
  }
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
    if (file) fd.append("file", file);
    const r = await fetch("/ai/chat", { method: "POST", body: fd });
    if (!r.ok) throw new Error(r.status + " " + r.statusText);
    const data = await r.json();
    thinking.remove();
    addMsg("assistant", data.response || "(no response)");
    const badge = document.getElementById("model-badge");
    if (badge && data.tier) badge.textContent = "model: " + data.tier;
    if (fileInp) { fileInp.value = ""; const fn = document.getElementById("file-name"); if (fn) fn.textContent = ""; }
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
  setAuthMode("login");
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

  const adminSection = document.getElementById("admin-creds-section");
  const adminNote = document.getElementById("admin-creds-note");
  if (adminSection) {
    if (account.is_admin) {
      adminSection.style.display = "block";
      if (adminNote && account.email) {
        adminNote.textContent = `Signed in as ${account.email}. Twilio, Cerebras, and Google OAuth app settings below.`;
      }
      await initAdminCredentials();
    } else {
      adminSection.style.display = "none";
    }
  }
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

// ---------- SETTINGS ----------
async function initSettings() {
  renderSidebar("/settings");
  const params = new URLSearchParams(location.search);
  const banner = document.getElementById("oauth-banner");
  if (banner) {
    if (params.get("oauth") === "ok" && params.get("scopes") !== "missing") {
      banner.style.display = "block";
      banner.className = "oauth-banner ok";
      banner.textContent = "Google connected successfully.";
    } else if (params.get("oauth") === "ok" && params.get("scopes") === "missing") {
      banner.style.display = "block";
      banner.className = "oauth-banner err";
      banner.textContent =
        "Google connected, but some Classroom permissions were not granted. Disconnect, then Connect again and accept ALL checkboxes.";
    } else if (params.get("oauth_error")) {
      banner.style.display = "block";
      banner.className = "oauth-banner err";
      banner.textContent = "Google OAuth failed: " + params.get("oauth_error");
    }
  }
  const [s, account] = await Promise.all([
    getJSON("/api/status"),
    getJSON("/api/account"),
  ]);
  if (banner && s.google_needs_reconnect && params.get("oauth") !== "ok") {
    banner.style.display = "block";
    banner.className = "oauth-banner err";
    banner.textContent =
      "Missing Google Classroom permissions. Disconnect Google, then Connect again and accept ALL permission checkboxes.";
  }
  const g = s.gmail && s.gmail.connected;
  const gs = document.getElementById("google-status");
  const ge = document.getElementById("google-email");
  const connectBtn = document.getElementById("google-connect-btn");
  const disconnectBtn = document.getElementById("google-disconnect-btn");
  if (gs) {
    gs.innerHTML = g
      ? '<span class="dot on">●</span> Connected'
      : '<span class="dot off">○</span> Not connected';
  }
  if (ge) {
    if (account.email) {
      ge.textContent = "Signed in as " + account.email
        + (account.google_missing_scopes && account.google_missing_scopes.length
          ? " · missing permissions — disconnect and reconnect"
          : "");
    } else {
      ge.textContent = g
        ? "Connected (email unknown — try Disconnect, then Connect again)"
        : "Not signed in. Each Google account must be added as a test user in Google Cloud Console while the app is in Testing mode.";
    }
  }
  if (connectBtn) connectBtn.textContent = g ? "Switch Google account" : "Connect Google";
  if (disconnectBtn) disconnectBtn.hidden = !g;
  ["gmail", "classroom", "buzz", "veracross"].forEach(k => {
    const c = s[k] || {};
    const el = document.getElementById("st-" + k);
    if (el) el.innerHTML = `${c.connected ? '<span class="dot on">●</span>' : '<span class="dot off">○</span>'} ` +
      `${c.count || 0} tasks · sync: ${c.last_sync ? fmtDate(c.last_sync) : "never"}`;
  });
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

async function initNotifications() {
  renderSidebar("/notifications");
  const [prefs, msgSt] = await Promise.all([
    getJSON("/api/notifications/prefs"),
    getJSON("/api/messaging/status"),
  ]);
  const box = document.getElementById("sms-status-box");
  if (box) {
    const ok = msgSt.sms_ready ? '<span class="dot on">●</span> SMS configured' : '<span class="dot off">○</span> SMS not ready';
    const reply = msgSt.reply_enabled ? "Webhook: set" : "Webhook: add Public HTTPS URL on Your account";
    let html = `<div>${ok} · ${reply}</div>` +
      `<div class="muted">School number: ${esc(msgSt.sms_from || "—")} · Your phone: ${esc(msgSt.your_phone || "—")}` +
      `${msgSt.your_name ? " (" + esc(msgSt.your_name) + ")" : ""}</div>`;
    if (msgSt.last_sms_error_hint) {
      html += `<div class="muted" style="color:var(--danger,#c44)">Last SMS error: ${esc(msgSt.last_sms_error_hint)}</div>`;
    }
    if (msgSt.hint) html += `<div class="muted">${esc(msgSt.hint)}</div>`;
    box.innerHTML = html;
  }
  NOTIFY_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!prefs[id];
    else el.value = prefs[id];
  });
  const ch = document.getElementById("notification_channel");
  if (ch) {
    ch.value = prefs.notification_channel || "sms";
    ch.onchange = updateChannelHint;
    updateChannelHint();
  }
  document.getElementById("notify-save").onclick = saveNotifications;
  document.getElementById("notify-test").onclick = testNotification;
}

async function saveNotifications() {
  const status = document.getElementById("notify-status");
  const chEl = document.getElementById("notification_channel");
  const body = { notification_channel: chEl ? chEl.value : "sms" };
  NOTIFY_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    body[id] = el.type === "checkbox" ? el.checked : parseInt(el.value, 10);
  });
  status.textContent = "Saving…";
  try {
    await postJSON("/api/notifications/prefs", body);
    status.textContent = "Saved. Scheduler updated.";
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

async function testNotification() {
  const status = document.getElementById("notify-status");
  status.textContent = "Sending test…";
  try {
    const r = await postJSON("/api/notifications/test");
    status.textContent = r.ok ? r.detail : ("Failed: " + (r.detail || "unknown"));
  } catch (e) {
    status.textContent = "Error: " + e;
  }
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
