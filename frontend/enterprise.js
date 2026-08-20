/* NewtonEDMS enterprise UI: workflow canvas, rules, compliance, RAG, connectors. */
const ENT_TABS = new Set([
  "rules", "forms", "zones", "holds", "cases", "bpmn", "rag", "connectors",
  "cluster", "compliance", "security-policy", "report-builder", "office",
]);

const _entAdmin = typeof adminTab === "function" ? adminTab : null;
adminTab = async function (tab) {
  document.querySelectorAll(".admin-item").forEach((b) => b.classList.toggle("active", b.dataset.admin === tab));
  if (ENT_TABS.has(tab)) {
    await renderEntTab(tab);
    return;
  }
  if (_entAdmin) return _entAdmin(tab);
};

const _entInsp = typeof inspTab === "function" ? inspTab : null;
inspTab = async function (tab) {
  if (tab === "pdfops" && currentDocId) {
    markInspTab(tab);
    await renderPdfOps($("insp-body"));
    return;
  }
  if (_entInsp) return _entInsp(tab);
};

async function renderEntTab(tab) {
  const content = $("admin-content");
  if (tab === "rules") {
    const rows = (await apiFetch("/automation-rules")) || [];
    content.innerHTML = `<h3 class="font-bold mb-2">Automation rules</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="rl-name" placeholder="Name" class="border p-2 rounded" />
        <select id="rl-event" class="border p-2 rounded"><option>document_created</option><option>document_processed</option><option>document_confirmed</option></select>
        <select id="rl-when"><option value="tag">if tag</option><option value="status">if status</option><option value="mime">if mime contains</option></select>
        <input id="rl-val" placeholder="invoice" class="border p-2 rounded" />
        <select id="rl-do"><option value="tag">then tag</option><option value="status">then set status</option><option value="workflow">then start workflow id</option></select>
        <input id="rl-actval" placeholder="auto" class="border p-2 rounded" />
        <button class="tb primary" onclick="createRuleBuilt()">Add</button>
      </div>
      <ul>${rows.map((r) => `<li class="border-b p-2">${esc(r.name)} · ${esc(r.event)}
        <button class="text-red-600" onclick="delRule(${r.id})">delete</button></li>`).join("") || "<li>None</li>"}</ul>`;
  } else if (tab === "forms") {
    const rows = (await apiFetch("/forms")) || [];
    content.innerHTML = `<h3 class="font-bold mb-2">Capture forms</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="fm-name" placeholder="Form name" class="border p-2 rounded" />
        <input id="fm-folder" type="number" placeholder="Folder id" class="border p-2 rounded w-28" />
        <button class="tb" onclick="fmAddField()">+ Field</button>
        <button class="tb primary" onclick="createFormBuilt()">Save form</button>
      </div>
      <div id="fm-fields" class="text-sm mb-2"></div>
      <ul>${rows.map((r) => `<li class="border-b p-2">${esc(r.name)} · <a href="/forms/${esc(r.token)}" target="_blank">open</a>
        <img alt="barcode" src="/api/barcodes/code128?data=${encodeURIComponent(r.token)}" style="height:28px;vertical-align:middle" /></li>`).join("") || "<li>None</li>"}</ul>`;
    window._fmFields = [];
  } else if (tab === "zones") {
    const rows = (await apiFetch("/zones")) || [];
    content.innerHTML = `<h3 class="font-bold mb-2">Zonal IDP templates</h3>
      <p class="text-xs mb-2">Zones are PDF-point rectangles: page, x, y, w, h, name.</p>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="zn-name" placeholder="Name" class="border p-2 rounded" />
        <input id="zn-json" placeholder='[{"page":1,"x":40,"y":40,"w":200,"h":24,"name":"invoice_no"}]' class="border p-2 rounded flex-1" />
        <button class="tb primary" onclick="createZone()">Add</button>
        <button class="tb" onclick="trainIdp()">Train classifier</button>
      </div>
      <ul>${rows.map((r) => `<li class="border-b p-2">${esc(r.name)} · ${(r.zones || []).length} zones</li>`).join("") || "<li>None</li>"}</ul>`;
  } else if (tab === "holds") {
    const rows = (await apiFetch("/legal-holds")) || [];
    content.innerHTML = `<h3 class="font-bold mb-2">Legal hold</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="lh-name" placeholder="Matter name" class="border p-2 rounded" />
        <input id="lh-reason" placeholder="Reason" class="border p-2 rounded flex-1" />
        <input id="lh-ids" placeholder="Document ids 1,2,3" class="border p-2 rounded" />
        <button class="tb" onclick="lhPickOpen()">Pick from folder</button>
        <button class="tb primary" onclick="createHold()">Place hold</button>
      </div>
      <div id="lh-pick"></div>
      <ul>${rows.map((r) => `<li class="border-b p-2">${esc(r.name)} ${r.active ? "ACTIVE" : "released"}
        <div class="text-xs">${(r.documents || []).map((d) => esc(d.title || "#" + d.id)).join(", ") || "no documents"}</div>
        ${r.active ? `<button onclick="releaseHold(${r.id})">Release</button>` : ""}</li>`).join("") || "<li>None</li>"}</ul>`;
  } else if (tab === "bpmn") {
    const [bpmn, cases] = await Promise.all([apiFetch("/bpmn"), apiFetch("/cases")]);
    content.innerHTML = `<h3 class="font-bold mb-2">BPMN 2.0 &amp; cases</h3>
      <textarea id="bpmn-xml" rows="8" class="w-full border" placeholder="Paste BPMN XML"></textarea>
      <div class="flex gap-2 mt-2 mb-3">
        <input id="bpmn-name" placeholder="Name" class="border p-2 rounded" />
        <button class="tb primary" onclick="uploadBpmn()">Import BPMN</button>
      </div>
      <ul>${(bpmn || []).map((b) => `<li class="border-b p-2">${esc(b.name)} · ${(b.graph && b.graph.nodes || []).length} nodes</li>`).join("")}</ul>
      <h4 class="font-bold mt-4">Cases</h4>
      <div class="flex gap-2 mb-2">
        <input id="cs-name" placeholder="Case name" class="border p-2 rounded" />
        <input id="cs-docs" placeholder="Doc ids" class="border p-2 rounded" />
        <select id="cs-bpmn"><option value="">BPMN…</option>${(bpmn || []).map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join("")}</select>
        <button class="tb primary" onclick="createCase()">Open case</button>
      </div>
      <ul>${(cases || []).map((c) => `<li class="border-b p-2">${esc(c.name)} · ${esc(c.status)} ${c.bpmn_id ? `<button onclick="startCase(${c.id})">Run process</button>` : ""}</li>`).join("") || "<li>None</li>"}</ul>`;
  } else if (tab === "rag") {
    content.innerHTML = `<h3 class="font-bold mb-2">GenAI / vector search</h3>
      <input id="rag-q" class="w-full border p-2 rounded mb-2" placeholder="Ask a question across indexed documents" />
      <button class="tb primary" onclick="runRag()">Ask</button>
      <div id="rag-chat" class="mt-3 text-sm space-y-2"></div>
      <pre id="rag-out" class="mt-3 text-xs whitespace-pre-wrap bg-slate-50 p-2 rounded"></pre>`;
  } else if (tab === "connectors") {
    const rows = (await apiFetch("/connectors")) || [];
    content.innerHTML = `<h3 class="font-bold mb-2">Connectors</h3>
      <p class="text-xs mb-2">Kinds: azure, smb, gdrive, docusign, onlyoffice, outlook, gcal, sap</p>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="cn-name" placeholder="Name" class="border p-2 rounded" />
        <select id="cn-kind" class="border p-2 rounded"><option>azure</option><option>smb</option><option>gdrive</option><option>docusign</option><option>onlyoffice</option><option>outlook</option><option>gcal</option><option>sap</option></select>
        <input id="cn-cfg" placeholder='{"account":"..."} or Graph {"access_token":"..."}' class="border p-2 rounded flex-1" />
        <button class="tb primary" onclick="createConnector()">Add</button>
      </div>
      <div class="flex gap-2 mb-2 flex-wrap">
        <button class="tb" onclick="ooOpen()">OnlyOffice config</button>
        <button class="tb" onclick="dsSend()">DocuSign send</button>
        <button class="tb" onclick="gdImport()">Drive import</button>
        <button class="tb" onclick="gcalSync()">GCal sync</button>
        <button class="tb" onclick="olMail()">Outlook mail</button>
      </div>
      <ul>${rows.map((r) => `<li class="border-b p-2">${esc(r.kind)} · ${esc(r.name)}</li>`).join("") || "<li>None</li>"}</ul>
      <pre id="cn-out" class="text-xs mt-2"></pre>`;
  } else if (tab === "cluster") {
    const c = await apiFetch("/cluster");
    content.innerHTML = `<h3 class="font-bold mb-2">Cluster</h3>
      <p>This node: <code>${esc(c.self || "")}</code></p>
      <table class="w-full text-sm mt-2"><thead><tr><th>Node</th><th>Role</th><th>Host</th><th>Alive</th></tr></thead>
      <tbody>${(c.members || []).map((m) => `<tr class="border-b"><td class="p-2">${esc(m.node_id)}</td><td>${esc(m.role)}</td><td>${esc(m.host || "")}</td><td>${m.alive ? "yes" : "no"}</td></tr>`).join("")}</tbody></table>`;
  } else if (tab === "compliance") {
    const c = await apiFetch("/compliance");
    const block = (name, pack) => `<div class="border rounded p-3"><h4 class="font-bold">${esc(name)}</h4>
      <p>${pack.passed}/${pack.total} controls</p>
      <ul class="text-xs">${Object.entries(pack.controls || {}).map(([k, v]) => `<li>${v ? "✓" : "✗"} ${esc(k)}</li>`).join("")}</ul></div>`;
    content.innerHTML = `<h3 class="font-bold mb-2">GDPR / HIPAA / ISO 27001</h3>
      <div class="grid grid-cols-3 gap-3">${block("GDPR", c.gdpr)}${block("HIPAA", c.hipaa)}${block("ISO 27001", c.iso27001)}</div>
      <p class="text-xs mt-3">Evidence: <a href="#" onclick="adminTab('audit');return false">Audit log</a> ·
        <a href="#" onclick="adminTab('holds');return false">Legal holds</a> ·
        <a href="#" onclick="adminTab('gdpr');return false">Subject export</a> ·
        <a href="#" onclick="adminTab('security-policy');return false">Access policy</a></p>`;
  } else if (tab === "security-policy") {
    const p = await apiFetch("/security-policy");
    content.innerHTML = `<h3 class="font-bold mb-2">Security policy</h3>
      <label>IP allowlist (comma)</label><input id="sp-allow" class="w-full border p-1" value="${esc((p.ip_allowlist || []).join(", "))}" />
      <label>IP denylist</label><input id="sp-deny" class="w-full border p-1" value="${esc((p.ip_denylist || []).join(", "))}" />
      <label>Max failed logins</label><input id="sp-fail" type="number" value="${p.max_failed_logins || 8}" />
      <label>Lockout minutes</label><input id="sp-lock" type="number" value="${p.lockout_minutes || 15}" />
      <label>Password max days (0=off)</label><input id="sp-pwd" type="number" value="${p.password_max_days || 0}" />
      <button class="tb primary mt-2" onclick="saveSecPolicyForm()">Save</button>`;
  } else if (tab === "report-builder") {
    const rows = (await apiFetch("/report-definitions")) || [];
    content.innerHTML = `<h3 class="font-bold mb-2">Custom reports</h3>
      <div class="flex gap-2 mb-3 flex-wrap">
        <input id="rp-name" placeholder="Name" class="border p-2 rounded" />
        <input id="rp-q" placeholder="tag:invoice" class="border p-2 rounded flex-1" />
        <select id="rp-g" class="border p-2 rounded"><option value="status">status</option><option value="source">source</option></select>
        <button class="tb primary" onclick="createReportDef()">Save</button>
      </div>
      <ul>${rows.map((r) => `<li class="border-b p-2">${esc(r.name)} · ${esc(r.query || "")} · by ${esc(r.group_by || "")}
        <button class="text-blue-600" onclick="runReportDef(${r.id})">run</button></li>`).join("") || "<li>None</li>"}</ul>
      <div id="rp-out" class="text-xs mt-2"></div>
      <div id="rp-chart" class="mt-2"></div>`;
  } else if (tab === "office") {
    const info = (await apiFetch("/office/addin/info")) || {};
    content.innerHTML = `
      <div style="padding:4px">
        <h3 class="font-bold text-base mb-1"><i class="fa-solid fa-file-word text-blue-600"></i> Microsoft Office Integration</h3>
        <p class="text-xs text-slate-500 mb-4">Enterprise WOPI Host, Desktop Protocol Launchers, and Office 365 Add-in suite for Word, Excel, PowerPoint, and Outlook.</p>

        <div class="grid grid-cols-2 gap-4 mb-4">
          <div class="border rounded-lg p-4 bg-slate-50 dark:bg-slate-800">
            <div class="flex items-center gap-2 mb-2">
              <i class="fa-solid fa-cloud text-blue-500 text-lg"></i>
              <strong class="text-sm">WOPI Protocol Host</strong>
            </div>
            <p class="text-xs text-slate-600 dark:text-slate-300 mb-2">Enables live in-browser co-authoring & editing with Microsoft 365, Office Online Server, Collabora, and OnlyOffice.</p>
            <div class="text-xs bg-slate-900 text-sky-300 p-2 rounded font-mono mb-2">GET /wopi/files/{id}<br>POST /wopi/files/{id}/contents</div>
            <div class="text-xs text-slate-500">Status: <span class="text-emerald-600 font-semibold">Active & Serving WOPI 2.0</span></div>
          </div>

          <div class="border rounded-lg p-4 bg-slate-50 dark:bg-slate-800">
            <div class="flex items-center gap-2 mb-2">
              <i class="fa-solid fa-desktop text-indigo-500 text-lg"></i>
              <strong class="text-sm">Desktop URI Handlers</strong>
            </div>
            <p class="text-xs text-slate-600 dark:text-slate-300 mb-2">Launch native desktop Office applications with direct WebDAV check-in and file locking.</p>
            <div class="text-xs bg-slate-900 text-sky-300 p-2 rounded font-mono mb-2">ms-word:ofe|u|...<br>ms-excel:ofe|u|...</div>
            <div class="text-xs text-slate-500">Status: <span class="text-emerald-600 font-semibold">Enabled (Word, Excel, PowerPoint)</span></div>
          </div>
        </div>

        <div class="border rounded-lg p-4 mb-4">
          <h4 class="font-bold text-sm mb-2"><i class="fa-solid fa-puzzle-piece text-amber-500"></i> Microsoft Office 365 Add-in (Word, Excel, PowerPoint, Outlook)</h4>
          <p class="text-xs text-slate-600 dark:text-slate-300 mb-3">Install the NewtonEDMS Add-in into Microsoft Office to explore the repository, insert metadata, save active documents, and archive Outlook emails.</p>
          <div class="flex gap-2 mb-3 flex-wrap">
            <a href="/api/office/addin/manifest.xml" class="tb primary" target="_blank"><i class="fa-solid fa-download"></i> Download Manifest.xml</a>
            <a href="/api/office/addin/manifest.json" class="tb" target="_blank"><i class="fa-solid fa-file-code"></i> Download Manifest.json</a>
            <a href="/static/office-addin/taskpane.html" class="tb" target="_blank"><i class="fa-solid fa-window-maximize"></i> Open Taskpane Preview</a>
          </div>
          <div class="bg-amber-50 dark:bg-slate-900 border border-amber-200 dark:border-slate-700 rounded p-3 text-xs">
            <strong>Sideloading Instructions:</strong><br>
            1. Download <code>manifest.xml</code> from the button above.<br>
            2. In desktop Microsoft Word or Excel, navigate to <strong>Insert > Add-ins > My Add-ins > Shared Folder</strong>.<br>
            3. Point Office to your manifest folder or deploy globally via the <strong>Microsoft 365 Admin Center</strong>.
          </div>
        </div>
      </div>
    `;
  }
}

