/* NewtonEDMS intelligence UI: cards, power search, dashboards, i18n, queue. */
let i18nCat = {};
let uiSettings = { powerSearch: true, cardLayout: "cards", tagCount: 8, previewSize: 120, noteLength: 80, titlePattern: "{{title}}", subtitlePattern: "{{corrOrg}}" };
let searchMode = "all";
let tagTri = {}; // name -> include | exclude | ignore
let orgsCatalog = [];
let equipmentCatalog = [];

function t(key) { return (i18nCat && i18nCat[key]) || key; }

async function loadIntel() {
  try { uiSettings = Object.assign(uiSettings, await apiFetch("/ui-settings") || {}); } catch (e) { /* */ }
  const loc = (currentUser && currentUser.locale) || uiSettings.locale || "en";
  try { i18nCat = await apiFetch(`/i18n/${loc}`) || {}; } catch (e) { i18nCat = {}; }
  applyI18n();
  try { orgsCatalog = await apiFetch("/organizations") || []; } catch (e) { orgsCatalog = []; }
  try { equipmentCatalog = await apiFetch("/equipment") || []; } catch (e) { equipmentCatalog = []; }
  renderPowerSearch();
}

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  const si = $("search-input");
  if (si) si.placeholder = t("search.placeholder");
}

function patternFill(tpl, d) {
  const corr = (contacts.find((c) => c.id === d.correspondent_id) || {});
  const org = (orgsCatalog.find((o) => o.id === d.organization_id) || {});
  return String(tpl || "")
    .replaceAll("{{title}}", d.title || d.name || "")
    .replaceAll("{{name}}", d.name || "")
    .replaceAll("{{corrOrg}}", org.name || corr.organization || corr.name || "")
    .replaceAll("{{corrPers}}", corr.name || "")
    .replaceAll("{{tags}}", d.tags || "");
}

const _origRenderDocList = typeof renderDocList === "function" ? renderDocList : null;
renderDocList = function (docs, title, sub) {
  lastDocs = docs;
  lastTitle = title;
  lastSub = sub;
  if (pageOffset >= docs.length) pageOffset = 0;
  const page = docs.slice(pageOffset, pageOffset + pageSize);
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
  const layout = uiSettings.cardLayout || gridView;
  const pager = `<div class="pager item-toolbar">
    <button onclick="changePage(-1)">Prev</button>
    <button onclick="nextUnconfirmed()"> ${t("item.next")}</button>
    <button onclick="downloadCurrentFilter()">ZIP</button>
    <select onchange="searchMode=this.value; runSearch()">
      <option value="all" ${searchMode==="all"?"selected":""}>${t("search.all")}</option>
      <option value="names" ${searchMode==="names"?"selected":""}>${t("search.names")}</option>
      <option value="contents" ${searchMode==="contents"?"selected":""}>${t("search.contents")}</option>
    </select>
  </div>`;
  if (layout === "cards" || layout === "tiles" || gridView === "tiles") {
    const size = parseInt(uiSettings.previewSize || 120, 10);
    $("doc-list").innerHTML = `${pager}<div class="item-cards">${page.map((d) => {
      const note = (d.notes || "").slice(0, uiSettings.noteLength || 80);
      const tags = (d.tags || "").split(",").filter(Boolean).slice(0, uiSettings.tagCount || 8);
      const thumb = d.thumbnail_path ? `/api/documents/${d.id}/thumbnail` : "";
      return `<article class="item-card ${d.confirmed ? "" : "is-new"}" draggable="true"
        ondragover="event.preventDefault()" ondrop="dropOnCard(event, ${d.id})"
        onclick="openDoc(${d.id})" oncontextmenu="docContext(event, ${d.id})">
        ${thumb ? `<img class="item-thumb" style="width:${size}px" src="${thumb}" alt="" />` : `<div class="item-thumb ph" style="width:${size}px"></div>`}
        <div>
          <h4>${esc(patternFill(uiSettings.titlePattern || "{{title}}", d))}${d.confirmed ? "" : ` <span class="pill">${t("item.new")}</span>`} ${statusPill(d.status)}</h4>
          <p class="sub">${esc(patternFill(uiSettings.subtitlePattern || "{{corrOrg}}", d))}</p>
          <p class="tags">${tags.map((tg) => `<span class="pill" draggable="true" ondragstart="dragTag(event,'${esc(tg)}')">${esc(tg)}</span>`).join("")}</p>
          ${note ? `<p class="note">${esc(note)}</p>` : ""}
        </div>
      </article>`;
    }).join("")}</div>`;
  } else if (_origRenderDocList) {
    _origRenderDocList(docs, title, sub);
    return;
  }
  updateStatus();
};

