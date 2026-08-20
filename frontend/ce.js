/* Community-parity UI: trash, clipboard, details tabs, admin, compose. */
let clipboard = { ids: [], mode: "copy", kind: "document" };
const ACL_FLAGS = ["read","preview","write","add","rename","delete","immutable","security","import","export","download","print","move","email","workflow","calendar","subscription","password","archive"];

async function ceInspTab(tab, body) {
  if (tab === "links") return renderLinks(body);
  if (tab === "history") return renderHistory(body);
  if (tab === "aliases") return renderAliases(body);
  if (tab === "subscriptions") return renderSubs(body);
  if (tab === "security") return renderDocSecurity(body);
  if (tab === "folder") return renderFolderDetails(body);
}

async function renderLinks(body) {
  const rows = (await apiFetch(`/documents/${currentDocId}/links`)) || [];
  body.innerHTML = `<p class="text-xs mb-2">Related documents</p>
    <div class="flex gap-1 mb-2"><input id="link-id" type="number" placeholder="Document id" class="border p-1 flex-1" />
    <button class="tb primary" onclick="addLink()">Link</button></div>
    <ul>${rows.map((r) => `<li class="border-b py-1 flex justify-between">#${r.src_id} → #${r.dst_id} (${esc(r.kind)})
      <button onclick="delLink(${r.id})">×</button></li>`).join("") || "<li>None</li>"}</ul>`;
}
async function addLink() {
  await apiFetch(`/documents/${currentDocId}/links`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dst_id: parseInt(val("link-id"), 10) }) });
  inspTab("links");
}
async function delLink(id) {
  await apiFetch(`/documents/${currentDocId}/links/${id}`, { method: "DELETE" });
  inspTab("links");
}

async function renderHistory(body) {
  const rows = (await apiFetch(`/documents/${currentDocId}/history`)) || [];
  body.innerHTML = `<table class="grid"><thead><tr><th>Action</th><th>Details</th><th>When</th></tr></thead>
    <tbody>${rows.map((l) => `<tr><td>${esc(l.action)}</td><td>${esc((l.details || "").slice(0, 80))}</td><td>${fmtDate(l.timestamp)}</td></tr>`).join("")}</tbody></table>`;
}