async function createRule() {
  await apiFetch("/automation-rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("rl-name"), event: val("rl-event"), condition: JSON.parse(val("rl-cond") || "{}"), actions: JSON.parse(val("rl-act") || "[]") }) });
  adminTab("rules");
}
async function delRule(id) { await apiFetch(`/automation-rules/${id}`, { method: "DELETE" }); adminTab("rules"); }
async function createForm() {
  await apiFetch("/forms", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("fm-name"), folder_id: parseInt(val("fm-folder"), 10), schema: JSON.parse(val("fm-schema") || "{}") }) });
  adminTab("forms");
}
async function createZone() {
  await apiFetch("/zones", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("zn-name"), zones: JSON.parse(val("zn-json") || "[]") }) });
  adminTab("zones");
}
async function trainIdp() { const r = await apiFetch("/idp/train", { method: "POST" }); toast("Classifier trained successfully: " + JSON.stringify(r)); }
async function createHold() {
  const ids = val("lh-ids").split(",").map((x) => parseInt(x.trim(), 10)).filter(Boolean);
  await apiFetch("/legal-holds", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("lh-name"), reason: val("lh-reason"), document_ids: ids }) });
  adminTab("holds");
}
async function releaseHold(id) { await apiFetch(`/legal-holds/${id}/release`, { method: "POST" }); adminTab("holds"); }
async function uploadBpmn() {
  const body = new FormData();
  body.append("name", val("bpmn-name"));
  body.append("xml", val("bpmn-xml"));
  await apiFetch("/bpmn", { method: "POST", body });
  adminTab("bpmn");
}
async function createCase() {
  const ids = val("cs-docs").split(",").map((x) => parseInt(x.trim(), 10)).filter(Boolean);
  const bpmnId = val("cs-bpmn") ? parseInt(val("cs-bpmn"), 10) : null;
  await apiFetch("/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("cs-name"), document_ids: ids, bpmn_id: bpmnId || undefined }) });
  adminTab("bpmn");
}
async function startCase(id) {
  const r = await apiFetch(`/cases/${id}/start`, { method: "POST" });
  toast(JSON.stringify(r));
  adminTab("bpmn");
}
async function runRag() {
  const r = await apiFetch("/rag", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: val("rag-q") }) });
  const chat = $("rag-chat");
  if (chat) {
    chat.insertAdjacentHTML("beforeend", `<div class="border rounded p-2"><b>Q:</b> ${esc(val("rag-q"))}<br><b>A (${esc(r.backend || "hashing")}):</b> ${esc(r.answer || "")}</div>`);
  }
  if ($("rag-out")) $("rag-out").textContent = (r.hits || []).map((h) => `#${h.document_id} (${h.score}) ${(h.text || "").slice(0, 180)}`).join("\n---\n");
}
async function createConnector() {
  await apiFetch("/connectors", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("cn-name"), kind: val("cn-kind"), config: JSON.parse(val("cn-cfg") || "{}") }) });
  adminTab("connectors");
}
async function saveSecPolicy() {
  await apiFetch("/security-policy", { method: "PUT", headers: { "Content-Type": "application/json" }, body: val("sec-json") });
  toast("Policy saved");
}
async function saveSecPolicyForm() {
  const body = {
    ip_allowlist: val("sp-allow").split(",").map((s) => s.trim()).filter(Boolean),
    ip_denylist: val("sp-deny").split(",").map((s) => s.trim()).filter(Boolean),
    max_failed_logins: parseInt(val("sp-fail"), 10) || 8,
    lockout_minutes: parseInt(val("sp-lock"), 10) || 15,
    password_max_days: parseInt(val("sp-pwd"), 10) || 0,
  };
  await apiFetch("/security-policy", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  toast("Policy saved");
}
async function createRuleBuilt() {
  const when = val("rl-when"), v = val("rl-val"), act = val("rl-do"), av = val("rl-actval");
  const condition = {};
  condition[when] = v;
  const actions = [{ type: act === "workflow" ? "workflow" : act, tags: act === "tag" ? av : undefined, status: act === "status" ? av : undefined, template_id: act === "workflow" ? parseInt(av, 10) : undefined }];
  await apiFetch("/automation-rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("rl-name"), event: val("rl-event"), condition, actions }) });
  adminTab("rules");
}
window._fmFields = window._fmFields || [];
function fmAddField() {
  const name = prompt("Field name", "title");
  if (!name) return;
  const label = prompt("Label", name) || name;
  const type = prompt("Type (text/number/date)", "text") || "text";
  window._fmFields.push({ name, label, type });
  const el = $("fm-fields");
  if (el) el.innerHTML = window._fmFields.map((f) => `${esc(f.label)} (${esc(f.type)})`).join(" · ");
}
async function createFormBuilt() {
  await apiFetch("/forms", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("fm-name"), folder_id: parseInt(val("fm-folder"), 10), schema: { fields: window._fmFields || [] } }) });
  window._fmFields = [];
  adminTab("forms");
}
async function lhPickOpen() {
  const docs = (await apiFetch(`/documents?folder_id=${currentFolderId || ""}&limit=50`)) || [];
  const el = $("lh-pick");
  if (!el) return;
  el.innerHTML = docs.map((d) => `<label class="block text-xs"><input type="checkbox" data-lh="${d.id}" /> ${esc(d.title || d.name)}</label>`).join("") +
    `<button class="tb mt-1" onclick="lhApplyPick()">Use selected</button>`;
}
function lhApplyPick() {
  const ids = [...document.querySelectorAll("[data-lh]:checked")].map((el) => el.dataset.lh);
  const inp = $("lh-ids");
  if (inp) inp.value = ids.join(",");
}
async function ooOpen() {
  if (!currentDocId) { toast("Open a document first"); return; }
  const r = await apiFetch(`/connectors/onlyoffice/${currentDocId}`);
  $("cn-out").textContent = JSON.stringify(r, null, 2);
}
async function dsSend() {
  if (!currentDocId) { toast("Open a document first"); return; }
  const email = prompt("Signer email");
  if (!email) return;
  const fd = new FormData();
  fd.append("doc_id", currentDocId);
  fd.append("email", email);
  fd.append("name", "Signer");
  const r = await apiFetch("/connectors/docusign/send", { method: "POST", body: fd });
  $("cn-out").textContent = JSON.stringify(r, null, 2);
}
async function gdImport() {
  const fileId = prompt("Google Drive file id");
  const fd = new FormData();
  fd.append("file_id", fileId);
  fd.append("folder_id", currentFolderId);
  const r = await apiFetch("/connectors/gdrive/import", { method: "POST", body: fd });
  toast("Imported #" + (r.id || ""));
}
async function gcalSync() {
  const r = await apiFetch("/connectors/gcal/sync", { method: "POST" });
  const out = $("cn-out");
  if (out) out.textContent = JSON.stringify(r);
  toast("Google Calendar: pushed " + (r.pushed || 0));
  return r;
}
async function olMail() {
  const r = await apiFetch("/connectors/outlook/mail");
  $("cn-out").textContent = JSON.stringify(r, null, 2);
}
async function createReportDef() {
  await apiFetch("/report-definitions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("rp-name"), query: val("rp-q"), group_by: val("rp-g") }) });
  adminTab("report-builder");
}
async function runReportDef(id) {
  const r = await apiFetch(`/report-definitions/${id}/run`);
  $("rp-out").textContent = JSON.stringify(r, null, 2);
  const chart = $("rp-chart");
  if (chart && r && r.groups) {
    const entries = Object.entries(r.groups);
    const max = Math.max(1, ...entries.map((e) => e[1]));
    chart.innerHTML = entries.map(([k, v]) => `<div class="flex items-center gap-2 text-xs"><span class="w-24">${esc(k)}</span><span style="display:inline-block;height:10px;background:#44a8d9;width:${(v / max) * 240}px"></span> ${v}</div>`).join("");
  }
}

async function renderPdfOps(body) {
  const ver = await apiFetch(`/documents/${currentDocId}/sign/verify`).catch(() => null);
  const sig = (currentDoc && currentDoc.metadata && currentDoc.metadata.signature) || null;
  body.innerHTML = `<h4 class="font-bold mb-2">PDF processing</h4>
    <div class="text-xs border rounded p-2 mb-2" id="sign-status">
      ${ver ? (ver.ok
        ? `<span class="text-emerald-600">✓ Signed${ver.signer ? " by " + esc(ver.signer) : ""}${ver.method ? " · " + esc(ver.method) : ""}</span>`
        : '<span class="text-red-600">✗ Signature check failed</span>') : '<span class="text-gray-500">Not signed</span>'}
      ${sig && sig.signed_at ? `<div class="text-gray-400">${esc(sig.signed_at)}</div>` : ""}
    </div>
    <input id="sign-reason" placeholder="Signature reason" class="w-full border p-1 rounded mb-1" value="approved" />
    <button class="tb primary w-full mb-2" onclick="doSign()"><i class="fa-solid fa-signature"></i> Sign document</button>
    <button class="tb w-full mb-2" onclick="verifySignatureNow()">Verify signature</button>
    <input id="wm-text" placeholder="Watermark text" class="w-full border p-1 rounded mb-1" value="CONFIDENTIAL" />
    <button class="tb w-full mb-2" onclick="doWatermark()">Watermark</button>
    <input id="st-text" placeholder="Stamp / barcode text" class="w-full border p-1 rounded mb-1" />
    <button class="tb w-full mb-2" onclick="doStamp()">Digital stamp</button>
    <input id="rd-pat" placeholder="Redact regex e.g. [A-Z]{2}\\d{2}[A-Z0-9]+" class="w-full border p-1 rounded mb-1" />
    <button class="tb w-full mb-2" onclick="doRedact()">Auto-redact</button>
    <button class="tb w-full mb-2" onclick="doSplitPdf()">Split pages</button>
    <button class="tb w-full mb-2" onclick="runIdpNow()">IDP capture</button>
    <button class="tb w-full" onclick="embedNow()">Index for RAG</button>`;
}
async function doWatermark() {
  await apiFetch(`/documents/${currentDocId}/watermark`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: val("wm-text") || "CONFIDENTIAL" }) });
  toast("Watermark applied successfully", "success");
  if (typeof openDoc === "function") await openDoc(currentDocId);
}
async function doStamp() {
  const fd = new FormData(); fd.append("text", val("st-text") || "STAMPED");
  await apiFetch(`/documents/${currentDocId}/stamp`, { method: "POST", body: fd });
  toast("Digital stamp applied", "success");
  if (typeof openDoc === "function") await openDoc(currentDocId);
}
async function doSign() {
  const reason = prompt("Why are you signing this document?", val("sign-reason") || "approved");
  if (reason == null) return;
  const fd = new FormData(); fd.append("reason", reason || "approved");
  try {
    const r = await apiFetch(`/documents/${currentDocId}/sign`, { method: "POST", body: fd });
    if (r) {
      toast("Document signed digitally", "success");
      await openDoc(currentDocId);
      inspTab("pdfops");
    }
  } catch (e) { toast(e.message, "error"); }
}
async function verifySignatureNow() {
  const r = await apiFetch(`/documents/${currentDocId}/sign/verify`).catch(() => null);
  const el = $("sign-status");
  if (!r) { if (el) el.innerHTML = '<span class="text-gray-500">Not signed</span>'; return; }
  if (el) el.innerHTML = r.ok
    ? `<span class="text-emerald-600">✓ Signed${r.signer ? " by " + esc(r.signer) : ""}${r.method ? " · " + esc(r.method) : ""}</span>`
    : '<span class="text-red-600">✗ Signature check failed</span>';
}
async function doRedact() {
  await apiFetch(`/documents/${currentDocId}/redact`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ patterns: [val("rd-pat") || "\\b\\d{3}-\\d{2}-\\d{4}\\b"] }) });
  toast("Auto-redaction applied", "success");
  if (typeof openDoc === "function") await openDoc(currentDocId);
}
async function doSplitPdf() {
  const r = await apiFetch(`/documents/${currentDocId}/split`, { method: "POST" });
  toast(`Split completed: ${r.count || (r.ids ? r.ids.length : 0)} pages created`, "success");
  if (typeof refreshCurrentList === "function") refreshCurrentList();
}
async function runIdpNow() {
  const r = await apiFetch(`/documents/${currentDocId}/idp`, { method: "POST" });
  toast("IDP capture completed: " + Object.keys(r.captured || {}).length + " fields captured", "success");
}
async function embedNow() {
  await apiFetch(`/documents/${currentDocId}/embed`, { method: "POST" });
  toast("Document embedded and indexed for RAG vector search", "success");
}
async function confirmReadCurrent() {
  if (!currentDocId) return;
  await apiFetch(`/documents/${currentDocId}/confirm-read`, { method: "POST" });
  toast("Reading confirmed and recorded in audit log", "success");
}
async function openRagChat() {
  navTo("admin");
  adminTab("rag");
}

