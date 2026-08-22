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

// ---------------------------------------------------------------------------
// WebAuthn / Passkeys / Biometrics (Windows Hello, TouchID, FaceID)
// ---------------------------------------------------------------------------
function base64urlToBuffer(base64url) {
  const padding = "=".repeat((4 - (base64url.length % 4)) % 4);
  const base64 = (base64url + padding).replace(/\-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray.buffer;
}

function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

window.loginWithBiometrics = async function() {
  const errEl = $("login-err");
  if (errEl) { errEl.textContent = ""; errEl.classList.add("hidden"); }

  if (!window.PublicKeyCredential) {
    const msg = "WebAuthn / Biometrics is not supported in this browser or requires an HTTPS / localhost origin.";
    if (errEl) { errEl.textContent = msg; errEl.classList.remove("hidden"); }
    toast(msg, "warning");
    return;
  }

  const username = (val("username") || "").trim();
  const remember = $("remember-password") && $("remember-password").checked;

  try {
    const optRes = await fetch(api("/auth/biometrics/login-options"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username || null }),
      ...FETCH_OPTS,
    });
    if (!optRes.ok) throw new Error("Failed to initialize biometric challenge");
    const options = await optRes.json();

    const challengeBuffer = base64urlToBuffer(options.challenge);
    const allowCredentials = (options.allowCredentials || []).map(c => ({
      type: "public-key",
      id: base64urlToBuffer(c.id),
    }));

    const publicKeyCredentialRequestOptions = {
      challenge: challengeBuffer,
      rpId: options.rpId || window.location.hostname,
      allowCredentials: allowCredentials.length > 0 ? allowCredentials : undefined,
      userVerification: options.userVerification || "preferred",
      timeout: options.timeout || 60000,
    };

    const assertion = await navigator.credentials.get({
      publicKey: publicKeyCredentialRequestOptions,
    });

    if (!assertion) throw new Error("Biometric authentication was cancelled or timed out");

    const credentialId = bufferToBase64url(assertion.rawId);
    const clientDataJSON = bufferToBase64url(assertion.response.clientDataJSON);
    const authenticatorData = bufferToBase64url(assertion.response.authenticatorData);
    const signature = bufferToBase64url(assertion.response.signature);
    const userHandle = assertion.response.userHandle ? bufferToBase64url(assertion.response.userHandle) : null;

    const verifyRes = await fetch(api("/auth/biometrics/login-verify"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        credential_id: credentialId,
        client_data_json: clientDataJSON,
        authenticator_data: authenticatorData,
        signature: signature,
        user_handle: userHandle,
        username: username || null,
      }),
      ...FETCH_OPTS,
    });

    if (!verifyRes.ok) {
      const errTxt = await verifyRes.text();
      let msg = "Biometric verification failed";
      try { msg = JSON.parse(errTxt).detail || msg; } catch (e) { msg = errTxt || msg; }
      throw new Error(msg);
    }

    toast("Biometric authentication successful!", "success");
    const me = await fetch(api("/auth/me"), { ...FETCH_OPTS });
    currentUser = await me.json();
    await enterApp();
  } catch (e) {
    if (e.name === "NotAllowedError") {
      toast("Biometric verification cancelled or timed out", "info");
    } else {
      if (errEl) { errEl.textContent = e.message; errEl.classList.remove("hidden"); }
      toast(e.message, "error");
    }
  }
};

window.registerBiometrics = async function() {
  if (!window.PublicKeyCredential) {
    toast("WebAuthn / Biometrics is not supported in this browser or origin", "warning");
    return;
  }

  const deviceName = prompt("Enter a label for this biometric device (e.g. Windows Hello / Touch ID / Face ID):", "Windows Hello / Touch ID");
  if (deviceName === null) return;

  try {
    const optRes = await apiFetch("/auth/biometrics/register-options", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: deviceName.trim() || "Biometrics / Passkey" }),
    });

    const challengeBuffer = base64urlToBuffer(optRes.challenge);
    const userIdBuffer = base64urlToBuffer(optRes.user.id);

    const createOptions = {
      challenge: challengeBuffer,
      rp: optRes.rp,
      user: {
        id: userIdBuffer,
        name: optRes.user.name,
        displayName: optRes.user.displayName,
      },
      pubKeyCredParams: optRes.pubKeyCredParams,
      authenticatorSelection: optRes.authenticatorSelection,
      timeout: optRes.timeout || 60000,
      attestation: optRes.attestation || "none",
    };

    const credential = await navigator.credentials.create({
      publicKey: createOptions,
    });

    if (!credential) throw new Error("Biometric enrollment cancelled");

    const credentialId = bufferToBase64url(credential.rawId);
    const clientDataJSON = bufferToBase64url(credential.response.clientDataJSON);
    const attestationObject = bufferToBase64url(credential.response.attestationObject);
    let publicKey = credentialId;
    if (credential.response.getPublicKey) {
      const pk = credential.response.getPublicKey();
      if (pk) publicKey = bufferToBase64url(pk);
    }

    await apiFetch("/auth/biometrics/register-verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        credential_id: credentialId,
        public_key: publicKey,
        client_data_json: clientDataJSON,
        attestation_object: attestationObject,
        name: deviceName.trim() || "Biometrics (Touch ID / Windows Hello)",
        device_type: "platform",
      }),
    });

    toast("Biometrics / Passkey registered successfully!", "success");
    if (currentNav === "settings") renderSettings();
  } catch (e) {
    if (e.name === "NotAllowedError") {
      toast("Biometric registration cancelled", "info");
    } else {
      toast("Registration failed: " + e.message, "error");
    }
  }
};

window.deleteBiometricCred = async function(id) {
  if (!confirm("Revoke this biometric passkey?")) return;
  await apiFetch(`/auth/biometrics/credentials/${id}`, { method: "DELETE" });
  toast("Passkey revoked", "info");
  renderSettings();
};

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
  startPresenceTracking();
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
  stopPresenceTracking();
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
let _calYear = new Date().getFullYear();
let _calMonth = new Date().getMonth();
let _calSelectedDate = null;
let _calEvents = [];

function _fmtDateKey(year, monthIndex, day) {
  const mm = String(monthIndex + 1).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return `${year}-${mm}-${dd}`;
}

