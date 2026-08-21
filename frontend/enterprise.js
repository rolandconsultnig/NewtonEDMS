/* NewtonEDMS enterprise UI: workflow canvas, rules, compliance, RAG, connectors, ProcessMaker studio. */
const ENT_TABS = new Set([
  "rules", "forms", "zones", "holds", "cases", "bpmn", "rag", "connectors",
  "cluster", "compliance", "security-policy", "report-builder", "office", "workflows", "legal",
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
  if (tab === "workflow" && currentDocId) {
    markInspTab(tab);
    await renderWorkflowTimelineTab($("insp-body"));
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
  } else if (tab === "workflows") {
    const [wfs, queue] = await Promise.all([
      apiFetch("/workflows"),
      apiFetch("/workflows/queue").catch(() => []),
    ]);
    content.innerHTML = `
      <div style="padding:4px">
        <div class="flex items-center justify-between mb-3">
          <div>
            <h3 class="font-bold text-base"><i class="fa-solid fa-diagram-project text-blue-600"></i> ProcessMaker Workflow Studio</h3>
            <p class="text-xs text-slate-500">Sequential & Parallel Routing, BPMN Gateways, Dynamic Metadata Forms, SLA Auto-Escalation, and Immutable Audit Trails.</p>
          </div>
          <button class="tb primary text-xs" onclick="openCreateWfDrawer()"><i class="fa-solid fa-plus"></i> New Process</button>
        </div>

        ${queue && queue.length ? `
          <div class="border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-slate-900 rounded-lg p-3 mb-4">
            <h4 class="font-bold text-xs text-amber-800 dark:text-amber-400 mb-2"><i class="fa-solid fa-clock-rotate-left"></i> My Pending Approval Queue (${queue.length})</h4>
            <div class="space-y-2">
              ${queue.map((t) => `
                <div class="flex items-center justify-between bg-white dark:bg-slate-800 p-2 rounded border border-slate-200 dark:border-slate-700 text-xs">
                  <div>
                    <span class="font-bold text-blue-600">${esc(t.step_name)}</span> on Document <a href="#" onclick="openDoc(${t.document_id});return false;" class="underline font-mono">#${t.document_id}</a>
                    <span class="ml-2 text-slate-500">SLA: ${t.sla_hours || 24}h ${t.escalated ? '<span class="text-red-500 font-bold">[ESCALATED]</span>' : ''}</span>
                  </div>
                  <button class="tb primary text-xs" onclick="openWorkflowSignOffModal(${t.id},'${esc(t.step_name)}',${esc(JSON.stringify(t.form_schema || []))})"><i class="fa-solid fa-signature"></i> Review & Sign</button>
                </div>
              `).join("")}
            </div>
          </div>
        ` : ''}

        <div id="wf-create-drawer" class="border rounded-lg p-4 bg-slate-50 dark:bg-slate-800 mb-4 hidden">
          <h4 class="font-bold text-sm mb-2">Create Business Process</h4>
          <div class="grid grid-cols-2 gap-3 mb-3">
            <div>
              <label class="block text-xs font-semibold mb-1">Process Name</label>
              <input id="pm-wf-name" placeholder="e.g. Purchase Order Approval" class="w-full border p-1.5 rounded text-xs bg-white dark:bg-slate-900" />
            </div>
            <div>
              <label class="block text-xs font-semibold mb-1">Routing Mode</label>
              <select id="pm-wf-routing" class="w-full border p-1.5 rounded text-xs bg-white dark:bg-slate-900">
                <option value="sequential">Sequential (One after another)</option>
                <option value="parallel_all">Parallel (All reviewers must approve)</option>
                <option value="parallel_any">Parallel (First to approve wins)</option>
              </select>
            </div>
          </div>
          <div class="grid grid-cols-3 gap-3 mb-3">
            <div>
              <label class="block text-xs font-semibold mb-1">Auto-Approval Rule (Optional)</label>
              <input id="pm-wf-auto" placeholder="e.g. amount < 1000" class="w-full border p-1.5 rounded text-xs bg-white dark:bg-slate-900" />
            </div>
            <div>
              <label class="block text-xs font-semibold mb-1">SLA Deadline (Hours)</label>
              <input id="pm-wf-sla" type="number" value="24" class="w-full border p-1.5 rounded text-xs bg-white dark:bg-slate-900" />
            </div>
            <div>
              <label class="block text-xs font-semibold mb-1">Auto-Escalation Role</label>
              <select id="pm-wf-esc" class="w-full border p-1.5 rounded text-xs bg-white dark:bg-slate-900">
                <option value="manager">Manager</option>
                <option value="finance">Finance Director</option>
                <option value="compliance">Compliance Officer</option>
                <option value="legal">Legal Counsel</option>
                <option value="executive">Executive</option>
                <option value="admin">Administrator</option>
              </select>
            </div>
          </div>
          <div class="mb-3">
            <label class="block text-xs font-semibold mb-1">Approval Steps (JSON or Drag Designer)</label>
            <textarea id="pm-wf-steps" rows="3" class="w-full border p-1.5 rounded text-xs font-mono bg-white dark:bg-slate-900" placeholder='[{"name":"Manager Review","assignee_role":"manager","form_schema":[{"name":"po_tax_id","label":"Tax ID"}]}]'>[{"name":"Manager Review","assignee_role":"manager","due_days":2},{"name":"Executive Approval","assignee_role":"executive","due_days":3}]</textarea>
          </div>
          <div class="flex gap-2 justify-end">
            <button class="tb text-xs" onclick="closeCreateWfDrawer()">Cancel</button>
            <button class="tb primary text-xs" onclick="saveProcessMakerWorkflow()"><i class="fa-solid fa-save"></i> Save Process</button>
          </div>
        </div>

        <div class="space-y-3">
          ${(wfs || []).map((w) => `
            <div class="border rounded-lg p-3 bg-white dark:bg-slate-800 shadow-sm">
              <div class="flex items-center justify-between mb-2">
                <div>
                  <strong class="text-sm font-semibold text-slate-800 dark:text-slate-100">${esc(w.name)}</strong>
                  <span class="ml-2 px-2 py-0.5 text-xs rounded-full bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 font-mono">${esc(w.routing_type || "sequential")}</span>
                  ${w.auto_approval_rule ? `<span class="ml-1 px-2 py-0.5 text-xs rounded-full bg-emerald-100 dark:bg-emerald-900 text-emerald-800 dark:text-emerald-200">Auto: ${esc(w.auto_approval_rule)}</span>` : ''}
                </div>
                <div class="flex gap-2">
                  <button class="tb text-xs" onclick="showWfDesigner(${w.id})"><i class="fa-solid fa-pen-ruler"></i> BPMN Studio</button>
                  <button class="tb text-xs text-red-600" onclick="delWorkflowTpl(${w.id})"><i class="fa-solid fa-trash"></i></button>
                </div>
              </div>
              <p class="text-xs text-slate-500 mb-2">${esc(w.description || "No description")} · SLA: ${w.sla_hours || 24}h · Escalates to: ${esc(w.escalate_to_role || "manager")}</p>
              <div class="flex gap-2 text-xs flex-wrap">
                ${(w.steps || []).map((s, i) => `
                  <span class="border rounded px-2 py-1 bg-slate-50 dark:bg-slate-900">
                    <strong>${i + 1}. ${esc(s.name || s)}</strong> (${esc(s.assignee_role || "User " + (s.assignee_id || ""))})
                  </span>
                `).join("<span class='text-slate-400 self-center'>→</span>")}
              </div>
              <div id="wf-des-${w.id}" class="mt-3"></div>
            </div>
          `).join("") || '<div class="text-xs text-slate-400 p-4 text-center">No workflow processes defined yet. Click "New Process" to create one.</div>'}
        </div>
      </div>
    `;
  } else if (tab === "legal") {
    await renderLegalTab(content);
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

function openCreateWfDrawer() {
  const el = $("wf-create-drawer");
  if (el) el.classList.remove("hidden");
}

function closeCreateWfDrawer() {
  const el = $("wf-create-drawer");
  if (el) el.classList.add("hidden");
}

async function saveProcessMakerWorkflow() {
  const name = val("pm-wf-name").trim();
  if (!name) {
    toast("Process name is required", "error");
    return;
  }
  const routing_type = val("pm-wf-routing") || "sequential";
  const auto_approval_rule = val("pm-wf-auto").trim() || null;
  const sla_hours = parseInt(val("pm-wf-sla"), 10) || 24;
  const escalate_to_role = val("pm-wf-esc") || "manager";
  let steps = [];
  try {
    steps = JSON.parse(val("pm-wf-steps") || "[]");
  } catch (e) {
    toast("Invalid JSON for workflow steps", "error");
    return;
  }

  try {
    await apiFetch("/workflows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        routing_type,
        auto_approval_rule,
        sla_hours,
        escalate_to_role,
        steps,
      }),
    });
    toast("ProcessMaker Workflow created successfully!", "success");
    closeCreateWfDrawer();
    adminTab("workflows");
  } catch (e) {
    toast(`Failed to create process: ${e.message}`, "error");
  }
}