/* Drag-and-drop workflow designer */
showWfDesigner = async function (id) {
  const wfs = (await apiFetch("/workflows")) || [];
  const w = wfs.find((x) => x.id === id);
  if (!w) return;
  const steps = w.steps || [];
  let graph = w.graph && w.graph.nodes ? w.graph : {
    nodes: steps.map((s, i) => ({ id: String(i), type: "userTask", name: s.name, x: 40 + (i % 4) * 160, y: 40 + Math.floor(i / 4) * 90, assignee_role: s.assignee_role, assignee_id: s.assignee_id })),
    edges: steps.slice(1).map((_, i) => ({ from: String(i), to: String(i + 1) })),
  };
  graph.nodes = (graph.nodes || []).map((n, i) => ({ x: 40 + (i % 4) * 160, y: 40 + Math.floor(i / 4) * 90, ...n }));
  const host = $(`wf-des-${id}`);
  host.innerHTML = `<div class="wf-canvas" id="wf-cv-${id}"></div>
    <div class="flex gap-2 mt-2 flex-wrap">
      <button class="tb" onclick="wfAddNode(${id},'userTask')">+ Task</button>
      <button class="tb" onclick="wfAddNode(${id},'exclusiveGateway')">+ XOR</button>
      <button class="tb" onclick="wfAddNode(${id},'parallelGateway')">+ AND</button>
      <button class="tb" onclick="wfAddNode(${id},'serviceTask')">+ Service</button>
      <button class="tb" onclick="wfEdgeMode(${id})">Connect edge</button>
      <button class="tb primary" onclick="saveWfCanvas(${id})">Save</button>
    </div>
    <p class="text-xs mt-1">Click a node to set assignee / XOR condition. Connect edge: click source then target.</p>
    <textarea id="wf-graph-${id}" class="hidden"></textarea>
    <input id="wf-steps-${id}" class="hidden" />`;
  window._wfGraph = window._wfGraph || {};
  window._wfGraph[id] = graph;
  paintWfCanvas(id);
};

