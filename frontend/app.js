/* NewtonEDMS SPA. */
const api = (path) => (path.startsWith("/api") ? path : `/api${path.startsWith("/") ? "" : "/"}${path}`);
const FETCH_OPTS = { credentials: "same-origin" };

let currentUser = null;
let currentFolderId = null;
let currentDocId = null;
let currentDoc = null;
let currentNav = "home";
let folders = [];
let contacts = [];
let peopleTab = "contacts";
let tagsCatalog = [];
let customFields = [];
let selectedIds = new Set();
let lastDocs = [];
let lastTitle = "Documents";
let lastSub = "";
let previewUrl = null;
let gridView = "list";
let pageSize = 50;
let pageOffset = 0;
const GRID_COLS = { title: true, file: true, size: true, ver: true, status: true, folder: true, date: true, rating: false, pages: false };

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}
const val = (id) => document.getElementById(id).value;
const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
  bindSplitters();
  bootstrap();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeInspector();
    closeDrops();
    return;
  }
  const tag = (e.target && e.target.tagName) || "";
  const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target && e.target.isContentEditable);
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  const inApp = $("app-shell") && !$("app-shell").classList.contains("is-hidden");
  if (!inApp) return;
  if (e.key === "/") {
    e.preventDefault();
    const s = $("search-input");
    if (s) s.focus();
  } else if (e.key === "u" || e.key === "U") {
    e.preventDefault();
    openUploadModal();
  }
});

async function apiFetch(path, opts = {}) {
  const headers = { Accept: "application/json", ...(opts.headers || {}) };
  const resp = await fetch(api(path), { ...opts, headers, ...FETCH_OPTS });
  if (resp.status === 401) { showLogin(); return null; }
  if (!resp.ok) throw new Error(await resp.text());
  const ct = resp.headers.get("content-type") || "";
  if (!ct.includes("json")) return {};
  return resp.json().catch(() => ({}));
}

function show(id, v) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle("is-hidden", !v);
  el.classList.remove("hidden");
  el.style.display = "";
}

const DASH_NAVS = ["home", "calendar", "tasks", "contacts", "settings", "messages"];

function productTabOf(nav) {
  if (nav === "admin") return "admin";
  if (nav === "search") return "search";
  if (DASH_NAVS.includes(nav)) return "dashboard";
  return "documents";
}

function layoutShell() {
  const body = $("app-body");
  if (!body) return;
  const tab = productTabOf(currentNav);
  body.dataset.layout = tab;
  const docsLike = tab === "documents" || tab === "search";
  show("left-pane", docsLike);
  show("split-left", docsLike);
  show("docs-stack", tab === "documents");
  show("search-stack", tab === "search");
  show("dash-tabs", tab === "dashboard");
  show("admin-nav", tab === "admin");
  show("split-admin", tab === "admin");
  const insp = docsLike && !!currentDocId;
  body.classList.toggle("has-inspector", insp);
  show("inspector", insp);
  show("split-insp", insp);
  document.querySelectorAll(".ptab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".dtab").forEach((b) => b.classList.toggle("active", b.dataset.dash === currentNav));
  updateStatus();
}

function updateStatus() {
  const su = $("status-user");
  const sf = $("status-folder");
  const sc = $("status-count");
  if (su && currentUser) su.textContent = currentUser.username;
  if (sf) sf.textContent = currentFolderId ? folderName(currentFolderId) : "";
  if (sc) sc.textContent = lastDocs.length ? `${lastDocs.length} document(s)` : "";
}

function openSection(stackId, name) {
  const stack = $(stackId);
  if (!stack) return;
  stack.querySelectorAll(".section").forEach((sec) => {
    const open = sec.dataset.sec === name;
    sec.classList.toggle("open", open);
    const icon = sec.querySelector(".section-h i");
    if (icon) icon.className = open ? "fa-solid fa-caret-down" : "fa-solid fa-caret-right";
  });
  if (name === "trash" && typeof loadTrash === "function") loadTrash();
}

function toggleDrop(id) {
  document.querySelectorAll(".drop").forEach((d) => {
    if (d.id !== id) d.classList.remove("open");
  });
  $(id).classList.toggle("open");
}
function closeDrops() {
  document.querySelectorAll(".drop").forEach((d) => d.classList.remove("open"));
  const m = $("ctx-menu");
  if (m) m.classList.remove("open");
}

const INSP_MORE_TABS = new Set(["files", "comments", "links", "history", "aliases", "subscriptions", "folder"]);
function markInspTab(tab) {
  document.querySelectorAll(".insp-tab[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  const moreBtn = $("insp-more-btn");
  if (moreBtn) moreBtn.classList.toggle("active", INSP_MORE_TABS.has(tab));
}

function filterAdminNav(q) {
  q = String(q || "").toLowerCase().trim();
  document.querySelectorAll("#admin-nav .admin-block").forEach((block) => {
    let n = 0;
    block.querySelectorAll(".admin-item").forEach((item) => {
      const show = !q || item.textContent.toLowerCase().includes(q);
      item.classList.toggle("is-hidden", !show);
      if (show) n++;
    });
    block.classList.toggle("is-hidden", n === 0);
    if (q && n) {
      block.classList.remove("collapsed");
      const i = block.querySelector(".admin-group i");
      if (i) i.className = "fa-solid fa-caret-down";
    }
  });
}
function toggleAdminGroup(btn) {
  const block = btn.closest(".admin-block");
  if (!block) return;
  block.classList.toggle("collapsed");
  const i = btn.querySelector("i");
  if (i) i.className = block.classList.contains("collapsed") ? "fa-solid fa-caret-right" : "fa-solid fa-caret-down";
}

function bindSplitters() {
  document.querySelectorAll(".splitter").forEach((el) => {
    el.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const target = el.dataset.target;
      const startX = e.clientX;
      const startLeft = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--left-w"), 10) || 280;
      const startInsp = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--insp-w"), 10) || 360;
      const move = (ev) => {
        const dx = ev.clientX - startX;
        if (target === "left" || target === "admin") {
          const w = Math.min(480, Math.max(180, startLeft + dx));
          document.documentElement.style.setProperty("--left-w", w + "px");
          if (target === "admin") $("admin-nav").style.width = w + "px";
        } else if (target === "insp") {
          const w = Math.min(560, Math.max(240, startInsp - dx));
          document.documentElement.style.setProperty("--insp-w", w + "px");
        }
      };
      const up = () => {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    });
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".drop") && !e.target.closest("#ctx-menu")) closeDrops();
  });
  document.addEventListener("contextmenu", (e) => {
    if (!e.target.closest("#ctx-menu") && !e.target.closest("tr[data-doc]") && !e.target.closest(".tree-item")) {
      const m = $("ctx-menu");
      if (m) m.classList.remove("open");
    }
  });
}

function openModal(id) { $(id).classList.add("open"); }
function closeModal(id) {
  $(id).classList.remove("open");
  $(id).querySelectorAll("p[id$='-err']").forEach((e) => e.classList.add("hidden"));
}

function formatBytes(b) {
  if (!b) return "-";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (b >= 1024 && i < 3) { b /= 1024; i++; }
  return `${b.toFixed(1)} ${u[i]}`;
}
function fmtDate(d) {
  if (!d) return "";
  try { return new Date(d).toLocaleString(); } catch { return d; }
}
function fmtDay(d) {
  if (!d) return "";
  return String(d).slice(0, 10);
}
function statusColor(s) {
  return {
    draft: "bg-gray-200 text-gray-800",
    review: "bg-yellow-200 text-yellow-900",
    approved: "bg-green-200 text-green-900",
    published: "bg-blue-200 text-blue-900",
    archived: "bg-slate-300 text-slate-800",
  }[s] || "bg-gray-100";
}
function procColor(s) {
  return {
    pending: "text-amber-600",
    running: "text-blue-600",
    done: "text-emerald-600",
    error: "text-red-600",
  }[s] || "text-gray-500";
}
function contactName(id) {
  const c = contacts.find((x) => x.id === id);
  return c ? c.name : "";
}
function folderName(id) {
  const f = folders.find((x) => x.id === id);
  return f ? f.name : `#${id}`;
}
function tagHtml(tags) {
  return (tags || "").split(",").map((t) => t.trim()).filter(Boolean)
    .map((t) => `<span class="tag-chip">${esc(t)}</span>`).join("");
}

// ---- Session --------------------------------------------------------------
async function bootstrap() {
  try {
    const sess = await fetch(api("/auth/session"), { ...FETCH_OPTS });
    if (sess.ok) {
      const data = await sess.json();
      if (data.user) { currentUser = data.user; await enterApp(); return; }
    }
  } catch (e) { /* login */ }
  showLogin();
}

const REMEMBER_USER_KEY = "newton_remember_user";
const REMEMBER_PASS_KEY = "newton_remember_pass";

function applyRememberedLogin() {
  const remember = $("remember-password");
  const userEl = $("username");
  const passEl = $("password");
  if (!userEl) return;
  try {
    const u = localStorage.getItem(REMEMBER_USER_KEY) || "";
    const p = localStorage.getItem(REMEMBER_PASS_KEY) || "";
    if (u) {
      userEl.value = u;
      if (remember) remember.checked = true;
    }
    if (p && passEl) passEl.value = p;
  } catch (e) { /* private mode */ }
}

function persistRememberedLogin() {
  const remember = $("remember-password") && $("remember-password").checked;
  try {
    if (remember) {
      localStorage.setItem(REMEMBER_USER_KEY, val("username"));
      localStorage.setItem(REMEMBER_PASS_KEY, val("password"));
    } else {
      localStorage.removeItem(REMEMBER_USER_KEY);
      localStorage.removeItem(REMEMBER_PASS_KEY);
    }
  } catch (e) { /* private mode */ }
}

async function login() {
  const form = new URLSearchParams();
  form.append("username", val("username"));
  form.append("password", val("password"));
  const remember = $("remember-password") && $("remember-password").checked;
  form.append("remember", remember ? "1" : "0");
  const totpEl = $("totp");
  const headers = {};
  if (totpEl && totpEl.value) headers["X-TOTP"] = totpEl.value;
  try {
    const res = await fetch(api("/auth/login"), { method: "POST", body: form, headers, ...FETCH_OPTS });
    if (res.status === 403) {
      const body = await res.text();
      if (body.includes("totp_required")) {
        totpEl.classList.remove("hidden");
        totpEl.focus();
        throw new Error("Enter your authenticator code");
      }
    }
    if (!res.ok) throw new Error((await res.text()) || "Login failed");
    persistRememberedLogin();
    const me = await fetch(api("/auth/me"), { ...FETCH_OPTS });
    currentUser = await me.json();
    await enterApp();
  } catch (e) {
    const err = $("login-err");
    err.textContent = e.message;
    err.classList.remove("hidden");
  }
}

async function logout() {
  try { await fetch(api("/auth/logout"), { method: "POST", ...FETCH_OPTS }); } catch (e) { /* ignore */ }
  currentUser = null;
  currentFolderId = null;
  currentDocId = null;
  showLogin();
}

async function enterApp() {
  applyTheme(currentUser.theme || "light");
  document.body.classList.add("in-app");
  show("login-view", false);
  show("app-shell", true);
  $("user-info").textContent = currentUser.username;
  const chip = $("user-chip");
  if (chip) {
    chip.title = currentUser.role || "";
    const av = chip.querySelector(".avatar-dot");
    if (av) av.textContent = String(currentUser.username || "?").slice(0, 1).toUpperCase();
  }
  show("admin-btn", ["superadmin", "admin"].includes(currentUser.role));
  try {
    await Promise.all([loadFolderTree(), loadCatalog()]);
  } catch (e) { console.error(e); }
  if (typeof loadIntel === "function") await loadIntel();
  fillFolderSelect();
  updateNotifBadge();
  navTo("folders");
}

function applyTheme(theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}
async function toggleTheme() {
  const next = document.documentElement.classList.contains("dark") ? "light" : "dark";
  applyTheme(next);
  try {
    await apiFetch("/auth/theme", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: next }),
    });
  } catch (e) { /* ignore */ }
}

function showLogin() {
  document.body.classList.remove("in-app");
  show("app-shell", false);
  show("login-view", true);
  if ($("login-err")) $("login-err").classList.add("hidden");
  applyRememberedLogin();
}

async function loadCatalog() {
  const [c, t, f] = await Promise.all([
    apiFetch("/contacts"),
    apiFetch("/tags"),
    apiFetch("/custom-fields"),
  ]);
  contacts = c || [];
  tagsCatalog = t || [];
  customFields = f || [];
  renderTagCloud();
  renderBookmarks();
  loadFacets();
}

function renderTagCloud() {
  const html = tagsCatalog.length
    ? tagsCatalog.map((t) => `<button class="tag-chip" onclick="runQuery('tag:${esc(t.name)}')">${esc(t.name)}</button>`).join("")
    : '<span style="color:var(--muted)">No tags yet</span>';
  if ($("tag-cloud")) $("tag-cloud").innerHTML = html;
}