window.openWorkflowSignOffModal = function (taskId, stepName, formSchema) {
  let schema = formSchema;
  if (typeof schema === "string") {
    try { schema = JSON.parse(schema); } catch (e) { schema = []; }
  }
  schema = schema || [];

  let modal = $("wf-signoff-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "wf-signoff-modal";
    modal.className = "modal";
    document.body.appendChild(modal);
  }

  modal.innerHTML = `
    <div style="max-width:540px;background:var(--bg-panel, #fff);padding:20px;border-radius:8px;box-shadow:0 10px 25px rgba(0,0,0,0.3)">
      <h3 class="font-bold text-base mb-1"><i class="fa-solid fa-signature text-blue-600"></i> Review &amp; Sign: ${esc(stepName)}</h3>
      <p class="text-xs text-slate-500 mb-3">Please fill required approval metadata and sign off on this document.</p>

      <form id="wf-signoff-form" onsubmit="return false;">
        ${schema.map((f) => `
          <div class="mb-2">
            <label class="block text-xs font-semibold mb-1">${esc(f.label || f.name)} ${f.required ? '<span class="text-red-500">*</span>' : ''}</label>
            <input name="${esc(f.name)}" type="${f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text'}"
              placeholder="${esc(f.placeholder || '')}" class="w-full border p-1.5 rounded text-xs" ${f.required ? 'required' : ''} />
          </div>
        `).join("")}

        <div class="mb-2">
          <label class="block text-xs font-semibold mb-1">Review Comments</label>
          <textarea id="wf-sign-comment" rows="2" class="w-full border p-1.5 rounded text-xs" placeholder="Add decision remarks…"></textarea>
        </div>

        <div class="mb-3">
          <label class="block text-xs font-semibold mb-1">Digital Signature / Token</label>
          <input id="wf-sign-token" class="w-full border p-1.5 rounded text-xs font-mono" placeholder="Type your full name or crypt-token e.g. SIG-DOE-2026" />
        </div>

        <div class="flex items-center justify-between pt-2 border-t mt-3">
          <button type="button" class="tb text-xs text-slate-600" onclick="closeModal('wf-signoff-modal')">Cancel</button>
          <div class="flex gap-2">
            <button type="button" class="tb text-xs text-red-600 border-red-300 hover:bg-red-50" onclick="submitWorkflowSignOff(${taskId}, 'reject')"><i class="fa-solid fa-xmark"></i> Reject</button>
            <button type="button" class="tb primary text-xs" onclick="submitWorkflowSignOff(${taskId}, 'approve')"><i class="fa-solid fa-check"></i> Approve &amp; Advance</button>
          </div>
        </div>
      </form>
    </div>
  `;

  openModal("wf-signoff-modal");
};