function paintWfCanvas(id) {
  const graph = window._wfGraph[id];
  const cv = $(`wf-cv-${id}`);
  if (!cv || !graph) return;
  cv.innerHTML = (graph.edges || []).map((e, i) => {
    const a = graph.nodes.find((n) => String(n.id) === String(e.from || e.source));
    const b = graph.nodes.find((n) => String(n.id) === String(e.to || e.target));
    if (!a || !b) return "";
    const x1 = (a.x || 0) + 60, y1 = (a.y || 0) + 18, x2 = (b.x || 0) + 60, y2 = (b.y || 0) + 18;
    return `<svg class="wf-edge" style="left:0;top:0;width:100%;height:100%"><line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#0284c7" stroke-width="2" marker-end="url(#arr)" /></svg>`;
  }).join("") + (graph.nodes || []).map((n) =>
    `<div class="wf-node ${esc(n.type || "")}" data-nid="${esc(String(n.id))}" style="left:${n.x || 0}px;top:${n.y || 0}px"
      onmousedown="wfDragStart(event,${id},'${esc(String(n.id))}')" onclick="wfSelectNode(event,${id},'${esc(String(n.id))}')">${esc(n.name || n.type)}<small>${esc(n.type || "")} ${esc(n.assignee_role || n.condition || "")}</small></div>`
  ).join("");
}