async function renderBookmarks() {
  const bms = (await apiFetch("/bookmarks")) || [];
  const openBm = (b) => {
    if (b.kind === "document" && b.resource_id) return `openDoc(${b.resource_id})`;
    if (b.kind === "folder" && b.resource_id) return `selectFolder(${b.resource_id})`;
    const q = esc(b.query || "").replace(/'/g, "\\'");
    return `runQuery('${q}')`;
  };
  const html = bms.length
    ? bms.map((b) => `<div class="flex justify-between gap-1">
        <button class="text-left" onclick="${openBm(b)}">${b.kind && b.kind !== "query" ? `<i class="fa-solid fa-${b.kind === "folder" ? "folder" : "file"}"></i> ` : ""}${esc(b.name)}</button>
        <button onclick="delBookmark(${b.id})"><i class="fa-solid fa-xmark"></i></button>
      </div>`).join("")
    : '<span style="color:var(--muted)">None saved</span>';
  if ($("bookmark-list")) $("bookmark-list").innerHTML = html;
  if ($("saved-list")) $("saved-list").innerHTML = bms.filter((b) => b.kind === "query" || !b.kind).map((b) =>
    `<div class="flex justify-between gap-1"><button onclick="runQuery('${esc(b.query || "").replace(/'/g, "\\'")}')">${esc(b.name)}</button>
     <button onclick="delBookmark(${b.id})"><i class="fa-solid fa-xmark"></i></button></div>`).join("") || '<span style="color:var(--muted)">None saved</span>';
}

function fillFolderSelect() {
  const sel = $("ft-folder");
  if (!sel) return;
  sel.innerHTML = '<option value="">All folders</option>' +
    folders.map((f) => `<option value="${f.id}">${esc(f.name)}</option>`).join("");
}

async function saveCurrentQuery() {
  const q = $("search-input").value.trim();
  if (!q) return alert("Type a query first");
  const name = prompt("Bookmark name", q.slice(0, 40));
  if (!name) return;
  await apiFetch("/bookmarks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, query: q }),
  });
  renderBookmarks();
}
async function delBookmark(id) {
  await apiFetch(`/bookmarks/${id}`, { method: "DELETE" });
  renderBookmarks();
}

async function loadFacets() {
  try {
    const f = await apiFetch("/facets");
    if (!f) return;
    const bits = [];
    Object.entries(f.by_status || {}).forEach(([k, v]) => {
      bits.push(`<button class="block hover:underline" onclick="runQuery('status:${esc(k)}')">${esc(k)} (${v})</button>`);
    });
    Object.entries(f.by_tag || {}).slice(0, 12).forEach(([k, v]) => {
      bits.push(`<button class="block hover:underline" onclick="runQuery('tag:${esc(k)}')">${esc(k)} (${v})</button>`);
    });
    if (f.overdue) bits.push(`<button class="block text-red-600" onclick="runQuery('due:overdue')">overdue (${f.overdue})</button>`);
    $("facet-list").innerHTML = bits.join("") || "No documents yet";
  } catch (e) { /* ignore */ }
}

// ---- Navigation -----------------------------------------------------------
function hideWork() {
  ["work-home", "work-docs", "work-calendar", "work-tasks", "work-contacts", "work-settings", "work-admin", "work-messages"]
    .forEach((id) => show(id, false));
}

async function navTo(name) {
  currentNav = name;
  hideWork();
  if (!["folders", "search", "inbox"].includes(name)) {
    currentDocId = null;
    currentDoc = null;
  }
  layoutShell();
  if (name === "home") { show("work-home", true); await renderDashboard(); }
  else if (name === "inbox") { show("work-docs", true); await loadDocsByQuery("inbox"); }
  else if (name === "search") { show("work-docs", true); await loadDocsByQuery($("search-input").value || $("ft-q")?.value || ""); }
  else if (name === "folders") { show("work-docs", true); await loadDocuments(); }
  else if (name === "calendar") { show("work-calendar", true); await renderCalendar(); }
  else if (name === "tasks") { show("work-tasks", true); await renderTasks(); }
  else if (name === "contacts") { show("work-contacts", true); await renderContacts(); }
  else if (name === "settings") { show("work-settings", true); await renderSettings(); }
  else if (name === "messages") { show("work-messages", true); if (typeof renderMessages === "function") await renderMessages(); }
  else if (name === "admin") { show("work-admin", true); await adminTab("users"); }
}

async function runSearch() {
  const header = $("search-input").value.trim();
  const ft = $("ft-q") ? $("ft-q").value.trim() : "";
  const folder = $("ft-folder") && $("ft-folder").value;
  let q = header || ft;
  if (folder && q && !/\bfolder:/.test(q)) q += ` folder:${folder}`;
  else if (folder && !q) q = `folder:${folder}`;
  if ($("ft-q") && (header || q)) $("ft-q").value = header || ft;
  if (!header && q) $("search-input").value = q;
  hideWork();
  show("work-docs", true);
  currentNav = q ? "search" : "folders";
  layoutShell();
  if (q) await loadDocsByQuery(q);
  else await loadDocuments();
}
function runQuery(q) {
  $("search-input").value = q;
  runSearch();
}

async function updateQueryChips(q) {
  const bar = $("query-bar");
  if (!q) { bar.classList.add("is-hidden"); return; }
  try {
    const parsed = await apiFetch(`/query/parse?q=${encodeURIComponent(q)}`);
    const chips = Object.entries(parsed.filters || {}).map(([k, v]) => `${k}:${JSON.stringify(v)}`).join("  ");
    $("query-chips").textContent = [chips, parsed.fulltext].filter(Boolean).join("  ·  ") || q;
    bar.classList.remove("is-hidden");
  } catch (e) { bar.classList.add("is-hidden"); }
}

// ---- Dashboard ------------------------------------------------------------
async function renderDashboard() {
  let home = { recent: [], overdue: [], inbox: [], jobs: [] };
  let r = null;
  try { home = await apiFetch("/dashboards/home") || home; } catch (e) { /* ignore */ }
  try { r = await apiFetch("/reports/summary"); } catch (e) { /* non-admin */ }
  const card = (title, rows, query) => `
    <div class="dashlet">
      <div class="dashlet-h">${title}${query ? ` <button onclick="runQuery('${query}')">Open</button>` : ""}</div>
      ${rows && rows.length
        ? `<ul>${rows.map((d) => `<li onclick="${d.document_id || d.id ? `openFromDash(${d.document_id || d.id})` : ""}">
            ${esc(d.title || d.kind || "")} <span style="color:var(--muted)">${esc(d.status || "")}</span></li>`).join("")}</ul>`
        : '<p class="empty">Nothing here yet</p>'}</div>`;
  const stats = r ? `
    <div class="stats">
      ${[["Documents", r.documents], ["Folders", r.folders], ["Users", r.users], ["Storage", formatBytes(r.total_size)]].map(([k, v]) =>
        `<div class="stat"><b>${v}</b>${k}</div>`).join("")}
    </div>` : "";
  $("work-home").innerHTML = `
    ${stats}
    <div class="dashlets">
      ${card("Recent documents", home.recent)}
      ${card("Overdue", home.overdue, "due:overdue")}
      ${card("Processing inbox", home.inbox, "inbox")}
      ${card("Processing jobs", home.jobs)}
    </div>
    <div class="dashlet" style="margin-top:10px">
      <div class="dashlet-h">Tag cloud</div>
      <div id="home-tag-cloud" class="p-2"></div>
    </div>`;
  if (typeof fillHomeTagCloud === "function") fillHomeTagCloud();
}

function openFromDash(id) {
  currentNav = "folders";
  hideWork();
  show("work-docs", true);
  openDoc(id);
}

// ---- Folders --------------------------------------------------------------
async function loadFolderTree() {
  folders = (await apiFetch("/folders/all")) || [];
  if (currentFolderId === null) {
    const root = folders.find((f) => f.parent_id === null);
    currentFolderId = root ? root.id : null;
  }
  renderTree();
  fillFolderSelect();
}

function renderTree() {
  const el = $("folder-tree");
  const root = folders.find((f) => f.parent_id === null);
  el.innerHTML = root ? treeNode(root, 0) : '<div class="text-gray-400 p-1">No folders</div>';
  const tools = $("folder-tools");
  if (tools) tools.classList.toggle("is-hidden", !currentFolderId || currentFolderId === (root && root.id));
}

function treeNode(folder, depth) {
  const selected = folder.id === currentFolderId ? "sel" : "";
  const children = folders.filter((c) => c.parent_id === folder.id);
  let html = `<div class="tree-item ${selected}" style="padding-left:${depth * 14 + 4}px" onclick="selectFolder(${folder.id})" oncontextmenu="folderContext(event, ${folder.id})">
    <i class="fa-solid fa-folder"></i>${esc(folder.name)}${folder.is_public ? ' <i class="fa-solid fa-globe" style="color:var(--muted);font-size:10px"></i>' : ""}
  </div>`;
  for (const child of children) html += treeNode(child, depth + 1);
  return html;
}

async function selectFolder(id) {
  currentFolderId = id;
  renderTree();
  show("folder-acl", false);
  currentNav = "folders";
  hideWork();
  show("work-docs", true);
  layoutShell();
  await loadDocuments();
}