async function renderAliases(body) {
  const rows = (await apiFetch(`/documents/${currentDocId}/aliases`)) || [];
  body.innerHTML = `<p class="text-xs mb-2">Shortcuts to this document in other folders.</p>
    <button class="tb" onclick="aliasHere()">Paste as alias in current folder</button>
    <ul>${rows.map((a) => `<li>#${a.id} in folder ${a.folder_id} — ${esc(a.title || a.name)}</li>`).join("") || "<li>None</li>"}</ul>`;
}
async function aliasHere() {
  if (!currentDocId || !currentFolderId) return;
  await apiFetch("/documents/copy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: [currentDocId], target_folder_id: currentFolderId, as_alias: true }) });
  inspTab("aliases");
}

async function renderSubs(body) {
  const rows = (await apiFetch("/subscriptions")) || [];
  const mine = rows.filter((s) => s.resource_type === "document" && s.resource_id === currentDocId);
  body.innerHTML = `<button class="tb primary" onclick="subscribeDoc()">Subscribe</button>
    <ul>${mine.map((s) => `<li>Watching <button onclick="unsub(${s.id})">remove</button></li>`).join("") || "<li>Not subscribed</li>"}</ul>`;
}
async function subscribeDoc() {
  await apiFetch("/subscriptions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resource_type: "document", resource_id: currentDocId }) });
  inspTab("subscriptions");
}
async function unsub(id) { await apiFetch(`/subscriptions/${id}`, { method: "DELETE" }); inspTab("subscriptions"); }

async function renderDocSecurity(body) {
  const d = currentDoc || {};
  const acl = (await apiFetch(`/documents/${currentDocId}/acl`).catch(() => [])) || [];
  const users = (await apiFetch("/users").catch(() => [])) || [];
  const groups = (await apiFetch("/groups").catch(() => [])) || [];
  body.innerHTML = `
    <label>Rating 0–5</label><input id="f-rating" type="number" min="0" max="5" value="${d.rating || 0}" />
    <label>Color</label><input id="f-color" value="${esc(d.color || "")}" placeholder="#44A8D9" />
    <label>Indexable</label><select id="f-idx"><option ${d.indexable==="indexable"?"selected":""}>indexable</option><option ${d.indexable==="metadata"?"selected":""}>metadata</option><option ${d.indexable==="unindexable"?"selected":""}>unindexable</option></select>
    <label><input type="checkbox" id="f-imm" ${d.immutable ? "checked" : ""} /> Immutable</label>
    <label>File password</label><input id="f-pass" type="password" placeholder="set or leave blank" />
    <div class="flex gap-1 mt-2">
      <button class="tb primary" onclick="saveFlags()">Save</button>
      <button class="tb" onclick="lockDoc()">Lock</button>
      <button class="tb" onclick="unlockDoc()">Unlock</button>
      <button class="tb" onclick="indexNow()">Index now</button>
      <button class="tb" onclick="splitDoc()">Split PDF</button>
      <button class="tb" onclick="convertDoc()">Convert to text</button>
    </div>
    <p class="text-xs mt-2">Pages: ${d.page_count || 0} · Locked by: ${d.locked_by || "—"} · Alias of: ${d.alias_of_id || "—"}</p>
    <h4 class="font-bold mt-3">Document ACL</h4>
    ${(acl || []).map((p) => `<div class="text-xs border-b py-1">${esc(p.principal_type)} #${p.principal_id}
      ${ACL_FLAGS.map((b) => `<label><input type="checkbox" ${p.flags && p.flags[b] ? "checked" : ""} data-dacl="${p.principal_type}:${p.principal_id}:${b}" /> ${b}</label>`).join(" ")}
      <button onclick="delDocAcl(${p.id})">×</button>
    </div>`).join("") || "<p class='text-xs'>No document ACL rows yet.</p>"}
    <div class="flex gap-1 mt-2 flex-wrap">
      <select id="dacl-pt"><option value="user">user</option><option value="group">group</option></select>
      <select id="dacl-pid">${users.map((u) => `<option value="${u.id}">${esc(u.username)}</option>`).join("")}${groups.map((g) => `<option value="${g.id}">g:${esc(g.name)}</option>`).join("")}</select>
      <button class="tb" onclick="addDocAcl()">Grant read</button>
      <button class="tb primary" onclick="saveDocAclBits()">Save ACL</button>
    </div>`;
}
async function saveDocAclBits() {
  const grouped = {};
  document.querySelectorAll("[data-dacl]").forEach((el) => {
    const [pt, pid, bit] = el.dataset.dacl.split(":");
    const key = pt + ":" + pid;
    grouped[key] = grouped[key] || { principal_type: pt, principal_id: parseInt(pid, 10), flags: {} };
    grouped[key].flags[bit] = el.checked;
  });
  for (const g of Object.values(grouped)) {
    await apiFetch(`/documents/${currentDocId}/acl`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(g) });
  }
  if (typeof toast === "function") toast("Document ACL saved"); else alert("ACL saved");
  inspTab("security");
}
async function addDocAcl() {
  await apiFetch(`/documents/${currentDocId}/acl`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ principal_type: val("dacl-pt"), principal_id: parseInt(val("dacl-pid"), 10), flags: { read: true, preview: true, download: true } }) });
  inspTab("security");
}
async function delDocAcl(id) {
  await apiFetch(`/documents/${currentDocId}/acl/${id}`, { method: "DELETE" });
  inspTab("security");
}
async function saveFlags() {
  await apiFetch(`/documents/${currentDocId}/flags`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rating: parseInt(val("f-rating"), 10), color: val("f-color"), indexable: val("f-idx"), immutable: $("f-imm").checked, password: val("f-pass") || undefined }) });
  await openDoc(currentDocId);
  inspTab("security");
}
async function lockDoc() { await apiFetch(`/documents/${currentDocId}/lock`, { method: "POST" }); openDoc(currentDocId); }
async function unlockDoc() { await apiFetch(`/documents/${currentDocId}/unlock`, { method: "POST" }); openDoc(currentDocId); }
async function indexNow() { await apiFetch(`/documents/${currentDocId}/index-now`, { method: "POST" }); alert("Indexed"); }
async function splitDoc() { const r = await apiFetch(`/documents/${currentDocId}/split`, { method: "POST" }); alert(`Created ${r.ids.length} pages`); refreshCurrentList(); }
async function convertDoc() { await apiFetch(`/documents/${currentDocId}/convert?fmt=txt`, { method: "POST" }); inspTab("files"); }