window.submitWorkflowSignOff = async function (taskId, action) {
  const form = $("wf-signoff-form");
  const formData = {};
  if (form) {
    const inputs = form.querySelectorAll("input[name]");
    for (const inp of inputs) {
      if (inp.required && !inp.value.trim() && action === "approve") {
        toast(`Field "${inp.name}" is required`, "error");
        inp.focus();
        return;
      }
      if (inp.value) formData[inp.name] = inp.value;
    }
  }

  const comment = val("wf-sign-comment");
  const signature = val("wf-sign-token");

  try {
    await apiFetch(`/tasks/${taskId}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        approved: action === "approve",
        comment,
        form_data: formData,
        signature: signature || undefined,
      }),
    });

    closeModal("wf-signoff-modal");
    toast(`Task ${action === "approve" ? "Approved" : "Rejected"} successfully!`, "success");
    if (typeof refreshCurrentList === "function") refreshCurrentList();
    if (currentDocId && typeof openDoc === "function") openDoc(currentDocId);
    adminTab("workflows");
  } catch (e) {
    toast(`Action failed: ${e.message}`, "error");
  }
};

async function renderWorkflowTimelineTab(container) {
  if (!currentDocId) return;
  container.innerHTML = `<div class="p-3 text-xs text-slate-400"><i class="fa-solid fa-spinner fa-spin"></i> Loading workflow timeline…</div>`;
  try {
    const instances = await apiFetch("/workflow-instances");
    const inst = (instances || []).find((i) => i.document_id === currentDocId);
    if (!inst) {
      container.innerHTML = `
        <div class="p-4 text-center text-xs text-slate-500">
          <i class="fa-solid fa-diagram-project text-2xl text-slate-300 mb-2 block"></i>
          No workflow active on this document.<br>
          <button class="tb primary text-xs mt-3" onclick="openStartWfModal()"><i class="fa-solid fa-play"></i> Start Approval Workflow</button>
        </div>
      `;
      return;
    }

    const logs = await apiFetch(`/workflows/instances/${inst.id}/timeline`).catch(() => []);
    container.innerHTML = `
      <div class="p-3 text-xs">
        <div class="flex items-center justify-between mb-3">
          <div>
            <strong class="text-sm font-semibold">Approval Lifecycle</strong>
            <span class="ml-2 px-2 py-0.5 rounded-full text-xs font-mono ${inst.status === 'completed' ? 'bg-emerald-100 text-emerald-800' : inst.status === 'rejected' ? 'bg-red-100 text-red-800' : 'bg-blue-100 text-blue-800'}">${esc(inst.status.toUpperCase())}</span>
          </div>
          <span class="text-slate-400">Instance #${inst.id}</span>
        </div>

        <div class="relative pl-6 space-y-4 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200 dark:before:bg-slate-700">
          ${logs.map((l) => `
            <div class="relative">
              <div class="absolute -left-6 top-0.5 w-3.5 h-3.5 rounded-full ${l.action === 'APPROVE' || l.action === 'AUTO_APPROVE' ? 'bg-emerald-500' : l.action === 'REJECT' ? 'bg-red-500' : l.action === 'ESCALATE' ? 'bg-amber-500' : 'bg-blue-500'} border-2 border-white dark:border-slate-800"></div>
              <div class="bg-slate-50 dark:bg-slate-800 p-2.5 rounded border border-slate-200 dark:border-slate-700">
                <div class="flex items-center justify-between mb-1">
                  <span class="font-bold text-slate-800 dark:text-slate-200">${esc(l.action)} ${l.to_state ? '→ ' + esc(l.to_state) : ''}</span>
                  <span class="text-slate-400 text-2xs">${esc(l.created_at || '')}</span>
                </div>
                <div class="text-slate-600 dark:text-slate-300 mb-1">By <strong>${esc(l.actor_name || "User")}</strong>: ${esc(l.comment || "No comment")}</div>
                ${l.signature ? `<div class="text-2xs font-mono text-emerald-600"><i class="fa-solid fa-lock"></i> Digital Signature: ${esc(l.signature)}</div>` : ''}
                ${l.form_data && Object.keys(l.form_data).length ? `
                  <div class="mt-1.5 pt-1.5 border-t border-slate-200 dark:border-slate-700 text-2xs text-slate-500">
                    <strong>Captured Metadata:</strong> ${Object.entries(l.form_data).map(([k, v]) => `${esc(k)}: <em>${esc(String(v))}</em>`).join(" · ")}
                  </div>
                ` : ''}
              </div>
            </div>
          `).join("") || '<div class="text-slate-400">No events logged yet.</div>'}
        </div>
      </div>
    `;
  } catch (e) {
    container.innerHTML = `<div class="p-3 text-xs text-red-500">Failed to load timeline: ${e.message}</div>`;
  }
}

/* =============================================================================
   LEGAL PRACTICE MANAGEMENT SUITE UI (Law Firms & Corporate Legal Departments)
   ============================================================================= */

let currentLegalMatterId = null;
let currentLegalSubTab = "documents";

async function renderLegalTab(content) {
  content.innerHTML = `<div class="p-4 text-xs text-slate-400"><i class="fa-solid fa-spinner fa-spin"></i> Loading Legal Matter Portfolio…</div>`;
  try {
    const matters = await apiFetch("/legal/matters").catch(() => []);
    const templates = await apiFetch("/legal/templates").catch(() => []);

    if (currentLegalMatterId) {
      const activeMatter = matters.find((m) => m.id === currentLegalMatterId);
      if (activeMatter) {
        await renderLegalMatterWorkspace(content, activeMatter);
        return;
      }
      currentLegalMatterId = null;
    }

    content.innerHTML = `
      <div style="padding:4px">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            <h3 class="font-bold text-base mb-0.5"><i class="fa-solid fa-scale-balanced text-amber-600"></i> Legal Matter Center & Practice Management</h3>
            <p class="text-xs text-slate-500">Matter-centric case files, ethical walls, automated document assembly, Bates stamping, email filing, and court e-Filing.</p>
          </div>
          <div class="flex gap-2 flex-wrap">
            <button class="tb text-xs" onclick="openLegalAssemblyModal()"><i class="fa-solid fa-wand-magic-sparkles text-amber-500"></i> Document Assembly</button>
            <button class="tb text-xs" onclick="openLegalBatesModal()"><i class="fa-solid fa-stamp text-indigo-500"></i> Bates Stamping</button>
            <button class="tb text-xs" onclick="openLegalCompareModal()"><i class="fa-solid fa-code-compare text-emerald-500"></i> Compare & Redline</button>
            <button class="tb primary text-xs" onclick="openNewMatterModal()"><i class="fa-solid fa-plus"></i> New Matter</button>
          </div>
        </div>

        <!-- Practice Area & Filter Bar -->
        <div class="flex items-center gap-2 mb-4 bg-slate-50 dark:bg-slate-800 p-2.5 rounded-lg border border-slate-200 dark:border-slate-700">
          <i class="fa-solid fa-filter text-slate-400"></i>
          <span class="text-xs font-semibold text-slate-600 dark:text-slate-300">Practice Area:</span>
          <select id="legal-filter-area" class="border rounded p-1 text-xs bg-white dark:bg-slate-900" onchange="filterLegalMatters()">
            <option value="">All Practice Areas</option>
            <option value="Litigation">Litigation & Dispute Resolution</option>
            <option value="Corporate">Corporate / M&A</option>
            <option value="Intellectual Property">Intellectual Property & Patents</option>
            <option value="Labor & Employment">Labor & Employment</option>
            <option value="Real Estate">Real Estate & Construction</option>
            <option value="Regulatory">Regulatory & Compliance</option>
          </select>

          <span class="text-xs font-semibold text-slate-600 dark:text-slate-300 ml-2">Status:</span>
          <select id="legal-filter-status" class="border rounded p-1 text-xs bg-white dark:bg-slate-900" onchange="filterLegalMatters()">
            <option value="">All Statuses</option>
            <option value="open">Active / Open</option>
            <option value="discovery">Discovery Phase</option>
            <option value="trial">Trial / Hearing</option>
            <option value="closed">Closed / Archived</option>
          </select>

          <input id="legal-search-q" placeholder="Search case name, matter #, client…" class="border rounded p-1 text-xs bg-white dark:bg-slate-900 flex-1 ml-2" oninput="filterLegalMatters()" />
        </div>

        <!-- Matter Portfolio Grid -->
        <div id="legal-matters-grid" class="space-y-3">
          ${matters.map((m) => renderMatterCard(m)).join("") || `
            <div class="border rounded-lg p-8 text-center bg-slate-50 dark:bg-slate-800/50">
              <i class="fa-solid fa-briefcase text-3xl text-slate-300 mb-3 block"></i>
              <strong class="text-sm font-semibold">No Legal Matters Registered</strong>
              <p class="text-xs text-slate-500 mt-1 mb-3">Create your first matter to organize pleadings, discovery, and ethical walls.</p>
              <button class="tb primary text-xs" onclick="openNewMatterModal()"><i class="fa-solid fa-plus"></i> Create Matter</button>
            </div>
          `}
        </div>
      </div>
    `;
  } catch (e) {
    content.innerHTML = `<div class="p-4 text-xs text-red-500">Failed to load legal suite: ${e.message}</div>`;
  }
}

function renderMatterCard(m) {
  const statusColors = {
    open: "bg-emerald-100 text-emerald-800 border-emerald-300",
    discovery: "bg-blue-100 text-blue-800 border-blue-300",
    trial: "bg-amber-100 text-amber-800 border-amber-300",
    closed: "bg-slate-100 text-slate-600 border-slate-300",
  };
  const colorCls = statusColors[m.status] || "bg-slate-100 text-slate-700 border-slate-300";

  return `
    <div class="border rounded-lg p-4 bg-white dark:bg-slate-800 hover:border-amber-500 transition-all shadow-sm matter-card" data-area="${esc(m.practice_area || '')}" data-status="${esc(m.status || '')}" data-search="${esc((m.matter_number + ' ' + m.title + ' ' + m.client_name).toLowerCase())}">
      <div class="flex items-start justify-between mb-2">
        <div>
          <div class="flex items-center gap-2 mb-1">
            <span class="font-mono font-bold text-xs bg-slate-100 dark:bg-slate-700 px-2 py-0.5 rounded text-slate-700 dark:text-slate-300">${esc(m.matter_number)}</span>
            <span class="text-2xs font-semibold px-2 py-0.5 rounded-full border ${colorCls}">${esc(m.status.toUpperCase())}</span>
            ${m.practice_area ? `<span class="text-2xs bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800 px-2 py-0.5 rounded">${esc(m.practice_area)}</span>` : ''}
          </div>
          <h4 class="font-bold text-sm text-slate-800 dark:text-slate-100">${esc(m.title)}</h4>
          <p class="text-xs text-slate-500">Client: <strong>${esc(m.client_name)}</strong> ${m.lead_attorney ? `· Lead: <em>${esc(m.lead_attorney)}</em>` : ''} ${m.court_name ? `· Court: ${esc(m.court_name)}` : ''}</p>
        </div>
        <div class="flex gap-2">
          <button class="tb primary text-xs" onclick="selectLegalMatter(${m.id})"><i class="fa-solid fa-folder-open"></i> Open Case Workspace</button>
        </div>
      </div>
      ${m.case_caption ? `
        <div class="bg-slate-50 dark:bg-slate-900/60 p-2 rounded text-2xs font-serif text-slate-600 dark:text-slate-300 border-l-2 border-amber-500 mt-2">
          <strong>Caption:</strong> ${esc(m.case_caption)} ${m.judge_name ? `(Presiding: ${esc(m.judge_name)})` : ''}
        </div>
      ` : ''}
    </div>
  `;
}

function filterLegalMatters() {
  const area = (val("legal-filter-area") || "").toLowerCase();
  const status = (val("legal-filter-status") || "").toLowerCase();
  const q = (val("legal-search-q") || "").toLowerCase();

  document.querySelectorAll(".matter-card").forEach((card) => {
    const cardArea = (card.dataset.area || "").toLowerCase();
    const cardStatus = (card.dataset.status || "").toLowerCase();
    const cardSearch = (card.dataset.search || "").toLowerCase();

    const matchArea = !area || cardArea.includes(area);
    const matchStatus = !status || cardStatus === status;
    const matchSearch = !q || cardSearch.includes(q);

    card.classList.toggle("hidden", !(matchArea && matchStatus && matchSearch));
  });
}

async function selectLegalMatter(matterId) {
  currentLegalMatterId = matterId;
  await adminTab("legal");
}

function exitLegalMatter() {
  currentLegalMatterId = null;
  adminTab("legal");
}

async function renderLegalMatterWorkspace(container, matter) {
  container.innerHTML = `
    <div style="padding:4px">
      <!-- Breadcrumb & Header -->
      <div class="flex items-center justify-between mb-3 border-b pb-3 flex-wrap gap-2">
        <div>
          <button class="text-xs text-blue-600 hover:underline mb-1 flex items-center gap-1" onclick="exitLegalMatter()">
            <i class="fa-solid fa-arrow-left"></i> Back to Matter Portfolio
          </button>
          <div class="flex items-center gap-2">
            <h3 class="font-bold text-base">${esc(matter.title)}</h3>
            <span class="font-mono text-xs bg-slate-100 dark:bg-slate-700 px-2 py-0.5 rounded font-bold">${esc(matter.matter_number)}</span>
            <span class="text-2xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full font-semibold">${esc(matter.practice_area || 'General')}</span>
          </div>
          <p class="text-xs text-slate-500">Client: <strong>${esc(matter.client_name)}</strong> · ${matter.court_name ? `Court: ${esc(matter.court_name)} · ` : ''}Billing Code: <code>${esc(matter.billing_code || 'N/A')}</code></p>
        </div>
        <div class="flex gap-2 flex-wrap">
          <button class="tb text-xs" onclick="openLegalEmailIngestModal(${matter.id})"><i class="fa-solid fa-envelope-open-text text-blue-500"></i> File Email (.eml)</button>
          <button class="tb text-xs" onclick="openLegalAssemblyModal(${matter.id})"><i class="fa-solid fa-wand-magic-sparkles text-amber-500"></i> Assemble Document</button>
          <button class="tb text-xs" onclick="openLegalBatesModal(${matter.id})"><i class="fa-solid fa-stamp text-indigo-500"></i> Bates Production</button>
          <button class="tb text-xs" onclick="openLegalEFilingModal(${matter.id})"><i class="fa-solid fa-file-shield text-emerald-600"></i> Court e-Filing Bundle</button>
          <button class="tb text-xs" onclick="openLegalExtranetModal(${matter.id})"><i class="fa-solid fa-share-nodes text-purple-600"></i> Client Portal Share</button>
        </div>
      </div>

      <!-- Navigation Sub-Tabs -->
      <div class="flex border-b mb-4 text-xs gap-4 font-semibold">
        <button class="pb-2 border-b-2 ${currentLegalSubTab === 'documents' ? 'border-amber-500 text-amber-600' : 'border-transparent text-slate-500'}" onclick="setLegalSubTab('documents')"><i class="fa-solid fa-folder"></i> Case Documents & Pleadings</button>
        <button class="pb-2 border-b-2 ${currentLegalSubTab === 'walls' ? 'border-amber-500 text-amber-600' : 'border-transparent text-slate-500'}" onclick="setLegalSubTab('walls')"><i class="fa-solid fa-shield-halved text-rose-500"></i> Ethical Walls & Conflicts</button>
        <button class="pb-2 border-b-2 ${currentLegalSubTab === 'productions' ? 'border-amber-500 text-amber-600' : 'border-transparent text-slate-500'}" onclick="setLegalSubTab('productions')"><i class="fa-solid fa-stamp text-indigo-500"></i> Bates Discovery Sets</button>
        <button class="pb-2 border-b-2 ${currentLegalSubTab === 'portals' ? 'border-amber-500 text-amber-600' : 'border-transparent text-slate-500'}" onclick="setLegalSubTab('portals')"><i class="fa-solid fa-globe text-purple-500"></i> Extranet Client Portals</button>
      </div>

      <div id="legal-subtab-container"></div>
    </div>
  `;

  await loadLegalSubTabContent(matter);
}

async function setLegalSubTab(subTab) {
  currentLegalSubTab = subTab;
  await adminTab("legal");
}

async function loadLegalSubTabContent(matter) {
  const container = $("legal-subtab-container");
  if (!container) return;

  if (currentLegalSubTab === "documents") {
    const docs = await apiFetch(`/legal/matters/${matter.id}/documents`).catch(() => []);
    container.innerHTML = `
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex gap-2">
            <span class="text-xs font-semibold text-slate-500 self-center">Category:</span>
            <button class="px-2 py-1 text-2xs rounded bg-amber-500 text-white font-medium">All (${docs.length})</button>
          </div>
          <span class="text-xs text-slate-400">Strict Ethical Isolation & Legal Privilege Active</span>
        </div>

        <div class="border rounded-lg overflow-hidden">
          <table class="w-full text-xs text-left border-collapse">
            <thead class="bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold">
              <tr>
                <th class="p-2.5">Title / Filename</th>
                <th class="p-2.5">Category</th>
                <th class="p-2.5">Confidentiality</th>
                <th class="p-2.5">Bates Number</th>
                <th class="p-2.5">Added Date</th>
                <th class="p-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-700">
              ${docs.map((d) => `
                <tr class="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td class="p-2.5">
                    <div class="font-bold text-slate-800 dark:text-slate-200">${esc(d.title || d.name)}</div>
                    <div class="text-2xs text-slate-400 font-mono">${esc(d.name)}</div>
                  </td>
                  <td class="p-2.5">
                    <span class="px-2 py-0.5 rounded text-2xs font-semibold uppercase bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300">${esc(d.category || 'general')}</span>
                  </td>
                  <td class="p-2.5">
                    <span class="px-2 py-0.5 rounded text-2xs font-semibold ${d.confidentiality === 'attorneys_eyes_only' ? 'bg-red-100 text-red-800' : d.confidentiality === 'confidential' ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-800'}">${esc((d.confidentiality || 'confidential').replace('_', ' ').toUpperCase())}</span>
                  </td>
                  <td class="p-2.5 font-mono text-2xs font-semibold text-indigo-600 dark:text-indigo-400">
                    ${esc(d.bates_range || '—')}
                  </td>
                  <td class="p-2.5 text-slate-400 text-2xs">
                    ${esc(d.added_at ? d.added_at.slice(0, 10) : '')}
                  </td>
                  <td class="p-2.5 text-right space-x-1">
                    <button class="tb text-2xs" onclick="openLegalRedactModal(${d.document_id})"><i class="fa-solid fa-eraser text-rose-500"></i> Redact PII</button>
                    <button class="tb text-2xs" onclick="openLegalCompareModal(${d.document_id})"><i class="fa-solid fa-code-compare text-blue-500"></i> Diff</button>
                  </td>
                </tr>
              `).join("") || `
                <tr>
                  <td colspan="6" class="p-6 text-center text-slate-400">
                    No documents attached to this matter yet.<br>
                    <button class="tb primary text-xs mt-2" onclick="openLegalEmailIngestModal(${matter.id})"><i class="fa-solid fa-plus"></i> File Email or Upload Instrument</button>
                  </td>
                </tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } else if (currentLegalSubTab === "walls") {
    const walls = await apiFetch(`/legal/matters/${matter.id}/walls`).catch(() => []);
    container.innerHTML = `
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h4 class="font-bold text-sm"><i class="fa-solid fa-shield-halved text-rose-500"></i> Conflict of Interest & Ethical Walls</h4>
            <p class="text-xs text-slate-500">Enforce strict data isolation preventing conflicted attorneys or staff from discovering or viewing this matter.</p>
          </div>
          <button class="tb primary text-xs" onclick="openLegalWallModal(${matter.id})"><i class="fa-solid fa-plus"></i> Add Ethical Wall</button>
        </div>

        <div class="space-y-3">
          ${walls.map((w) => `
            <div class="border rounded-lg p-3 bg-rose-50 dark:bg-rose-950/20 border-rose-200 dark:border-rose-800">
              <div class="flex items-center justify-between mb-1">
                <strong class="text-xs text-rose-900 dark:text-rose-200">Barrier Reason: ${esc(w.barrier_reason)}</strong>
                <span class="text-2xs font-semibold px-2 py-0.5 rounded bg-rose-200 text-rose-800">${w.active ? 'ENFORCED' : 'INACTIVE'}</span>
              </div>
              <p class="text-xs text-slate-600 dark:text-slate-300">Walled Conflicted User IDs: <code class="font-mono bg-white dark:bg-slate-900 px-1 py-0.5 rounded border">${esc((w.walled_user_ids || []).join(", ") || "None")}</code></p>
              <div class="text-2xs text-slate-400 mt-1">Audit Policy: Any attempt by walled users to query, view, or search this matter returns 403 Forbidden.</div>
            </div>
          `).join("") || '<div class="p-6 text-center text-xs text-slate-400 border rounded-lg">No active ethical walls for this matter.</div>'}
        </div>
      </div>
    `;
  } else if (currentLegalSubTab === "productions") {
    const productions = await apiFetch(`/legal/matters/${matter.id}/bates-productions`).catch(() => []);
    container.innerHTML = `
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h4 class="font-bold text-sm"><i class="fa-solid fa-stamp text-indigo-500"></i> Bates Discovery Production Sets</h4>
            <p class="text-xs text-slate-500">Sequential pagination stamps applied across litigation discovery documents.</p>
          </div>
          <button class="tb primary text-xs" onclick="openLegalBatesModal(${matter.id})"><i class="fa-solid fa-plus"></i> New Bates Production</button>
        </div>

        <div class="border rounded-lg overflow-hidden">
          <table class="w-full text-xs text-left border-collapse">
            <thead class="bg-slate-50 dark:bg-slate-800 font-semibold">
              <tr>
                <th class="p-2.5">Production Set</th>
                <th class="p-2.5">Bates Range</th>
                <th class="p-2.5">Total Pages</th>
                <th class="p-2.5">Position & Disclaimer</th>
                <th class="p-2.5">Created Date</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-700">
              ${productions.map((p) => `
                <tr class="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td class="p-2.5 font-bold">${esc(p.production_name)}</td>
                  <td class="p-2.5 font-mono text-indigo-600 dark:text-indigo-400 font-semibold">${esc(p.bates_start)} → ${esc(p.bates_end)}</td>
                  <td class="p-2.5">${p.total_pages} pages</td>
                  <td class="p-2.5 text-slate-500">${esc(p.position)} ${p.disclaimer_text ? `(${esc(p.disclaimer_text)})` : ''}</td>
                  <td class="p-2.5 text-slate-400 text-2xs">${esc(p.created_at ? p.created_at.slice(0, 10) : '')}</td>
                </tr>
              `).join("") || '<tr><td colspan="5" class="p-6 text-center text-slate-400">No Bates production sets created yet.</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } else if (currentLegalSubTab === "portals") {
    container.innerHTML = `
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h4 class="font-bold text-sm"><i class="fa-solid fa-globe text-purple-500"></i> Secure Extranet Client Portals</h4>
            <p class="text-xs text-slate-500">Password-protected, watermarked matter access for clients and co-counsel.</p>
          </div>
          <button class="tb primary text-xs" onclick="openLegalExtranetModal(${matter.id})"><i class="fa-solid fa-plus"></i> Share via Extranet</button>
        </div>
        <div class="p-4 bg-slate-50 dark:bg-slate-800 rounded-lg border text-xs text-slate-500">
          Generate encrypted portal access links with expiration and dynamic watermarking (e.g. <code>CONFIDENTIAL - PREPARED FOR CLIENT</code>).
        </div>
      </div>
    `;
  }
}

/* =============================================================================
   LEGAL MODALS & POPUPS
   ============================================================================= */

function openNewMatterModal() {
  showModal(`
    <div class="p-4" style="max-width:550px">
      <h3 class="font-bold text-base mb-3"><i class="fa-solid fa-briefcase text-amber-600"></i> Register New Legal Matter</h3>
      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Matter Number *</label>
          <input id="nm-number" value="MAT-${new Date().getFullYear()}-${Math.floor(100 + Math.random()*900)}" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono" />
        </div>
        <div>
          <label class="block font-semibold mb-1">Matter Title *</label>
          <input id="nm-title" placeholder="e.g. Acme Corp v. Global Tech Patent Litigation" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Client Name *</label>
            <input id="nm-client" placeholder="e.g. Acme Corporation" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Practice Area</label>
            <select id="nm-area" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
              <option value="Litigation">Litigation & Disputes</option>
              <option value="Corporate">Corporate / M&A</option>
              <option value="Intellectual Property">Intellectual Property</option>
              <option value="Labor & Employment">Labor & Employment</option>
              <option value="Real Estate">Real Estate</option>
              <option value="Regulatory">Regulatory & Compliance</option>
            </select>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Lead Attorney</label>
            <input id="nm-attorney" placeholder="e.g. Jane Smith, Esq." class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Billing Code</label>
            <input id="nm-billing" placeholder="e.g. ACM-LIT-2026" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono" />
          </div>
        </div>
        <div>
          <label class="block font-semibold mb-1">Court Name & Case Caption</label>
          <input id="nm-court" placeholder="e.g. U.S. District Court, N.D. Cal." class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 mb-1" />
          <textarea id="nm-caption" rows="2" placeholder="e.g. Acme Corp., Plaintiff, v. Global Tech Ltd., Defendant" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-serif"></textarea>
        </div>
      </div>
      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs" onclick="saveNewMatter()">Create Matter</button>
      </div>
    </div>
  `);
}

async function saveNewMatter() {
  try {
    const payload = {
      matter_number: val("nm-number"),
      title: val("nm-title"),
      client_name: val("nm-client"),
      practice_area: val("nm-area"),
      lead_attorney: val("nm-attorney"),
      billing_code: val("nm-billing"),
      court_name: val("nm-court"),
      case_caption: val("nm-caption"),
    };
    if (!payload.matter_number || !payload.title || !payload.client_name) {
      toast("Matter number, title, and client name are required.", "error");
      return;
    }
    const res = await apiFetch("/legal/matters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    closeModal();
    toast(`Matter ${res.matter_number} created successfully!`, "success");
    currentLegalMatterId = res.id;
    adminTab("legal");
  } catch (e) {
    toast(`Failed to create matter: ${e.message}`, "error");
  }
}

async function openLegalEmailIngestModal(matterId) {
  showModal(`
    <div class="p-4" style="max-width:500px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-envelope-open-text text-blue-500"></i> File Outlook / Gmail Message (.eml)</h3>
      <p class="text-xs text-slate-500 mb-3">Upload standard RFC822 / .eml file. Preserves email headers, thread metadata, and extracts all attachments directly into the Matter file.</p>
      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Select .eml / .msg File *</label>
          <input type="file" id="eml-file" accept=".eml,.msg" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>
      </div>
      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs" onclick="submitLegalEmailFiling(${matterId})">Ingest & File to Matter</button>
      </div>
    </div>
  `);
}

async function submitLegalEmailFiling(matterId) {
  const fileInput = $("eml-file");
  if (!fileInput || !fileInput.files.length) {
    toast("Please select an .eml file to upload.", "error");
    return;
  }
  const file = fileInput.files[0];
  const formData = new FormData();
  formData.append("file", file);

  try {
    const token = localStorage.getItem("newton_access_token") || localStorage.getItem("token");
    const res = await fetch(`/api/legal/matters/${matterId}/emails/ingest`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    closeModal();
    toast(`Email "${data.subject}" and ${data.attachment_count} attachments filed to matter!`, "success");
    adminTab("legal");
  } catch (e) {
    toast(`Email filing failed: ${e.message}`, "error");
  }
}

async function openLegalAssemblyModal(matterId) {
  const templates = (await apiFetch("/legal/templates")) || [];
  const matters = (await apiFetch("/legal/matters")) || [];

  showModal(`
    <div class="p-4" style="max-width:600px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-wand-magic-sparkles text-amber-500"></i> Automated Document Assembly</h3>
      <p class="text-xs text-slate-500 mb-3">Generate legally binding instruments (NDAs, Briefs, Contracts) by auto-populating master templates with case metadata.</p>
      
      <div class="space-y-3 text-xs">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Master Legal Template *</label>
            <select id="asm-template" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" onchange="loadLegalTemplateFields()">
              <option value="">Select a template…</option>
              ${templates.map((t) => `<option value="${t.id}">${esc(t.name)} (${esc(t.category)})</option>`).join("")}
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1">Target Matter *</label>
            <select id="asm-matter" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
              ${matters.map((m) => `<option value="${m.id}" ${matterId && m.id === matterId ? 'selected' : ''}>${esc(m.matter_number)} - ${esc(m.title)}</option>`).join("")}
            </select>
          </div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Document Title *</label>
          <input id="asm-title" placeholder="e.g. Non-Disclosure Agreement - Acme Corp" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>

        <div id="asm-variables-box" class="border rounded p-3 bg-slate-50 dark:bg-slate-900 space-y-2 hidden">
          <strong class="block text-2xs uppercase text-slate-400">Template Variables & Placeholders</strong>
          <div id="asm-fields" class="space-y-2"></div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Output Format</label>
          <select id="asm-format" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
            <option value="pdf">Court-Ready PDF Document</option>
            <option value="markdown">Editable Markdown / Text</option>
          </select>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs" onclick="submitLegalAssembly()">Assemble Document</button>
      </div>
    </div>
  `);
}

async function loadLegalTemplateFields() {
  const tplId = parseInt(val("asm-template"), 10);
  const box = $("asm-variables-box");
  const fieldsContainer = $("asm-fields");
  if (!tplId) {
    box.classList.add("hidden");
    return;
  }
  const templates = (await apiFetch("/legal/templates")) || [];
  const tpl = templates.find((t) => t.id === tplId);
  if (!tpl || !tpl.placeholders || !tpl.placeholders.length) {
    box.classList.add("hidden");
    return;
  }

  fieldsContainer.innerHTML = tpl.placeholders.map((p) => `
    <div>
      <label class="block font-semibold text-2xs text-slate-600 dark:text-slate-300">{{${esc(p)}}}</label>
      <input class="w-full border p-1 rounded text-xs bg-white dark:bg-slate-800 asm-var-input" data-var="${esc(p)}" placeholder="Value for ${esc(p)}" />
    </div>
  `).join("");
  box.classList.remove("hidden");
}

async function submitLegalAssembly() {
  const tplId = parseInt(val("asm-template"), 10);
  const matterId = parseInt(val("asm-matter"), 10);
  const title = val("asm-title");
  const outputFormat = val("asm-format") || "pdf";

  if (!tplId || !matterId || !title) {
    toast("Template, Matter, and Document Title are required.", "error");
    return;
  }

  const varData = {};
  document.querySelectorAll(".asm-var-input").forEach((inp) => {
    varData[inp.dataset.var] = inp.value;
  });

  try {
    const res = await apiFetch("/legal/assembly", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_id: tplId,
        matter_id: matterId,
        document_title: title,
        output_format: outputFormat,
        variable_data: varData,
      }),
    });
    closeModal();
    toast(`Assembled legal document "${res.title}" created successfully!`, "success");
    adminTab("legal");
  } catch (e) {
    toast(`Assembly failed: ${e.message}`, "error");
  }
}

async function openLegalBatesModal(matterId) {
  const matters = (await apiFetch("/legal/matters")) || [];
  showModal(`
    <div class="p-4" style="max-width:550px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-stamp text-indigo-500"></i> Bates Stamping & Discovery Production</h3>
      <p class="text-xs text-slate-500 mb-3">Apply sequential pagination stamps across discovery documents with customized legal disclaimers.</p>
      
      <div class="space-y-3 text-xs">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Target Matter *</label>
            <select id="bts-matter" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
              ${matters.map((m) => `<option value="${m.id}" ${matterId && m.id === matterId ? 'selected' : ''}>${esc(m.matter_number)} - ${esc(m.title)}</option>`).join("")}
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1">Production Set Name *</label>
            <input id="bts-set" value="PROD-${new Date().toISOString().slice(0,10).replace(/-/g,'')}" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono" />
          </div>
        </div>

        <div class="grid grid-cols-3 gap-3">
          <div>
            <label class="block font-semibold mb-1">Bates Prefix *</label>
            <input id="bts-prefix" value="PLTF-" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono font-bold" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Starting Number</label>
            <input id="bts-start" type="number" value="1" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Zero Padding</label>
            <input id="bts-pad" type="number" value="6" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Position on Page</label>
            <select id="bts-pos" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
              <option value="bottom-right">Bottom Right (Standard)</option>
              <option value="bottom-left">Bottom Left</option>
              <option value="top-right">Top Right</option>
              <option value="top-left">Top Left</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1">Confidentiality Disclaimer</label>
            <input id="bts-disc" value="CONFIDENTIAL - SUBJECT TO PROTECTIVE ORDER" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono text-2xs" />
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs" onclick="submitLegalBatesStamping()">Run Bates Production</button>
      </div>
    </div>
  `);
}

async function submitLegalBatesStamping() {
  const matterId = parseInt(val("bts-matter"), 10);
  const docs = await apiFetch(`/legal/matters/${matterId}/documents`).catch(() => []);
  const docIds = docs.map((d) => d.document_id);

  if (!docIds.length) {
    toast("No documents found in selected matter to stamp.", "error");
    return;
  }

  try {
    const res = await apiFetch(`/legal/matters/${matterId}/bates-production`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        matter_id: matterId,
        production_name: val("bts-set"),
        document_ids: docIds,
        prefix: val("bts-prefix") || "PLTF-",
        start_number: parseInt(val("bts-start") || "1", 10),
        pad_length: parseInt(val("bts-pad") || "6", 10),
        position: val("bts-pos") || "bottom-right",
        disclaimer_text: val("bts-disc") || "",
      }),
    });
    closeModal();
    toast(`Bates stamped ${res.total_documents} documents (${res.bates_start} → ${res.bates_end})!`, "success");
    adminTab("legal");
  } catch (e) {
    toast(`Bates stamping failed: ${e.message}`, "error");
  }
}