function dragTag(ev, name) { ev.dataTransfer.setData("text/tag", name); }
async function dropOnCard(ev, id) {
  ev.preventDefault();
  const tag = ev.dataTransfer.getData("text/tag");
  const folder = ev.dataTransfer.getData("text/folder");
  if (tag) {
    const d = lastDocs.find((x) => x.id === id);
    const tags = new Set((d.tags || "").split(",").map((s) => s.trim()).filter(Boolean));
    tags.add(tag);
    await apiFetch("/documents/bulk-edit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: [id], tags: [...tags].join(",") }) });
    refreshCurrentList();
  }
}

async function nextUnconfirmed() {
  const q = ($("search-input") && $("search-input").value) || "confirmed:new";
  const after = currentDocId || 0;
  const n = await apiFetch(`/documents/next?q=${encodeURIComponent(q)}&after=${after}`);
  if (n && n.id) openDoc(n.id);
}

async function confirmCurrent() {
  if (!currentDocId) return;
  await apiFetch(`/documents/${currentDocId}/confirm`, { method: "POST" });
  nextUnconfirmed();
}
async function unconfirmCurrent() {
  if (!currentDocId) return;
  await apiFetch(`/documents/${currentDocId}/unconfirm`, { method: "POST" });
  refreshCurrentList();
}

async function downloadCurrentFilter() {
  const q = ($("search-input") && $("search-input").value) || "";
  window.location = `/api/documents/download-all?q=${encodeURIComponent(q)}&fmt=pdf`;
}

function renderPowerSearch() {
  const stack = $("search-stack");
  if (!stack || $("power-search-box")) return;
  const box = document.createElement("div");
  box.className = "section open";
  box.id = "power-search-box";
  box.innerHTML = `<div class="section-h"><i class="fa-solid fa-caret-down"></i> ${t("search.power")}</div>
    <div class="section-b" id="power-search-body"></div>`;
  stack.prepend(box);
  refreshPowerFilters();
}

async function refreshPowerFilters() {
  const el = $("power-search-body");
  if (!el) return;
  const tags = tagsCatalog || [];
  const corr = contacts || [];
  el.innerHTML = `
    <label>Tags</label>
    <div class="tag-tri">${tags.map((tg) => {
      const st = tagTri[tg.name] || "ignore";
      return `<button class="tri ${st}" onclick="cycleTag('${esc(tg.name)}')">${esc(tg.name)}${tg.category ? ` <small>${esc(tg.category)}</small>` : ""}</button>`;
    }).join("")}</div>
    <label>Correspondent</label>
    <select id="ps-corr" onchange="applyPowerQuery()"><option value="">Any</option>${corr.map((c) => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join("")}</select>
    <label>Concerning</label>
    <select id="ps-conc" onchange="applyPowerQuery()"><option value="">Any</option>${corr.filter((c) => c.kind !== "correspondent").map((c) => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join("")}</select>
    <label>Custom field (name=value, * ok)</label>
    <input id="ps-field" placeholder="amount=*" onchange="applyPowerQuery()" />
    <label>Date from</label><input id="ps-from" type="date" onchange="applyPowerQuery()" />
    <label>Date to</label><input id="ps-to" type="date" onchange="applyPowerQuery()" />
    <button onclick="applyPowerQuery()">Apply</button>
  `;
}

function cycleTag(name) {
  const cur = tagTri[name] || "ignore";
  tagTri[name] = cur === "ignore" ? "include" : cur === "include" ? "exclude" : "ignore";
  refreshPowerFilters();
  applyPowerQuery();
}

function applyPowerQuery() {
  const parts = [];
  Object.entries(tagTri).forEach(([n, st]) => {
    if (st === "include") parts.push(`tag:${n}`);
    if (st === "exclude") parts.push(`NOT tag:${n}`);
  });
  const corr = $("ps-corr") && $("ps-corr").value;
  const conc = $("ps-conc") && $("ps-conc").value;
  const field = $("ps-field") && $("ps-field").value;
  const from = $("ps-from") && $("ps-from").value;
  const to = $("ps-to") && $("ps-to").value;
  if (corr) parts.push(`corr.pers:${corr}`);
  if (conc) parts.push(`conc.pers:${conc}`);
  if (field && field.includes("=")) {
    const [n, v] = field.split("=");
    parts.push(`f:${n.trim()}:${v.trim()}`);
  }
  if (from || to) parts.push(`dateIn:${from || "1970-01-01"},${to || "today"}`);
  if ($("search-input")) $("search-input").value = parts.join(" ");
  runSearch();
}

const _origRunSearch = typeof runSearch === "function" ? runSearch : null;
runSearch = async function () {
  const header = $("search-input").value.trim();
  const ft = $("ft-q") ? $("ft-q").value.trim() : "";
  const folder = $("ft-folder") && $("ft-folder").value;
  let q = header || ft;
  if (folder && q && !/\bfolder:/.test(q)) q += ` folder:${folder}`;
  else if (folder && !q) q = `folder:${folder}`;
  hideWork();
  show("work-docs", true);
  currentNav = q ? "search" : "folders";
  layoutShell();
  if (q) {
    await updateQueryChips(q);
    const docs = (await apiFetch(`/query?q=${encodeURIComponent(q)}&mode=${encodeURIComponent(searchMode)}`)) || [];
    renderDocList(docs, "Search results", q);
  } else await loadDocuments();
};

const _origDashboard = typeof renderDashboard === "function" ? renderDashboard : null;
renderDashboard = async function () {
  let home = { recent: [], overdue: [], inbox: [], jobs: [], board: null };
  try { home = await apiFetch("/dashboards/home") || home; } catch (e) { /* */ }
  if (home.board && home.board.layout && home.board.layout.length) {
    try {
      const rendered = await apiFetch(`/dashboards/${home.board.id}/render`);
      $("work-home").innerHTML = `<div class="dash-editor-bar">
        <button onclick="editDashboards()">${esc(home.board.name)}</button>
      </div><div class="dashlets">${(rendered.layout || []).map(renderDashBox).join("")}</div>`;
      return;
    } catch (e) { /* fall through */ }
  }
  if (_origDashboard) return _origDashboard();
};

function renderDashBox(box) {
  const kind = box.kind || box.type || "markdown";
  if (kind === "markdown" || kind === "message") {
    return `<div class="dashlet"><div class="dashlet-h">${esc(box.title || "Note")}</div><div class="p-2">${esc(box.text || box.markdown || "")}</div></div>`;
  }
  if (kind === "stats") {
    return `<div class="dashlet"><div class="dashlet-h">${esc(box.title || "Stats")}</div><p class="p-2">${box.count || 0} items</p></div>`;
  }
  if (kind === "query" || kind === "query-table" || kind === "table") {
    const rows = box.rows || [];
    return `<div class="dashlet"><div class="dashlet-h">${esc(box.title || box.query || "Query")}</div>
      <ul>${rows.map((r) => `<li onclick="openFromDash(${r.id})">${esc(r.title)}</li>`).join("") || "<li>None</li>"}</ul></div>`;
  }
  if (kind === "upload") {
    return `<div class="dashlet"><div class="dashlet-h">Upload</div><button onclick="openUploadModal()">Upload</button></div>`;
  }
  return `<div class="dashlet"><div class="dashlet-h">${esc(kind)}</div></div>`;
}

async function editDashboards() {
  const boards = await apiFetch("/dashboards") || [];
  const html = `<h3>Dashboards</h3>
    ${boards.map((b) => `<div class="row"><b>${esc(b.name)}</b> ${b.is_default ? "(default)" : ""}
      <button onclick="setDefaultBoard(${b.id})">Default</button></div>`).join("")}
    <input id="new-board-name" placeholder="New board name" />
    <p class="text-xs mt-2">Widgets</p>
    <label><input type="checkbox" id="w-md" checked /> Welcome note</label>
    <label><input type="checkbox" id="w-recent" checked /> Recent documents</label>
    <label><input type="checkbox" id="w-overdue" /> Overdue query</label>
    <label><input type="checkbox" id="w-upload" /> Upload</label>
    <label><input type="checkbox" id="w-stats" /> Stats</label>
    <button onclick="createBoard()">Create</button>`;
  $("work-home").innerHTML = html;
}

async function createBoard() {
  const name = val("new-board-name");
  const layout = [];
  if ($("w-md") && $("w-md").checked) layout.push({ kind: "markdown", title: "Hello", text: "Welcome to NewtonEDMS" });
  if ($("w-recent") && $("w-recent").checked) layout.push({ kind: "query-table", title: "Recent", query: "" });
  if ($("w-overdue") && $("w-overdue").checked) layout.push({ kind: "query-table", title: "Overdue", query: "due:overdue" });
  if ($("w-upload") && $("w-upload").checked) layout.push({ kind: "upload", title: "Upload" });
  if ($("w-stats") && $("w-stats").checked) layout.push({ kind: "stats", title: "Stats" });
  await apiFetch("/dashboards", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, layout, is_default: true }) });
  navTo("home");
}
async function setDefaultBoard(id) {
  await apiFetch(`/dashboards/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_default: true }) });
  navTo("home");
}

const _origSettings = typeof renderSettings === "function" ? renderSettings : null;
renderSettings = async function () {
  if (_origSettings) await _origSettings();
  const el = $("work-settings");
  if (!el) return;
  let coll = {};
  try { coll = await apiFetch("/collectives/current") || {}; } catch (e) { /* */ }
  el.insertAdjacentHTML("beforeend", `
    <div class="dashlet" style="margin-top:12px">
      <div class="dashlet-h">${t("collective.settings")}</div>
      <div class="p-2">
        <p>Collective: <b>${esc(coll.name || "")}</b></p>
        <label>Switch collective</label>
        <select id="coll-switch"></select>
        <button onclick="switchCollective()">Switch</button>
        <p>Invite code: <code>${esc(coll.invite_code || "")}</code>
          <button onclick="rotateInvite()">Rotate</button></p>
        <label>Join another</label>
        <input id="invite-join" placeholder="Invite code" />
        <button onclick="joinCollective()">Join</button>
        <label>Language</label>
        <select id="coll-lang"><option>eng</option><option>deu</option><option>fra</option><option>spa</option></select>
        <button onclick="saveCollective()">Save</button>
      </div>
    </div>
    <div class="dashlet" style="margin-top:12px">
      <div class="dashlet-h">UI</div>
      <div class="p-2">
        <label><input type="checkbox" id="ui-power" ${uiSettings.powerSearch !== false ? "checked" : ""}/> Power search</label>
        <label>Card layout</label>
        <select id="ui-cards">
          <option value="cards" ${uiSettings.cardLayout==="cards"?"selected":""}>Cards</option>
          <option value="list" ${uiSettings.cardLayout==="list"?"selected":""}>List</option>
        </select>
        <label>Tags to show</label>
        <input id="ui-tags" type="number" value="${uiSettings.tagCount || 8}" />
        <label>Interface language</label>
        <select id="ui-locale">
          <option value="en">English</option><option value="de">Deutsch</option>
          <option value="fr">Français</option><option value="es">Español</option>
        </select>
        <button onclick="saveUiSettings()">Save UI</button>
      </div>
    </div>
    <div class="dashlet" style="margin-top:12px">
      <div class="dashlet-h">${t("catalog.organizations")}</div>
      <div id="org-list" class="p-2"></div>
      <input id="org-name" placeholder="Name" />
      <input id="org-emails" placeholder="Emails (comma)" />
      <button onclick="addOrg()">Add</button>
    </div>
    <div class="dashlet" style="margin-top:12px">
      <div class="dashlet-h">${t("catalog.equipment")}</div>
      <div id="eq-list" class="p-2"></div>
      <input id="eq-name" placeholder="Name" />
      <button onclick="addEq()">Add</button>
    </div>`);
  fillCatalogs();
  try {
    const colls = await apiFetch("/collectives") || [];
    if ($("coll-switch")) {
      $("coll-switch").innerHTML = colls.map((c) => `<option value="${c.id}" ${c.id === coll.id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
    }
  } catch (e) { /* */ }
};