async function renameFolder() {
  const f = folders.find((x) => x.id === currentFolderId);
  if (!f) return;
  const name = prompt("New folder name", f.name);
  if (!name || name === f.name) return;
  try {
    await apiFetch(`/folders/${f.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, parent_id: f.parent_id, is_public: f.is_public }),
    });
    loadFolderTree();
  } catch (e) { alert("Rename failed: " + e.message); }
}

async function deleteFolder() {
  const f = folders.find((x) => x.id === currentFolderId);
  if (!f) return;
  if (!confirm(`Delete folder "${f.name}"? It must be empty.`)) return;
  try {
    await apiFetch(`/folders/${f.id}`, { method: "DELETE" });
    currentFolderId = null;
    await loadFolderTree();
    loadDocuments();
  } catch (e) { alert("Delete failed: " + e.message); }
}

function openFolderModal() { openModal("folder-modal"); }

async function createFolder() {
  const name = val("folder-name");
  if (!name) {
    const err = $("folder-err");
    err.textContent = "Name required"; err.classList.remove("hidden");
    return;
  }
  try {
    await apiFetch("/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, parent_id: currentFolderId, is_public: $("folder-public").checked }),
    });
    closeModal("folder-modal");
    $("folder-name").value = "";
    loadFolderTree();
  } catch (e) {
    const err = $("folder-err");
    err.textContent = e.message; err.classList.remove("hidden");
  }
}

async function openFolderAcl() {
  const box = $("folder-acl");
  box.classList.remove("is-hidden");
  try {
    const perms = (await apiFetch(`/folders/${currentFolderId}/acl`).catch(() => apiFetch(`/folders/${currentFolderId}/permissions`))) || [];
    let users = [];
    let groups = [];
    try { users = (await apiFetch("/users")) || []; } catch (e) { /* admin-only */ }
    try { groups = (await apiFetch("/groups")) || []; } catch (e) { /* admin-only */ }
    const bits = ["read","preview","write","add","rename","delete","download","print","move","email","security","import","export","workflow","calendar","subscription"];
    const rows = perms.map((p) => {
      const flags = p.flags || {};
      return `<div class="acl-row">${esc(p.principal_type)} #${p.principal_id}<br>
        ${bits.map((b) => `<label><input type="checkbox" ${flags[b] || (b === "read" && p.can_read) ? "checked" : ""} data-acl="${p.principal_type}:${p.principal_id}:${b}" /> ${b}</label>`).join(" ")}</div>`;
    }).join("") || "<div class='text-gray-400'>No ACL entries (owner/admin only)</div>";
    const whoOpts = users.map((u) => `<option value="user:${u.id}">${esc(u.username)}</option>`).join("")
      + groups.map((g) => `<option value="group:${g.id}">grp:${esc(g.name)}</option>`).join("");
    box.innerHTML = `${rows}
      <div class="mt-2 flex flex-wrap gap-1">
        ${whoOpts
          ? `<select id="acl-who" class="border p-1 rounded flex-1">${whoOpts}</select>`
          : `<input id="acl-who" placeholder="user:1 or group:2" class="border p-1 rounded flex-1" />`}
      </div>
      ${bits.map((b) => `<label class="mr-1"><input id="acl-${b}" type="checkbox" ${b === "read" ? "checked" : ""} /> ${b}</label>`).join(" ")}
      <button onclick="saveFolderAcl()" class="text-blue-600">Grant</button>
      <button onclick="saveAclBits && saveAclBits()" class="text-blue-600">Save bits</button>`;
  } catch (e) {
    box.innerHTML = `<span class="text-red-600">${esc(e.message)}</span>`;
  }
}

async function saveFolderAcl() {
  const who = val("acl-who").split(":");
  const bits = ["read","preview","write","add","rename","delete","download","print","move","email","security","import","export","workflow","calendar","subscription"];
  const flags = {};
  bits.forEach((b) => { const el = $("acl-" + b); if (el) flags[b] = el.checked; });
  await apiFetch(`/folders/${currentFolderId}/acl`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ principal_type: who[0], principal_id: parseInt(who[1], 10), flags }),
  });
  openFolderAcl();
}

// ---- Documents ------------------------------------------------------------
async function loadDocuments() {
  if (!currentFolderId) return;
  $("search-input").value = "";
  $("query-bar").classList.add("is-hidden");
  const docs = (await apiFetch(`/documents?folder_id=${currentFolderId}`)) || [];
  const f = folders.find((x) => x.id === currentFolderId);
  renderDocList(docs, f ? f.name : "Folder", `Folder #${currentFolderId}`);
}

async function loadDocsByQuery(q) {
  $("search-input").value = q;
  await updateQueryChips(q);
  const path = q ? `/query?q=${encodeURIComponent(q)}` : "/documents";
  const docs = (await apiFetch(path)) || [];
  const title = q === "inbox" ? "Processing inbox" : (q ? "Search results" : "All items");
  renderDocList(docs, title, q ? `Query · ${q}` : "All visible documents");
}

function renderDocList(docs, title, sub) {
  lastDocs = docs;
  lastTitle = title;
  lastSub = sub;
  if (pageOffset >= docs.length) pageOffset = 0;
  const page = docs.slice(pageOffset, pageOffset + pageSize);
  const pages = Math.max(1, Math.ceil(docs.length / pageSize));
  const pageNo = Math.floor(pageOffset / pageSize) + 1;
  $("work-title").textContent = title;
  $("work-sub").textContent = `${docs.length} item(s)`;
  selectedIds = new Set([...selectedIds].filter((id) => docs.some((d) => d.id === id)));
  updateBulkBar();
  if (!docs.length) {
    $("doc-list").innerHTML = "";
    show("no-docs", true);
    updateStatus();
    return;
  }
  show("no-docs", false);
  const pager = `<div class="pager">
    <button onclick="changePage(-1)" ${pageOffset === 0 ? "disabled" : ""}>Prev</button>
    <span>Page ${pageNo}/${pages}</span>
    <button onclick="changePage(1)" ${pageOffset + pageSize >= docs.length ? "disabled" : ""}>Next</button>
    <select onchange="pageSize=parseInt(this.value,10);pageOffset=0;renderDocList(lastDocs,lastTitle,lastSub)">
      ${[25, 50, 100, 200].map((n) => `<option ${n === pageSize ? "selected" : ""}>${n}</option>`).join("")}
    </select>
    <span class="col-pick">${Object.keys(GRID_COLS).map((k) =>
      `<label><input type="checkbox" ${GRID_COLS[k] ? "checked" : ""} onchange="GRID_COLS.${k}=this.checked;renderDocList(lastDocs,lastTitle,lastSub)" /> ${k}</label>`).join("")}</span>
  </div>`;
  if (gridView === "tiles") {
    $("doc-list").innerHTML = `${pager}<div class="dashlets">${page.map((d) => `<div class="dashlet tile" onclick="openDoc(${d.id})" oncontextmenu="docContext(event, ${d.id})">
      <div class="dashlet-h">${esc(d.title || d.name)} ${statusPill(d.status)}</div>
      <div class="p-2 text-xs">${esc(d.name)} · ${formatBytes(d.size)} · v${d.current_version}
        ${d.rating ? ` · ★${d.rating}` : ""}${d.page_count ? ` · ${d.page_count}p` : ""}</div></div>`).join("")}</div>`;
  } else {
    const th = (key, label) => GRID_COLS[key] ? `<th>${label}</th>` : "";
    $("doc-list").innerHTML = `${pager}
      <table class="grid">
        <thead><tr>
          <th style="width:28px"></th>
          ${th("title", "Title")}${th("file", "File")}${th("size", "Size")}${th("ver", "Ver")}${th("status", "Status")}${th("folder", "Folder")}${th("date", "Date")}${th("rating", "Rating")}${th("pages", "Pages")}
        </tr></thead>
        <tbody>${page.map(docRow).join("")}</tbody>
      </table>`;
  }
  updateStatus();
}

function changePage(dir) {
  pageOffset = Math.max(0, pageOffset + dir * pageSize);
  renderDocList(lastDocs, lastTitle, lastSub);
}
function toggleGridView() {
  gridView = gridView === "list" ? "tiles" : "list";
  renderDocList(lastDocs, lastTitle, lastSub);
}

function statusPill(s) {
  const k = String(s || "draft").toLowerCase().replace(/[^a-z]/g, "");
  return `<span class="st-pill st-${k}">${esc(s || "")}</span>`;
}

function docRow(d) {
  const sel = selectedIds.has(d.id) ? "selected" : "";
  const active = currentDocId === d.id ? "active" : "";
  const td = (key, html) => GRID_COLS[key] ? `<td>${html}</td>` : "";
  return `<tr class="${sel} ${active}" data-doc="${d.id}" onclick="openDoc(${d.id})" oncontextmenu="docContext(event, ${d.id})">
    <td onclick="event.stopPropagation()"><input type="checkbox" ${selectedIds.has(d.id) ? "checked" : ""} onclick="toggleSelect(${d.id})" /></td>
    ${td("title", `${esc(d.title || d.name)}${d.checked_out_by || d.locked_by ? ' <i class="fa-solid fa-lock" style="color:var(--orange)"></i>' : ""}${d.immutable ? ' <i class="fa-solid fa-shield"></i>' : ""}`)}
    ${td("file", esc(d.name))}
    ${td("size", formatBytes(d.size))}
    ${td("ver", "v" + d.current_version)}
    ${td("status", statusPill(d.status))}
    ${td("folder", esc(folderName(d.folder_id)))}
    ${td("date", fmtDay(d.item_date || d.updated_at || d.created_at))}
    ${td("rating", d.rating || "")}
    ${td("pages", d.page_count || "")}
  </tr>`;
}

function toggleSelect(id) {
  if (selectedIds.has(id)) selectedIds.delete(id);
  else selectedIds.add(id);
  updateBulkBar();
  renderDocList(lastDocs, lastTitle, lastSub);
}
function updateBulkBar() {
  const n = selectedIds.size;
  $("bulk-bar").classList.toggle("is-hidden", n === 0);
  $("bulk-count").textContent = `${n} selected`;
}
function clearSelection() { selectedIds.clear(); updateBulkBar(); renderDocList(lastDocs, lastTitle, lastSub); }

async function applyBulk() {
  if (!selectedIds.size) return;
  const payload = { ids: [...selectedIds] };
  if (val("bulk-tags")) payload.tags = val("bulk-tags");
  if (val("bulk-status")) payload.status = val("bulk-status");
  await apiFetch("/documents/bulk-edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  clearSelection();
  refreshCurrentList();
}

function bulkEditSelected() {
  if (!selectedIds.size) return alert("Select one or more items (checkboxes).");
  $("bulk-bar").classList.remove("is-hidden");
}

async function mergeSelected() {
  if (selectedIds.size < 2) return alert("Select at least two items to merge.");
  const title = prompt("Merged item title", "Merged document");
  if (!title) return;
  await apiFetch("/documents/merge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids: [...selectedIds], title, folder_id: currentFolderId }),
  });
  clearSelection();
  refreshCurrentList();
}

async function mailSelected() {
  const ids = selectedIds.size ? [...selectedIds] : (currentDocId ? [currentDocId] : []);
  if (!ids.length) return alert("Select documents or open one.");
  const to = prompt("Send to email address");
  if (!to) return;
  try {
    await apiFetch("/mail/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_ids: ids, to, subject: "Documents from NewtonEDMS" }),
    });
    alert("Sent");
  } catch (e) { alert(e.message); }
}

function refreshCurrentList() {
  if (currentNav === "inbox") loadDocsByQuery("inbox");
  else if (currentNav === "search") loadDocsByQuery($("search-input").value);
  else loadDocuments();
  loadFacets();
}

// ---- Inspector ------------------------------------------------------------
async function openDoc(id) {
  currentDocId = id;
  currentDoc = await apiFetch(`/documents/${id}`);
  if (!currentDoc) return;
  if (currentDoc.folder_id && currentFolderId !== currentDoc.folder_id) {
    currentFolderId = currentDoc.folder_id;
    renderTree();
  }
  layoutShell();
  $("insp-title").textContent = currentDoc.title || currentDoc.name;
  $("insp-sub").textContent = `${currentDoc.name} · ${formatBytes(currentDoc.size)} · ${currentDoc.mime || ""}`;
  $("insp-lock").innerHTML = currentDoc.checked_out_by
    ? '<i class="fa-solid fa-lock-open"></i> Check in'
    : '<i class="fa-solid fa-lock"></i> Check out';
  document.querySelectorAll("tr[data-doc]").forEach((el) => el.classList.toggle("active", el.dataset.doc === String(id)));
  inspTab("details");
}

function closeInspector() {
  currentDocId = null;
  currentDoc = null;
  if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
  layoutShell();
}

function showCtxMenu(e, html) {
  e.preventDefault();
  e.stopPropagation();
  const m = $("ctx-menu");
  m.innerHTML = html;
  m.style.left = Math.min(e.clientX, window.innerWidth - 220) + "px";
  m.style.top = Math.min(e.clientY, window.innerHeight - 240) + "px";
  m.classList.add("open");
}

function docContext(e, id) {
  const d = lastDocs.find((x) => x.id === id) || {};
  showCtxMenu(e, `
    <button onclick="openDoc(${id}); inspTab('preview'); closeDrops()">Preview</button>
    <button onclick="downloadDoc(${id}); closeDrops()">Download</button>
    <div class="sep"></div>
    <button onclick="openDoc(${id}); toggleCheckout(); closeDrops()">${d.checked_out_by ? "Check in" : "Check out"}</button>
    <button onclick="toggleSelect(${id}); closeDrops()">Select</button>
    <button onclick="currentDocId=${id}; mailSelected(); closeDrops()">Send mail</button>
    <div class="sep"></div>
    <button onclick="openDoc(${id}); reprocessDoc(); closeDrops()">Process (OCR)</button>
    <button onclick="deleteDoc(${id}); closeDrops()">Delete</button>
  `);
}

function folderContext(e, id) {
  showCtxMenu(e, `
    <button onclick="selectFolder(${id}); closeDrops()">Open</button>
    <button onclick="currentFolderId=${id}; openFolderModal(); closeDrops()">Create subfolder</button>
    <button onclick="currentFolderId=${id}; renameFolder(); closeDrops()">Rename</button>
    <button onclick="currentFolderId=${id}; openFolderAcl(); closeDrops()">Security</button>
    <button onclick="currentFolderId=${id}; exportFolder(); closeDrops()">Export ZIP</button>
    <button onclick="runQuery('folder:${id}'); closeDrops()">Search in folder</button>
    <div class="sep"></div>
    <button onclick="currentFolderId=${id}; deleteFolder(); closeDrops()">Delete</button>
  `);
}

async function inspTab(tab) {
  markInspTab(tab);
  const body = $("insp-body");
  if (tab === "folder") {
    show("inspector", true);
    if (typeof ceInspTab === "function") await ceInspTab(tab, body);
    return;
  }
  if (!currentDocId) return;
  if (tab === "details") await renderInspDetails(body);
  else if (tab === "preview") await renderInspPreview(body);
  else if (tab === "versions") await renderInspVersions(body);
  else if (tab === "files") await renderInspFiles(body);
  else if (tab === "comments") await renderInspComments(body);
  else if (tab === "share") await renderInspShare(body);
  else if (tab === "workflow") await renderInspWorkflow(body);
  else if (typeof ceInspTab === "function") await ceInspTab(tab, body);
}

async function renderInspDetails(body) {
  const d = currentDoc || await apiFetch(`/documents/${currentDocId}`);
  currentDoc = d;
  const [fields, values, suggest, dups] = await Promise.all([
    apiFetch("/custom-fields"),
    apiFetch(`/documents/${currentDocId}/fields`),
    apiFetch(`/documents/${currentDocId}/suggest`).catch(() => ({ tags: [], contacts: [], dates: [] })),
    apiFetch(`/documents/${currentDocId}/duplicates`).catch(() => []),
  ]);
  customFields = fields || [];
  const valMap = {};
  (values || []).forEach((v) => { valMap[v.field_id] = v.value; });
  const optContacts = (kind) =>
    `<option value="">—</option>` + contacts.map((c) =>
      `<option value="${c.id}" ${d[kind] === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  body.innerHTML = `
    <label class="block text-xs text-gray-500">Title</label>
    <input id="d-title" class="w-full border p-1 rounded mb-2" value="${esc(d.title)}" />
    <label class="block text-xs text-gray-500">Tags (comma)</label>
    <input id="d-tags" class="w-full border p-1 rounded mb-2" value="${esc(d.tags || "")}" />
    <div class="grid grid-cols-2 gap-2">
      <div><label class="text-xs text-gray-500">Correspondent</label>
        <select id="d-corr" class="w-full border p-1 rounded">${optContacts("correspondent_id")}</select></div>
      <div><label class="text-xs text-gray-500">Concerning</label>
        <select id="d-conc" class="w-full border p-1 rounded">${optContacts("concerning_id")}</select></div>
      <div><label class="text-xs text-gray-500">Item date</label>
        <input id="d-item" type="date" class="w-full border p-1 rounded" value="${fmtDay(d.item_date)}" /></div>
      <div><label class="text-xs text-gray-500">Due date</label>
        <input id="d-due" type="date" class="w-full border p-1 rounded" value="${fmtDay(d.due_date)}" /></div>
      <div><label class="text-xs text-gray-500">Direction</label>
        <select id="d-dir" class="w-full border p-1 rounded">
          <option value="">—</option>
          ${["incoming", "outgoing"].map((x) => `<option ${d.direction === x ? "selected" : ""}>${x}</option>`).join("")}
        </select></div>
      <div><label class="text-xs text-gray-500">Status</label>
        <select id="d-status" class="w-full border p-1 rounded">
          ${["draft", "review", "approved", "published", "archived"].map((s) => `<option ${d.status === s ? "selected" : ""}>${s}</option>`).join("")}
        </select></div>
    </div>
    <label class="block text-xs text-gray-500 mt-2">Custom ID</label>
    <input id="d-custom" class="w-full border p-1 rounded mb-2" value="${esc(d.custom_id || "")}" />
    <label class="block text-xs text-gray-500">Language / equipment</label>
    <div class="grid grid-cols-2 gap-2 mb-2">
      <input id="d-lang" class="border p-1 rounded" placeholder="en" value="${esc(d.language || "")}" />
      <input id="d-equip" class="border p-1 rounded" placeholder="equipment" value="${esc(d.equipment || "")}" />
    </div>
    <label class="block text-xs text-gray-500">Notes</label>
    <textarea id="d-notes" class="w-full border p-1 rounded mb-2 h-16">${esc(d.notes || "")}</textarea>
    ${(customFields || []).map((f) => `
      <label class="block text-xs text-gray-500">${esc(f.label || f.name)} (${esc(f.ftype)})</label>
      <input class="w-full border p-1 rounded mb-1 cf-val" data-fid="${f.id}" value="${esc(valMap[f.id] || "")}" />`).join("")}
    <button onclick="saveDetails()" class="mt-2 w-full bg-blue-600 text-white py-1.5 rounded">Save metadata</button>
    ${suggest && (suggest.tags || []).length ? `<div class="mt-3 p-2 bg-blue-100 rounded">
      <div class="text-xs font-bold mb-1">NLP suggestions</div>
      ${(suggest.tags || []).map((t) => `<button class="tag-chip" onclick="applySuggestTag('${esc(t)}')">${esc(t)}</button>`).join("")}
      ${(suggest.contacts || []).map((c) => `<button class="tag-chip" onclick="applySuggestContact(${c.id})">${esc(c.name)}</button>`).join("")}
      ${(suggest.dates || []).map((dt) => `<span class="text-xs ml-1">${esc(dt)}</span>`).join("")}
      ${suggest.language ? `<span class="text-xs ml-1">lang ${esc(suggest.language)}</span>` : ""}
    </div>` : ""}
    ${dups && dups.length ? `<div class="mt-3 text-xs text-amber-700">Duplicates: ${dups.map((x) => `#${x.id} ${esc(x.title)}`).join(", ")}</div>` : ""}
    <div class="mt-3 text-xs text-gray-400">source ${esc(d.source || "upload")} · hash ${(d.content_hash || "").slice(0, 12)}</div>`;
}

async function saveDetails() {
  const form = new FormData();
  form.append("title", val("d-title"));
  form.append("tags", val("d-tags"));
  form.append("notes", val("d-notes"));
  form.append("due_date", val("d-due"));
  form.append("item_date", val("d-item"));
  form.append("custom_id", val("d-custom"));
  form.append("direction", val("d-dir"));
  form.append("status", val("d-status"));
  form.append("language", val("d-lang"));
  form.append("equipment", val("d-equip"));
  if (val("d-corr")) form.append("correspondent_id", val("d-corr"));
  if (val("d-conc")) form.append("concerning_id", val("d-conc"));
  await apiFetch(`/documents/${currentDocId}`, { method: "PUT", body: form });
  const payload = [...document.querySelectorAll(".cf-val")].map((el) => ({
    field_id: parseInt(el.dataset.fid, 10),
    value: el.value,
  }));
  if (payload.length) {
    await apiFetch(`/documents/${currentDocId}/fields`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }
  await openDoc(currentDocId);
  refreshCurrentList();
}

function applySuggestTag(t) {
  const el = $("d-tags");
  const cur = el.value.split(",").map((x) => x.trim()).filter(Boolean);
  if (!cur.includes(t)) cur.push(t);
  el.value = cur.join(", ");
}
function applySuggestContact(id) { $("d-corr").value = String(id); }

async function renderInspPreview(body) {
  const text = await apiFetch(`/documents/${currentDocId}/text`);
  const mime = (currentDoc && currentDoc.mime) || "";
  const isPdf = mime.includes("pdf");
  const isImg = mime.startsWith("image/");
  let preview = "";
  if (isImg || isPdf) {
    preview = `<div id="preview-frame" class="preview-frame">${isPdf ? "Loading PDF…" : "Loading image…"}</div>`;
    loadBlobPreview(mime);
  }
  body.innerHTML = `${preview}
    <div class="text-xs text-gray-500 mb-1">Extracted text · ${esc(text.processing_status || "")}</div>
    <pre class="whitespace-pre-wrap text-xs bg-slate-50 p-2 rounded max-h-40 overflow-y-auto">${esc(text.text || "(no text yet — click OCR to reprocess)")}</pre>`;
}

async function loadBlobPreview(mime) {
  try {
    const resp = await fetch(api(`/documents/${currentDocId}/preview`), { ...FETCH_OPTS });
    if (!resp.ok) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const blob = await resp.blob();
    previewUrl = URL.createObjectURL(blob);
    const frame = $("preview-frame");
    if (!frame) return;
    if (mime.startsWith("image/")) frame.innerHTML = `<img src="${previewUrl}" class="preview-img" />`;
    else frame.innerHTML = `<iframe src="${previewUrl}#toolbar=1&navpanes=1" class="preview-pdf" title="Preview"></iframe>`;
  } catch (e) { /* ignore */ }
}

async function renderInspVersions(body) {
  const versions = (await apiFetch(`/documents/${currentDocId}/versions`)) || [];
  body.innerHTML = `
    <ul>${versions.map((v) => `<li class="border-b py-2 flex justify-between">
      <span>v${v.version_number} · ${formatBytes(v.size)}<br><span class="text-xs text-gray-500">${fmtDate(v.created_at)} ${esc(v.comment || "")}</span></span>
      <span>
        <button onclick="downloadDoc(${currentDocId}, ${v.version_number})" class="text-blue-600 mr-1"><i class="fa-solid fa-download"></i></button>
        <button onclick="restoreVersion(${v.version_number})" class="text-emerald-600"><i class="fa-solid fa-rotate-left"></i></button>
      </span></li>`).join("")}</ul>
    <button onclick="$('version-file').click()" class="mt-3 w-full border rounded py-1">Add version (check-in file)</button>`;
}

async function restoreVersion(vn) {
  if (!confirm(`Restore version ${vn}?`)) return;
  await apiFetch(`/documents/${currentDocId}/restore/${vn}`, { method: "POST" });
  await openDoc(currentDocId);
  refreshCurrentList();
}

async function doAddVersion(input) {
  const file = input.files[0];
  input.value = "";
  if (!file || !currentDocId) return;
  const comment = prompt("Version comment", `Upload of ${file.name}`) ?? "";
  const form = new FormData();
  form.append("file", file);
  form.append("comment", comment);
  await apiFetch(`/documents/${currentDocId}/versions`, { method: "POST", body: form });
  inspTab("versions");
  refreshCurrentList();
}

async function renderInspFiles(body) {
  const atts = (await apiFetch(`/documents/${currentDocId}/attachments`)) || [];
  body.innerHTML = `
    <p class="text-xs text-gray-500 mb-2">Additional files on this item. The primary file is downloaded from the footer.</p>
    <ul>${atts.length ? atts.map((a) => `<li class="border-b py-1 flex justify-between">
      <span>${esc(a.name)} · ${formatBytes(a.size)} · ${esc(a.role)}</span>
      <a class="text-blue-600" href="/api/documents/${currentDocId}/attachments/${a.id}/download" target="_blank">open</a>
    </li>`).join("") : '<li class="text-gray-400">No extra attachments</li>'}</ul>
    <button onclick="$('attach-file').click()" class="mt-3 w-full border rounded py-1">Add attachment</button>`;
}

async function doAddAttachment(input) {
  const file = input.files[0];
  input.value = "";
  if (!file || !currentDocId) return;
  const form = new FormData();
  form.append("file", file);
  await apiFetch(`/documents/${currentDocId}/attachments`, { method: "POST", body: form });
  inspTab("files");
}

async function renderInspComments(body) {
  const comments = (await apiFetch(`/documents/${currentDocId}/comments`)) || [];
  body.innerHTML = `
    <ul class="mb-2">${comments.length ? comments.map((c) => `<li class="border-b py-1"><b>${esc(c.author_name || c.username)}</b>${c.author_name ? ' <span class="text-xs text-gray-400">via share</span>' : ""}
      <span class="text-xs text-gray-400">${fmtDate(c.created_at)}</span><div>${esc(c.text)}</div></li>`).join("") : '<li class="text-gray-400">No comments</li>'}</ul>
    <div class="flex gap-1"><input id="comment-text" class="flex-1 border p-1 rounded" placeholder="Add a comment" />
    <button onclick="addComment()" class="bg-blue-600 text-white px-2 rounded">Post</button></div>`;
}

async function addComment() {
  const text = val("comment-text");
  if (!text) return;
  await apiFetch(`/documents/${currentDocId}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  inspTab("comments");
}

async function renderInspShare(body) {
  const [shares, acl, users, groups] = await Promise.all([
    apiFetch(`/documents/${currentDocId}/shares`),
    apiFetch(`/documents/${currentDocId}/acl`).catch(() => []),
    apiFetch("/users").catch(() => []),
    apiFetch("/groups").catch(() => []),
  ]);
  const canManage = currentUser && currentDoc &&
    (currentDoc.created_by === currentUser.id || ["superadmin", "admin"].includes(currentUser.role));
  const nameOf = (p) => p.principal_type === "group"
    ? `group: ${((groups || []).find((g) => g.id === p.principal_id) || {}).name || p.principal_id}`
    : `user: ${((users || []).find((u) => u.id === p.principal_id) || {}).username || p.principal_id}`;
  const kindLabel = { view: "view only", comment: "view + comment", download: "download" };
  body.innerHTML = `
    <label class="text-xs text-gray-500">Share link — permission level</label>
    <select id="share-kind" class="w-full border p-1 rounded mb-1">
      <option value="view">View only (read-only in browser)</option>
      <option value="comment">View &amp; comment</option>
      <option value="download">Download</option>
    </select>
    <input id="share-name" placeholder="Link name" class="w-full border p-1 rounded mb-1" />
    <div class="flex gap-1 mb-1">
      <input id="share-days" type="number" placeholder="Days (7)" class="border p-1 rounded w-28" />
      <input id="share-max" type="number" placeholder="Max DL" class="border p-1 rounded w-24" />
    </div>
    <input id="share-pass" type="password" placeholder="Optional password" class="w-full border p-1 rounded mb-2" />
    <button onclick="createShare()" class="w-full bg-blue-600 text-white py-1 rounded">Create share link</button>
    <ul class="mb-2 mt-2">${(shares || []).length ? shares.map((s) => `<li class="border-b py-1 text-xs">
      <a class="text-blue-600 break-all" href="${s.kind === "download" ? s.url : "/share/" + s.token}" target="_blank">${location.origin}${s.kind === "download" ? s.url : "/share/" + s.token}</a>
      <div><span class="tag-chip">${kindLabel[s.kind] || s.kind}</span>
        ${s.download_count}${s.max_downloads ? "/" + s.max_downloads : ""} downloads
        ${s.password_protected ? " · password" : ""} · exp ${fmtDay(s.expires_at)}
        <button class="text-red-600 ml-2" onclick="deleteShare(${s.id})">revoke</button></div>
    </li>`).join("") : '<li class="text-gray-400">No share links</li>'}</ul>
    <div class="border-t pt-2 mt-2">
      <label class="text-xs text-gray-500">Internal access — grant a user or group</label>
      <div class="flex gap-1 mb-1">
        <select id="sh-principal" class="flex-1 border p-1 rounded text-xs">
          ${(users || []).filter((u) => u.id !== (currentDoc || {}).created_by).map((u) => `<option value="user:${u.id}">user: ${esc(u.username)}</option>`).join("")}
          ${(groups || []).map((g) => `<option value="group:${g.id}">group: ${esc(g.name)}</option>`).join("")}
        </select>
        <select id="sh-perm" class="border p-1 rounded text-xs">
          <option value="read">View only</option>
          <option value="write">Edit</option>
        </select>
      </div>
      <button onclick="grantDocAccess()" class="w-full border rounded py-1 mb-2">Grant access</button>
      <ul class="text-xs">${(acl || []).length ? acl.map((p) => `<li class="border-b py-1">${esc(nameOf(p))}
        <span class="tag-chip">${p.flags && p.flags.write ? "edit" : "view"}</span>
        <button class="text-red-600 ml-2" onclick="revokeDocAccess(${p.id})">revoke</button></li>`).join("") : '<li class="text-gray-400">No direct grants (folder ACL still applies)</li>'}</ul>
    </div>
    ${canManage && (users || []).length ? `
    <div class="border-t pt-2 mt-2">
      <label class="text-xs text-gray-500">Ownership transfer</label>
      <div class="flex gap-1 mb-1">
        <select id="sh-owner" class="flex-1 border p-1 rounded text-xs">
          ${(users || []).filter((u) => u.id !== (currentDoc || {}).created_by).map((u) => `<option value="${u.id}">${esc(u.username)}</option>`).join("")}
        </select>
        <button onclick="transferOwnership()" class="border rounded px-2 text-xs">Transfer</button>
      </div>
    </div>` : ""}`;
}

async function createShare() {
  const q = [`kind=${val("share-kind") || "download"}`];
  if (val("share-days")) q.push(`expires_days=${val("share-days")}`);
  if (val("share-max")) q.push(`max_downloads=${val("share-max")}`);
  if (val("share-pass")) q.push(`password=${encodeURIComponent(val("share-pass"))}`);
  if (val("share-name")) q.push(`name=${encodeURIComponent(val("share-name"))}`);
  await apiFetch(`/documents/${currentDocId}/shares?${q.join("&")}`, { method: "POST" });
  inspTab("share");
}
async function deleteShare(id) {
  await apiFetch(`/documents/${currentDocId}/shares/${id}`, { method: "DELETE" });
  inspTab("share");
}
async function grantDocAccess() {
  const [ptype, pid] = val("sh-principal").split(":");
  const write = val("sh-perm") === "write";
  try {
    await apiFetch(`/documents/${currentDocId}/acl`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        principal_type: ptype,
        principal_id: parseInt(pid, 10),
        flags: { read: true, preview: true, download: true, write, delete: write },
      }),
    });
    inspTab("share");
  } catch (e) { alert(e.message); }
}
async function revokeDocAccess(permId) {
  try {
    await apiFetch(`/documents/${currentDocId}/acl/${permId}`, { method: "DELETE" });
    inspTab("share");
  } catch (e) { alert(e.message); }
}
async function transferOwnership() {
  const target = val("sh-owner");
  const name = ($("sh-owner").selectedOptions[0] || {}).textContent || target;
  if (!target || !confirm(`Transfer ownership of this document to ${name}? You will no longer be the owner.`)) return;
  try {
    await apiFetch(`/documents/${currentDocId}/owner`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: parseInt(target, 10) }),
    });
    await openDoc(currentDocId);
    inspTab("share");
    refreshCurrentList();
  } catch (e) { alert(e.message); }
}