function wfDragStart(ev, id, nid) {
  ev.preventDefault();
  const graph = window._wfGraph[id];
  const node = graph.nodes.find((n) => String(n.id) === String(nid));
  const ox = ev.clientX - (node.x || 0), oy = ev.clientY - (node.y || 0);
  function move(e) { node.x = e.clientX - ox; node.y = e.clientY - oy; paintWfCanvas(id); }
  function up() { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); }
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", up);
}

function wfAddNode(id, type) {
  const graph = window._wfGraph[id];
  const nid = "n" + Date.now();
  graph.nodes.push({ id: nid, type, name: type, x: 80, y: 80, assignee_role: type === "userTask" ? "admin" : null });
  paintWfCanvas(id);
}

function wfEdgeMode(id) {
  window._wfEdge = { id, from: null };
  toast("Click source node, then target node");
}

function wfSelectNode(ev, id, nid) {
  ev.stopPropagation();
  if (window._wfEdge && window._wfEdge.id === id) {
    if (!window._wfEdge.from) { window._wfEdge.from = nid; return; }
    const graph = window._wfGraph[id];
    graph.edges = graph.edges || [];
    graph.edges.push({ from: String(window._wfEdge.from), to: String(nid), condition: "" });
    window._wfEdge = null;
    paintWfCanvas(id);
    return;
  }
  const graph = window._wfGraph[id];
  const node = graph.nodes.find((n) => String(n.id) === String(nid));
  if (!node) return;
  const name = prompt("Name", node.name || node.type);
  if (name == null) return;
  node.name = name;
  if ((node.type || "") === "userTask") {
    node.assignee_role = prompt("Assignee role (admin/manager/user)", node.assignee_role || "admin") || node.assignee_role;
    const aid = prompt("Assignee user id (optional)", node.assignee_id || "");
    node.assignee_id = aid ? parseInt(aid, 10) : null;
  }
  if ((node.type || "").toLowerCase().includes("exclusive")) {
    const edge = (graph.edges || []).find((e) => String(e.from) === String(nid));
    if (edge) edge.condition = prompt("XOR condition e.g. decision==approved", edge.condition || "") || edge.condition;
  }
  paintWfCanvas(id);
}

async function saveWfCanvas(id) {
  const graph = window._wfGraph[id];
  const steps = (graph.nodes || []).filter((n) => n.type === "userTask").map((n) => ({
    name: n.name, assignee_role: n.assignee_role || "admin", assignee_id: n.assignee_id || null, due_days: n.due_days || 3,
  }));
  await apiFetch(`/workflows/${id}/graph`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ graph, steps }) });
  toast("Workflow graph saved successfully", "success");
}