async function openLegalRedactModal(docId) {
  showModal(`
    <div class="p-4" style="max-width:500px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-eraser text-rose-500"></i> Permanent Non-Reversible Redaction</h3>
      <p class="text-xs text-slate-500 mb-3">Burns opaque black boxes and permanently removes underlying character glyphs from the document layer.</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Built-in PII Patterns</label>
          <div class="space-y-1.5 border rounded p-2.5 bg-slate-50 dark:bg-slate-900">
            <label class="flex items-center gap-2"><input type="checkbox" id="rd-ssn" checked /> <span>Social Security Numbers (US SSN: <code>XXX-XX-XXXX</code>)</span></label>
            <label class="flex items-center gap-2"><input type="checkbox" id="rd-cc" checked /> <span>Credit Card Numbers (Visa, MasterCard, Amex)</span></label>
            <label class="flex items-center gap-2"><input type="checkbox" id="rd-email" /> <span>Email Addresses</span></label>
            <label class="flex items-center gap-2"><input type="checkbox" id="rd-phone" /> <span>Phone Numbers</span></label>
          </div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Custom Sensitive Words / Regex (comma separated)</label>
          <input id="rd-custom" placeholder="e.g. ConfidentialTradeSecret, AcmeCorpPassword" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>

        <div>
          <label class="flex items-center gap-2 font-semibold">
            <input type="checkbox" id="rd-save-new" checked />
            <span>Save as new redacted copy (Preserves untouched original)</span>
          </label>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs bg-rose-600 hover:bg-rose-700" onclick="submitLegalRedaction(${docId})">Apply Permanent Redaction</button>
      </div>
    </div>
  `);
}