async function renderInspWorkflow(body) {
  const [wfs, inst] = await Promise.all([
    apiFetch("/workflows"),
    apiFetch("/workflow-instances").catch(() => []),
  ]);
  const mine = (inst || []).filter((i) => i.document_id === currentDocId);
  body.innerHTML = `
    <label class="text-xs text-gray-500">Start workflow</label>
    <select id="wf-template" class="w-full border p-1 rounded mb-2">
      ${(wfs || []).map((w) => `<option value="${w.id}">${esc(w.name)}</option>`).join("") || '<option value="">No templates</option>'}
    </select>
    <button onclick="startWorkflow()" class="w-full bg-amber-600 text-white py-1 rounded mb-3">Start</button>
    ${mine.length ? mine.map((i) => `<div class="text-xs border-b py-1">Instance #${i.id} · ${esc(i.status)}</div>`).join("") : '<p class="text-gray-400 text-xs">No workflow on this document</p>'}`;
}

async function startWorkflow() {
  const tplId = val("wf-template");
  if (!tplId) return;
  await apiFetch(`/documents/${currentDocId}/workflows?template_id=${tplId}`, { method: "POST" });
  inspTab("workflow");
}

async function toggleCheckout() {
  if (!currentDoc) return;
  const path = currentDoc.checked_out_by ? "checkin" : "checkout";
  await apiFetch(`/documents/${currentDocId}/${path}`, { method: "POST" });
  await openDoc(currentDocId);
  refreshCurrentList();
}