async function renderFolderDetails(body) {
  const f = folders.find((x) => x.id === currentFolderId);
  if (!f) { body.innerHTML = "<p>Select a folder</p>"; return; }
  const hist = (await apiFetch(`/folders/${currentFolderId}/history`)) || [];
  const acl = (await apiFetch(`/folders/${currentFolderId}/acl`).catch(() => [])) || [];
  const trig = (await apiFetch(`/folders/${currentFolderId}/triggers`)) || [];
  body.innerHTML = `
    <p><b>${esc(f.name)}</b> · ${esc(f.kind || "folder")} · quota ${formatBytes(f.quota_bytes || 0)}</p>
    <div class="flex gap-1 my-2">
      <button class="tb" onclick="starFolder()">Bookmark</button>
      <button class="tb" onclick="subscribeFolder()">Subscribe</button>
      <button class="tb" onclick="markWorkspace()">Workspace</button>
    </div>
    <h4 class="font-bold mt-2">Security bits</h4>
    ${(acl || []).map((p) => `<div class="text-xs border-b py-1">${esc(p.principal_type)} #${p.principal_id}
      ${ACL_FLAGS.map((b) => `<label><input type="checkbox" ${p.flags && p.flags[b] ? "checked" : ""} data-acl="${p.principal_type}:${p.principal_id}:${b}" /> ${b}</label>`).join(" ")}
    </div>`).join("") || "<p>No ACL rows. Use the folder Security button.</p>"}
    <button class="tb primary mt-1" onclick="saveAclBits()">Save ACL</button>
    <h4 class="font-bold mt-3">History</h4>
    <ul>${hist.slice(0, 20).map((h) => `<li>${esc(h.action)} · ${fmtDate(h.timestamp)}</li>`).join("") || "<li>None</li>"}</ul>
    <h4 class="font-bold mt-3">Workflow triggers</h4>
    <div class="flex gap-1"><input id="tr-tpl" type="number" placeholder="Template id" /><select id="tr-ev"><option>create</option><option>checkin</option></select>
      <button class="tb" onclick="addTrigger()">Add</button></div>
    <ul>${trig.map((t) => `<li>tpl ${t.template_id} on ${esc(t.event)} <button onclick="delTrigger(${t.id})">×</button></li>`).join("")}</ul>`;
}
async function starFolder() {
  await apiFetch("/stars", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "folder", resource_id: currentFolderId, name: folderName(currentFolderId) }) });
  renderBookmarks();
}
async function subscribeFolder() {
  await apiFetch("/subscriptions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resource_type: "folder", resource_id: currentFolderId }) });
  alert("Subscribed");
}
async function markWorkspace() { await apiFetch(`/folders/${currentFolderId}/workspace`, { method: "POST" }); loadFolderTree(); }
async function addTrigger() {
  await apiFetch(`/folders/${currentFolderId}/triggers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ template_id: parseInt(val("tr-tpl"), 10), event: val("tr-ev") }) });
  inspTab("folder");
}
async function delTrigger(id) { await apiFetch(`/folders/${currentFolderId}/triggers/${id}`, { method: "DELETE" }); inspTab("folder"); }
async function saveAclBits() {
  const grouped = {};
  document.querySelectorAll("[data-acl]").forEach((el) => {
    const [pt, pid, bit] = el.dataset.acl.split(":");
    const key = pt + ":" + pid;
    grouped[key] = grouped[key] || { principal_type: pt, principal_id: parseInt(pid, 10), flags: {} };
    grouped[key].flags[bit] = el.checked;
  });
  for (const g of Object.values(grouped)) {
    await apiFetch(`/folders/${currentFolderId}/acl`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(g) });
  }
  alert("ACL saved");
}

async function loadTrash() {
  const [docs, folds] = await Promise.all([apiFetch("/trash/documents"), apiFetch("/trash/folders")]);
  const el = $("trash-list");
  if (!el) return;
  el.innerHTML = `<p class="text-xs mb-1">Documents</p>
    ${(docs || []).map((d) => `<div class="flex justify-between text-xs py-1"><span>${esc(d.title || d.name)}</span>
      <span><button onclick="restoreDoc(${d.id})">Restore</button> <button onclick="purgeDoc(${d.id})">Delete</button></span></div>`).join("") || "<p>Empty</p>"}
    <p class="text-xs mt-2 mb-1">Folders</p>
    ${(folds || []).map((f) => `<div class="flex justify-between text-xs py-1"><span>${esc(f.name)}</span>
      <span><button onclick="restoreFolder(${f.id})">Restore</button> <button onclick="purgeFolder(${f.id})">Delete</button></span></div>`).join("") || "<p>Empty</p>"}`;
}
async function restoreDoc(id) { await apiFetch(`/trash/documents/${id}/restore`, { method: "POST" }); loadTrash(); refreshCurrentList(); }
async function restoreFolder(id) { await apiFetch(`/trash/folders/${id}/restore`, { method: "POST" }); loadTrash(); loadFolderTree(); }
async function purgeDoc(id) { if (!confirm("Permanently delete this document?")) return; await apiFetch(`/trash/documents/${id}`, { method: "DELETE" }); loadTrash(); }
async function purgeFolder(id) { if (!confirm("Permanently delete folder?")) return; await apiFetch(`/trash/folders/${id}`, { method: "DELETE" }); loadTrash(); }
async function emptyTrash() { if (!confirm("Empty trash?")) return; await apiFetch("/trash/empty", { method: "POST" }); loadTrash(); }

function cutSelected() { clipboard = { ids: [...selectedIds], mode: "cut", kind: "document" }; closeDrops(); }
function copySelected() { clipboard = { ids: selectedIds.size ? [...selectedIds] : (currentDocId ? [currentDocId] : []), mode: "copy", kind: "document" }; closeDrops(); }
async function pasteClipboard() {
  if (!clipboard.ids.length || !currentFolderId) return;
  const path = clipboard.mode === "cut" ? "/documents/move" : "/documents/copy";
  await apiFetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: clipboard.ids, target_folder_id: currentFolderId, as_alias: false }) });
  if (clipboard.mode === "cut") clipboard.ids = [];
  refreshCurrentList();
}
async function pasteAlias() {
  if (!clipboard.ids.length || !currentFolderId) return;
  await apiFetch("/documents/copy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: clipboard.ids, target_folder_id: currentFolderId, as_alias: true }) });
  refreshCurrentList();
}

const _docContext = docContext;
docContext = function (e, id) {
  const d = lastDocs.find((x) => x.id === id) || {};
  showCtxMenu(e, `
    <button onclick="openDoc(${id}); inspTab('preview'); closeDrops()">Preview</button>
    <button onclick="downloadDoc(${id}); closeDrops()">Download</button>
    <button onclick="openDoc(${id}); inspTab('links'); closeDrops()">Links</button>
    <div class="sep"></div>
    <button onclick="selectedIds.add(${id}); cutSelected()">Cut</button>
    <button onclick="selectedIds.add(${id}); copySelected()">Copy</button>
    <button onclick="pasteClipboard()">Paste</button>
    <button onclick="pasteAlias()">Paste as alias</button>
    <div class="sep"></div>
    <button onclick="openDoc(${id}); toggleCheckout(); closeDrops()">${d.checked_out_by ? "Check in" : "Check out"}</button>
    <button onclick="currentDocId=${id}; lockDoc(); closeDrops()">Lock</button>
    <button onclick="currentDocId=${id}; unlockDoc(); closeDrops()">Unlock</button>
    <button onclick="apiFetch('/stars',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'document',resource_id:${id},name:'doc'})}); closeDrops()">Bookmark</button>
    <div class="sep"></div>
    <button onclick="openMailCompose(); closeDrops()">Send mail</button>
    <button onclick="openDoc(${id}); reprocessDoc(); closeDrops()">Index / OCR</button>
    <button onclick="deleteDoc(${id}); closeDrops()">Delete</button>
  `);
};

const _folderContext = folderContext;
folderContext = function (e, id) {
  showCtxMenu(e, `
    <button onclick="selectFolder(${id}); closeDrops()">Open</button>
    <button onclick="currentFolderId=${id}; openFolderModal(); closeDrops()">Create</button>
    <button onclick="currentFolderId=${id}; renameFolder(); closeDrops()">Rename</button>
    <button onclick="clipboard={ids:[${id}],mode:'cut',kind:'folder'}; closeDrops()">Cut</button>
    <button onclick="clipboard={ids:[${id}],mode:'copy',kind:'folder'}; closeDrops()">Copy</button>
    <button onclick="pasteFolder(${id}); closeDrops()">Paste here</button>
    <button onclick="pasteFolderAlias(${id}); closeDrops()">Paste as alias</button>
    <button onclick="currentFolderId=${id}; openFolderAcl(); closeDrops()">Security</button>
    <button onclick="currentFolderId=${id}; exportFolder(); closeDrops()">Export ZIP</button>
    <button onclick="exportArchive(${id}); closeDrops()">Export archive</button>
    <button onclick="runQuery('folder:${id}'); closeDrops()">Search in folder</button>
    <button onclick="starFolderId(${id}); closeDrops()">Bookmark</button>
    <button onclick="mergeIntoFolder(${id}); closeDrops()">Merge clipboard folder here</button>
    <button onclick="applyFolderTemplate(${id}); closeDrops()">Apply folder template</button>
    <div class="sep"></div>
    <button onclick="currentFolderId=${id}; deleteFolder(); closeDrops()">Delete</button>
  `);
};
async function pasteFolder(targetId) {
  if (!clipboard.ids.length) return;
  const path = clipboard.mode === "cut" ? "/folders/move" : "/folders/copy";
  await apiFetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ folder_id: clipboard.ids[0], target_folder_id: targetId }) });
  loadFolderTree();
}
async function pasteFolderAlias(targetId) {
  if (!clipboard.ids.length) return;
  await apiFetch("/folders/copy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ folder_id: clipboard.ids[0], target_folder_id: targetId, as_alias: true }) });
  loadFolderTree();
}
async function starFolderId(id) {
  await apiFetch("/stars", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "folder", resource_id: id, name: folderName(id) }) });
  renderBookmarks();
}
async function exportArchive(id) {
  const resp = await fetch(api(`/folders/${id}/export-archive`), { method: "POST", ...FETCH_OPTS });
  const blob = await resp.blob();
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `archive_${id}.zip`; a.click();
}
async function mergeIntoFolder(targetId) {
  if (!clipboard.ids.length || clipboard.kind !== "folder") return alert("Cut/copy a folder first");
  await apiFetch("/folders/merge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ folder_id: clipboard.ids[0], target_folder_id: targetId }) });
  loadFolderTree();
}
async function applyFolderTemplate(folderId) {
  const tpls = (await apiFetch("/folder-templates")) || [];
  if (!tpls.length) return alert("Create a folder template in Administration first");
  const id = prompt("Template id:\n" + tpls.map((t) => `${t.id}: ${t.name}`).join("\n"), String(tpls[0].id));
  if (!id) return;
  await apiFetch(`/folders/${folderId}/apply-template/${id}`, { method: "POST" });
  loadFolderTree();
}

function openMailCompose() {
  const ids = selectedIds.size ? [...selectedIds] : (currentDocId ? [currentDocId] : []);
  if (!ids.length) return alert("Select documents first");
  $("mail-subject").value = "Documents from NewtonEDMS";
  openModal("mail-modal");
}
async function sendComposedMail() {
  const ids = selectedIds.size ? [...selectedIds] : (currentDocId ? [currentDocId] : []);
  await apiFetch("/mail/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_ids: ids, to: val("mail-to"), cc: val("mail-cc") || undefined, subject: val("mail-subject"), body: val("mail-body") }) });
  closeModal("mail-modal");
  alert("Sent");
}

async function importZipFile(input) {
  const file = input.files[0];
  input.value = "";
  if (!file || !currentFolderId) return;
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(api(`/folders/${currentFolderId}/import-zip`), { method: "POST", body: form, ...FETCH_OPTS });
  const r = await resp.json();
  alert(`Imported ${r.imported} files`);
  refreshCurrentList();
}

async function runParametric() {
  const tags = val("p-tags").split(",").map((t) => t.trim()).filter(Boolean);
  const payload = { status: val("p-status") || null, tags, locked: $("p-locked").checked || null, immutable: $("p-imm").checked || null };
  if (val("p-field")) payload.fields = { 0: val("p-field") };
  const docs = await apiFetch("/search/parametric", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  hideWork(); show("work-docs", true); currentNav = "search"; layoutShell();
  renderDocList(docs || [], "Parametric search", "");
}

async function fillHomeTagCloud() {
  const cloud = (await apiFetch("/tags/cloud")) || [];
  const el = $("home-tag-cloud");
  if (el) el.innerHTML = cloud.map((t) => `<button class="tag-chip" onclick="runQuery('tag:${esc(t.name)}')">${esc(t.name)} (${t.count})</button>`).join("") || "No tags";
}

async function renderMessages() {
  const rows = (await apiFetch("/messages")) || [];
  const users = (await apiFetch("/users").catch(() => [])) || [];
  $("work-messages").innerHTML = `
    <h3 class="font-bold mb-2">Messages</h3>
    <div class="flex gap-2 mb-3">
      <select id="msg-to">${users.map((u) => `<option value="${u.id}">${esc(u.username)}</option>`).join("")}</select>
      <input id="msg-subj" placeholder="Subject" class="border p-1 flex-1" />
      <input id="msg-body" placeholder="Body" class="border p-1 flex-1" />
      <button class="tb primary" onclick="sendMsg()">Send</button>
    </div>
    <ul>${rows.map((m) => `<li class="border-b py-1 ${m.read ? "" : "font-bold"}"><b>${esc(m.subject)}</b> — ${esc(m.body)} <span class="text-xs">${fmtDate(m.created_at)}</span>
      ${m.read ? "" : `<button onclick="markMsgRead(${m.id})">mark read</button>`}</li>`).join("") || "<li>None</li>"}</ul>`;
}
async function sendMsg() {
  await apiFetch("/messages", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ to_id: parseInt(val("msg-to"), 10), subject: val("msg-subj"), body: val("msg-body") }) });
  renderMessages();
}
async function markMsgRead(id) {
  await apiFetch(`/messages/${id}/read`, { method: "POST" });
  renderMessages();
}

async function ceAdminTab(tab, content) {
  if (tab === "tickets") {
    const rows = (await apiFetch("/tickets")) || [];
    content.innerHTML = `<h3>Tickets</h3><table class="w-full text-sm"><thead><tr><th>Doc</th><th>Kind</th><th>Downloads</th><th>URL</th></tr></thead>
      <tbody>${rows.map((t) => `<tr><td>#${t.document_id}</td><td>${esc(t.kind)}</td><td>${t.download_count}/${t.max_downloads || "∞"}</td><td><a href="${t.url}" target="_blank">${esc(t.token.slice(0, 8))}…</a></td></tr>`).join("")}</tbody></table>`;
  } else if (tab === "ocr") {
    const s = await apiFetch("/settings/ocr");
    content.innerHTML = `<h3>OCR</h3><textarea id="ocr-json" rows="8" class="w-full border">${esc(s.value || '{"lang":"eng","enabled":true}')}</textarea>
      <button class="tb primary mt-2" onclick="saveSetting('ocr','ocr-json')">Save</button>`;
  } else if (tab === "gui") {
    content.innerHTML = `<h3>Interface</h3>
      <p>Language <input id="gui-lang" value="${esc(currentUser.locale || "en")}" /></p>
      <p>Density <select id="gui-den"><option>compact</option><option selected>standard</option><option>comfortable</option></select></p>
      <button class="tb primary" onclick="saveProfileGui()">Save</button>
      <p class="text-xs mt-2">WebDAV: /webdav · CMIS: /cmis/browser · SOAP: /soap/document</p>`;
  } else if (tab === "ldap") {
    const s = await apiFetch("/settings/ldap");
    content.innerHTML = `<h3>LDAP</h3><textarea id="ldap-json" rows="8" class="w-full border">${esc(s.value || '{"url":"ldap://localhost","base_dn":"dc=example,dc=com","user_dn_pattern":"uid={username},{base}"}')}</textarea>
      <button class="tb primary" onclick="saveSetting('ldap','ldap-json')">Save</button>
      <button class="tb" onclick="testLdap()">Test bind</button>`;
  } else if (tab === "stores") {
    const rows = (await apiFetch("/stores")) || [];
    content.innerHTML = `<h3>Stores</h3>
      <div class="flex gap-2 mb-2"><input id="st-name" placeholder="Name" /><input id="st-path" placeholder="Path" class="flex-1" /><button class="tb primary" onclick="addStore()">Add</button></div>
      <ul>${rows.map((s) => `<li>${esc(s.name)} · ${esc(s.kind)} · ${esc(s.path)} <button onclick="delStore(${s.id})">×</button></li>`).join("")}</ul>`;
  } else if (tab === "scheduled") {
    const rows = (await apiFetch("/tasks/scheduled")) || [];
    content.innerHTML = `<h3>Scheduled tasks</h3><table class="w-full text-sm"><thead><tr><th>Name</th><th>Every</th><th>Last</th><th></th></tr></thead>
      <tbody>${rows.map((t) => `<tr><td>${esc(t.name)}</td><td>${t.interval_minutes}m ${t.enabled ? "on" : "off"}</td><td>${esc(t.last_status || "")} ${esc(t.last_message || "")}</td>
        <td><button onclick="runSched(${t.id})">Run</button></td></tr>`).join("")}</tbody></table>`;
  } else if (tab === "index") {
    const st = await apiFetch("/index/stats").catch(() => ({ docs: 0 }));
    content.innerHTML = `<h3>Search index</h3><p>${st.docs || 0} documents in ${esc(st.path || "")}</p>
      <button class="tb primary" onclick="rebuildIndex()">Rebuild</button>`;
  } else if (tab === "sessions") {
    const rows = (await apiFetch("/sessions")) || [];
    const logins = (await apiFetch("/logins")) || [];
    content.innerHTML = `<h3>Sessions</h3><ul>${rows.map((s) => `<li>${s.ip || ""} · ${fmtDate(s.last_seen_at)} <button onclick="killSession(${s.id})">revoke</button></li>`).join("")}</ul>
      <h3 class="mt-3">Last logins</h3><ul>${logins.map((l) => `<li>${esc(l.username || "")} ${l.success ? "ok" : "fail"} ${l.ip || ""} ${fmtDate(l.created_at)}</li>`).join("")}</ul>`;
  } else if (tab === "protocols") {
    content.innerHTML = `<h3>Protocols</h3>
      <p>WebDAV: <code>${location.origin}/webdav/</code> (Basic auth)</p>
      <p>CMIS browser: <code>${location.origin}/cmis/browser</code></p>
      <p>SOAP: POST <code>${location.origin}/soap/document</code>, /soap/folder, /soap/search, /soap/auth, /soap/system</p>`;
  } else if (tab === "logs") {
    const r = await apiFetch("/logs");
    content.innerHTML = `<h3>Logs</h3><pre class="text-xs bg-slate-50 p-2 max-h-96 overflow-auto">${esc((r.lines || []).join("\n") || "No log file")}</pre>
      <button class="tb" onclick="apiFetch('/system/restart',{method:'POST'}).then(x=>alert(x.message))">Restart hint</button>`;
  } else if (tab === "folder-templates") {
    const rows = (await apiFetch("/folder-templates")) || [];
    content.innerHTML = `<h3>Folder templates</h3>
      <div class="flex gap-2 mb-2"><input id="ft-name" placeholder="Name" /><input id="ft-tree" placeholder='[{"name":"Inbox"}]' class="flex-1" />
      <button class="tb primary" onclick="addFolderTpl()">Add</button></div>
      <ul>${rows.map((t) => `<li>${esc(t.name)} #${t.id} · ${esc(JSON.stringify(t.tree || []))}</li>`).join("") || "<li>None</li>"}</ul>
      <p class="text-xs mt-2">Right-click a folder → Apply folder template</p>`;
  } else if (tab === "naming") {
    const rows = (await apiFetch("/naming-schemes")) || [];
    content.innerHTML = `<h3>Custom ID schemes</h3>
      <div class="flex gap-2 mb-2"><input id="ns-name" placeholder="Name" /><input id="ns-pat" placeholder="{folder}-{seq}" class="flex-1" />
      <button class="tb primary" onclick="addScheme()">Add</button></div>
      <ul>${rows.map((s) => `<li>${esc(s.name)} · ${esc(s.pattern)}</li>`).join("") || "<li>None</li>"}</ul>`;
  } else if (tab === "converters") {
    const rows = (await apiFetch("/converters")) || [];
    content.innerHTML = `<h3>Converters</h3><ul>${rows.map((c) => `<li>${esc(c.name)} — ${c.available ? "available" : "missing"}</li>`).join("")}</ul>
      <p class="text-xs mt-2">Split PDF and Convert to text are on the document Security tab.</p>`;
  } else if (tab === "reports") {
    const [locked, dups, archived, apiCalls, deleted] = await Promise.all([
      apiFetch("/reports/locked"), apiFetch("/reports/duplicates"), apiFetch("/reports/archived"),
      apiFetch("/reports/api-calls"), apiFetch("/reports/deleted"),
    ]);
    content.innerHTML = `<h3>Reports</h3>
      <p><b>Locked:</b> ${(locked || []).length} · <b>Duplicates:</b> ${(dups || []).length} · <b>Archived:</b> ${(archived || []).length}</p>
      <p><b>Deleted docs:</b> ${((deleted && deleted.documents) || []).length} · folders ${((deleted && deleted.folders) || []).length}</p>
      <p><b>API calls:</b> ${(apiCalls || []).map((a) => `${esc(a.action)} ${a.count}`).join(", ")}</p>`;
  }
}

async function addFolderTpl() {
  const tree = val("ft-tree") ? JSON.parse(val("ft-tree")) : [];
  await apiFetch("/folder-templates", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("ft-name"), tree }) });
  adminTab("folder-templates");
}
async function addScheme() {
  await apiFetch("/naming-schemes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("ns-name"), pattern: val("ns-pat") }) });
  adminTab("naming");
}

async function saveSetting(key, id) {
  await apiFetch(`/settings/${key}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: val(id) }) });
  alert("Saved");
}
async function saveProfileGui() {
  await apiFetch("/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ locale: val("gui-lang"), density: val("gui-den") }) });
  document.documentElement.dataset.density = val("gui-den");
  alert("Saved");
}
async function testLdap() { const r = await apiFetch("/ldap/test", { method: "POST" }); alert(r.message || JSON.stringify(r)); }
async function addStore() {
  await apiFetch("/stores", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("st-name"), path: val("st-path") }) });
  adminTab("stores");
}
async function delStore(id) { await apiFetch(`/stores/${id}`, { method: "DELETE" }); adminTab("stores"); }
async function runSched(id) { await apiFetch(`/tasks/scheduled/${id}/run`, { method: "POST" }); adminTab("scheduled"); }
async function rebuildIndex() { const r = await apiFetch("/index/rebuild", { method: "POST" }); alert(`Indexed ${r.indexed}`); }
async function killSession(id) { await apiFetch(`/sessions/${id}`, { method: "DELETE" }); adminTab("sessions"); }

document.addEventListener("DOMContentLoaded", () => {
  const area = $("work-docs");
  if (!area) return;
  area.addEventListener("dragover", (e) => { e.preventDefault(); area.style.outline = "2px dashed #44a8d9"; });
  area.addEventListener("dragleave", () => { area.style.outline = ""; });
  area.addEventListener("drop", async (e) => {
    e.preventDefault(); area.style.outline = "";
    if (!currentFolderId || !e.dataTransfer.files.length) return;
    for (const file of e.dataTransfer.files) {
      const form = new FormData();
      form.append("file", file);
      form.append("folder_id", currentFolderId);
      form.append("title", file.name);
      await fetch(api("/documents"), { method: "POST", body: form, ...FETCH_OPTS });
    }
    refreshCurrentList();
  });
});