async function fillCatalogs() {
  const orgs = await apiFetch("/organizations") || [];
  const eqs = await apiFetch("/equipment") || [];
  if ($("org-list")) $("org-list").innerHTML = orgs.map((o) => `<div>${esc(o.name)}</div>`).join("");
  if ($("eq-list")) $("eq-list").innerHTML = eqs.map((o) => `<div>${esc(o.name)}</div>`).join("");
}
async function addOrg() {
  const fd = new FormData();
  fd.append("name", val("org-name"));
  fd.append("emails", val("org-emails") || "");
  await fetch("/api/organizations", { method: "POST", body: fd, credentials: "same-origin" });
  fillCatalogs();
}
async function addEq() {
  const fd = new FormData();
  fd.append("name", val("eq-name"));
  await fetch("/api/equipment", { method: "POST", body: fd, credentials: "same-origin" });
  fillCatalogs();
}
async function saveUiSettings() {
  uiSettings.powerSearch = $("ui-power").checked;
  uiSettings.cardLayout = $("ui-cards").value;
  uiSettings.tagCount = parseInt($("ui-tags").value, 10) || 8;
  uiSettings.locale = $("ui-locale").value;
  await apiFetch("/ui-settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(uiSettings) });
  await loadIntel();
}
async function saveCollective() {
  await apiFetch("/collectives/current", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language: $("coll-lang").value }) });
}
async function rotateInvite() {
  await apiFetch("/collectives/current", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rotate_invite: true }) });
  renderSettings();
}
async function joinCollective() {
  const fd = new FormData();
  fd.append("code", val("invite-join"));
  await fetch("/api/collectives/invite", { method: "POST", body: fd, credentials: "same-origin" });
  renderSettings();
}
async function switchCollective() {
  const id = val("coll-switch");
  if (!id) return;
  await apiFetch(`/collectives/switch?collective_id=${id}`, { method: "POST" });
  location.reload();
}