async function reprocessDoc() {
  await apiFetch(`/documents/${currentDocId}/reprocess`, { method: "POST" });
  alert("Queued for processing (OCR / index)");
  refreshCurrentList();
}

async function downloadOriginal() {
  try {
    const resp = await fetch(api(`/documents/${currentDocId}/original`), { ...FETCH_OPTS });
    if (!resp.ok) { alert("No original stored"); return; }
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (currentDoc && currentDoc.name) || "original";
    document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { alert(e.message); }
}

async function downloadDoc(id, version) {
  const url = api(`/documents/${id}/download`) + (version ? `?v=${version}` : "");
  try {
    const resp = await fetch(url, { ...FETCH_OPTS });
    if (!resp.ok) { alert("Download failed"); return; }
    const blob = await resp.blob();
    const cd = resp.headers.get("content-disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/i);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = m ? m[1] : "download";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
  } catch (e) { alert(e.message); }
}

async function deleteDoc(id) {
  if (!confirm("Delete this document?")) return;
  await apiFetch(`/documents/${id}`, { method: "DELETE" });
  closeInspector();
  refreshCurrentList();
}

async function exportFolder() {
  if (!currentFolderId) return;
  const resp = await fetch(api(`/folders/${currentFolderId}/export`), { ...FETCH_OPTS });
  if (!resp.ok) { alert("Export failed"); return; }
  const blob = await resp.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `folder_${currentFolderId}.zip`;
  document.body.appendChild(a); a.click(); a.remove();
}

async function openUploadModal() {
  try {
    const tpls = (await apiFetch("/metadata-templates")) || [];
    $("upload-template").innerHTML = '<option value="">No metadata template</option>' +
      tpls.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
  } catch (e) { /* optional */ }
  openModal("upload-modal");
}

async function uploadDoc() {
  const files = $("upload-file").files;
  if (!files.length) {
    const err = $("upload-err");
    err.textContent = "Select at least one file"; err.classList.remove("hidden");
    return;
  }
  const form = new FormData();
  form.append("folder_id", currentFolderId);
  form.append("tags", val("upload-tags"));
  form.append("metadata", val("upload-meta") || "{}");
  const tplId = val("upload-template");
  if (tplId) form.append("template_id", tplId);
  try {
    if (files.length === 1) {
      form.append("title", val("upload-title") || files[0].name);
      form.append("file", files[0]);
      await apiFetch("/documents", { method: "POST", body: form });
    } else {
      for (const f of files) form.append("files", f);
      await apiFetch("/documents/bulk", { method: "POST", body: form });
    }
    closeModal("upload-modal");
    refreshCurrentList();
  } catch (e) {
    const err = $("upload-err");
    err.textContent = e.message; err.classList.remove("hidden");
  }
}

// ---- Calendar / tasks / contacts / settings -------------------------------
async function renderCalendar() {
  const events = (await apiFetch("/calendar")) || [];
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const first = new Date(y, m, 1).getDay();
  const days = new Date(y, m + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < first; i++) cells.push("<div></div>");
  for (let d = 1; d <= days; d++) {
    const dayEvents = events.filter((e) => {
      const dt = new Date(e.start_at);
      return dt.getFullYear() === y && dt.getMonth() === m && dt.getDate() === d;
    });
    cells.push(`<div class="cal-day"><b>${d}</b>${dayEvents.map((e) => `<div class="cal-ev">${esc(e.title)}</div>`).join("")}</div>`);
  }
  $("work-calendar").innerHTML = `
    <h2 class="text-lg font-bold mb-3">Calendar · ${now.toLocaleString(undefined, { month: "long", year: "numeric" })}</h2>
    <div class="bg-white rounded shadow p-4 mb-3 flex flex-wrap gap-2">
      <input id="cal-title" placeholder="Event title" class="border p-2 rounded flex-1" />
      <input id="cal-start" type="datetime-local" class="border p-2 rounded" />
      <input id="cal-end" type="datetime-local" class="border p-2 rounded" />
      <input id="cal-doc" type="number" placeholder="Doc id (optional)" class="border p-2 rounded w-32" />
      <button onclick="createEvent()" class="bg-blue-600 text-white px-3 rounded">Add</button>
    </div>
    <div class="cal-grid">${["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].map((d) => `<div class="cal-h">${d}</div>`).join("")}${cells.join("")}</div>
    <div class="bg-white rounded shadow divide-y mt-3">
      ${events.length ? events.map((e) => `<div class="p-3 flex justify-between">
        <div><b>${esc(e.title)}</b><div class="text-xs text-gray-500">${fmtDate(e.start_at)} ${e.document_id ? "· doc #" + e.document_id : ""}</div></div>
        <button class="text-red-600" onclick="delEvent(${e.id})"><i class="fa-solid fa-trash"></i></button>
      </div>`).join("") : '<p class="p-4 text-gray-400">No events</p>'}
    </div>`;
}
async function createEvent() {
  await apiFetch("/calendar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: val("cal-title"),
      start_at: val("cal-start"),
      document_id: val("cal-doc") ? parseInt(val("cal-doc"), 10) : null,
    }),
  });
  renderCalendar();
}
async function delEvent(id) {
  await apiFetch(`/calendar/${id}`, { method: "DELETE" });
  renderCalendar();
}