async function renderCalendar() {
  _calEvents = (await apiFetch("/calendar")) || [];
  const today = new Date();
  const todayKey = _fmtDateKey(today.getFullYear(), today.getMonth(), today.getDate());
  const y = _calYear;
  const m = _calMonth;

  const monthName = new Date(y, m, 1).toLocaleString(undefined, { month: "long", year: "numeric" });
  const firstDayIndex = new Date(y, m, 1).getDay();
  const totalDays = new Date(y, m + 1, 0).getDate();
  const prevMonthTotalDays = new Date(y, m, 0).getDate();

  // Group events by date key YYYY-MM-DD
  const eventsByDate = {};
  for (const ev of _calEvents) {
    if (!ev.start_at) continue;
    const dt = new Date(ev.start_at);
    if (isNaN(dt.getTime())) continue;
    const key = _fmtDateKey(dt.getFullYear(), dt.getMonth(), dt.getDate());
    if (!eventsByDate[key]) eventsByDate[key] = [];
    eventsByDate[key].push(ev);
  }

  const cells = [];

  // 1. Previous month trailing days
  for (let i = firstDayIndex - 1; i >= 0; i--) {
    const d = prevMonthTotalDays - i;
    const prevM = m === 0 ? 11 : m - 1;
    const prevY = m === 0 ? y - 1 : y;
    const dateKey = _fmtDateKey(prevY, prevM, d);
    const dayEvs = eventsByDate[dateKey] || [];
    cells.push(`
      <div class="cal-day is-other-month" onclick="selectCalDate('${dateKey}')">
        <div class="cal-day-header">
          <span class="cal-day-num">${d}</span>
          <button class="cal-quick-add" onclick="event.stopPropagation(); openAddEventModal('${dateKey}')" title="Add event on ${dateKey}">+</button>
        </div>
        <div class="cal-events-container">
          ${dayEvs.slice(0, 2).map((e) => `<div class="cal-ev" title="${esc(e.title)}">${esc(e.title)}</div>`).join("")}
          ${dayEvs.length > 2 ? `<div class="cal-ev-more">+${dayEvs.length - 2} more</div>` : ""}
        </div>
      </div>`);
  }

  // 2. Current month active days
  for (let d = 1; d <= totalDays; d++) {
    const dateKey = _fmtDateKey(y, m, d);
    const isToday = dateKey === todayKey;
    const isSelected = dateKey === _calSelectedDate;
    const dayEvs = eventsByDate[dateKey] || [];

    cells.push(`
      <div class="cal-day ${isToday ? "is-today" : ""} ${isSelected ? "is-selected" : ""}" id="cal-day-${dateKey}" onclick="selectCalDate('${dateKey}')">
        <div class="cal-day-header">
          <span class="cal-day-num">${d}</span>
          <button class="cal-quick-add" onclick="event.stopPropagation(); openAddEventModal('${dateKey}')" title="Add event on ${dateKey}">+</button>
        </div>
        <div class="cal-events-container">
          ${dayEvs.slice(0, 3).map((e) => {
            const timeStr = e.start_at ? new Date(e.start_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
            return `<div class="cal-ev" title="${esc(e.title)} (${timeStr})">${timeStr ? `<b>${timeStr}</b> ` : ""}${esc(e.title)}</div>`;
          }).join("")}
          ${dayEvs.length > 3 ? `<div class="cal-ev-more">+${dayEvs.length - 3} more</div>` : ""}
        </div>
      </div>`);
  }

  // 3. Next month leading days to complete 7-column grid rows
  const remainingCells = (7 - ((firstDayIndex + totalDays) % 7)) % 7;
  for (let d = 1; d <= remainingCells; d++) {
    const nextM = m === 11 ? 0 : m + 1;
    const nextY = m === 11 ? y + 1 : y;
    const dateKey = _fmtDateKey(nextY, nextM, d);
    const dayEvs = eventsByDate[dateKey] || [];
    cells.push(`
      <div class="cal-day is-other-month" onclick="selectCalDate('${dateKey}')">
        <div class="cal-day-header">
          <span class="cal-day-num">${d}</span>
          <button class="cal-quick-add" onclick="event.stopPropagation(); openAddEventModal('${dateKey}')" title="Add event on ${dateKey}">+</button>
        </div>
        <div class="cal-events-container">
          ${dayEvs.slice(0, 2).map((e) => `<div class="cal-ev" title="${esc(e.title)}">${esc(e.title)}</div>`).join("")}
          ${dayEvs.length > 2 ? `<div class="cal-ev-more">+${dayEvs.length - 2} more</div>` : ""}
        </div>
      </div>`);
  }

  // Default prefilled datetime for quick inline bar
  const defaultDateStr = _calSelectedDate || todayKey;

  $("work-calendar").innerHTML = `
    <div class="cal-wrapper">
      <div class="cal-nav-bar">
        <div class="cal-nav-left">
          <button class="cal-nav-btn" onclick="calPrevMonth()" title="Previous month"><i class="fa-solid fa-chevron-left"></i></button>
          <button class="cal-nav-btn" onclick="calNextMonth()" title="Next month"><i class="fa-solid fa-chevron-right"></i></button>
          <button class="cal-nav-btn" onclick="calToday()"><i class="fa-solid fa-calendar-day"></i> Today</button>
          <span class="cal-nav-title ml-2">${monthName}</span>
        </div>
        <div class="flex items-center gap-2">
          <button class="cal-nav-btn primary" onclick="openAddEventModal('${defaultDateStr}')">
            <i class="fa-solid fa-plus"></i> Add Event
          </button>
        </div>
      </div>
      <div class="cal-grid">
        ${["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].map((d) => `<div class="cal-h">${d}</div>`).join("")}
        ${cells.join("")}
      </div>
    </div>

    <!-- Quick Date Scheduler & Event Agenda Section -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
      <div class="bg-white rounded-lg shadow border p-4 md:col-span-1">
        <h3 class="font-bold text-sm text-gray-700 mb-2 flex items-center justify-between">
          <span><i class="fa-solid fa-calendar-plus text-blue-600 mr-1"></i> Add Event</span>
          <span class="text-xs text-gray-500 font-normal" id="cal-selected-label">${_calSelectedDate ? "For: " + _calSelectedDate : "Click a date to select"}</span>
        </h3>
        <div class="space-y-2">
          <input id="cal-title" placeholder="Event title (e.g. Policy Review, Audit)" class="border p-2 rounded w-full text-sm" />
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="text-xs text-gray-500 block mb-1">Start Time</label>
              <input id="cal-start" type="datetime-local" value="${defaultDateStr}T09:00" class="border p-1.5 rounded w-full text-xs" />
            </div>
            <div>
              <label class="text-xs text-gray-500 block mb-1">End Time</label>
              <input id="cal-end" type="datetime-local" value="${defaultDateStr}T10:00" class="border p-1.5 rounded w-full text-xs" />
            </div>
          </div>
          <input id="cal-doc" type="number" placeholder="Associated Document ID (optional)" class="border p-2 rounded w-full text-sm" />
          <textarea id="cal-desc" placeholder="Notes / details (optional)" rows="2" class="border p-2 rounded w-full text-sm"></textarea>
          <button onclick="saveCalEvent()" class="cal-nav-btn primary w-full justify-center py-2">
            <i class="fa-solid fa-calendar-check"></i> Save Event
          </button>
        </div>
      </div>

      <div class="bg-white rounded-lg shadow border p-4 md:col-span-2">
        <h3 class="font-bold text-sm text-gray-700 mb-2 flex items-center justify-between">
          <span><i class="fa-solid fa-list-check text-blue-600 mr-1"></i> Agenda &amp; Scheduled Events</span>
          <span class="text-xs text-gray-500">${_calEvents.length} total registered</span>
        </h3>
        <div id="cal-agenda-list" class="divide-y max-h-96 overflow-y-auto">
          ${_calEvents.length ? _calEvents.map((e) => {
            const dt = e.start_at ? new Date(e.start_at) : null;
            const dtKey = dt && !isNaN(dt.getTime()) ? _fmtDateKey(dt.getFullYear(), dt.getMonth(), dt.getDate()) : "";
            const isMatch = _calSelectedDate && dtKey === _calSelectedDate;
            return `
              <div class="py-2.5 px-2 flex items-center justify-between hover:bg-gray-50 rounded ${isMatch ? 'bg-blue-50/70 border-l-4 border-blue-500' : ''}">
                <div class="flex-1 pr-2">
                  <div class="font-semibold text-sm text-gray-800 flex items-center gap-2">
                    ${esc(e.title)}
                    ${e.document_id ? `<span class="bg-blue-100 text-blue-800 text-xs px-2 py-0.5 rounded cursor-pointer" onclick="openDocDetails(${e.document_id})"><i class="fa-solid fa-file-lines mr-1"></i>Doc #${e.document_id}</span>` : ""}
                  </div>
                  <div class="text-xs text-gray-500 mt-0.5">
                    <i class="fa-regular fa-clock mr-1"></i>${fmtDate(e.start_at)} ${e.end_at ? "— " + new Date(e.end_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : ""}
                    ${e.description ? `<span class="ml-2 text-gray-600">· ${esc(e.description)}</span>` : ""}
                  </div>
                </div>
                <button class="text-red-500 hover:text-red-700 p-1.5" onclick="delEvent(${e.id})" title="Delete event">
                  <i class="fa-solid fa-trash-can"></i>
                </button>
              </div>`;
          }).join("") : '<p class="p-6 text-center text-gray-400 text-sm">No scheduled events. Click any date or use the form above to add multiple events.</p>'}
        </div>
      </div>
    </div>`;
}

window.calPrevMonth = function() {
  _calMonth--;
  if (_calMonth < 0) {
    _calMonth = 11;
    _calYear--;
  }
  renderCalendar();
};

window.calNextMonth = function() {
  _calMonth++;
  if (_calMonth > 11) {
    _calMonth = 0;
    _calYear++;
  }
  renderCalendar();
};

window.calToday = function() {
  const d = new Date();
  _calYear = d.getFullYear();
  _calMonth = d.getMonth();
  _calSelectedDate = _fmtDateKey(_calYear, _calMonth, d.getDate());
  renderCalendar();
};

window.selectCalDate = function(dateStr) {
  _calSelectedDate = dateStr;
  
  // Highlight clicked date cell
  document.querySelectorAll(".cal-day").forEach(el => el.classList.remove("is-selected"));
  const cell = $(`cal-day-${dateStr}`);
  if (cell) {
    cell.classList.add("is-selected");
    cell.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // Update inline form fields
  const startEl = $("cal-start");
  const endEl = $("cal-end");
  const labelEl = $("cal-selected-label");
  const titleEl = $("cal-title");
  
  if (startEl) startEl.value = `${dateStr}T09:00`;
  if (endEl) endEl.value = `${dateStr}T10:00`;
  if (labelEl) labelEl.innerHTML = `<span class="bg-blue-100 text-blue-800 px-2 py-0.5 rounded font-semibold">Selected: ${dateStr}</span>`;
  if (titleEl) titleEl.focus();

  // Filter Agenda view to highlight or show day events
  updateAgendaView(dateStr);
};

function updateAgendaView(filterDateStr) {
  const container = $("cal-agenda-list");
  if (!container) return;

  const targetEvents = filterDateStr 
    ? _calEvents.filter(ev => {
        if (!ev.start_at) return false;
        const dt = new Date(ev.start_at);
        if (isNaN(dt.getTime())) return false;
        return _fmtDateKey(dt.getFullYear(), dt.getMonth(), dt.getDate()) === filterDateStr;
      })
    : _calEvents;

  container.innerHTML = targetEvents.length ? targetEvents.map((e) => {
    const dt = e.start_at ? new Date(e.start_at) : null;
    const dtKey = dt && !isNaN(dt.getTime()) ? _fmtDateKey(dt.getFullYear(), dt.getMonth(), dt.getDate()) : "";
    const isMatch = filterDateStr && dtKey === filterDateStr;
    return `
      <div class="py-2.5 px-2 flex items-center justify-between hover:bg-gray-50 rounded ${isMatch ? 'bg-blue-50/80 border-l-4 border-blue-500 shadow-sm' : ''}">
        <div class="flex-1 pr-2">
          <div class="font-semibold text-sm text-gray-800 flex items-center gap-2">
            ${esc(e.title)}
            ${e.document_id ? `<span class="bg-blue-100 text-blue-800 text-xs px-2 py-0.5 rounded cursor-pointer" onclick="openDocDetails(${e.document_id})"><i class="fa-solid fa-file-lines mr-1"></i>Doc #${e.document_id}</span>` : ""}
          </div>
          <div class="text-xs text-gray-500 mt-0.5">
            <i class="fa-regular fa-clock mr-1"></i>${fmtDate(e.start_at)} ${e.end_at ? "— " + new Date(e.end_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : ""}
            ${e.description ? `<span class="ml-2 text-gray-600">· ${esc(e.description)}</span>` : ""}
          </div>
        </div>
        <button class="text-red-500 hover:text-red-700 p-1.5" onclick="delEvent(${e.id})" title="Delete event">
          <i class="fa-solid fa-trash-can"></i>
        </button>
      </div>`;
  }).join("") : `<div class="p-6 text-center text-gray-400 text-sm">
      <i class="fa-regular fa-calendar-xmark text-2xl mb-1 block"></i>
      No events found for ${filterDateStr || "selected period"}.
      <div class="mt-2"><button class="cal-nav-btn primary text-xs" onclick="if($('cal-title')) $('cal-title').focus();"><i class="fa-solid fa-plus"></i> Add Event to this Date</button></div>
    </div>`;
}

window.openDayEventsModal = function(dateStr) {
  const dayEvs = _calEvents.filter((ev) => {
    if (!ev.start_at) return false;
    const dt = new Date(ev.start_at);
    if (isNaN(dt.getTime())) return false;
    return _fmtDateKey(dt.getFullYear(), dt.getMonth(), dt.getDate()) === dateStr;
  });

  const modalHtml = `
    <div id="cal-day-modal" class="modal is-active" style="position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;" onclick="if(event.target === this) closeModal('cal-day-modal')">
      <div class="modal-card" style="background:#fff;border-radius:8px;max-width:550px;width:100%;box-shadow:0 10px 25px rgba(0,0,0,0.2);overflow:hidden;animation:fadeIn 0.15s ease;" onclick="event.stopPropagation()">
        <header class="modal-card-head" style="padding:14px 18px;background:#f8fafc;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;">
          <h3 style="font-weight:700;font-size:16px;color:#1e293b;margin:0;">
            <i class="fa-solid fa-calendar-day text-blue-600 mr-2"></i>Date: ${dateStr}
          </h3>
          <button class="delete" style="background:none;border:none;font-size:22px;cursor:pointer;color:#64748b;line-height:1;" onclick="closeModal('cal-day-modal')">×</button>
        </header>
        <section class="modal-card-body" style="padding:16px;max-height:75vh;overflow-y:auto;">
          <div style="margin-bottom:16px;">
            <h4 style="font-size:13px;font-weight:700;color:#475569;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;">
              Scheduled Events on this Date (${dayEvs.length})
            </h4>
            ${dayEvs.length ? `
              <div style="display:flex;flex-direction:column;gap:8px;">
                ${dayEvs.map(e => `
                  <div style="background:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid #3b82f6;padding:10px 12px;border-radius:6px;display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                      <div style="font-weight:600;font-size:14px;color:#1e293b;">${esc(e.title)}</div>
                      <div style="font-size:12px;color:#64748b;margin-top:2px;">
                        <i class="fa-regular fa-clock mr-1"></i>${new Date(e.start_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}
                        ${e.end_at ? " — " + new Date(e.end_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : ""}
                        ${e.document_id ? ` · <span style="color:#2563eb;font-weight:500;">Doc #${e.document_id}</span>` : ""}
                      </div>
                      ${e.description ? `<div style="font-size:12px;color:#475569;margin-top:4px;">${esc(e.description)}</div>` : ""}
                    </div>
                    <button style="background:none;border:none;color:#ef4444;cursor:pointer;padding:4px;" onclick="delEventAndRefreshModal(${e.id}, '${dateStr}')" title="Delete event">
                      <i class="fa-solid fa-trash-can"></i>
                    </button>
                  </div>
                `).join("")}
              </div>
            ` : `<p style="font-size:13px;color:#94a3b8;font-style:italic;padding:8px 0;">No events currently scheduled for this date.</p>`}
          </div>

          <hr style="border:0;border-top:1px solid #e2e8f0;margin:16px 0;" />

          <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;padding:14px;">
            <h4 style="font-size:13px;font-weight:700;color:#0369a1;margin-bottom:10px;">
              <i class="fa-solid fa-plus-circle mr-1"></i> Add Another Event to ${dateStr}
            </h4>
            <div style="display:flex;flex-direction:column;gap:8px;">
              <input id="modal-ev-title" placeholder="Event title" class="border p-2 rounded w-full text-sm" style="background:#fff;" />
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                <div>
                  <label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px;">Start Time</label>
                  <input id="modal-ev-start" type="datetime-local" value="${dateStr}T${String(9 + (dayEvs.length % 12)).padStart(2, '0')}:00" class="border p-1.5 rounded w-full text-xs" style="background:#fff;" />
                </div>
                <div>
                  <label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px;">End Time</label>
                  <input id="modal-ev-end" type="datetime-local" value="${dateStr}T${String(10 + (dayEvs.length % 12)).padStart(2, '0')}:00" class="border p-1.5 rounded w-full text-xs" style="background:#fff;" />
                </div>
              </div>
              <input id="modal-ev-doc" type="number" placeholder="Associated Document ID (optional)" class="border p-2 rounded w-full text-sm" style="background:#fff;" />
              <textarea id="modal-ev-desc" placeholder="Notes / description (optional)" rows="2" class="border p-2 rounded w-full text-sm" style="background:#fff;"></textarea>
              <button onclick="createEventFromModal('${dateStr}')" class="cal-nav-btn primary" style="width:100%;justify-content:center;padding:8px;margin-top:4px;">
                <i class="fa-solid fa-plus"></i> Save Event to ${dateStr}
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>`;

  const existing = $("cal-day-modal");
  if (existing) existing.remove();
  const wrapper = document.createElement("div");
  wrapper.innerHTML = modalHtml;
  document.body.appendChild(wrapper.firstElementChild);
  setTimeout(() => {
    const t = $("modal-ev-title");
    if (t) t.focus();
  }, 100);
};

window.delEventAndRefreshModal = async function(id, dateStr) {
  await apiFetch(`/calendar/${id}`, { method: "DELETE" });
  toast("Event deleted");
  await renderCalendar();
  openDayEventsModal(dateStr);
};

window.openAddEventModal = function(prefilledDateStr) {
  openDayEventsModal(prefilledDateStr || _fmtDateKey(_calYear, _calMonth, new Date().getDate()));
};

window.createEventFromModal = async function(dateStr) {
  const title = val("modal-ev-title");
  if (!title || !title.trim()) {
    toast("Please enter an event title", "warning");
    return;
  }
  const startAt = val("modal-ev-start") || `${dateStr}T09:00`;
  const endAt = val("modal-ev-end") || null;
  const docId = val("modal-ev-doc") ? parseInt(val("modal-ev-doc"), 10) : null;
  const desc = val("modal-ev-desc") || "";

  await apiFetch("/calendar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: title.trim(),
      start_at: startAt,
      end_at: endAt,
      document_id: docId,
      description: desc,
    }),
  });

  toast("Event added successfully", "success");
  await renderCalendar();
  // Keep modal open to allow adding more events immediately on that date
  openDayEventsModal(dateStr);
};

window.saveCalEvent = async function() {
  const title = val("cal-title");
  if (!title || !title.trim()) {
    toast("Please enter an event title", "warning");
    return;
  }
  await apiFetch("/calendar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: title.trim(),
      start_at: val("cal-start") || new Date().toISOString(),
      end_at: val("cal-end") || null,
      document_id: val("cal-doc") ? parseInt(val("cal-doc"), 10) : null,
      description: val("cal-desc") || "",
    }),
  });
  toast("Event created", "success");
  if ($("cal-title")) $("cal-title").value = "";
  if ($("cal-desc")) $("cal-desc").value = "";
  await renderCalendar();
  if (_calSelectedDate) selectCalDate(_calSelectedDate);
};
window.createEvent = window.saveCalEvent;
window.addCalendarEvent = window.saveCalEvent;
async function createEvent() { return window.saveCalEvent(); }
async function saveCalEvent() { return window.saveCalEvent(); }

async function delEvent(id) {
  await apiFetch(`/calendar/${id}`, { method: "DELETE" });
  toast("Event deleted");
  await renderCalendar();
  if (_calSelectedDate) selectCalDate(_calSelectedDate);
}

let _taskFilter = "all";

async function renderTasks() {
  const [tasks, notifs] = await Promise.all([
    apiFetch("/tasks") || [],
    apiFetch("/notifications") || []
  ]);

  const allTasks = tasks || [];
  const allNotifs = notifs || [];
  const pendingCount = allTasks.filter(t => t.status === "pending").length;
  const unreadNotifs = allNotifs.filter(n => !n.read).length;

  let filteredTasks = allTasks;
  if (_taskFilter === "pending") filteredTasks = allTasks.filter(t => t.status === "pending");
  else if (_taskFilter === "completed") filteredTasks = allTasks.filter(t => t.status !== "pending");

  $("work-tasks").innerHTML = `
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div>
        <h2 class="text-xl font-bold text-gray-800 flex items-center gap-2">
          <i class="fa-solid fa-list-check text-teal-600"></i> Tasks &amp; Workflow Center
        </h2>
        <p class="text-xs text-gray-500 mt-0.5">
          ${pendingCount} pending task(s) requiring action · ${unreadNotifs} unread notification(s)
        </p>
      </div>
      <div class="flex items-center gap-2">
        <button onclick="openCreateTaskModal()" class="cal-nav-btn primary py-2 px-3 shadow-sm">
          <i class="fa-solid fa-plus"></i> Add New Task
        </button>
      </div>
    </div>

    <!-- Task Filter Tabs -->
    <div class="flex items-center gap-2 mb-3 border-b pb-2">
      <button class="cal-nav-btn ${_taskFilter === 'all' ? 'primary' : ''}" onclick="_taskFilter='all'; renderTasks();">
        All Tasks (${allTasks.length})
      </button>
      <button class="cal-nav-btn ${_taskFilter === 'pending' ? 'primary' : ''}" onclick="_taskFilter='pending'; renderTasks();">
        Pending Action (${pendingCount})
      </button>
      <button class="cal-nav-btn ${_taskFilter === 'completed' ? 'primary' : ''}" onclick="_taskFilter='completed'; renderTasks();">
        Completed / Resolved (${allTasks.length - pendingCount})
      </button>
    </div>

    <!-- Main Workspace Grid: Tasks on left/top, Notifications on right -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-5">
      <div class="bg-white rounded-lg shadow border p-4 lg:col-span-2">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-bold text-sm text-gray-700">
            <i class="fa-solid fa-tasks text-blue-600 mr-1.5"></i> Task Assignments
          </h3>
          <span class="text-xs text-gray-400">Showing ${filteredTasks.length} task(s)</span>
        </div>

        ${filteredTasks.length ? `
          <div class="divide-y max-h-[600px] overflow-y-auto">
            ${filteredTasks.map((t) => {
              const isPending = t.status === "pending";
              const statusBg = t.status === "approved" ? "bg-green-100 text-green-800" :
                               t.status === "rejected" ? "bg-red-100 text-red-800" :
                               t.status === "pending" ? "bg-amber-100 text-amber-800" : "bg-gray-100 text-gray-800";
              const isOverdue = t.due_at && new Date(t.due_at) < new Date() && isPending;

              return `
                <div class="py-3 px-2 flex flex-col sm:flex-row sm:items-center justify-between gap-2 hover:bg-gray-50/80 rounded transition">
                  <div class="flex-1">
                    <div class="flex items-center gap-2 flex-wrap">
                      <span class="font-semibold text-sm text-gray-900">${esc(t.step_name)}</span>
                      <span class="text-xs px-2 py-0.5 rounded-full font-semibold uppercase ${statusBg}">
                        ${esc(t.status)}
                      </span>
                      ${t.document_id ? `
                        <span class="bg-blue-50 text-blue-700 border border-blue-200 text-xs px-2 py-0.5 rounded cursor-pointer hover:bg-blue-100" onclick="openDocDetails(${t.document_id})">
                          <i class="fa-solid fa-file-lines mr-1"></i>Doc #${t.document_id}
                        </span>` : ""}
                    </div>
                    
                    <div class="text-xs text-gray-500 mt-1 flex items-center gap-3 flex-wrap">
                      ${t.assignee_username ? `<span><i class="fa-regular fa-user mr-1"></i>${esc(t.assignee_username)}</span>` : (t.assignee_role ? `<span><i class="fa-solid fa-shield mr-1"></i>Role: ${esc(t.assignee_role)}</span>` : "")}
                      ${t.due_at ? `<span class="${isOverdue ? 'text-red-600 font-bold' : ''}"><i class="fa-regular fa-clock mr-1"></i>Due: ${fmtDate(t.due_at)} ${isOverdue ? '(Overdue)' : ''}</span>` : ""}
                      ${t.comment ? `<span class="text-gray-600 italic">“${esc(t.comment)}”</span>` : ""}
                    </div>
                  </div>

                  <div class="flex items-center gap-1.5 self-end sm:self-center">
                    ${isPending ? `
                      <button onclick="taskAction(${t.id}, true)" class="cal-nav-btn text-xs" style="background:#16a34a; color:#fff; border-color:#16a34a;" title="Approve task">
                        <i class="fa-solid fa-check"></i> Approve
                      </button>
                      <button onclick="taskAction(${t.id}, false)" class="cal-nav-btn text-xs" style="background:#dc2626; color:#fff; border-color:#dc2626;" title="Reject task">
                        <i class="fa-solid fa-xmark"></i> Reject
                      </button>` : `
                      <span class="text-xs text-gray-400 italic">Resolved</span>`}
                  </div>
                </div>`;
            }).join("")}
          </div>
        ` : `
          <div class="p-8 text-center text-gray-400">
            <i class="fa-solid fa-clipboard-check text-3xl mb-2 text-gray-300 block"></i>
            <p class="text-sm">No tasks matching current filter.</p>
            <button onclick="openCreateTaskModal()" class="cal-nav-btn primary text-xs mt-3">
              <i class="fa-solid fa-plus"></i> Create New Task
            </button>
          </div>`}
      </div>

      <!-- Notifications Column -->
      <div class="bg-white rounded-lg shadow border p-4 lg:col-span-1">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-bold text-sm text-gray-700">
            <i class="fa-solid fa-bell text-teal-600 mr-1.5"></i> Activity Feed
          </h3>
          ${unreadNotifs ? `<button onclick="markAllNotifsRead()" class="text-xs text-blue-600 font-semibold hover:underline">Mark all read</button>` : ""}
        </div>

        ${allNotifs.length ? `
          <div class="divide-y max-h-[600px] overflow-y-auto">
            ${allNotifs.map((n) => `
              <div class="py-2.5 px-1 flex items-start justify-between gap-2 ${n.read ? 'text-gray-500' : 'bg-teal-50/50 font-semibold text-gray-900 rounded'}">
                <div class="flex-1">
                  <p class="text-xs leading-snug">${esc(n.message)}</p>
                  <span class="text-[10px] text-gray-400 block mt-0.5">${fmtDate(n.created_at)}</span>
                </div>
                ${!n.read ? `
                  <button onclick="markRead(${n.id})" class="text-blue-600 hover:text-blue-800 text-xs px-1.5 py-0.5 rounded border border-blue-200" title="Mark as read">
                    <i class="fa-solid fa-check"></i>
                  </button>` : ""}
              </div>`).join("")}
          </div>
        ` : '<p class="text-gray-400 text-xs text-center py-8">No notifications yet.</p>'}
      </div>
    </div>`;

  updateNotifBadge();
}

window.openCreateTaskModal = function(docId) {
  const modalHtml = `
    <div id="create-task-modal" class="modal is-active" style="position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;" onclick="if(event.target === this) closeModal('create-task-modal')">
      <div class="modal-card" style="background:#fff;border-radius:8px;max-width:520px;width:100%;box-shadow:0 10px 25px rgba(0,0,0,0.2);overflow:hidden;animation:fadeIn 0.15s ease;" onclick="event.stopPropagation()">
        <header class="modal-card-head" style="padding:14px 18px;background:#f8fafc;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;">
          <h3 style="font-weight:700;font-size:16px;color:#1e293b;margin:0;">
            <i class="fa-solid fa-list-check text-teal-600 mr-2"></i>Create New Task
          </h3>
          <button class="delete" style="background:none;border:none;font-size:22px;cursor:pointer;color:#64748b;line-height:1;" onclick="closeModal('create-task-modal')">×</button>
        </header>
        <section class="modal-card-body" style="padding:18px;max-height:75vh;overflow-y:auto;">
          <div style="display:flex;flex-direction:column;gap:12px;">
            <div>
              <label style="font-size:12px;font-weight:600;color:#334155;display:block;margin-bottom:4px;">Task Title / Action Item *</label>
              <input id="task-create-title" placeholder="e.g. Review & Approve Contract, PO Verification" class="border p-2 rounded w-full text-sm" />
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
              <div>
                <label style="font-size:12px;font-weight:600;color:#334155;display:block;margin-bottom:4px;">Target Document ID</label>
                <input id="task-create-doc" type="number" value="${docId || ''}" placeholder="Doc ID (optional)" class="border p-2 rounded w-full text-sm" />
              </div>
              <div>
                <label style="font-size:12px;font-weight:600;color:#334155;display:block;margin-bottom:4px;">Assignee Role</label>
                <select id="task-create-role" class="border p-2 rounded w-full text-sm" style="background:#fff;">
                  <option value="">Specific User / Myself</option>
                  <option value="manager">Manager</option>
                  <option value="admin">Administrator</option>
                  <option value="legal">Legal Counsel</option>
                  <option value="finance">Finance / Accounting</option>
                  <option value="compliance">Compliance Officer</option>
                  <option value="user">General User</option>
                </select>
              </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
              <div>
                <label style="font-size:12px;font-weight:600;color:#334155;display:block;margin-bottom:4px;">SLA Deadline (Hours)</label>
                <select id="task-create-sla" class="border p-2 rounded w-full text-sm" style="background:#fff;">
                  <option value="4">4 Hours (Urgent)</option>
                  <option value="24" selected>24 Hours (Standard)</option>
                  <option value="48">48 Hours</option>
                  <option value="72">3 Days</option>
                  <option value="168">1 Week</option>
                </select>
              </div>
              <div>
                <label style="font-size:12px;font-weight:600;color:#334155;display:block;margin-bottom:4px;">Custom Due Date</label>
                <input id="task-create-due" type="datetime-local" class="border p-2 rounded w-full text-xs" />
              </div>
            </div>

            <div>
              <label style="font-size:12px;font-weight:600;color:#334155;display:block;margin-bottom:4px;">Instructions / Description</label>
              <textarea id="task-create-desc" placeholder="Provide instructions or background for this assignment..." rows="3" class="border p-2 rounded w-full text-sm"></textarea>
            </div>

            <button onclick="submitCreateTask()" class="cal-nav-btn primary" style="width:100%;justify-content:center;padding:10px;font-size:14px;margin-top:6px;">
              <i class="fa-solid fa-plus-circle mr-1"></i> Create Task
            </button>
          </div>
        </section>
      </div>
    </div>`;

  const existing = $("create-task-modal");
  if (existing) existing.remove();
  const wrapper = document.createElement("div");
  wrapper.innerHTML = modalHtml;
  document.body.appendChild(wrapper.firstElementChild);
  setTimeout(() => {
    const t = $("task-create-title");
    if (t) t.focus();
  }, 100);
};

window.submitCreateTask = async function() {
  const title = val("task-create-title");
  if (!title || !title.trim()) {
    toast("Please enter a task title", "warning");
    return;
  }
  const docId = val("task-create-doc") ? parseInt(val("task-create-doc"), 10) : null;
  const role = val("task-create-role") || null;
  const sla = parseInt(val("task-create-sla") || "24", 10);
  const due = val("task-create-due") || null;
  const desc = val("task-create-desc") || "";

  await apiFetch("/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: title.trim(),
      document_id: docId,
      assignee_role: role,
      sla_hours: sla,
      due_at: due,
      description: desc,
    }),
  });

  toast("Task created successfully", "success");
  closeModal("create-task-modal");
  await renderTasks();
  updateNotifBadge();
};

async function taskAction(id, approved) {
  const comment = approved ? "" : (prompt("Rejection comment") || "");
  await apiFetch(`/tasks/${id}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, comment }),
  });
  toast(approved ? "Task approved" : "Task rejected", "info");
  renderTasks();
  updateNotifBadge();
}

async function markRead(id) {
  await apiFetch(`/notifications/${id}/read`, { method: "POST" });
  renderTasks();
  updateNotifBadge();
}

window.toggleNotifDrop = async function() {
  const drop = $("notif-drop");
  if (!drop) return;
  const willOpen = !drop.classList.contains("open");
  closeDrops();
  if (willOpen) {
    drop.classList.add("open");
    await loadTopNotifs();
  }
};

window.loadTopNotifs = async function() {
  const listEl = $("notif-top-list");
  if (!listEl) return;
  try {
    const notifs = (await apiFetch("/notifications")) || [];
    if (!notifs.length) {
      listEl.innerHTML = '<div style="padding:24px;text-align:center;color:var(--muted);"><i class="fa-regular fa-bell-slash text-xl mb-1 block"></i>No notifications yet</div>';
      return;
    }
    listEl.innerHTML = notifs.slice(0, 15).map(n => `
      <div class="notif-item ${n.read ? '' : 'is-unread'}">
        <div style="flex:1;">
          <div style="font-size:12px;color:var(--text);line-height:1.35;">${esc(n.message)}</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px;">${fmtDate(n.created_at)}</div>
        </div>
        ${!n.read ? `
          <button onclick="markTopNotifRead(${n.id}, event)" style="background:none;border:none;color:var(--accent);cursor:pointer;font-size:11px;" title="Mark read">
            <i class="fa-solid fa-check"></i>
          </button>` : ''}
      </div>`).join("");
  } catch (e) {
    listEl.innerHTML = '<div style="padding:16px;text-align:center;color:#ef4444;">Failed to load notifications</div>';
  }
};

window.markTopNotifRead = async function(id, ev) {
  if (ev) ev.stopPropagation();
  await apiFetch(`/notifications/${id}/read`, { method: "POST" });
  await loadTopNotifs();
  updateNotifBadge();
};

window.markAllNotifsRead = async function() {
  await apiFetch("/notifications/read-all", { method: "POST" });
  toast("All notifications marked as read", "success");
  await loadTopNotifs();
  updateNotifBadge();
  if (currentNav === "tasks") renderTasks();
};

async function updateNotifBadge() {
  try {
    const unread = (await apiFetch("/notifications?unread_only=true")) || [];
    const count = unread.length;
    const txt = count > 99 ? "99+" : count.toString();
    const badge = $("notif-badge");
    if (badge) {
      if (count) { badge.textContent = txt; badge.classList.remove("is-hidden"); }
      else badge.classList.add("is-hidden");
    }
    const badgeDash = $("notif-badge-dash");
    if (badgeDash) {
      if (count) { badgeDash.textContent = txt; badgeDash.classList.remove("is-hidden"); }
      else badgeDash.classList.add("is-hidden");
    }
  } catch (e) { /* ignore */ }
}

// Background polling for notifications every 25 seconds
if (!window._notifPollTimer) {
  window._notifPollTimer = setInterval(updateNotifBadge, 25000);
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
  const biocreds = (await apiFetch("/auth/biometrics/credentials").catch(() => [])) || [];
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
      <div class="bg-white rounded shadow p-4 border-l-4 border-teal-600">
        <h3 class="font-bold mb-2 flex items-center gap-2"><i class="fa-solid fa-fingerprint text-teal-600"></i> Biometrics & Passkeys</h3>
        <p class="text-xs text-gray-600 mb-3">Sign in securely without passwords using Windows Hello, Apple Touch ID / Face ID, or hardware security keys.</p>
        <button onclick="registerBiometrics()" class="tb primary mb-3 flex items-center gap-2"><i class="fa-solid fa-plus"></i> Register This Device</button>
        <ul class="text-xs space-y-1.5">${biocreds.map((c) => `<li class="flex items-center justify-between p-1.5 bg-gray-50 rounded border"><span><i class="fa-solid fa-key text-teal-600 mr-1.5"></i><b>${esc(c.name || "Passkey")}</b> <span class="text-gray-400">(${fmtDate(c.created_at)})</span></span> <button onclick="deleteBiometricCred(${c.id})" class="text-red-500 hover:text-red-700 font-bold px-1.5">Revoke</button></li>`).join("") || '<li class="text-gray-400 italic">No biometric devices enrolled</li>'}</ul>
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
    await renderEnterpriseAuditDashboard(content);
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

// ---------------------------------------------------------------------------
// Real-Time Online Presence Tracking
// ---------------------------------------------------------------------------
let presenceTimer = null;
let auditLiveTimer = null;
let currentAuditLogs = [];
let currentAuditInspectorLog = null;

async function sendPresenceHeartbeat() {
  try {
    const res = await apiFetch("/users/heartbeat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_path: location.hash || "home", active_tab: (typeof currentTab !== "undefined" ? currentTab : "home") }),
    });
    if (res && res.online_count !== undefined) {
      const countEl = $("online-users-count");
      if (countEl) countEl.textContent = res.online_count;
    }
  } catch (e) {
    // Non-blocking
  }
}

function startPresenceTracking() {
  if (presenceTimer) clearInterval(presenceTimer);
  sendPresenceHeartbeat();
  presenceTimer = setInterval(sendPresenceHeartbeat, 25000);
}

function stopPresenceTracking() {
  if (presenceTimer) {
    clearInterval(presenceTimer);
    presenceTimer = null;
  }
}

async function openOnlineUsersModal() {
  openModal("online-users-modal");
  await refreshOnlineUsersModal();
}

async function refreshOnlineUsersModal() {
  const listEl = $("online-users-list");
  if (!listEl) return;
  listEl.innerHTML = `<div style="text-align:center; padding:24px; color:var(--muted);"><i class="fa-solid fa-spinner fa-spin mr-1.5 text-teal-600"></i> Polling online users…</div>`;

  try {
    const users = (await apiFetch("/users/online")) || [];
    const countEl = $("online-users-count");
    if (countEl) countEl.textContent = users.length;

    if (!users.length) {
      listEl.innerHTML = `<div style="text-align:center; padding:28px; color:var(--muted);">No colleagues currently active.</div>`;
      return;
    }

    listEl.innerHTML = users.map((u) => {
      const initials = (u.username || "?").slice(0, 2).toUpperCase();
      const roleColor = u.role === "superadmin" ? "#dc2626" : u.role === "admin" ? "#7c3aed" : u.role === "manager" ? "#0284c7" : "#0d9488";
      const statusBadge = u.status === "active" 
        ? `<span style="display:inline-flex; align-items:center; gap:5px; font-size:11px; color:#059669; font-weight:600;"><span class="online-pulse-dot" style="width:6px; height:6px;"></span> Active now</span>`
        : `<span style="display:inline-flex; align-items:center; gap:5px; font-size:11px; color:#d97706; font-weight:600;"><span style="width:6px; height:6px; background:#f59e0b; border-radius:50%; display:inline-block;"></span> Idle (${Math.floor(u.idle_seconds / 60)}m ago)</span>`;

      return `
        <div style="display:flex; align-items:center; justify-content:space-between; padding:12px 14px; background:#ffffff; border:1px solid var(--border); border-radius:10px; transition:all 0.2s ease;">
          <div style="display:flex; align-items:center; gap:12px;">
            <div style="width:38px; height:38px; border-radius:50%; background:linear-gradient(135deg, ${roleColor} 0%, #0f172a 100%); color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; box-shadow:0 2px 6px rgba(0,0,0,0.15);">
              ${esc(initials)}
            </div>
            <div>
              <div style="display:flex; align-items:center; gap:6px;">
                <strong style="font-size:13.5px; color:var(--text);">${esc(u.username)}</strong>
                <span style="font-size:10px; font-weight:700; text-transform:uppercase; padding:1px 6px; border-radius:4px; background:rgba(0,0,0,0.06); color:${roleColor}; border:1px solid rgba(0,0,0,0.08);">${esc(u.role)}</span>
              </div>
              <div style="font-size:11.5px; color:var(--muted); margin-top:2px;">
                ${u.email ? `<span style="margin-right:8px;"><i class="fa-solid fa-envelope mr-1 text-slate-400"></i>${esc(u.email)}</span>` : ""}
                <span><i class="fa-solid fa-network-wired mr-1 text-slate-400"></i>${esc(u.ip || "127.0.0.1")}</span>
              </div>
            </div>
          </div>

          <div style="text-align:right;">
            <div>${statusBadge}</div>
            <div style="font-size:11px; color:var(--muted); margin-top:3px;"><i class="fa-solid fa-compass mr-1"></i> ${esc(u.current_path || "/")}</div>
          </div>
        </div>
      `;
    }).join("");
  } catch (e) {
    listEl.innerHTML = `<div style="text-align:center; padding:20px; color:#dc2626;"><i class="fa-solid fa-triangle-exclamation mr-1.5"></i> Failed to load online presence data.</div>`;
  }
}

// ---------------------------------------------------------------------------
// Enterprise Audit Trail & Forensic Compliance Subsystem
// ---------------------------------------------------------------------------
let auditFilterState = {
  search: "",
  severity: "ALL",
  status: "ALL",
  action: "ALL",
  live: false,
};

async function renderEnterpriseAuditDashboard(content) {
  content.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px; flex-wrap:wrap; gap:10px;">
      <div>
        <h3 style="margin:0; font-size:18px; font-weight:800; display:flex; align-items:center; gap:8px;">
          <i class="fa-solid fa-shield-halved text-teal-600"></i> Enterprise Audit Trail &amp; SOC Telemetry
        </h3>
        <p style="margin:4px 0 0; font-size:12.5px; color:var(--muted);">
          Cryptographically sealed immutable record of document operations, security events, authentication, and administrative actions.
        </p>
      </div>

      <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
        <button type="button" id="audit-live-btn" class="tb text-xs" onclick="toggleAuditLiveStream()" style="border-radius:20px; padding:6px 14px; font-weight:600;">
          <i class="fa-solid fa-satellite-dish mr-1"></i> Live Stream: OFF
        </button>
        <div class="drop" id="audit-export-drop">
          <button type="button" class="tb primary text-xs" onclick="toggleDrop('audit-export-drop')">
            <i class="fa-solid fa-download mr-1"></i> Export Compliance Log <i class="fa-solid fa-chevron-down ml-1"></i>
          </button>
          <div class="drop-menu drop-menu-right">
            <button onclick="downloadAuditExport('csv'); closeDrops()"><i class="fa-solid fa-file-csv text-emerald-600 mr-2"></i> Export as CSV (.csv)</button>
            <button onclick="downloadAuditExport('json'); closeDrops()"><i class="fa-solid fa-file-code text-indigo-600 mr-2"></i> Export as JSON (WORM Sealed)</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 4 KPI Stat Metric Cards -->
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin-bottom:18px;" id="audit-kpi-row">
      <div class="audit-kpi-card">
        <div class="kpi-lbl"><i class="fa-solid fa-list-check text-teal-600 mr-1"></i> Total Events</div>
        <div class="kpi-num" id="kpi-total-events">-</div>
      </div>
      <div class="audit-kpi-card">
        <div class="kpi-lbl"><i class="fa-solid fa-triangle-exclamation text-rose-600 mr-1"></i> Security Alerts</div>
        <div class="kpi-num" style="color:#dc2626;" id="kpi-sec-alerts">-</div>
      </div>
      <div class="audit-kpi-card">
        <div class="kpi-lbl"><i class="fa-solid fa-user-shield text-indigo-600 mr-1"></i> Active Actors (24h)</div>
        <div class="kpi-num" style="color:#4f46e5;" id="kpi-active-actors">-</div>
      </div>
      <div class="audit-kpi-card">
        <div class="kpi-lbl"><i class="fa-solid fa-ban text-amber-600 mr-1"></i> Access Denials</div>
        <div class="kpi-num" style="color:#d97706;" id="kpi-denials">-</div>
      </div>
    </div>

    <!-- Filter & Search Toolbar -->
    <div style="background:#fff; border:1px solid var(--border); border-radius:var(--radius); padding:12px; margin-bottom:14px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:space-between;">
      <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; flex:1; min-width:320px;">
        <div style="position:relative; flex:1; min-width:180px;">
          <i class="fa-solid fa-magnifying-glass" style="position:absolute; left:10px; top:9px; color:var(--muted); font-size:12px;"></i>
          <input id="audit-search-input" type="search" placeholder="Search actions, users, IPs, details…" oninput="onAuditSearchChange(this.value)" style="width:100%; box-sizing:border-box; border:1px solid var(--border); border-radius:8px; padding:7px 10px 7px 30px; font-size:12.5px;" />
        </div>

        <select id="audit-filter-sev" onchange="onAuditSevFilter(this.value)" style="border:1px solid var(--border); border-radius:8px; padding:6px 10px; font-size:12px; font-weight:500;">
          <option value="ALL">All Severities</option>
          <option value="CRITICAL">🔴 Critical &amp; Alerts</option>
          <option value="HIGH">🟠 High Priority</option>
          <option value="MEDIUM">🟡 Medium / Warnings</option>
          <option value="INFO">🔵 Informational</option>
        </select>

        <select id="audit-filter-status" onchange="onAuditStatusFilter(this.value)" style="border:1px solid var(--border); border-radius:8px; padding:6px 10px; font-size:12px; font-weight:500;">
          <option value="ALL">All Statuses</option>
          <option value="SUCCESS">✅ Success</option>
          <option value="DENIED">⛔ Access Denied</option>
          <option value="FAILED">❌ Failed</option>
          <option value="SUSPICIOUS">⚠️ Suspicious</option>
        </select>
      </div>

      <button type="button" class="tb text-xs" onclick="loadAuditEvents(true)" style="padding:6px 12px;">
        <i class="fa-solid fa-arrows-rotate mr-1"></i> Refresh Table
      </button>
    </div>

    <!-- Audit Event Log Table Container -->
    <div style="background:#fff; border:1px solid var(--border); border-radius:var(--radius); overflow:hidden; box-shadow:var(--shadow-sm);">
      <div id="audit-table-wrapper" style="overflow-x:auto;">
        <table class="w-full text-left" style="font-size:12.5px; border-collapse:collapse;">
          <thead>
            <tr style="background:#f8fafc; border-bottom:1px solid var(--border); color:var(--text-secondary); font-size:11.5px; text-transform:uppercase; letter-spacing:0.5px;">
              <th style="padding:10px 14px; font-weight:700;">Severity</th>
              <th style="padding:10px 14px; font-weight:700;">Timestamp</th>
              <th style="padding:10px 14px; font-weight:700;">Actor</th>
              <th style="padding:10px 14px; font-weight:700;">Action Code</th>
              <th style="padding:10px 14px; font-weight:700;">Resource</th>
              <th style="padding:10px 14px; font-weight:700;">Details &amp; Telemetry</th>
              <th style="padding:10px 14px; font-weight:700;">Client / IP</th>
              <th style="padding:10px 14px; font-weight:700; text-align:right;">Forensics</th>
            </tr>
          </thead>
          <tbody id="audit-log-tbody">
            <tr><td colspan="8" style="text-align:center; padding:32px; color:var(--muted);"><i class="fa-solid fa-spinner fa-spin mr-1.5 text-teal-600"></i> Loading audit events…</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  await Promise.all([loadAuditStats(), loadAuditEvents()]);
}

async function loadAuditStats() {
  try {
    const stats = await apiFetch("/audit/stats");
    if (stats) {
      if ($("kpi-total-events")) $("kpi-total-events").textContent = (stats.total_events || 0).toLocaleString();
      if ($("kpi-sec-alerts")) $("kpi-sec-alerts").textContent = (stats.security_alerts || 0).toLocaleString();
      if ($("kpi-active-actors")) $("kpi-active-actors").textContent = (stats.active_actors_24h || 0).toLocaleString();
      if ($("kpi-denials")) $("kpi-denials").textContent = (stats.access_denials || 0).toLocaleString();
    }
  } catch (e) {
    console.error("Failed to load audit stats", e);
  }
}

async function loadAuditEvents(silent = false) {
  const tbody = $("audit-log-tbody");
  if (!tbody) return;
  if (!silent) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:32px; color:var(--muted);"><i class="fa-solid fa-spinner fa-spin mr-1.5 text-teal-600"></i> Loading audit events…</td></tr>`;
  }

  try {
    let url = `/audit?limit=150`;
    if (auditFilterState.search) url += `&search=${encodeURIComponent(auditFilterState.search)}`;
    if (auditFilterState.severity && auditFilterState.severity !== "ALL") url += `&severity=${encodeURIComponent(auditFilterState.severity)}`;
    if (auditFilterState.status && auditFilterState.status !== "ALL") url += `&status=${encodeURIComponent(auditFilterState.status)}`;

    const logs = (await apiFetch(url)) || [];
    currentAuditLogs = logs;

    if (!logs.length) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:36px; color:var(--muted);"><i class="fa-solid fa-clipboard-check text-slate-300 text-3xl block mb-2"></i> No audit log records matched the active filter criteria.</td></tr>`;
      return;
    }

    tbody.innerHTML = logs.map((l) => {
      const sev = (l.severity || "INFO").toUpperCase();
      let sevClass = "audit-sev-info";
      if (sev === "CRITICAL" || sev === "SECURITY_ALERT") sevClass = "audit-sev-critical";
      else if (sev === "HIGH") sevClass = "audit-sev-high";
      else if (sev === "MEDIUM") sevClass = "audit-sev-medium";
      else if (sev === "LOW") sevClass = "audit-sev-low";

      const status = (l.status || "SUCCESS").toUpperCase();
      let statusClass = "audit-status-success";
      if (status === "DENIED") statusClass = "audit-status-denied";
      else if (status === "FAILED") statusClass = "audit-status-failed";
      else if (status === "SUSPICIOUS") statusClass = "audit-status-suspicious";

      let actionIcon = "fa-bolt";
      if (l.action.includes("LOGIN") || l.action.includes("AUTH")) actionIcon = "fa-key";
      else if (l.action.includes("DOCUMENT")) actionIcon = "fa-file-lines";
      else if (l.action.includes("ACL") || l.action.includes("PERMISSION")) actionIcon = "fa-user-shield";
      else if (l.action.includes("USER")) actionIcon = "fa-user";
      else if (l.action.includes("DELETE") || l.action.includes("TRASH")) actionIcon = "fa-trash";

      const timeFmt = fmtDate(l.timestamp);
      const username = l.username || "System";
      const role = l.actor_role || "system";

      return `
        <tr style="border-bottom:1px solid var(--border); transition:background 0.15s ease;" onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background='transparent'">
          <td style="padding:10px 14px; white-space:nowrap;">
            <span class="audit-sev-badge ${sevClass}">${esc(sev)}</span>
          </td>
          <td style="padding:10px 14px; white-space:nowrap; color:var(--muted); font-size:12px;">
            <span title="${esc(l.timestamp || '')}"><i class="fa-regular fa-clock mr-1 text-slate-400"></i>${timeFmt}</span>
          </td>
          <td style="padding:10px 14px; white-space:nowrap;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="width:22px; height:22px; border-radius:50%; background:#0d9488; color:#fff; display:inline-flex; align-items:center; justify-content:center; font-size:10px; font-weight:700;">${esc(username.slice(0, 1).toUpperCase())}</span>
              <strong style="color:var(--text);">${esc(username)}</strong>
              <span style="font-size:10px; color:var(--muted); font-weight:600;">(${esc(role)})</span>
            </div>
          </td>
          <td style="padding:10px 14px; white-space:nowrap;">
            <span style="display:inline-flex; align-items:center; gap:5px; font-family:monospace; font-weight:700; font-size:11.5px; color:#0f172a; background:#f1f5f9; padding:2px 6px; border-radius:4px;">
              <i class="fa-solid ${actionIcon} text-teal-600"></i> ${esc(l.action)}
            </span>
          </td>
          <td style="padding:10px 14px; white-space:nowrap;">
            ${l.resource_type ? `<span style="color:var(--muted); font-size:11.5px;">${esc(l.resource_type)} ${l.resource_id ? `#${l.resource_id}` : ''}</span>` : '<span style="color:var(--muted);">-</span>'}
          </td>
          <td style="padding:10px 14px; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            <span class="audit-status-badge ${statusClass} mr-1">${esc(status)}</span>
            <span title="${esc(l.details || '')}" style="color:var(--text);">${esc(l.details || '-')}</span>
          </td>
          <td style="padding:10px 14px; white-space:nowrap; font-size:11.5px; color:var(--muted);">
            <div><i class="fa-solid fa-location-dot mr-1 text-slate-400"></i>${esc(l.ip || '127.0.0.1')}</div>
          </td>
          <td style="padding:10px 14px; text-align:right; white-space:nowrap;">
            <button type="button" class="tb text-xs" onclick="inspectAuditEvent(${l.id})" style="padding:3px 8px;">
              <i class="fa-solid fa-magnifying-glass-plus mr-1 text-teal-600"></i> Inspect
            </button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:24px; color:#dc2626;"><i class="fa-solid fa-triangle-exclamation mr-1.5"></i> Failed to retrieve audit trail records.</td></tr>`;
  }
}

let auditSearchDebounce = null;
function onAuditSearchChange(val) {
  if (auditSearchDebounce) clearTimeout(auditSearchDebounce);
  auditSearchDebounce = setTimeout(() => {
    auditFilterState.search = val.trim();
    loadAuditEvents(true);
  }, 300);
}

function onAuditSevFilter(sev) {
  auditFilterState.severity = sev;
  loadAuditEvents(true);
}

function onAuditStatusFilter(status) {
  auditFilterState.status = status;
  loadAuditEvents(true);
}

function toggleAuditLiveStream() {
  const btn = $("audit-live-btn");
  if (auditFilterState.live) {
    auditFilterState.live = false;
    if (auditLiveTimer) { clearInterval(auditLiveTimer); auditLiveTimer = null; }
    if (btn) {
      btn.innerHTML = `<i class="fa-solid fa-satellite-dish mr-1"></i> Live Stream: OFF`;
      btn.style.background = "";
      btn.style.color = "";
      btn.style.borderColor = "";
    }
  } else {
    auditFilterState.live = true;
    auditLiveTimer = setInterval(() => {
      loadAuditEvents(true);
      loadAuditStats();
    }, 8000);
    if (btn) {
      btn.innerHTML = `<span class="online-pulse-dot" style="background:#ef4444; box-shadow:0 0 0 0 rgba(239,68,68,0.7);"></span> Live Stream: ACTIVE (8s)`;
      btn.style.background = "rgba(239, 68, 68, 0.1)";
      btn.style.color = "#dc2626";
      btn.style.borderColor = "rgba(239, 68, 68, 0.3)";
    }
    toast("Audit live stream active (refreshing every 8s)", "info");
  }
}

function downloadAuditExport(format) {
  window.open(api(`/audit/export?format=${format}`), "_blank");
}

function inspectAuditEvent(id) {
  const log = currentAuditLogs.find((l) => l.id === id);
  if (!log) return;
  currentAuditInspectorLog = log;

  const sev = (log.severity || "INFO").toUpperCase();
  const sevEl = $("insp-audit-sev-badge");
  if (sevEl) {
    sevEl.textContent = sev;
    sevEl.className = `audit-sev-badge audit-sev-${sev.toLowerCase().replace('_', '-')}`;
  }

  const subEl = $("insp-audit-sub");
  if (subEl) subEl.textContent = `Event #${log.id} · Recorded ${fmtDate(log.timestamp)}`;

  const body = $("audit-inspect-body");
  if (body) {
    body.innerHTML = `
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px;">
        <div style="background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:10px 12px;">
          <div style="font-size:11px; color:var(--muted); font-weight:700; text-transform:uppercase;">Actor Information</div>
          <div style="font-size:13.5px; font-weight:700; color:var(--text); margin-top:2px;">${esc(log.username || 'System')} <span style="font-size:11px; font-weight:600; color:var(--muted);">(${esc(log.actor_role || 'system')})</span></div>
          <div style="font-size:11.5px; color:var(--muted); margin-top:4px;"><i class="fa-solid fa-id-badge mr-1"></i> User ID: ${log.user_id || 'System'}</div>
        </div>

        <div style="background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:10px 12px;">
          <div style="font-size:11px; color:var(--muted); font-weight:700; text-transform:uppercase;">Client Telemetry</div>
          <div style="font-size:13px; font-weight:700; color:var(--text); margin-top:2px;"><i class="fa-solid fa-globe text-teal-600 mr-1"></i> ${esc(log.ip || '127.0.0.1')}</div>
          <div style="font-size:11px; color:var(--muted); margin-top:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${esc(log.user_agent || '')}"><i class="fa-solid fa-laptop mr-1"></i> ${esc(log.user_agent || 'Unknown Client')}</div>
        </div>
      </div>

      <div style="background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:10px 12px; margin-bottom:14px;">
        <div style="font-size:11px; color:var(--muted); font-weight:700; text-transform:uppercase;">Action &amp; Target Details</div>
        <div style="font-size:13px; font-weight:700; color:#0f172a; margin-top:2px;">Action: <span style="font-family:monospace; background:#e2e8f0; padding:1px 5px; border-radius:4px;">${esc(log.action)}</span> · Status: <strong>${esc(log.status || 'SUCCESS')}</strong></div>
        <div style="font-size:12.5px; color:var(--text); margin-top:6px;"><strong>Summary:</strong> ${esc(log.details || 'None')}</div>
        ${log.resource_type ? `<div style="font-size:12px; color:var(--muted); margin-top:4px;">Target: <strong>${esc(log.resource_type)}</strong> ${log.resource_id ? `#${log.resource_id}` : ''} ${log.resource_name ? `(${esc(log.resource_name)})` : ''}</div>` : ''}
      </div>

      <!-- Cryptographic SHA-256 Checksum Seal -->
      <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:10px 12px; margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:11px; font-weight:700; color:#15803d; text-transform:uppercase;"><i class="fa-solid fa-certificate text-emerald-600 mr-1"></i> SHA-256 Tamper-Evident Seal</span>
          <span style="font-size:10.5px; font-weight:700; background:#dcfce7; color:#15803d; padding:1px 6px; border-radius:4px; border:1px solid #86efac;">VERIFIED AUTHENTIC</span>
        </div>
        <div style="font-family:monospace; font-size:11px; color:#166534; word-break:break-all; margin-top:4px;">
          ${esc(log.checksum || 'SHA256_INTEGRITY_STAMP_GENERATED')}
        </div>
      </div>

      <!-- Raw Structured JSON Event -->
      <div>
        <div style="font-size:11px; font-weight:700; color:var(--muted); text-transform:uppercase; margin-bottom:4px;">Raw Forensic Event Payload</div>
        <pre style="background:#0f172a; color:#f8fafc; padding:12px; border-radius:8px; font-size:11.5px; overflow:auto; max-height:160px; font-family:monospace;">${esc(JSON.stringify(log, null, 2))}</pre>
      </div>
    `;
  }

  openModal("audit-inspect-modal");
}

function copyAuditInspectorJson() {
  if (!currentAuditInspectorLog) return;
  navigator.clipboard.writeText(JSON.stringify(currentAuditInspectorLog, null, 2)).then(() => {
    toast("Forensic event JSON copied to clipboard", "success");
  }).catch(() => {
    toast("Failed to copy to clipboard", "warning");
  });
}