const _origAdmin = typeof adminTab === "function" ? adminTab : null;
adminTab = async function (tab) {
  if (tab === "jobs") {
    show("work-admin", true);
    const rows = await apiFetch("/jobs/queue") || [];
    $("admin-content").innerHTML = `<h3>${t("queue.title")}</h3>
      <select id="jq-status" onchange="adminTab('jobs')"><option value="">all</option>
        <option>queued</option><option>running</option><option>done</option><option>failed</option><option>error</option></select>
      <table class="grid"><thead><tr><th>ID</th><th>Kind</th><th>Status</th><th>Doc</th><th>Msg</th><th></th></tr></thead>
      <tbody>${rows.map((j) => `<tr><td>${j.id}</td><td>${esc(j.kind)}</td><td>${esc(j.status)}</td><td>${j.document_id || ""}</td>
        <td>${esc(j.message || "")}</td>
        <td><button onclick="retryJob(${j.id})">Retry</button> <button onclick="viewJobLog(${j.id})">Log</button></td></tr>`).join("")}</tbody></table>`;
    return;
  }
  if (_origAdmin) return _origAdmin(tab);
};

async function retryJob(id) {
  await apiFetch(`/jobs/${id}/retry`, { method: "POST" });
  adminTab("jobs");
}
async function viewJobLog(id) {
  const log = await apiFetch(`/jobs/${id}/logs`);
  alert(log.log_text || JSON.stringify(log.entries || [], null, 2));
}