async function renderTasks() {
  const [tasks, notifs] = await Promise.all([apiFetch("/tasks"), apiFetch("/notifications")]);
  $("work-tasks").innerHTML = `
    <h2 class="text-lg font-bold mb-3">Tasks & notifications</h2>
    <div class="bg-white rounded shadow p-4 mb-4">
      <h3 class="font-bold mb-2">Workflow tasks</h3>
      ${(tasks || []).length ? `<table class="w-full text-sm"><thead><tr class="text-left text-gray-500"><th class="p-1">Step</th><th>Doc</th><th>Status</th><th></th></tr></thead>
        <tbody>${tasks.map((t) => `<tr class="border-b"><td class="p-1">${esc(t.step_name)}</td><td><button class="text-blue-600" onclick="openDoc(${t.document_id})">#${t.document_id}</button></td>
          <td>${esc(t.status)}</td><td>${t.status === "pending" ? `
            <button onclick="taskAction(${t.id}, true)" class="text-green-600 mr-2">Approve</button>
            <button onclick="taskAction(${t.id}, false)" class="text-red-600">Reject</button>` : ""}</td></tr>`).join("")}</tbody></table>`
        : '<p class="text-gray-400">No tasks</p>'}
    </div>
    <div class="bg-white rounded shadow p-4">
      <h3 class="font-bold mb-2">Notifications</h3>
      ${(notifs || []).length ? notifs.map((n) => `<div class="border-b py-2 flex justify-between ${n.read ? "text-gray-400" : ""}">
        <span>${esc(n.message)} <span class="text-xs">${fmtDate(n.created_at)}</span></span>
        ${!n.read ? `<button onclick="markRead(${n.id})" class="text-blue-600 text-xs">Read</button>` : ""}
      </div>`).join("") : '<p class="text-gray-400">No notifications</p>'}
    </div>`;
  updateNotifBadge();
}
async function taskAction(id, approved) {
  const comment = approved ? "" : (prompt("Rejection comment") || "");
  await apiFetch(`/tasks/${id}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, comment }),
  });
  renderTasks();
}
async function markRead(id) {
  await apiFetch(`/notifications/${id}/read`, { method: "POST" });
  renderTasks();
}
async function updateNotifBadge() {
  try {
    const unread = (await apiFetch("/notifications?unread_only=true")) || [];
    const badge = $("notif-badge");
    if (unread.length) { badge.textContent = unread.length; badge.classList.remove("is-hidden"); }
    else badge.classList.add("is-hidden");
  } catch (e) { /* ignore */ }
}

// ---- People (address book + user & group management) ----------------------
function isAdminUser() {
  return !!currentUser && ["superadmin", "admin"].includes(currentUser.role);
}

async function renderContacts() {
  const tabs = [["contacts", "Address book"]];
  if (isAdminUser()) tabs.push(["users", "Users"], ["groups", "Groups"]);
  $("work-contacts").innerHTML = `
    <div class="flex items-center gap-2 mb-3 flex-wrap">
      <h2 class="text-lg font-bold mr-2">People</h2>
      ${tabs.map(([k, label]) =>
        `<button class="tb ${peopleTab === k ? "primary" : ""}" data-people="${k}" onclick="peopleTabSwitch('${k}')">${label}</button>`
      ).join("")}
    </div>
    <div id="people-pane"></div>`;
  await renderPeoplePane();
}

async function peopleTabSwitch(name) {
  peopleTab = name;
  await renderContacts();
}

async function renderPeoplePane() {
  const pane = $("people-pane");
  if (!pane) return;
  if (peopleTab === "users" && isAdminUser()) await renderPeopleUsers(pane);
  else if (peopleTab === "groups" && isAdminUser()) await renderPeopleGroups(pane);
  else {
    peopleTab = "contacts";
    contacts = (await apiFetch("/contacts")) || [];
    pane.innerHTML = `
      <h3 class="font-bold mb-2">Address book</h3>
      <div class="bg-white rounded shadow p-4 mb-3 flex flex-wrap gap-2">
        <input id="ct-name" placeholder="Name" class="border p-2 rounded" />
        <input id="ct-org" placeholder="Organization" class="border p-2 rounded" />
        <input id="ct-email" placeholder="Email" class="border p-2 rounded" />
        <select id="ct-kind" class="border p-2 rounded"><option value="both">both</option><option value="correspondent">correspondent</option><option value="concerning">concerning</option></select>
        <button onclick="createContact()" class="bg-blue-600 text-white px-3 rounded">Add</button>
      </div>
      <div class="bg-white rounded shadow overflow-hidden">
        <table class="w-full text-sm"><thead class="bg-slate-50"><tr><th class="p-2 text-left">Name</th><th>Org</th><th>Email</th><th>Kind</th><th></th></tr></thead>
        <tbody>${contacts.map((c) => `<tr class="border-b"><td class="p-2">${esc(c.name)}</td><td>${esc(c.organization || "")}</td>
          <td>${esc(c.email || "")}</td><td>${esc(c.kind)}</td>
          <td><button class="text-red-600" onclick="delContact(${c.id})"><i class="fa-solid fa-trash"></i></button></td></tr>`).join("")}</tbody></table>
      </div>`;
  }
}

const ROLE_OPTIONS = ["user", "manager", "admin", "superadmin"];

async function renderPeopleUsers(pane) {
  const users = (await apiFetch("/users")) || [];
  const roleSel = (u) => `<select onchange="peopleSetUserRole(${u.id}, this.value)" class="border p-1 rounded text-sm">`
    + ROLE_OPTIONS.map((r) => `<option value="${r}" ${u.role === r ? "selected" : ""}>${r}</option>`).join("")
    + `</select>`;
  pane.innerHTML = `
    <h3 class="font-bold mb-2">Users &amp; roles</h3>
    <div class="flex gap-2 mb-3 flex-wrap">
      <input id="nu-name" placeholder="Username" class="border p-2 rounded" />
      <input id="nu-email" placeholder="Email" class="border p-2 rounded flex-1" />
      <input id="nu-pass" type="password" placeholder="Password" class="border p-2 rounded" />
      <select id="nu-role" class="border p-2 rounded">${ROLE_OPTIONS.map((r) => `<option value="${r}">${r}</option>`).join("")}</select>
      <button onclick="adminCreateUser()" class="px-3 py-1 bg-blue-600 text-white rounded">Add user</button>
    </div>
    <div class="bg-white rounded shadow overflow-x-auto">
      <table class="w-full text-left text-sm"><thead class="bg-gray-100"><tr class="border-b">
        <th class="p-2">User</th><th>Role</th><th>Active</th><th>Quota</th><th>Last login</th><th></th></tr></thead>
      <tbody>${users.map((u) => `<tr class="border-b">
        <td class="p-2"><b>${esc(u.username)}</b>${u.id === currentUser.id ? ' <span class="text-xs text-gray-400">(you)</span>' : ""}
          <div class="text-xs text-gray-500"><a class="hover:underline cursor-pointer" onclick="peopleEditUserEmail(${u.id}, '${esc(u.email || "")}')">${esc(u.email || "add email")}</a></div></td>
        <td>${roleSel(u)}</td>
        <td>${u.is_active ? '<span class="text-emerald-600">✓ active</span>' : '<span class="text-red-600">✗ disabled</span>'}</td>
        <td class="text-xs">${u.quota_bytes ? formatBytes(u.quota_bytes) : '<span class="text-gray-400">unlimited</span>'}</td>
        <td class="text-xs">${u.last_login_at ? esc(fmtDate(u.last_login_at)) : "—"}</td>
        <td class="whitespace-nowrap">
          <button onclick="setUserQuota(${u.id})" class="text-blue-600 mr-2" title="Set storage quota">quota</button>
          ${u.id === currentUser.id
            ? `<button disabled class="text-gray-400 mr-2" title="You cannot deactivate your own account">${u.is_active ? "disable" : "enable"}</button>
               <button disabled class="text-gray-400" title="You cannot delete your own account"><i class="fa-solid fa-trash"></i></button>`
            : `<button onclick="adminToggleUser(${u.id}, ${!u.is_active})" class="text-orange-600 mr-2" title="Enable or disable login">${u.is_active ? "disable" : "enable"}</button>
               <button onclick="adminDeleteUser(${u.id}, '${esc(u.username)}')" class="text-red-600" title="Delete"><i class="fa-solid fa-trash"></i></button>`}
        </td></tr>`).join("")}</tbody></table>
    </div>`;
}

async function renderPeopleGroups(pane) {
  const [groups, users] = await Promise.all([apiFetch("/groups"), apiFetch("/users")]);
  const roster = await Promise.all((groups || []).map((g) =>
    apiFetch(`/groups/${g.id}/users`).catch(() => [])));
  pane.innerHTML = `
    <h3 class="font-bold mb-2">Groups</h3>
    <div class="flex gap-2 mb-3 flex-wrap">
      <input id="ng-name" placeholder="Group name" class="border p-2 rounded" />
      <input id="ng-desc" placeholder="Description" class="border p-2 rounded flex-1" />
      <button onclick="adminCreateGroup()" class="px-3 py-1 bg-blue-600 text-white rounded">Add group</button>
    </div>
    ${(groups || []).map((g, i) => {
      const members = roster[i] || [];
      const nonMembers = (users || []).filter((u) => !members.some((m) => m.id === u.id));
      return `<div class="bg-white rounded shadow p-3 mb-2">
        <div class="flex justify-between items-center flex-wrap gap-2">
          <div><b>${esc(g.name)}</b> <span class="text-xs text-gray-400">${members.length} member(s)</span>
            <div class="text-xs text-gray-500">${esc(g.description || "")}</div></div>
          <span class="whitespace-nowrap">
            <button onclick="adminRenameGroup(${g.id}, '${esc(g.name)}', '${esc(g.description || "")}')" class="text-blue-600 mr-2">rename</button>
            <button onclick="adminDeleteGroup(${g.id}, '${esc(g.name)}')" class="text-red-600"><i class="fa-solid fa-trash"></i></button>
          </span>
        </div>
        <div class="flex flex-wrap gap-1 mt-2">
          ${members.map((m) => `<span class="tag-chip">${esc(m.username)}
            <button onclick="peopleRemoveMember(${g.id}, ${m.id})" title="Remove from group">×</button></span>`).join("")
            || '<span class="text-xs text-gray-400">No members yet</span>'}
        </div>
        <div class="flex gap-2 mt-2">
          <select id="gsel-${g.id}" class="border p-1 rounded text-sm">
            ${nonMembers.map((u) => `<option value="${u.id}">${esc(u.username)}</option>`).join("")
              || '<option value="">— all users assigned —</option>'}
          </select>
          <button onclick="adminAddMember(${g.id})" class="text-blue-600 text-sm">Add member</button>
        </div>
      </div>`;
    }).join("") || '<p class="text-gray-400">No groups yet.</p>'}`;
}

async function refreshPeopleOrAdmin(tab) {
  if (currentNav === "contacts") await renderContacts();
  else await adminTab(tab);
}

async function peopleSetUserRole(id, role) {
  try {
    await apiFetch(`/users/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role }) });
    toast(`Role set to ${role}`);
    refreshPeopleOrAdmin("users");
  } catch (e) { alert(e.message); }
}