async function submitLegalRedaction(docId) {
  const presets = [];
  if ($("rd-ssn")?.checked) presets.push("us_ssn");
  if ($("rd-cc")?.checked) presets.push("credit_card");
  if ($("rd-email")?.checked) presets.push("email");
  if ($("rd-phone")?.checked) presets.push("phone");

  const customWords = (val("rd-custom") || "").split(",").map((s) => s.trim()).filter(Boolean);
  const saveAsNew = $("rd-save-new")?.checked !== false;

  try {
    const res = await apiFetch(`/legal/documents/${docId}/redact-permanent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patterns: customWords,
        builtin_presets: presets,
        save_as_new: saveAsNew,
      }),
    });
    closeModal();
    toast(`Redaction applied! ${res.redactions_applied} sensitive items permanently removed.`, "success");
    adminTab("legal");
  } catch (e) {
    toast(`Redaction failed: ${e.message}`, "error");
  }
}

async function openLegalCompareModal(docIdA) {
  const docs = (await apiFetch("/documents")) || [];
  showModal(`
    <div class="p-4" style="max-width:700px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-code-compare text-emerald-500"></i> Legal Redline & Version Comparison</h3>
      <p class="text-xs text-slate-500 mb-3">Compare two document versions with inline redline markup (<ins class="bg-emerald-100 text-emerald-800 underline">additions</ins> and <del class="bg-red-100 text-red-800 line-through">deletions</del>).</p>

      <div class="grid grid-cols-2 gap-3 text-xs mb-3">
        <div>
          <label class="block font-semibold mb-1">Base Document (Original)</label>
          <select id="cmp-doc-a" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
            ${docs.map((d) => `<option value="${d.id}" ${docIdA && d.id === docIdA ? 'selected' : ''}>${esc(d.title || d.name)}</option>`).join("")}
          </select>
        </div>
        <div>
          <label class="block font-semibold mb-1">Revised Document</label>
          <select id="cmp-doc-b" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
            ${docs.map((d) => `<option value="${d.id}">${esc(d.title || d.name)}</option>`).join("")}
          </select>
        </div>
      </div>

      <div id="cmp-results" class="border rounded p-3 bg-slate-50 dark:bg-slate-900 max-h-72 overflow-y-auto hidden"></div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
        <button class="tb primary text-xs" onclick="submitLegalCompare()">Generate Legal Redline</button>
      </div>
    </div>
  `);
}

async function submitLegalCompare() {
  const docA = parseInt(val("cmp-doc-a"), 10);
  const docB = parseInt(val("cmp-doc-b"), 10);
  if (!docA || !docB) {
    toast("Select two documents to compare.", "error");
    return;
  }

  const resultsBox = $("cmp-results");
  resultsBox.innerHTML = `<div class="text-xs text-slate-400"><i class="fa-solid fa-spinner fa-spin"></i> Computing redline diff…</div>`;
  resultsBox.classList.remove("hidden");

  try {
    const res = await apiFetch("/legal/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id_a: docA, doc_id_b: docB }),
    });

    resultsBox.innerHTML = `
      <div class="text-xs space-y-2">
        <div class="flex items-center gap-4 bg-white dark:bg-slate-800 p-2 rounded border">
          <span><strong>Similarity:</strong> ${res.similarity_ratio}%</span>
          <span class="text-emerald-600"><strong>Insertions:</strong> +${res.insertions_count} words</span>
          <span class="text-red-600"><strong>Deletions:</strong> -${res.deletions_count} words</span>
        </div>
        <div class="bg-white dark:bg-slate-800 p-3 rounded border font-serif leading-relaxed text-slate-800 dark:text-slate-200">
          ${res.inline_html}
        </div>
      </div>
    `;
  } catch (e) {
    resultsBox.innerHTML = `<div class="text-xs text-red-500">Comparison failed: ${e.message}</div>`;
  }
}

async function openLegalEFilingModal(matterId) {
  const docs = await apiFetch(`/legal/matters/${matterId}/documents`).catch(() => []);
  showModal(`
    <div class="p-4" style="max-width:550px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-file-shield text-emerald-600"></i> Assemble Court e-Filing Bundle</h3>
      <p class="text-xs text-slate-500 mb-3">Generates standardized caption cover sheet, Table of Exhibits, and cryptographically signs with SHA-256 e-filing hash.</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Primary Pleading / Motion Document *</label>
          <select id="ef-pleading" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
            ${docs.map((d) => `<option value="${d.document_id}">${esc(d.title || d.name)}</option>`).join("")}
          </select>
        </div>

        <div>
          <label class="block font-semibold mb-1">Select Exhibits to Include</label>
          <div class="space-y-1 max-h-36 overflow-y-auto border rounded p-2 bg-slate-50 dark:bg-slate-900">
            ${docs.map((d) => `
              <label class="flex items-center gap-2">
                <input type="checkbox" class="ef-exhibit-cb" value="${d.document_id}" />
                <span>${esc(d.title || d.name)} <em class="text-slate-400 font-mono">(${esc(d.bates_range || 'No Bates')})</em></span>
              </label>
            `).join("") || '<div class="text-slate-400">No documents in matter.</div>'}
          </div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Package Title</label>
          <input id="ef-title" placeholder="e.g. Motion to Dismiss with Exhibits A-C" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs bg-emerald-600 hover:bg-emerald-700" onclick="submitLegalEFiling(${matterId})">Generate Court Package</button>
      </div>
    </div>
  `);
}

async function submitLegalEFiling(matterId) {
  const pleadingId = parseInt(val("ef-pleading"), 10);
  const exhibitIds = [];
  document.querySelectorAll(".ef-exhibit-cb:checked").forEach((cb) => {
    exhibitIds.push(parseInt(cb.value, 10));
  });

  if (!pleadingId) {
    toast("Please select a primary pleading document.", "error");
    return;
  }

  try {
    const res = await apiFetch(`/legal/matters/${matterId}/efiling/package`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        matter_id: matterId,
        pleading_doc_id: pleadingId,
        exhibit_doc_ids: exhibitIds,
        package_name: val("ef-title") || undefined,
      }),
    });
    closeModal();
    toast(`Court e-Filing bundle created! Hash: ${res.efiling_hash.slice(0, 12)}…`, "success");
    adminTab("legal");
  } catch (e) {
    toast(`e-Filing packaging failed: ${e.message}`, "error");
  }
}

async function openLegalExtranetModal(matterId) {
  const docs = await apiFetch(`/legal/matters/${matterId}/documents`).catch(() => []);
  showModal(`
    <div class="p-4" style="max-width:550px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-share-nodes text-purple-600"></i> Secure Extranet Client Share</h3>
      <p class="text-xs text-slate-500 mb-3">Create an encrypted, password-protected portal token for clients or outside counsel.</p>

      <div class="space-y-3 text-xs">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Recipient Name *</label>
            <input id="ext-name" placeholder="e.g. John Client" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Recipient Email *</label>
            <input id="ext-email" type="email" placeholder="client@example.com" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Portal Access Password *</label>
          <input id="ext-pwd" type="password" placeholder="Enter strong passcode" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>

        <div>
          <label class="block font-semibold mb-1">Dynamic Watermark</label>
          <input id="ext-wm" value="CONFIDENTIAL - PREPARED FOR CLIENT REVIEW" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono text-2xs" />
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs bg-purple-600 hover:bg-purple-700" onclick="submitLegalExtranet(${matterId})">Create Portal Link</button>
      </div>
    </div>
  `);
}

async function submitLegalExtranet(matterId) {
  const docs = await apiFetch(`/legal/matters/${matterId}/documents`).catch(() => []);
  const docIds = docs.map((d) => d.document_id);

  try {
    const res = await apiFetch("/legal/portals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        matter_id: matterId,
        document_ids: docIds,
        recipient_name: val("ext-name"),
        recipient_email: val("ext-email"),
        password: val("ext-pwd"),
        watermark_text: val("ext-wm"),
      }),
    });
    closeModal();
    toast(`Extranet portal generated! Token: ${res.portal_token}`, "success");
    adminTab("legal");
  } catch (e) {
    toast(`Portal generation failed: ${e.message}`, "error");
  }
}

async function openLegalWallModal(matterId) {
  const users = (await apiFetch("/users")) || [];
  showModal(`
    <div class="p-4" style="max-width:500px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-shield-halved text-rose-500"></i> Enforce Ethical Wall</h3>
      <p class="text-xs text-slate-500 mb-3">Select conflicted attorneys or paralegals to bar them from viewing, searching, or editing this matter.</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Barrier Reason *</label>
          <input id="wl-reason" placeholder="e.g. Prior representation of adverse party at previous firm" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>

        <div>
          <label class="block font-semibold mb-1">Conflicted Users to Screen</label>
          <div class="space-y-1.5 max-h-40 overflow-y-auto border rounded p-2.5 bg-slate-50 dark:bg-slate-900">
            ${users.map((u) => `
              <label class="flex items-center gap-2">
                <input type="checkbox" class="wl-user-cb" value="${u.id}" />
                <span>${esc(u.username)} (${esc(u.email || u.role || 'user')})</span>
              </label>
            `).join("")}
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs bg-rose-600 hover:bg-rose-700" onclick="submitLegalWall(${matterId})">Enforce Ethical Wall</button>
      </div>
    </div>
  `);
}

async function submitLegalWall(matterId) {
  const reason = val("wl-reason");
  const userIds = [];
  document.querySelectorAll(".wl-user-cb:checked").forEach((cb) => {
    userIds.push(parseInt(cb.value, 10));
  });

  if (!reason || !userIds.length) {
    toast("Please enter a barrier reason and select at least one conflicted user.", "error");
    return;
  }

  try {
    await apiFetch(`/legal/matters/${matterId}/walls`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        matter_id: matterId,
        barrier_reason: reason,
        walled_user_ids: userIds,
      }),
    });
    closeModal();
    toast("Ethical wall enforced successfully!", "success");
    adminTab("legal");
  } catch (e) {
    toast(`Failed to enforce ethical wall: ${e.message}`, "error");
  }
}