const _origUpload = typeof uploadDoc === "function" ? uploadDoc : null;
uploadDoc = async function () {
  const files = $("upload-file").files;
  if (!files.length) return;
  if ($("upload-group") && $("upload-group").checked) {
    const fd = new FormData();
    fd.append("folder_id", currentFolderId);
    fd.append("title", val("upload-title") || files[0].name);
    fd.append("tags", val("upload-tags") || "");
    fd.append("skip_duplicates", $("upload-skipdup") && $("upload-skipdup").checked ? "true" : "false");
    for (const f of files) fd.append("files", f);
    await fetch("/api/documents/group", { method: "POST", body: fd, credentials: "same-origin" });
    closeModal("upload-modal");
    loadDocuments();
    return;
  }
  if (_origUpload) return _origUpload();
};

const _origMail = typeof sendComposedMail === "function" ? sendComposedMail : null;
sendComposedMail = async function () {
  const ids = selectedIds.size ? [...selectedIds] : (currentDocId ? [currentDocId] : []);
  await apiFetch("/mail/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_ids: ids,
      to: val("mail-to"),
      cc: val("mail-cc"),
      subject: val("mail-subject") || "Documents",
      body: val("mail-body"),
      attach_pdf: $("mail-pdf") && $("mail-pdf").checked,
    }),
  });
  closeModal("mail-modal");
};

document.addEventListener("DOMContentLoaded", () => {
  setTimeout(loadIntel, 400);
});