async function peopleEditUserEmail(id, current) {
  const email = prompt("Email address", current);
  if (email == null) return;
  try {
    await apiFetch(`/users/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
    refreshPeopleOrAdmin("users");
  } catch (e) { alert(e.message); }
}

async function peopleRemoveMember(groupId, userId) {
  await apiFetch(`/groups/${groupId}/users/${userId}`, { method: "DELETE" });
  refreshPeopleOrAdmin("groups");
}

async function createContact() {
  await apiFetch("/contacts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: val("ct-name"), organization: val("ct-org"), email: val("ct-email"), kind: val("ct-kind") }),
  });
  loadCatalog();
  renderContacts();
}
async function delContact(id) {
  await apiFetch(`/contacts/${id}`, { method: "DELETE" });
  loadCatalog();
  renderContacts();
}

async function renderSettings() {
  const quota = await apiFetch("/quota").catch(() => ({ used: 0, limit: 0 }));
  const keys = (await apiFetch("/apikeys").catch(() => [])) || [];
  const logins = (await apiFetch("/logins").catch(() => [])) || [];
  const devices = (await apiFetch("/devices").catch(() => [])) || [];
  const hours = currentUser.working_hours || {};
  $("work-settings").innerHTML = `
    <h2 class="text-lg font-bold mb-3">User settings</h2>
    <div class="grid md:grid-cols-2 gap-4">
      <div class="bg-white rounded shadow p-4">
        <h3 class="font-bold mb-2">Appearance</h3>
        <button onclick="toggleTheme()" class="px-3 py-1 border rounded mb-2">Toggle light / dark</button>
        <p>Language <input id="set-locale" value="${esc(currentUser.locale || "en")}" class="border p-1" /></p>
        <p>Density <select id="set-den"><option>compact</option><option ${currentUser.density === "standard" ? "selected" : ""}>standard</option><option>comfortable</option></select></p>
        <p>Avatar URL <input id="set-av" value="${esc(currentUser.avatar || "")}" class="border p-1 w-full" /></p>
        <button class="tb primary mt-2" onclick="saveAccountProfile()">Save</button>
      </div>
      <div class="bg-white rounded shadow p-4">
        <h3 class="font-bold mb-2">Two-factor authentication (TOTP)</h3>
        <p class="text-sm mb-2">Status: <b>${currentUser.totp_enabled ? "enabled" : "disabled"}</b></p>
        <div id="totp-box"></div>
        ${currentUser.totp_enabled
          ? `<input id="totp-off" placeholder="Authenticator code" class="border p-2 rounded w-full mb-2" />
             <button onclick="disableTotp()" class="bg-red-600 text-white px-3 py-1 rounded">Disable 2FA</button>`
          : `<button onclick="setupTotp()" class="bg-blue-600 text-white px-3 py-1 rounded">Set up 2FA</button>`}
      </div>
      <div class="bg-white rounded shadow p-4">
        <h3 class="font-bold mb-2">Quota</h3>
        <p>${formatBytes(quota.used)} used of ${quota.limit ? formatBytes(quota.limit) : "unlimited"}</p>
      </div>
      <div class="bg-white rounded shadow p-4">
        <h3 class="font-bold mb-2">Working hours</h3>
        <input id="wh-json" class="w-full border p-1" value='${esc(JSON.stringify(hours.start ? hours : { start: "09:00", end: "17:00", days: "Mon-Fri" }))}' />
        <button class="tb mt-1" onclick="saveWorkingHours()">Save hours</button>
      </div>
      <div class="bg-white rounded shadow p-4">
        <h3 class="font-bold mb-2">API keys</h3>
        <div class="flex gap-1 mb-2"><input id="ak-name" placeholder="Name" class="border p-1 flex-1" /><button class="tb primary" onclick="createApiKey()">Create</button></div>
        <ul>${keys.map((k) => `<li>${esc(k.name)} · ${esc(k.prefix)}… <button onclick="delApiKey(${k.id})">revoke</button></li>`).join("") || "<li>None</li>"}</ul>
      </div>
      <div class="bg-white rounded shadow p-4">
        <h3 class="font-bold mb-2">Trusted devices</h3>
        <div class="flex gap-1 mb-2"><input id="dv-name" placeholder="This browser" class="border p-1 flex-1" /><button class="tb" onclick="trustDevice()">Trust</button></div>
        <ul>${devices.map((d) => `<li>${esc(d.name || d.user_agent || "")} <button onclick="delDevice(${d.id})">×</button></li>`).join("") || "<li>None</li>"}</ul>
        <h4 class="font-bold mt-2">Last logins</h4>
        <ul>${logins.slice(0, 8).map((l) => `<li>${esc(l.username || "")} ${l.success ? "ok" : "fail"} ${fmtDate(l.created_at)}</li>`).join("") || "<li>None</li>"}</ul>
      </div>
    </div>`;
}
async function saveAccountProfile() {
  await apiFetch("/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ locale: val("set-locale"), density: val("set-den"), avatar: val("set-av") }) });
  currentUser.locale = val("set-locale"); currentUser.density = val("set-den"); currentUser.avatar = val("set-av");
  document.documentElement.dataset.density = val("set-den");
  alert("Saved");
}
async function saveWorkingHours() {
  await apiFetch("/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ working_hours: JSON.parse(val("wh-json")) }) });
  alert("Saved");
}
async function createApiKey() {
  const r = await apiFetch("/apikeys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("ak-name") || "key" }) });
  alert("Copy this secret now: " + r.secret);
  renderSettings();
}
async function delApiKey(id) { await apiFetch(`/apikeys/${id}`, { method: "DELETE" }); renderSettings(); }
async function trustDevice() {
  await apiFetch("/devices", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("dv-name") || navigator.userAgent, fingerprint: (navigator.userAgent || "browser") + "|" + location.host }) });
  renderSettings();
}
async function delDevice(id) { await apiFetch(`/devices/${id}`, { method: "DELETE" }); renderSettings(); }
async function setupTotp() {
  const r = await apiFetch("/auth/totp/setup", { method: "POST" });
  $("totp-box").innerHTML = `
    <p class="text-xs break-all mb-2">Secret: <code>${esc(r.secret)}</code></p>
    <p class="text-xs text-gray-500 mb-2">Add to an authenticator app, then confirm.</p>
    <input id="totp-on" placeholder="Code" class="border p-2 rounded w-full mb-2" />
    <button onclick="enableTotp()" class="bg-emerald-600 text-white px-3 py-1 rounded">Enable</button>`;
}
async function enableTotp() {
  const form = new FormData();
  form.append("code", val("totp-on"));
  await apiFetch("/auth/totp/enable", { method: "POST", body: form });
  currentUser.totp_enabled = true;
  renderSettings();
}
async function disableTotp() {
  const form = new FormData();
  form.append("code", val("totp-off"));
  await apiFetch("/auth/totp/disable", { method: "POST", body: form });
  currentUser.totp_enabled = false;
  renderSettings();
}

// ---- Admin ----------------------------------------------------------------
async function adminCreateUser() {
  try {
    await apiFetch("/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: val("nu-name"), email: val("nu-email"), password: val("nu-pass"), role: val("nu-role") }),
    });
    refreshPeopleOrAdmin("users");
  } catch (e) { alert(e.message); }
}
async function adminToggleUser(id, active) {
  try {
    await apiFetch(`/users/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: active }) });
    refreshPeopleOrAdmin("users");
  } catch (e) { alert(e.message); }
}
async function adminDeleteUser(id, username) {
  if (!confirm(`Delete user "${username}"?`)) return;
  try { await apiFetch(`/users/${id}`, { method: "DELETE" }); refreshPeopleOrAdmin("users"); }
  catch (e) { alert(e.message); }
}
async function setUserQuota(id) {
  const mb = prompt("Storage quota in MB for this user (0 = unlimited)", "0");
  if (mb == null) return;
  const n = parseInt(mb, 10);
  if (Number.isNaN(n) || n < 0) return;
  await apiFetch("/quota", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: id, quota_bytes: n * 1024 * 1024 }) });
  toast("Quota saved");
  refreshPeopleOrAdmin("users");
}
async function adminCreateGroup() {
  await apiFetch("/groups", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("ng-name"), description: val("ng-desc") }) });
  refreshPeopleOrAdmin("groups");
}
async function adminDeleteGroup(id, name) {
  if (!confirm(`Delete group "${name}"?`)) return;
  await apiFetch(`/groups/${id}`, { method: "DELETE" });
  refreshPeopleOrAdmin("groups");
}
async function adminRenameGroup(id, name, description) {
  const next = prompt("New group name", name);
  if (!next) return;
  await apiFetch(`/groups/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: next, description: description || "" }) });
  refreshPeopleOrAdmin("groups");
}
async function adminAddMember(groupId) {
  const userId = parseInt($(`gsel-${groupId}`).value, 10);
  if (!userId) { alert("No user selected."); return; }
  await apiFetch(`/groups/${groupId}/users/${userId}`, { method: "POST" });
  refreshPeopleOrAdmin("groups");
}

async function adminTab(tab) {
  document.querySelectorAll(".admin-item").forEach((b) => b.classList.toggle("active", b.dataset.admin === tab));
  const content = $("admin-content");
  if (tab === "users") {
    const users = (await apiFetch("/users")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Users & RBAC</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="nu-name" placeholder="Username" class="border p-2 rounded" />
        <input id="nu-email" placeholder="Email" class="border p-2 rounded flex-1" />
        <input id="nu-pass" type="password" placeholder="Password" class="border p-2 rounded" />
        <select id="nu-role" class="border p-2 rounded"><option value="user">user</option><option value="manager">manager</option><option value="admin">admin</option><option value="superadmin">superadmin</option></select>
        <button onclick="adminCreateUser()" class="px-3 py-1 bg-blue-600 text-white rounded">Add</button>
      </div>
      <table class="w-full text-left text-sm"><thead><tr class="bg-gray-100"><th class="p-2">User</th><th>Role</th><th>Active</th><th>Quota</th><th></th></tr></thead>
      <tbody>${users.map((u) => `<tr class="border-b"><td class="p-2">${esc(u.username)}${u.id === currentUser.id ? ' <span class="text-xs text-gray-400">(you)</span>' : ""}<div class="text-xs text-gray-500">${esc(u.email || "")}</div></td><td>${esc(u.role)}</td><td>${u.is_active ? "✓" : "✗"}</td>
        <td class="text-xs">${u.quota_bytes ? formatBytes(u.quota_bytes) : '<span class="text-gray-400">unlimited</span>'}</td>
        <td class="whitespace-nowrap"><button onclick="setUserQuota(${u.id})" class="text-blue-600 mr-2">quota</button>
        ${u.id === currentUser.id
          ? `<button disabled class="text-gray-400 mr-2" title="You cannot deactivate your own account">${u.is_active ? "disable" : "enable"}</button>
             <button disabled class="text-gray-400" title="You cannot delete your own account"><i class="fa-solid fa-trash"></i></button>`
          : `<button onclick="adminToggleUser(${u.id}, ${!u.is_active})" class="text-orange-600 mr-2" title="Enable or disable login">${u.is_active ? "disable" : "enable"}</button>
             <button onclick="adminDeleteUser(${u.id}, '${esc(u.username)}')" class="text-red-600"><i class="fa-solid fa-trash"></i></button>`}</td></tr>`).join("")}</tbody></table>`;
  } else if (tab === "groups") {
    const [groups, users] = await Promise.all([apiFetch("/groups"), apiFetch("/users")]);
    content.innerHTML = `
      <h3 class="font-bold mb-2">Groups</h3>
      <div class="flex gap-2 mb-3"><input id="ng-name" placeholder="Name" class="border p-2 rounded" /><input id="ng-desc" placeholder="Description" class="border p-2 rounded flex-1" />
        <button onclick="adminCreateGroup()" class="px-3 py-1 bg-blue-600 text-white rounded">Add</button></div>
      ${(groups || []).map((g) => `<div class="border rounded p-2 mb-2"><div class="flex justify-between"><b>${esc(g.name)}</b>
        <span>
            <button onclick="adminRenameGroup(${g.id}, '${esc(g.name)}', '${esc(g.description || "")}')" class="text-blue-600 mr-2">rename</button>
            <button onclick="adminDeleteGroup(${g.id}, '${esc(g.name)}')" class="text-red-600"><i class="fa-solid fa-trash"></i></button>
          </span></div>
        <p class="text-xs text-gray-500">${esc(g.description || "")}</p>
        <div class="flex gap-2 mt-2"><select id="gsel-${g.id}" class="border p-1 rounded text-sm">${(users || []).map((u) => `<option value="${u.id}">${esc(u.username)}</option>`).join("")}</select>
        <button onclick="adminAddMember(${g.id})" class="text-blue-600 text-sm">Add member</button></div></div>`).join("")}`;
  } else if (tab === "jobs") {
    const jobs = (await apiFetch("/jobs")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Processing jobs</h3>
      <button onclick="runJobsNow()" class="px-3 py-1 bg-emerald-600 text-white rounded mb-3">Run queued jobs</button>
      <table class="w-full text-sm"><thead><tr class="bg-gray-100"><th class="p-2">ID</th><th>Kind</th><th>Doc</th><th>Status</th><th>Message</th><th></th></tr></thead>
      <tbody>${jobs.map((j) => `<tr class="border-b"><td class="p-2">${j.id}</td><td>${esc(j.kind)}</td><td>${j.document_id || ""}</td><td>${esc(j.status)}</td>
        <td class="text-xs">${esc((j.message || "").slice(0, 80))}</td>
        <td>${j.status === "queued" || j.status === "running" ? `<button onclick="cancelJob(${j.id})" class="text-red-600">cancel</button>` : ""}</td></tr>`).join("")}</tbody></table>`;
  } else if (tab === "intelligence") {
    const [tags, fields] = await Promise.all([apiFetch("/tags"), apiFetch("/custom-fields")]);
    content.innerHTML = `
      <h3 class="font-bold mb-2">Tag catalog & custom fields</h3>
      <div class="flex gap-2 mb-2"><input id="tg-name" placeholder="Tag" class="border p-2 rounded" /><button onclick="createTag()" class="px-3 py-1 bg-blue-600 text-white rounded">Add tag</button></div>
      <p class="mb-3">${(tags || []).map((t) => `<span class="tag-chip">${esc(t.name)} <button onclick="delTag(${t.id})">×</button></span>`).join("")}</p>
      <div class="flex gap-2 mb-2"><input id="cf-name" placeholder="Field name" class="border p-2 rounded" />
        <select id="cf-type" class="border p-2 rounded"><option>text</option><option>number</option><option>date</option><option>bool</option><option>money</option></select>
        <button onclick="createField()" class="px-3 py-1 bg-blue-600 text-white rounded">Add field</button></div>
      <p>${(fields || []).map((f) => `${esc(f.name)} (${esc(f.ftype)}) <button class="text-red-600" onclick="delField(${f.id})">×</button>`).join(" · ")}</p>`;
  } else if (tab === "uploads") {
    const opens = (await apiFetch("/open-uploads")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Anonymous upload URLs</h3>
      <div class="flex gap-2 mb-2 flex-wrap">
        <input id="ou-name" placeholder="Name" class="border p-2 rounded" />
        <input id="ou-folder" type="number" placeholder="Folder id" class="border p-2 rounded w-28" value="${currentFolderId || ""}" />
        <input id="ou-tags" placeholder="Tags" class="border p-2 rounded" />
        <button onclick="createOpenUpload()" class="px-3 py-1 bg-blue-600 text-white rounded">Create</button>
      </div>
      <ul>${opens.map((o) => `<li class="border-b p-2 text-sm">${esc(o.name)} — <a class="text-blue-600" href="${o.url}" target="_blank">${location.origin}${o.url}</a>
        (${o.upload_count}/${o.max_files}) <button class="text-red-600" onclick="delOpen(${o.id})">revoke</button></li>`).join("") || '<li class="text-gray-400">None</li>'}</ul>`;
  } else if (tab === "templates") {
    const tpls = (await apiFetch("/metadata-templates")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Metadata templates</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="tpl-name" placeholder="Name" class="border p-2 rounded" />
        <input id="tpl-desc" placeholder="Description" class="border p-2 rounded flex-1" />
        <input id="tpl-fields" placeholder='[{"key":"customer","default":""}]' class="border p-2 rounded flex-1" />
        <button onclick="createTemplate()" class="px-3 py-1 bg-blue-600 text-white rounded">Add</button>
      </div>
      <table class="w-full text-sm"><tbody>${tpls.map((t) => `<tr class="border-b"><td class="p-2">${esc(t.name)}</td><td class="text-xs">${esc(JSON.stringify(t.fields || []))}</td>
        <td><button onclick="delTemplate(${t.id})" class="text-red-600"><i class="fa-solid fa-trash"></i></button></td></tr>`).join("")}</tbody></table>`;
  } else if (tab === "imports") {
    const imps = (await apiFetch("/import/folders")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Watched import folders</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <select id="imp-proto"><option value="local">local</option><option value="ftp">ftp</option><option value="imap">imap (one-shot below)</option></select>
        <input id="imp-name" placeholder="Name" class="border p-2 rounded" />
        <input id="imp-path" placeholder="Local path or remote path" class="border p-2 rounded flex-1" />
        <input id="imp-host" placeholder="Host (ftp)" class="border p-2 rounded" />
        <input id="imp-user" placeholder="User" class="border p-2 rounded" />
        <input id="imp-pass" type="password" placeholder="Password" class="border p-2 rounded" />
        <input id="imp-target" type="number" placeholder="Target folder" class="border p-2 rounded w-32" />
        <label class="text-sm flex items-center gap-1"><input id="imp-del" type="checkbox" /> Move source</label>
        <button onclick="createImport()" class="px-3 py-1 bg-blue-600 text-white rounded">Add</button>
      </div>
      <h4 class="font-semibold text-sm mb-1">IMAP import (one-shot)</h4>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="em-host" placeholder="IMAP host" class="border p-2 rounded" />
        <input id="em-user" placeholder="User" class="border p-2 rounded" />
        <input id="em-pass" type="password" placeholder="Password" class="border p-2 rounded" />
        <input id="em-target" type="number" placeholder="Folder id" class="border p-2 rounded w-28" />
        <button onclick="runEmailImport()" class="px-3 py-1 bg-emerald-600 text-white rounded">Import</button>
      </div>
      <table class="w-full text-sm"><thead><tr class="bg-gray-100"><th class="p-2">Name</th><th>Path</th><th>Target</th><th></th></tr></thead>
      <tbody>${imps.map((i) => `<tr class="border-b"><td class="p-2">${esc(i.name)} <span class="text-xs">${esc(i.protocol || "local")}</span></td><td>${esc(i.local_path || i.host || "")}</td><td>#${i.target_folder_id}</td>
        <td><button onclick="scanImport(${i.id})" class="text-emerald-600 mr-2"><i class="fa-solid fa-arrows-rotate"></i></button>
        <button onclick="delImport(${i.id})" class="text-red-600"><i class="fa-solid fa-trash"></i></button></td></tr>`).join("")}</tbody></table>`;
  } else if (tab === "mail") {
    const rows = (await apiFetch("/mail-settings")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">SMTP / IMAP accounts</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <select id="ms-kind" class="border p-2 rounded"><option value="smtp">smtp</option><option value="imap">imap</option></select>
        <input id="ms-name" placeholder="Name" class="border p-2 rounded" />
        <input id="ms-host" placeholder="Host" class="border p-2 rounded" />
        <input id="ms-port" type="number" value="587" class="border p-2 rounded w-20" />
        <input id="ms-user" placeholder="Username" class="border p-2 rounded" />
        <input id="ms-pass" type="password" placeholder="Password" class="border p-2 rounded" />
        <button onclick="createMail()" class="px-3 py-1 bg-blue-600 text-white rounded">Save</button>
      </div>
      <ul>${rows.map((r) => `<li class="border-b p-2">${esc(r.kind)} · ${esc(r.name)} · ${esc(r.host)}:${r.port}
        <button class="text-red-600" onclick="delMail(${r.id})">delete</button></li>`).join("") || '<li class="text-gray-400">None configured</li>'}</ul>`;
  } else if (tab === "retention") {
    const pols = (await apiFetch("/retention-policies")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Retention policies</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="ret-name" placeholder="Name" class="border p-2 rounded" />
        <input id="ret-folder" type="number" placeholder="Folder id (blank=all)" class="border p-2 rounded w-40" />
        <input id="ret-years" type="number" value="7" class="border p-2 rounded w-20" />
        <select id="ret-action" class="border p-2 rounded"><option value="archive">archive</option><option value="delete">delete</option></select>
        <button onclick="createPolicy()" class="px-3 py-1 bg-blue-600 text-white rounded">Add</button>
        <button onclick="applyPolicies()" class="px-3 py-1 bg-amber-600 text-white rounded">Apply now</button>
      </div>
      <table class="w-full text-sm"><tbody>${pols.map((p) => `<tr class="border-b"><td class="p-2">${esc(p.name)}</td><td>${p.folder_id ? "#" + p.folder_id : "all"}</td><td>${p.years}y</td><td>${esc(p.action)}</td>
        <td><button onclick="delPolicy(${p.id})" class="text-red-600"><i class="fa-solid fa-trash"></i></button></td></tr>`).join("")}</tbody></table>`;
  } else if (tab === "workflows") {
    const wfs = (await apiFetch("/workflows")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Workflow templates</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="wf-name" placeholder="Name" class="border p-2 rounded" />
        <input id="wf-desc" placeholder="Description" class="border p-2 rounded" />
        <input id="wf-steps" placeholder='[{"name":"Review","assignee_role":"admin","due_days":3}]' class="border p-2 rounded flex-1" />
        <button onclick="createWorkflowTpl()" class="px-3 py-1 bg-blue-600 text-white rounded">Add</button>
      </div>
      <table class="w-full text-sm"><tbody>${wfs.map((w) => `<tr class="border-b"><td class="p-2">${esc(w.name)}</td><td class="text-xs">${esc(JSON.stringify(w.steps || []))}</td>
        <td><button onclick="showWfDesigner(${w.id})" class="text-blue-600 mr-2">Designer</button>
        <button onclick="delWorkflowTpl(${w.id})" class="text-red-600"><i class="fa-solid fa-trash"></i></button></td></tr>
        <tr><td colspan="3"><div id="wf-des-${w.id}"></div></td></tr>`).join("")}</tbody></table>`;
  } else if (tab === "addons") {
    const addons = (await apiFetch("/addons")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Addons / webhooks (on_process)</h3>
      <div class="flex gap-2 mb-3">
        <input id="ad-name" placeholder="Name" class="border p-2 rounded" />
        <input id="ad-url" placeholder="https://example/webhook" class="border p-2 rounded flex-1" />
        <button onclick="createAddon()" class="px-3 py-1 bg-blue-600 text-white rounded">Add</button>
      </div>
      <ul>${addons.map((a) => `<li class="border-b p-2">${esc(a.name)} · ${esc(a.webhook_url)}
        <button class="text-red-600" onclick="delAddon(${a.id})">delete</button></li>`).join("") || '<li class="text-gray-400">None</li>'}</ul>`;
  } else if (tab === "reports") {
    const r = await apiFetch("/reports/summary");
    const facets = await apiFetch("/facets");
    content.innerHTML = `
      <h3 class="font-bold mb-2">Reports & facets</h3>
      <div class="grid grid-cols-4 gap-3 mb-4">
        ${[["Users", r.users], ["Groups", r.groups], ["Folders", r.folders], ["Documents", r.documents]].map(([k, v]) =>
          `<div class="bg-gray-50 border rounded p-3 text-center"><div class="text-2xl font-bold">${v}</div><div class="text-sm text-gray-500">${k}</div></div>`).join("")}
      </div>
      <p class="mb-2"><b>Storage:</b> ${formatBytes(r.total_size)} · <b>Downloads 30d:</b> ${r.recent_downloads} · <b>Overdue:</b> ${facets.overdue}</p>
      <p class="mb-2"><b>Status:</b> ${Object.entries(r.by_status || {}).map(([k, v]) => `${esc(k)}: ${v}`).join(", ") || "none"}</p>
      <p class="mb-2"><b>Types:</b> ${Object.entries(facets.by_extension || {}).map(([k, v]) => `${esc(k)}: ${v}`).join(", ") || "none"}</p>
      <p><b>Tags:</b> ${Object.entries(facets.by_tag || {}).map(([k, v]) => `${esc(k)} (${v})`).join(", ") || "none"}</p>
      <div id="report-suites" class="mt-4"></div>`;
    if (typeof ceAdminTab === "function") {
      const extra = document.createElement("div");
      extra.id = "report-suites-body";
      content.appendChild(extra);
      const locked = await apiFetch("/reports/locked").catch(() => []);
      const dups = await apiFetch("/reports/duplicates").catch(() => []);
      const archived = await apiFetch("/reports/archived").catch(() => []);
      const deleted = await apiFetch("/reports/deleted").catch(() => ({ documents: [], folders: [] }));
      extra.innerHTML = `<h4 class="font-bold mt-3">Locked / checkout</h4><p>${(locked || []).length} documents</p>
        <h4 class="font-bold mt-2">Duplicates</h4><p>${(dups || []).length}</p>
        <h4 class="font-bold mt-2">Archived</h4><p>${(archived || []).length}</p>
        <h4 class="font-bold mt-2">Deleted</h4><p>${((deleted && deleted.documents) || []).length} documents · ${((deleted && deleted.folders) || []).length} folders</p>`;
    }
  } else if (tab === "backup") {
    const backups = (await apiFetch("/backup")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Backups</h3>
      <button onclick="runBackup()" class="px-3 py-1 bg-blue-600 text-white rounded mb-3">Create backup now</button>
      <ul>${backups.length ? backups.map((b) => `<li class="border-b p-2">${esc(b.file)} — ${formatBytes(b.size)}</li>`).join("") : '<li class="text-gray-400 p-2">No backups yet</li>'}</ul>`;
  } else if (tab === "audit") {
    const logs = (await apiFetch("/audit")) || [];
    content.innerHTML = `
      <h3 class="font-bold mb-2">Audit trail</h3>
      <table class="w-full text-sm"><thead><tr class="bg-gray-100"><th class="p-2">Action</th><th>Resource</th><th>Details</th><th>Time</th></tr></thead>
      <tbody>${logs.map((l) => `<tr class="border-b"><td class="p-2">${esc(l.action)}</td><td>${esc(l.resource_type || "")} ${l.resource_id || ""}</td>
        <td>${esc((l.details || "").slice(0, 80))}</td><td>${fmtDate(l.timestamp)}</td></tr>`).join("")}</tbody></table>`;
  } else if (typeof ceAdminTab === "function") {
    await ceAdminTab(tab, content);
  }
}

async function runJobsNow() { await apiFetch("/jobs/run", { method: "POST" }); adminTab("jobs"); }
async function cancelJob(id) { await apiFetch(`/jobs/${id}/cancel`, { method: "POST" }); adminTab("jobs"); }
async function createTag() {
  await apiFetch("/tags", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("tg-name") }) });
  loadCatalog(); adminTab("intelligence");
}
async function delTag(id) { await apiFetch(`/tags/${id}`, { method: "DELETE" }); loadCatalog(); adminTab("intelligence"); }
async function createField() {
  await apiFetch("/custom-fields", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("cf-name"), ftype: val("cf-type") }) });
  loadCatalog(); adminTab("intelligence");
}
async function delField(id) { await apiFetch(`/custom-fields/${id}`, { method: "DELETE" }); loadCatalog(); adminTab("intelligence"); }
async function createOpenUpload() {
  await apiFetch("/open-uploads", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("ou-name"), folder_id: parseInt(val("ou-folder"), 10), tags: val("ou-tags") }) });
  adminTab("uploads");
}
async function delOpen(id) { await apiFetch(`/open-uploads/${id}`, { method: "DELETE" }); adminTab("uploads"); }
async function createTemplate() {
  const fields = val("tpl-fields") ? JSON.parse(val("tpl-fields")) : [];
  await apiFetch("/metadata-templates", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("tpl-name"), description: val("tpl-desc"), fields }) });
  adminTab("templates");
}
async function delTemplate(id) { await apiFetch(`/metadata-templates/${id}`, { method: "DELETE" }); adminTab("templates"); }
async function createImport() {
  await apiFetch("/import/folders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("imp-name"), local_path: val("imp-path"), target_folder_id: parseInt(val("imp-target"), 10), delete_after_import: $("imp-del").checked, protocol: val("imp-proto") || "local", host: val("imp-host") || null, username: val("imp-user") || null, password: val("imp-pass") || null, remote_path: val("imp-path") || null }) });
  adminTab("imports");
}
async function scanImport(id) {
  const r = await apiFetch(`/import/folders/${id}/scan`, { method: "POST" });
  alert(`Scanned ${r.scanned}, imported ${r.imported}`);
  adminTab("imports");
}
async function delImport(id) { await apiFetch(`/import/folders/${id}`, { method: "DELETE" }); adminTab("imports"); }
async function runEmailImport() {
  const r = await apiFetch("/import/email", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ host: val("em-host"), username: val("em-user"), password: val("em-pass"), target_folder_id: parseInt(val("em-target"), 10) }) });
  alert(`Imported ${r.imported} attachments`);
}
async function createMail() {
  await apiFetch("/mail-settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: val("ms-kind"), name: val("ms-name"), host: val("ms-host"), port: parseInt(val("ms-port"), 10), username: val("ms-user"), password: val("ms-pass") }) });
  adminTab("mail");
}
async function delMail(id) { await apiFetch(`/mail-settings/${id}`, { method: "DELETE" }); adminTab("mail"); }
async function createPolicy() {
  await apiFetch("/retention-policies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("ret-name"), folder_id: val("ret-folder") ? parseInt(val("ret-folder"), 10) : null, years: parseInt(val("ret-years"), 10) || 7, action: val("ret-action") }) });
  adminTab("retention");
}
async function delPolicy(id) { await apiFetch(`/retention-policies/${id}`, { method: "DELETE" }); adminTab("retention"); }
async function applyPolicies() {
  if (!confirm("Apply all retention policies now?")) return;
  const r = await apiFetch("/retention-policies/apply", { method: "POST" });
  alert(`Affected ${r.affected} documents`);
}
async function createWorkflowTpl() {
  const steps = val("wf-steps") ? JSON.parse(val("wf-steps")) : [];
  await apiFetch("/workflows", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("wf-name"), description: val("wf-desc"), steps }) });
  adminTab("workflows");
}
async function delWorkflowTpl(id) { await apiFetch(`/workflows/${id}`, { method: "DELETE" }); adminTab("workflows"); }
async function showWfDesigner(id) {
  const wfs = (await apiFetch("/workflows")) || [];
  const w = wfs.find((x) => x.id === id);
  if (!w) return;
  const steps = w.steps || [];
  const graph = w.graph || { nodes: steps.map((s, i) => ({ id: i, name: s.name })), edges: steps.slice(1).map((_, i) => ({ from: i, to: i + 1 })) };
  $(`wf-des-${id}`).innerHTML = `<div class="wf-designer">
    ${steps.map((s, i) => `<div class="wf-node">${esc(s.name)} <small>${esc(s.assignee_role || "")}</small></div>${i < steps.length - 1 ? '<div class="wf-arrow">↓</div>' : ""}`).join("") || "<p>No steps</p>"}
    <textarea id="wf-graph-${id}" rows="8" class="w-full border mt-2">${esc(JSON.stringify(graph, null, 2))}</textarea>
    <input id="wf-steps-${id}" class="w-full border mt-1" value='${esc(JSON.stringify(steps))}' />
    <button class="tb primary mt-1" onclick="saveWfGraph(${id})">Save graph &amp; triggers</button>
  </div>`;
}
async function saveWfGraph(id) {
  const graph = JSON.parse(val(`wf-graph-${id}`));
  const steps = JSON.parse(val(`wf-steps-${id}`));
  await apiFetch(`/workflows/${id}/graph`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ graph, steps }) });
  alert("Workflow saved");
}
async function createAddon() {
  await apiFetch("/addons", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("ad-name"), webhook_url: val("ad-url") }) });
  adminTab("addons");
}
async function delAddon(id) { await apiFetch(`/addons/${id}`, { method: "DELETE" }); adminTab("addons"); }
async function runBackup() {
  const r = await apiFetch("/backup", { method: "POST" });
  alert(`Backup ${r.file} created`);
  adminTab("backup");
}
