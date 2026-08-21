/* NewtonEDMS enterprise UI: workflow canvas, rules, compliance, RAG, connectors, ProcessMaker studio. */

function showModal(html) {
  let modal = document.getElementById("enterprise-dynamic-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "enterprise-dynamic-modal";
    modal.className = "modal";
    modal.style.position = "fixed";
    modal.style.inset = "0";
    modal.style.zIndex = "9999";
    modal.style.background = "rgba(15, 23, 42, 0.65)";
    modal.style.backdropFilter = "blur(4px)";
    modal.style.alignItems = "center";
    modal.style.justifyContent = "center";
    modal.style.overflowY = "auto";
    modal.style.padding = "20px";
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });
    document.body.appendChild(modal);
  }
  modal.innerHTML = html;
  const card = modal.firstElementChild;
  if (card) {
    card.classList.add("bg-white", "dark:bg-slate-900", "border", "border-slate-200", "dark:border-slate-800", "rounded-xl", "shadow-2xl", "overflow-hidden", "w-full");
    card.style.maxHeight = "90vh";
    card.style.overflowY = "auto";
  }
  modal.classList.add("open");
  modal.style.display = "flex";
}

const _origCloseModal = typeof closeModal === "function" ? closeModal : null;
closeModal = function (id) {
  if (id && id !== "enterprise-dynamic-modal") {
    if (_origCloseModal) _origCloseModal(id);
    const el = document.getElementById(id);
    if (el) {
      el.classList.remove("open");
      el.style.display = "none";
    }
  } else {
    const dynamicModal = document.getElementById("enterprise-dynamic-modal");
    if (dynamicModal) {
      dynamicModal.classList.remove("open");
      dynamicModal.style.display = "none";
      dynamicModal.innerHTML = "";
    }
  }
};

window.showModal = showModal;
window.closeModal = closeModal;

const ENT_TABS = new Set([
  "rules", "forms", "zones", "holds", "cases", "bpmn", "rag", "connectors",
  "cluster", "compliance", "security-policy", "report-builder", "office", "workflows", "legal", "accounting", "insurance", "medical",
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
  } else if (tab === "accounting") {
    await renderAccountingTab(content);
  } else if (tab === "insurance") {
    await renderInsuranceTab(content);
  } else if (tab === "medical") {
    await renderMedicalTab(content);
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

/* =============================================================================
   ACCOUNTING & FINANCIAL EDMS UI (2/3-Way Matching, OCR, ERP Sync, PEPPOL)
   ============================================================================= */

async function renderAccountingTab(content) {
  content.innerHTML = `<div class="p-4 text-xs text-slate-400"><i class="fa-solid fa-spinner fa-spin"></i> Loading Financial & AP Center…</div>`;
  try {
    const invoices = (await apiFetch("/accounting/invoices")) || [];
    const pos = (await apiFetch("/accounting/purchase-orders")) || [];

    const matched3wayCount = invoices.filter((i) => i.matching_status === "matched_3way" || i.matching_status === "matched_2way").length;
    const discrepanciesCount = invoices.filter((i) => i.matching_status === "price_variance" || i.matching_status === "quantity_variance").length;
    const duplicatesCount = invoices.filter((i) => i.is_duplicate).length;

    content.innerHTML = `
      <div style="padding:4px">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            <h3 class="font-bold text-base mb-0.5"><i class="fa-solid fa-file-invoice-dollar text-emerald-600"></i> Accounts Payable & Financial EDMS Hub</h3>
            <p class="text-xs text-slate-500">Automated 2-way and 3-way matching, line-item OCR extraction, ERP/GL sync, PEPPOL e-invoicing, and auditor portals.</p>
          </div>
          <div class="flex gap-2 flex-wrap">
            <button class="tb text-xs" onclick="openAccountingPOModal()"><i class="fa-solid fa-clipboard-list text-blue-500"></i> POs &amp; GRNs</button>
            <button class="tb text-xs" onclick="openBatchBarcodeModal()"><i class="fa-solid fa-barcode text-indigo-500"></i> Barcode Batch Split</button>
            <button class="tb text-xs" onclick="openPeppolModal()"><i class="fa-solid fa-file-code text-amber-500"></i> PEPPOL E-Invoicing</button>
            <button class="tb text-xs" onclick="openAuditorPortalModal()"><i class="fa-solid fa-user-shield text-purple-500"></i> Auditor Portals</button>
            <button class="tb primary text-xs" onclick="openNewInvoiceModal()"><i class="fa-solid fa-plus"></i> Ingest Invoice</button>
          </div>
        </div>

        <!-- Metrics Cards -->
        <div class="grid grid-cols-4 gap-3 mb-4">
          <div class="border rounded-lg p-3 bg-slate-50 dark:bg-slate-800">
            <div class="text-2xs uppercase text-slate-400 font-bold mb-1">Total Invoices</div>
            <div class="text-xl font-bold text-slate-800 dark:text-slate-100">${invoices.length}</div>
            <div class="text-2xs text-slate-500 mt-1">${pos.length} Active POs referenced</div>
          </div>
          <div class="border rounded-lg p-3 bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800">
            <div class="text-2xs uppercase text-emerald-600 dark:text-emerald-400 font-bold mb-1">2/3-Way Matched</div>
            <div class="text-xl font-bold text-emerald-700 dark:text-emerald-300">${matched3wayCount}</div>
            <div class="text-2xs text-emerald-600 dark:text-emerald-400 mt-1">Verified with PO &amp; GRN</div>
          </div>
          <div class="border rounded-lg p-3 bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800">
            <div class="text-2xs uppercase text-amber-600 dark:text-amber-400 font-bold mb-1">Price/Qty Variances</div>
            <div class="text-xl font-bold text-amber-700 dark:text-amber-300">${discrepanciesCount}</div>
            <div class="text-2xs text-amber-600 dark:text-amber-400 mt-1">Discrepancy flag active</div>
          </div>
          <div class="border rounded-lg p-3 bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-800">
            <div class="text-2xs uppercase text-rose-600 dark:text-rose-400 font-bold mb-1">Duplicate Alerts</div>
            <div class="text-xl font-bold text-rose-700 dark:text-rose-300">${duplicatesCount}</div>
            <div class="text-2xs text-rose-600 dark:text-rose-400 mt-1">Potential double-payment</div>
          </div>
        </div>

        <!-- Invoices Table -->
        <div class="border rounded-lg overflow-hidden bg-white dark:bg-slate-800 shadow-sm">
          <div class="p-3 bg-slate-50 dark:bg-slate-800/80 border-b flex items-center justify-between flex-wrap gap-2">
            <strong class="text-xs font-semibold">Vendor Invoices &amp; Accounts Payable Vouchers</strong>
            <span class="text-2xs text-slate-400">Strict WORM Audit Compliance Enforced</span>
          </div>

          <table class="w-full text-xs text-left border-collapse">
            <thead class="bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold border-b">
              <tr>
                <th class="p-2.5">Invoice #</th>
                <th class="p-2.5">Vendor</th>
                <th class="p-2.5">PO / GRN Ref</th>
                <th class="p-2.5">Total Amount</th>
                <th class="p-2.5">GL Account</th>
                <th class="p-2.5">Matching Status</th>
                <th class="p-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-700">
              ${invoices.map((inv) => renderInvoiceRow(inv)).join("") || `
                <tr>
                  <td colspan="7" class="p-8 text-center text-slate-400">
                    <i class="fa-solid fa-receipt text-3xl mb-2 text-slate-300 block"></i>
                    No vendor invoices recorded yet.<br>
                    <button class="tb primary text-xs mt-3" onclick="openNewInvoiceModal()"><i class="fa-solid fa-plus"></i> Ingest First Invoice</button>
                  </td>
                </tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } catch (e) {
    content.innerHTML = `<div class="p-4 text-xs text-red-500">Failed to load accounting suite: ${e.message}</div>`;
  }
}

function renderInvoiceRow(inv) {
  const matchColors = {
    matched_3way: "bg-emerald-100 text-emerald-800 border-emerald-300",
    matched_2way: "bg-blue-100 text-blue-800 border-blue-300",
    price_variance: "bg-rose-100 text-rose-800 border-rose-300",
    quantity_variance: "bg-amber-100 text-amber-800 border-amber-300",
    missing_po: "bg-orange-100 text-orange-800 border-orange-300",
    missing_grn: "bg-amber-100 text-amber-800 border-amber-300",
    unmatched: "bg-slate-100 text-slate-700 border-slate-300",
  };
  const badgeCls = matchColors[inv.matching_status] || "bg-slate-100 text-slate-700";

  return `
    <tr class="hover:bg-slate-50 dark:hover:bg-slate-800/50">
      <td class="p-2.5 font-mono font-bold text-slate-800 dark:text-slate-200">
        ${esc(inv.invoice_number)}
        ${inv.is_duplicate ? `<span class="ml-1.5 px-1.5 py-0.5 rounded text-3xs font-bold uppercase bg-rose-600 text-white animate-pulse">DUPLICATE</span>` : ''}
      </td>
      <td class="p-2.5">
        <div class="font-semibold">${esc(inv.vendor_name)}</div>
        ${inv.vendor_tax_id ? `<div class="text-2xs text-slate-400 font-mono">Tax ID: ${esc(inv.vendor_tax_id)}</div>` : ''}
      </td>
      <td class="p-2.5 font-mono text-2xs">
        <div>PO: <strong>${esc(inv.po_number || 'None')}</strong></div>
        ${inv.grn_number ? `<div class="text-slate-400">GRN: ${esc(inv.grn_number)}</div>` : ''}
      </td>
      <td class="p-2.5 font-bold text-slate-900 dark:text-slate-100">
        $${inv.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        <span class="text-2xs font-normal text-slate-400">(${esc(inv.currency)})</span>
      </td>
      <td class="p-2.5 text-2xs font-mono">
        <span class="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-700">${esc(inv.gl_account || '6000-General')}</span>
      </td>
      <td class="p-2.5">
        <span class="px-2 py-0.5 rounded text-2xs font-semibold uppercase border ${badgeCls}">${esc(inv.matching_status.replace(/_/g, ' '))}</span>
      </td>
      <td class="p-2.5 text-right space-x-1">
        <button class="tb text-2xs" onclick="open3WayMatchVisualizerModal(${inv.id})"><i class="fa-solid fa-code-compare text-blue-500"></i> Match Visualizer</button>
        <button class="tb text-2xs" onclick="openERPSyncModal(${inv.id})"><i class="fa-solid fa-arrows-rotate text-emerald-500"></i> Sync ERP</button>
      </td>
    </tr>
  `;
}

/* =============================================================================
   ACCOUNTING MODALS & WORKFLOWS
   ============================================================================= */

async function openNewInvoiceModal() {
  const pos = (await apiFetch("/accounting/purchase-orders")) || [];
  showModal(`
    <div class="p-4" style="max-width:650px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-receipt text-emerald-600"></i> Ingest Vendor Invoice &amp; Run 3-Way Match</h3>
      <p class="text-xs text-slate-500 mb-3">Upload invoice PDF or enter header details. Triggers automated OCR parsing, duplicate check, and PO/GRN matching.</p>

      <div class="space-y-3 text-xs">
        <div class="p-2.5 bg-slate-50 dark:bg-slate-900 rounded border">
          <label class="block font-semibold mb-1">OCR Text / Raw Invoice Paste (Auto-Extracts Line Items)</label>
          <textarea id="inv-ocr-text" rows="3" placeholder="Paste invoice text or receipt dump to auto-populate fields…" class="w-full border p-1.5 rounded bg-white dark:bg-slate-800 text-2xs font-mono"></textarea>
          <button class="tb text-2xs mt-1" onclick="runInvoiceOcrExtract()"><i class="fa-solid fa-wand-magic-sparkles text-amber-500"></i> Auto-Populate from OCR</button>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Invoice Number *</label>
            <input id="inv-number" placeholder="e.g. INV-2026-8801" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Vendor Name *</label>
            <input id="inv-vendor" placeholder="e.g. Dell Technologies" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
        </div>

        <div class="grid grid-cols-3 gap-3">
          <div>
            <label class="block font-semibold mb-1">Vendor Tax ID / VAT</label>
            <input id="inv-taxid" placeholder="e.g. US-45892019" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Matching Purchase Order</label>
            <select id="inv-po" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
              <option value="">No PO reference</option>
              ${pos.map((p) => `<option value="${p.po_number}">${esc(p.po_number)} - ${esc(p.vendor_name)} ($${p.total_amount})</option>`).join("")}
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1">GRN Number</label>
            <input id="inv-grn" placeholder="e.g. GRN-2026-4401" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono" />
          </div>
        </div>

        <div class="grid grid-cols-3 gap-3">
          <div>
            <label class="block font-semibold mb-1">Subtotal ($)</label>
            <input id="inv-subtotal" type="number" step="0.01" value="0.00" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Tax Amount ($)</label>
            <input id="inv-tax" type="number" step="0.01" value="0.00" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Total Amount ($) *</label>
            <input id="inv-total" type="number" step="0.01" value="0.00" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-bold text-emerald-600" />
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">GL Account</label>
            <input id="inv-gl" value="6010-Office Supplies & Tech" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono text-2xs" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Cost Center</label>
            <input id="inv-cc" value="CC-OPERATIONS-01" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono text-2xs" />
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs" onclick="submitNewInvoice()">Create &amp; 3-Way Match</button>
      </div>
    </div>
  `);
}

async function runInvoiceOcrExtract() {
  const text = val("inv-ocr-text");
  if (!text) {
    toast("Please enter invoice text to extract.", "error");
    return;
  }
  try {
    const res = await apiFetch("/accounting/invoices/extract-ocr", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (res.invoice_number) $("inv-number").value = res.invoice_number;
    if (res.vendor_name) $("inv-vendor").value = res.vendor_name;
    if (res.vendor_tax_id) $("inv-taxid").value = res.vendor_tax_id;
    if (res.po_number) $("inv-po").value = res.po_number;
    if (res.subtotal) $("inv-subtotal").value = res.subtotal;
    if (res.tax_amount) $("inv-tax").value = res.tax_amount;
    if (res.total_amount) $("inv-total").value = res.total_amount;
    toast("Extracted invoice header and line items successfully!", "success");
  } catch (e) {
    toast(`Extraction failed: ${e.message}`, "error");
  }
}

async function submitNewInvoice() {
  const invNum = val("inv-number");
  const vendor = val("inv-vendor");
  const totalAmt = parseFloat(val("inv-total") || "0.0");

  if (!invNum || !vendor || !totalAmt) {
    toast("Invoice number, vendor, and total amount are required.", "error");
    return;
  }

  try {
    const res = await apiFetch("/accounting/invoices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        invoice_number: invNum,
        vendor_name: vendor,
        vendor_tax_id: val("inv-taxid") || undefined,
        po_number: val("inv-po") || undefined,
        grn_number: val("inv-grn") || undefined,
        subtotal: parseFloat(val("inv-subtotal") || "0.0"),
        tax_amount: parseFloat(val("inv-tax") || "0.0"),
        total_amount: totalAmt,
        gl_account: val("inv-gl") || undefined,
        cost_center: val("inv-cc") || undefined,
      }),
    });
    closeModal();
    toast(`Invoice ${res.invoice_number} registered! Matching: ${res.matching_status.toUpperCase()}`, "success");
    adminTab("accounting");
  } catch (e) {
    toast(`Invoice creation failed: ${e.message}`, "error");
  }
}

async function open3WayMatchVisualizerModal(invoiceId) {
  const matchResult = await apiFetch(`/accounting/invoices/${invoiceId}/match`, { method: "POST" }).catch(() => null);
  const inv = await apiFetch(`/accounting/invoices/${invoiceId}`).catch(() => null);

  if (!matchResult || !inv) {
    toast("Failed to load matching visualizer.", "error");
    return;
  }

  showModal(`
    <div class="p-4" style="max-width:750px">
      <div class="flex items-center justify-between mb-2">
        <h3 class="font-bold text-base"><i class="fa-solid fa-code-compare text-blue-600"></i> Automated 3-Way Match Visualizer</h3>
        <span class="px-2 py-0.5 rounded text-xs font-semibold uppercase ${matchResult.status === 'matched_3way' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}">${esc(matchResult.status.replace(/_/g, ' '))}</span>
      </div>
      <p class="text-xs text-slate-500 mb-3">${esc(matchResult.notes)}</p>

      <div class="grid grid-cols-3 gap-3 mb-4 text-xs">
        <div class="p-2.5 rounded border bg-slate-50 dark:bg-slate-900">
          <strong class="text-slate-500 block mb-1">1. Vendor Invoice</strong>
          <div class="font-bold text-sm">${esc(inv.invoice_number)}</div>
          <div>Vendor: <strong>${esc(inv.vendor_name)}</strong></div>
          <div>Amount: <strong>$${inv.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong></div>
        </div>
        <div class="p-2.5 rounded border bg-slate-50 dark:bg-slate-900">
          <strong class="text-slate-500 block mb-1">2. Purchase Order</strong>
          <div class="font-bold text-sm">${esc(matchResult.po_number || 'N/A')}</div>
          <div>Status: <span class="text-blue-600 font-semibold">${matchResult.po_number ? 'Referenced' : 'Missing'}</span></div>
        </div>
        <div class="p-2.5 rounded border bg-slate-50 dark:bg-slate-900">
          <strong class="text-slate-500 block mb-1">3. Goods Received Note</strong>
          <div class="font-bold text-sm">${esc(matchResult.grn_number || 'N/A')}</div>
          <div>Status: <span class="text-emerald-600 font-semibold">${matchResult.grn_number ? 'Warehouse Verified' : 'No GRN'}</span></div>
        </div>
      </div>

      ${matchResult.discrepancies && matchResult.discrepancies.length ? `
        <div class="p-3 bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-800 rounded-lg mb-3">
          <strong class="text-xs text-rose-800 dark:text-rose-200 block mb-1"><i class="fa-solid fa-triangle-exclamation"></i> Discrepancy Warnings:</strong>
          <ul class="list-disc pl-4 text-xs text-rose-700 dark:text-rose-300 space-y-1">
            ${matchResult.discrepancies.map((d) => `<li>${esc(d)}</li>`).join("")}
          </ul>
        </div>
      ` : ''}

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
        <button class="tb primary text-xs" onclick="openERPSyncModal(${invoiceId})"><i class="fa-solid fa-arrows-rotate"></i> Sync to ERP GL</button>
      </div>
    </div>
  `);
}

async function openAccountingPOModal() {
  const pos = (await apiFetch("/accounting/purchase-orders")) || [];
  const grns = (await apiFetch("/accounting/grns")) || [];

  showModal(`
    <div class="p-4" style="max-width:700px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-clipboard-list text-blue-600"></i> Purchase Orders &amp; Warehouse GRNs</h3>
      <div class="grid grid-cols-2 gap-4 text-xs mb-4">
        <div class="border rounded-lg p-3 bg-slate-50 dark:bg-slate-900">
          <h4 class="font-bold mb-2 text-slate-800 dark:text-slate-200">Registered POs (${pos.length})</h4>
          <div class="space-y-2 max-h-48 overflow-y-auto">
            ${pos.map((p) => `
              <div class="p-2 bg-white dark:bg-slate-800 rounded border">
                <div class="flex justify-between font-bold"><span>${esc(p.po_number)}</span><span>$${p.total_amount.toFixed(2)}</span></div>
                <div class="text-2xs text-slate-500">${esc(p.vendor_name)} · ${p.status}</div>
              </div>
            `).join("") || '<div class="text-slate-400">No POs registered.</div>'}
          </div>
        </div>

        <div class="border rounded-lg p-3 bg-slate-50 dark:bg-slate-900">
          <h4 class="font-bold mb-2 text-slate-800 dark:text-slate-200">Warehouse Receiving GRNs (${grns.length})</h4>
          <div class="space-y-2 max-h-48 overflow-y-auto">
            ${grns.map((g) => `
              <div class="p-2 bg-white dark:bg-slate-800 rounded border">
                <div class="flex justify-between font-bold"><span>${esc(g.grn_number)}</span><span>PO: ${esc(g.po_number)}</span></div>
                <div class="text-2xs text-slate-500">${esc(g.vendor_name)}</div>
              </div>
            `).join("") || '<div class="text-slate-400">No GRNs recorded.</div>'}
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-2">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
      </div>
    </div>
  `);
}

async function openBatchBarcodeModal() {
  const folders = (await apiFetch("/folders")) || [];
  showModal(`
    <div class="p-4" style="max-width:500px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-barcode text-indigo-500"></i> Barcode Separator Batch Splitter</h3>
      <p class="text-xs text-slate-500 mb-3">Upload multi-page scanned PDF batches. Automatically splits documents at QR codes or separator pages (<code>[PAGE_SPLIT]</code> or <code>BARCODE:xxx</code>).</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Target Folder *</label>
          <select id="bc-folder" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
            ${folders.map((f) => `<option value="${f.id}">${esc(f.name)}</option>`).join("")}
          </select>
        </div>

        <div>
          <label class="block font-semibold mb-1">Batch Batch Name</label>
          <input id="bc-name" value="AP_Batch_Scan_${new Date().toISOString().slice(0,10)}" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono" />
        </div>

        <div>
          <label class="block font-semibold mb-1">Multi-page PDF File *</label>
          <input type="file" id="bc-file" accept=".pdf" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs" onclick="submitBatchBarcodeSplit()">Split &amp; Index Batch</button>
      </div>
    </div>
  `);
}

async function submitBatchBarcodeSplit() {
  const fileInput = $("bc-file");
  const folderId = val("bc-folder");
  if (!fileInput || !fileInput.files.length) {
    toast("Please select a PDF file.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("folder_id", folderId);
  formData.append("batch_name", val("bc-name") || "Batch_Scan");

  try {
    const token = localStorage.getItem("newton_access_token") || localStorage.getItem("token");
    const res = await fetch("/api/accounting/batch-split", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    closeModal();
    toast(`Batch split complete! Generated ${data.split_documents_count} indexed vouchers.`, "success");
    adminTab("accounting");
  } catch (e) {
    toast(`Batch split failed: ${e.message}`, "error");
  }
}

async function openPeppolModal() {
  showModal(`
    <div class="p-4" style="max-width:550px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-file-code text-amber-500"></i> PEPPOL BIS Billing 3.0 &amp; UBL E-Invoice Validator</h3>
      <p class="text-xs text-slate-500 mb-3">Upload structured XML e-Invoices to validate European PEPPOL, UBL 2.1, and Factur-X tax compliance rules.</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">E-Invoice XML File *</label>
          <input type="file" id="pep-file" accept=".xml" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>
      </div>

      <div id="pep-results" class="border rounded p-3 bg-slate-50 dark:bg-slate-900 text-xs mt-3 hidden"></div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
        <button class="tb primary text-xs" onclick="submitPeppolValidation()">Validate E-Invoice</button>
      </div>
    </div>
  `);
}

async function submitPeppolValidation() {
  const fileInput = $("pep-file");
  if (!fileInput || !fileInput.files.length) {
    toast("Select an XML file.", "error");
    return;
  }
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  const resultsBox = $("pep-results");
  resultsBox.innerHTML = `<div class="text-slate-400"><i class="fa-solid fa-spinner fa-spin"></i> Validating PEPPOL schema…</div>`;
  resultsBox.classList.remove("hidden");

  try {
    const token = localStorage.getItem("newton_access_token") || localStorage.getItem("token");
    const res = await fetch("/api/accounting/einvoice/validate", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    const data = await res.json();

    resultsBox.innerHTML = `
      <div class="space-y-2">
        <div class="flex items-center justify-between">
          <strong class="text-sm font-bold">${esc(data.standard)}</strong>
          <span class="px-2 py-0.5 rounded text-2xs font-semibold ${data.valid ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'}">${data.valid ? 'VALID COMPLIANT' : 'SCHEMA ERRORS'}</span>
        </div>
        <div>Invoice #: <strong>${esc(data.invoice_number)}</strong> · Payable: <strong>$${(data.payable_amount || 0).toFixed(2)}</strong></div>
        <div>Supplier: <strong>${esc(data.supplier_name)}</strong> (Tax ID: <code>${esc(data.supplier_tax_id || 'N/A')}</code>)</div>
        ${data.errors && data.errors.length ? `<div class="text-rose-600 font-semibold">${data.errors.join("; ")}</div>` : ''}
      </div>
    `;
  } catch (e) {
    resultsBox.innerHTML = `<div class="text-rose-600">Validation error: ${e.message}</div>`;
  }
}

async function openAuditorPortalModal() {
  const docs = (await apiFetch("/documents")) || [];
  showModal(`
    <div class="p-4" style="max-width:550px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-user-shield text-purple-500"></i> Generate Read-Only Auditor Portal</h3>
      <p class="text-xs text-slate-500 mb-3">Create temporary, restricted review access for internal/external auditors to inspect voucher sample batches.</p>

      <div class="space-y-3 text-xs">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Auditor Name *</label>
            <input id="aud-name" placeholder="e.g. PwC Lead Senior" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Auditor Email *</label>
            <input id="aud-email" type="email" placeholder="auditor@pwc.com" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Audit Firm Name</label>
          <input id="aud-firm" placeholder="e.g. PricewaterhouseCoopers LLP" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>

        <div>
          <label class="block font-semibold mb-1">Access Password *</label>
          <input id="aud-pwd" type="password" placeholder="Enter secure auditor password" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>

        <div>
          <label class="block font-semibold mb-1">Select Sample Documents</label>
          <div class="space-y-1 max-h-32 overflow-y-auto border rounded p-2 bg-slate-50 dark:bg-slate-900">
            ${docs.map((d) => `
              <label class="flex items-center gap-2">
                <input type="checkbox" class="aud-doc-cb" value="${d.id}" checked />
                <span>${esc(d.title || d.name)}</span>
              </label>
            `).join("") || '<div class="text-slate-400">No documents available.</div>'}
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs bg-purple-600 hover:bg-purple-700" onclick="submitAuditorPortal()">Generate Auditor Link</button>
      </div>
    </div>
  `);
}

async function submitAuditorPortal() {
  const docIds = [];
  document.querySelectorAll(".aud-doc-cb:checked").forEach((cb) => {
    docIds.push(parseInt(cb.value, 10));
  });

  try {
    const res = await apiFetch("/accounting/auditor-portals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        auditor_name: val("aud-name"),
        auditor_email: val("aud-email"),
        firm_name: val("aud-firm"),
        password: val("aud-pwd"),
        sample_document_ids: docIds,
        allowed_gl_accounts: ["6000-OpEx", "1000-Cash", "2000-AP"],
      }),
    });
    closeModal();
    toast(`Auditor portal token generated! Token: ${res.token}`, "success");
    adminTab("accounting");
  } catch (e) {
    toast(`Portal generation failed: ${e.message}`, "error");
  }
}

async function openERPSyncModal(invoiceId) {
  showModal(`
    <div class="p-4" style="max-width:500px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-arrows-rotate text-emerald-600"></i> Sync Source Document to ERP / GL</h3>
      <p class="text-xs text-slate-500 mb-3">Attach verified voucher directly to specific General Ledger transactions and cost centers.</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Target ERP Platform *</label>
          <select id="erp-plat" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-semibold">
            <option value="sap">SAP S/4HANA / ERP</option>
            <option value="netsuite">Oracle NetSuite</option>
            <option value="quickbooks">QuickBooks Online</option>
            <option value="xero">Xero Cloud Accounting</option>
            <option value="sage">Sage Intacct</option>
          </select>
        </div>

        <div>
          <label class="block font-semibold mb-1">GL Account Mapping</label>
          <input id="erp-gl" value="6010-Office Supplies & Hardware" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono text-2xs" />
        </div>

        <div>
          <label class="block font-semibold mb-1">Cost Center</label>
          <input id="erp-cc" value="CC-IT-CORP" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono text-2xs" />
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs" onclick="submitERPSync(${invoiceId})">Synchronize with ERP</button>
      </div>
    </div>
  `);
}

async function submitERPSync(invoiceId) {
  try {
    const res = await apiFetch(`/accounting/invoices/${invoiceId}/erp-sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform: val("erp-plat"),
        gl_account: val("erp-gl"),
        cost_center: val("erp-cc"),
      }),
    });
    closeModal();
    toast(`Synchronized with ${res.platform.toUpperCase()}! Voucher: ${res.voucher_reference}`, "success");
    adminTab("accounting");
  } catch (e) {
    toast(`ERP sync failed: ${e.message}`, "error");
  }
}

/* =============================================================================
   INSURANCE & CLAIMS EDMS UI (FNOL, Multi-Format Evidence, IDP, Fraud, Portals)
   ============================================================================= */

async function renderInsuranceTab(content) {
  content.innerHTML = `<div class="p-4 text-xs text-slate-400"><i class="fa-solid fa-spinner fa-spin"></i> Loading Insurance & Claims Center…</div>`;
  try {
    const claims = (await apiFetch("/insurance/claims")) || [];
    const policies = (await apiFetch("/insurance/policies")) || [];

    const autoApprovedCount = claims.filter((c) => c.auto_approved).length;
    const fraudAlertsCount = claims.filter((c) => (c.fraud_score || 0) >= 30).length;
    const underReviewCount = claims.filter((c) => c.status === "under_review").length;

    content.innerHTML = `
      <div style="padding:4px">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            <h3 class="font-bold text-base mb-0.5"><i class="fa-solid fa-car-burst text-rose-600"></i> Insurance Claims &amp; Policy EDMS Hub</h3>
            <p class="text-xs text-slate-500">First Notice of Loss (FNOL) ingestion, automated adjudication, multi-format crash evidence, IDP parsing, and EXIF fraud detection.</p>
          </div>
          <div class="flex gap-2 flex-wrap">
            <button class="tb text-xs" onclick="openInsurancePolicyModal()"><i class="fa-solid fa-shield-halved text-blue-500"></i> Policy Portfolio</button>
            <button class="tb text-xs" onclick="openInsuranceIDPModal()"><i class="fa-solid fa-wand-magic-sparkles text-amber-500"></i> IDP Extraction</button>
            <button class="tb text-xs" onclick="openClaimPortalModal()"><i class="fa-solid fa-user-shield text-purple-500"></i> Adjuster Portals</button>
            <button class="tb primary text-xs" onclick="openFNOLModal()"><i class="fa-solid fa-plus"></i> Intake FNOL Claim</button>
          </div>
        </div>

        <!-- Metrics Cards -->
        <div class="grid grid-cols-4 gap-3 mb-4">
          <div class="border rounded-lg p-3 bg-slate-50 dark:bg-slate-800">
            <div class="text-2xs uppercase text-slate-400 font-bold mb-1">Active Policies</div>
            <div class="text-xl font-bold text-slate-800 dark:text-slate-100">${policies.length}</div>
            <div class="text-2xs text-slate-500 mt-1">Master &amp; Endorsement Riders</div>
          </div>
          <div class="border rounded-lg p-3 bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800">
            <div class="text-2xs uppercase text-emerald-600 dark:text-emerald-400 font-bold mb-1">Auto-Approved Claims</div>
            <div class="text-xl font-bold text-emerald-700 dark:text-emerald-300">${autoApprovedCount}</div>
            <div class="text-2xs text-emerald-600 dark:text-emerald-400 mt-1">Instant STP (&lt;$1.5k threshold)</div>
          </div>
          <div class="border rounded-lg p-3 bg-blue-50 dark:bg-blue-950/30 border-blue-200 dark:border-blue-800">
            <div class="text-2xs uppercase text-blue-600 dark:text-blue-400 font-bold mb-1">Under Adjuster Review</div>
            <div class="text-xl font-bold text-blue-700 dark:text-blue-300">${underReviewCount}</div>
            <div class="text-2xs text-blue-600 dark:text-blue-400 mt-1">Specialized &amp; High Loss Queues</div>
          </div>
          <div class="border rounded-lg p-3 bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-800">
            <div class="text-2xs uppercase text-rose-600 dark:text-rose-400 font-bold mb-1">Fraud Risk Alerts</div>
            <div class="text-xl font-bold text-rose-700 dark:text-rose-300">${fraudAlertsCount}</div>
            <div class="text-2xs text-rose-600 dark:text-rose-400 mt-1">EXIF or Photo Hash flagged</div>
          </div>
        </div>

        <!-- Claims Docket Table -->
        <div class="border rounded-lg overflow-hidden bg-white dark:bg-slate-800 shadow-sm">
          <div class="p-3 bg-slate-50 dark:bg-slate-800/80 border-b flex items-center justify-between flex-wrap gap-2">
            <strong class="text-xs font-semibold">Claims Processing Docket &amp; Adjudication Register</strong>
            <span class="text-2xs text-slate-400">Integrated with Guidewire / Duck Creek Policy APIs</span>
          </div>

          <table class="w-full text-xs text-left border-collapse">
            <thead class="bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold border-b">
              <tr>
                <th class="p-2.5">Claim #</th>
                <th class="p-2.5">Claimant &amp; Insured</th>
                <th class="p-2.5">Loss Type &amp; Date</th>
                <th class="p-2.5">Estimated / Settlement</th>
                <th class="p-2.5">Adjudication Status</th>
                <th class="p-2.5">Fraud Score</th>
                <th class="p-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-700">
              ${claims.map((c) => renderClaimRow(c)).join("") || `
                <tr>
                  <td colspan="7" class="p-8 text-center text-slate-400">
                    <i class="fa-solid fa-shield-cat text-3xl mb-2 text-slate-300 block"></i>
                    No claims submitted yet.<br>
                    <button class="tb primary text-xs mt-3" onclick="openFNOLModal()"><i class="fa-solid fa-plus"></i> Intake First FNOL Claim</button>
                  </td>
                </tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } catch (e) {
    content.innerHTML = `<div class="p-4 text-xs text-red-500">Failed to load insurance suite: ${e.message}</div>`;
  }
}

function renderClaimRow(c) {
  const lossIcons = {
    collision: "fa-car-crash text-rose-500",
    theft: "fa-mask text-amber-500",
    water_damage: "fa-water text-blue-500",
    fire: "fa-fire text-orange-500",
    bodily_injury: "fa-user-injured text-purple-500",
    storm: "fa-cloud-bolt text-indigo-500",
  };
  const icon = lossIcons[c.loss_type] || "fa-triangle-exclamation text-slate-500";

  let statusBadge = `<span class="px-2 py-0.5 rounded text-2xs font-semibold uppercase bg-slate-100 text-slate-700 border">${esc(c.status)}</span>`;
  if (c.auto_approved) {
    statusBadge = `<span class="px-2 py-0.5 rounded text-2xs font-bold uppercase bg-emerald-100 text-emerald-800 border border-emerald-300"><i class="fa-solid fa-bolt"></i> AUTO-APPROVED</span>`;
  } else if (c.status === "approved" || c.status === "settled") {
    statusBadge = `<span class="px-2 py-0.5 rounded text-2xs font-semibold uppercase bg-emerald-100 text-emerald-800 border border-emerald-300">${esc(c.status)}</span>`;
  } else if (c.status === "under_review") {
    statusBadge = `<span class="px-2 py-0.5 rounded text-2xs font-semibold uppercase bg-blue-100 text-blue-800 border border-blue-300">Under Review</span>`;
  }

  let fraudBadge = `<span class="px-1.5 py-0.5 rounded text-3xs font-semibold bg-slate-100 text-slate-500">0% Clean</span>`;
  if (c.fraud_score >= 50) {
    fraudBadge = `<span class="px-1.5 py-0.5 rounded text-3xs font-bold uppercase bg-rose-600 text-white animate-pulse"><i class="fa-solid fa-skull-crossbones"></i> ${c.fraud_score}% HIGH RISK</span>`;
  } else if (c.fraud_score > 0) {
    fraudBadge = `<span class="px-1.5 py-0.5 rounded text-3xs font-semibold bg-amber-100 text-amber-800">${c.fraud_score}% Risk</span>`;
  }

  return `
    <tr class="hover:bg-slate-50 dark:hover:bg-slate-800/50">
      <td class="p-2.5 font-mono font-bold text-slate-800 dark:text-slate-200">
        ${esc(c.claim_number)}
      </td>
      <td class="p-2.5">
        <div class="font-semibold">${esc(c.claimant_name)}</div>
        <div class="text-2xs text-slate-400">Policy ID #${c.policy_id}</div>
      </td>
      <td class="p-2.5">
        <div class="flex items-center gap-1.5 font-medium">
          <i class="fa-solid ${icon}"></i>
          <span>${esc(c.loss_type.replace(/_/g, ' ').toUpperCase())}</span>
        </div>
        <div class="text-2xs text-slate-400 font-mono">${c.loss_date ? c.loss_date.slice(0, 10) : 'N/A'}</div>
      </td>
      <td class="p-2.5">
        <div class="font-bold text-slate-900 dark:text-slate-100">Est: $${c.estimated_loss.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
        ${c.settlement_amount > 0 ? `<div class="text-2xs font-bold text-emerald-600 dark:text-emerald-400">Payout: $${c.settlement_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>` : ''}
      </td>
      <td class="p-2.5">
        ${statusBadge}
      </td>
      <td class="p-2.5">
        ${fraudBadge}
      </td>
      <td class="p-2.5 text-right space-x-1">
        <button class="tb text-2xs" onclick="openClaimDetailWorkspace(${c.id})"><i class="fa-solid fa-folder-open text-blue-500"></i> Evidence &amp; Workspace</button>
        <button class="tb text-2xs" onclick="downloadSettlementPDF(${c.id})"><i class="fa-solid fa-file-pdf text-rose-500"></i> Payout PDF</button>
      </td>
    </tr>
  `;
}

/* =============================================================================
   INSURANCE MODALS & WORKFLOWS
   ============================================================================= */

async function openFNOLModal() {
  const policies = (await apiFetch("/insurance/policies")) || [];
  showModal(`
    <div class="p-4" style="max-width:650px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-file-shield text-rose-600"></i> First Notice of Loss (FNOL) Intake Wizard</h3>
      <p class="text-xs text-slate-500 mb-3">Submit initial loss incident. Automated engine checks policy active status, deductible rules, and low-value STP auto-approval (&lt;$1,500).</p>

      <div class="space-y-3 text-xs">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Claim Number *</label>
            <input id="fnol-num" value="CLM-2026-${Math.floor(1000 + Math.random() * 9000)}" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono font-bold" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Select Active Policy *</label>
            <select id="fnol-policy" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-semibold">
              ${policies.map((p) => `<option value="${p.id}">${esc(p.policy_number)} - ${esc(p.insured_name)} (${esc(p.policy_type).toUpperCase()}, Deductible: $${p.deductible})</option>`).join("")}
            </select>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Claimant Name *</label>
            <input id="fnol-claimant" placeholder="e.g. Alexander Vance" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Loss Type *</label>
            <select id="fnol-type" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-semibold">
              <option value="collision">Vehicle Collision / Accident</option>
              <option value="storm">Wind &amp; Storm Damage (Property)</option>
              <option value="water_damage">Water Damage / Plumbing Leak</option>
              <option value="theft">Theft &amp; Burglary</option>
              <option value="fire">Fire &amp; Smoke Damage</option>
              <option value="bodily_injury">Bodily Injury / Medical Casualty</option>
            </select>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Estimated Loss Amount ($) *</label>
            <input id="fnol-amt" type="number" step="0.01" value="1200.00" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-bold text-rose-600" />
            <span class="text-3xs text-slate-400 mt-0.5 block">&le; $1,500 with no injury triggers instant auto-approval.</span>
          </div>
          <div>
            <label class="block font-semibold mb-1">Loss Location</label>
            <input id="fnol-loc" placeholder="e.g. Intersection of 5th Ave &amp; Main St" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Incident Description &amp; Loss Details</label>
          <textarea id="fnol-notes" rows="3" placeholder="Describe how the loss occurred, emergency services notified, witness statements…" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900"></textarea>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs" onclick="submitFNOL()">Submit FNOL &amp; Adjudicate</button>
      </div>
    </div>
  `);
}

async function submitFNOL() {
  const claimNum = val("fnol-num");
  const claimant = val("fnol-claimant");
  const amt = parseFloat(val("fnol-amt") || "0.0");
  const policyId = parseInt(val("fnol-policy"), 10);

  if (!claimNum || !claimant || !policyId) {
    toast("Claim number, claimant, and policy are required.", "error");
    return;
  }

  try {
    const res = await apiFetch("/insurance/claims", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        claim_number: claimNum,
        policy_id: policyId,
        claimant_name: claimant,
        loss_type: val("fnol-type"),
        loss_location: val("fnol-loc") || undefined,
        estimated_loss: amt,
        notes: val("fnol-notes") || undefined,
      }),
    });
    closeModal();
    if (res.auto_approved) {
      toast(`Claim ${res.claim_number} AUTO-APPROVED! Net payout: $${res.settlement_amount.toFixed(2)}`, "success");
    } else {
      toast(`Claim ${res.claim_number} registered! Status: ${res.status.toUpperCase()}`, "success");
    }
    adminTab("insurance");
  } catch (e) {
    toast(`FNOL submission failed: ${e.message}`, "error");
  }
}

async function openClaimDetailWorkspace(claimId) {
  const claim = await apiFetch(`/insurance/claims/${claimId}`).catch(() => null);
  const evidenceList = (await apiFetch(`/insurance/claims/${claimId}/evidence`).catch(() => [])) || [];
  const folders = (await apiFetch("/folders")) || [];

  if (!claim) {
    toast("Failed to load claim details.", "error");
    return;
  }

  showModal(`
    <div class="p-4" style="max-width:850px">
      <div class="flex items-center justify-between mb-3 border-b pb-2">
        <div>
          <h3 class="font-bold text-base"><i class="fa-solid fa-folder-open text-blue-600"></i> Claim File: ${esc(claim.claim_number)}</h3>
          <span class="text-xs text-slate-500">Claimant: <strong>${esc(claim.claimant_name)}</strong> · Policy #${claim.policy_id}</span>
        </div>
        <div class="flex items-center gap-2">
          ${claim.auto_approved ? '<span class="px-2 py-0.5 rounded text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">AUTO-APPROVED</span>' : ''}
          <button class="tb primary text-xs" onclick="downloadSettlementPDF(${claim.id})"><i class="fa-solid fa-file-pdf"></i> Settlement PDF</button>
        </div>
      </div>

      <!-- Claim Summary Info -->
      <div class="grid grid-cols-4 gap-3 mb-4 text-xs">
        <div class="p-2.5 rounded border bg-slate-50 dark:bg-slate-900">
          <span class="text-slate-400 block text-2xs uppercase font-bold">Loss Type</span>
          <strong class="text-sm font-semibold">${esc(claim.loss_type.toUpperCase())}</strong>
        </div>
        <div class="p-2.5 rounded border bg-slate-50 dark:bg-slate-900">
          <span class="text-slate-400 block text-2xs uppercase font-bold">Estimated Loss</span>
          <strong class="text-sm font-semibold text-rose-600">$${claim.estimated_loss.toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong>
        </div>
        <div class="p-2.5 rounded border bg-slate-50 dark:bg-slate-900">
          <span class="text-slate-400 block text-2xs uppercase font-bold">Approved Settlement</span>
          <strong class="text-sm font-semibold text-emerald-600">$${claim.settlement_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong>
        </div>
        <div class="p-2.5 rounded border bg-slate-50 dark:bg-slate-900">
          <span class="text-slate-400 block text-2xs uppercase font-bold">Fraud Risk Score</span>
          <strong class="text-sm font-semibold ${claim.fraud_score >= 50 ? 'text-rose-600' : 'text-slate-700'}">${claim.fraud_score}% Risk</strong>
        </div>
      </div>

      ${claim.fraud_flags && claim.fraud_flags.length ? `
        <div class="p-3 bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-800 rounded-lg mb-4 text-xs">
          <strong class="text-rose-800 dark:text-rose-200 block mb-1"><i class="fa-solid fa-triangle-exclamation"></i> Fraud &amp; Alteration Flags Detected:</strong>
          <ul class="list-disc pl-4 text-rose-700 dark:text-rose-300 space-y-0.5">
            ${claim.fraud_flags.map((f) => `<li>${esc(f)}</li>`).join("")}
          </ul>
        </div>
      ` : ''}

      <!-- Evidence Upload Box -->
      <div class="p-3 border rounded-lg bg-slate-50 dark:bg-slate-900 mb-4 text-xs">
        <h4 class="font-bold mb-2"><i class="fa-solid fa-camera text-indigo-500"></i> Ingest Multi-Format Crash &amp; Loss Evidence (Photos, Dashcam Video, Audio, Estimates)</h4>
        <div class="grid grid-cols-3 gap-2">
          <div>
            <label class="block text-2xs font-semibold mb-1">Evidence Type</label>
            <select id="ev-type" class="w-full border p-1 rounded bg-white dark:bg-slate-800 text-2xs">
              <option value="scene_photo">Scene / Crash Photo (Auto EXIF Check)</option>
              <option value="dashcam_video">Dashcam Video Footage (MP4)</option>
              <option value="audio_statement">Recorded Claimant Audio Statement</option>
              <option value="drone_footage">Drone Survey Footage</option>
              <option value="police_report">Police Traffic Crash Report</option>
              <option value="repair_estimate">Auto Body Repair Estimate</option>
              <option value="medical_bill">Hospital / Medical Bill</option>
            </select>
          </div>
          <div>
            <label class="block text-2xs font-semibold mb-1">Folder Destination</label>
            <select id="ev-folder" class="w-full border p-1 rounded bg-white dark:bg-slate-800 text-2xs">
              ${folders.map((f) => `<option value="${f.id}">${esc(f.name)}</option>`).join("")}
            </select>
          </div>
          <div>
            <label class="block text-2xs font-semibold mb-1">Select Evidence File</label>
            <input type="file" id="ev-file" class="w-full border p-1 rounded bg-white dark:bg-slate-800 text-2xs" />
          </div>
        </div>
        <div class="flex justify-end mt-2">
          <button class="tb primary text-2xs" onclick="uploadEvidenceForClaim(${claim.id})"><i class="fa-solid fa-cloud-arrow-up"></i> Upload &amp; Run EXIF Fraud Check</button>
        </div>
      </div>

      <!-- Evidence Gallery -->
      <h4 class="font-bold text-xs mb-2"><i class="fa-solid fa-images text-slate-500"></i> Ingested Evidence Gallery (${evidenceList.length})</h4>
      <div class="space-y-2 max-h-56 overflow-y-auto">
        ${evidenceList.map((e) => `
          <div class="p-2.5 border rounded-lg bg-white dark:bg-slate-800 flex items-center justify-between text-xs">
            <div class="space-y-0.5">
              <div class="font-semibold flex items-center gap-1.5">
                <span class="px-1.5 py-0.5 rounded text-3xs font-bold uppercase bg-slate-100 dark:bg-slate-700">${esc(e.evidence_type.replace(/_/g, ' '))}</span>
                <span>Document ID #${e.document_id}</span>
                ${e.is_fraud_flagged ? '<span class="px-1.5 py-0.5 rounded text-3xs font-bold uppercase bg-rose-600 text-white animate-pulse">SUSPICIOUS EXIF</span>' : ''}
              </div>
              <div class="text-2xs text-slate-500">${esc(e.notes || 'No notes')} · Hash: <code class="text-3xs">${esc(e.image_hash ? e.image_hash.slice(0, 16) : 'N/A')}…</code></div>
            </div>
            <div class="text-right">
              <span class="text-2xs text-slate-400 font-mono">${e.created_at ? e.created_at.slice(0, 10) : ''}</span>
            </div>
          </div>
        `).join("") || '<div class="text-xs text-slate-400 p-4 text-center border rounded">No evidence uploaded yet.</div>'}
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
      </div>
    </div>
  `);
}

async function uploadEvidenceForClaim(claimId) {
  const fileInput = $("ev-file");
  const folderId = val("ev-folder");
  const evType = val("ev-type");

  if (!fileInput || !fileInput.files.length) {
    toast("Please select an evidence file.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("folder_id", folderId);
  formData.append("evidence_type", evType);
  formData.append("notes", `Uploaded via Claim File #${claimId}`);

  try {
    const token = localStorage.getItem("newton_access_token") || localStorage.getItem("token");
    const res = await fetch(`/api/insurance/claims/${claimId}/evidence`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    toast(`Evidence uploaded! Fraud Flag: ${data.is_fraud_flagged ? 'ALERT!' : 'CLEAN'}`, data.is_fraud_flagged ? "error" : "success");
    openClaimDetailWorkspace(claimId);
  } catch (e) {
    toast(`Upload failed: ${e.message}`, "error");
  }
}

async function downloadSettlementPDF(claimId) {
  try {
    const token = localStorage.getItem("newton_access_token") || localStorage.getItem("token");
    const res = await fetch(`/api/insurance/claims/${claimId}/generate-settlement`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ notes: "Official payout certified by insurance claims department." }),
    });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Settlement_Claim_${claimId}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast("Downloaded official Settlement Statement PDF!", "success");
  } catch (e) {
    toast(`Download failed: ${e.message}`, "error");
  }
}

async function openInsurancePolicyModal() {
  const policies = (await apiFetch("/insurance/policies")) || [];
  showModal(`
    <div class="p-4" style="max-width:700px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-shield-halved text-blue-600"></i> Policy Administration &amp; Endorsement Portfolio</h3>
      <div class="space-y-2 max-h-56 overflow-y-auto mb-4 text-xs">
        ${policies.map((p) => `
          <div class="p-2.5 border rounded-lg bg-slate-50 dark:bg-slate-900 flex justify-between items-center">
            <div>
              <div class="font-bold text-slate-800 dark:text-slate-200">${esc(p.policy_number)} - ${esc(p.insured_name)}</div>
              <div class="text-2xs text-slate-500 font-mono">Type: ${esc(p.policy_type.toUpperCase())} · Limit: $${p.coverage_limit.toLocaleString()} · Deductible: $${p.deductible}</div>
            </div>
            <span class="px-2 py-0.5 rounded text-2xs font-semibold uppercase bg-blue-100 text-blue-800">${esc(p.status)}</span>
          </div>
        `).join("") || '<div class="text-slate-400">No policies registered.</div>'}
      </div>
      <div class="flex justify-end gap-2">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
      </div>
    </div>
  `);
}

async function openInsuranceIDPModal() {
  showModal(`
    <div class="p-4" style="max-width:600px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-wand-magic-sparkles text-amber-500"></i> IDP Claims Document Parser</h3>
      <p class="text-xs text-slate-500 mb-3">Extract structured accident, diagnosis, and estimate metadata from unstructured documents.</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Document Category</label>
          <select id="idp-type" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
            <option value="police_report">Police Traffic Crash / Incident Report</option>
            <option value="medical_record">Medical Billing &amp; ICD-10 Diagnosis</option>
            <option value="repair_estimate">Auto Body Repair Estimate (VIN, Parts, Labor)</option>
          </select>
        </div>

        <div>
          <label class="block font-semibold mb-1">OCR Raw Text / Report Paste</label>
          <textarea id="idp-text" rows="5" placeholder="Paste police crash narrative, medical discharge bill, or repair estimate dump…" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono text-2xs"></textarea>
        </div>
      </div>

      <div id="idp-results" class="border rounded p-3 bg-slate-50 dark:bg-slate-900 text-xs mt-3 hidden"></div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
        <button class="tb primary text-xs" onclick="submitIDPExtract()">Extract Structured Fields</button>
      </div>
    </div>
  `);
}

async function submitIDPExtract() {
  const text = val("idp-text");
  const docType = val("idp-type");
  if (!text) {
    toast("Please enter text to parse.", "error");
    return;
  }

  const resultsBox = $("idp-results");
  resultsBox.innerHTML = `<div class="text-slate-400"><i class="fa-solid fa-spinner fa-spin"></i> Parsing structured claims metadata…</div>`;
  resultsBox.classList.remove("hidden");

  try {
    const res = await apiFetch("/insurance/idp/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_type: docType, text }),
    });
    resultsBox.innerHTML = `<pre class="text-2xs font-mono overflow-x-auto">${esc(JSON.stringify(res, null, 2))}</pre>`;
    toast("IDP extraction complete!", "success");
  } catch (e) {
    resultsBox.innerHTML = `<div class="text-rose-600">IDP extraction error: ${e.message}</div>`;
  }
}

async function openClaimPortalModal() {
  const claims = (await apiFetch("/insurance/claims")) || [];
  showModal(`
    <div class="p-4" style="max-width:550px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-user-shield text-purple-500"></i> Generate Secure Adjuster / Policyholder Portal</h3>
      <p class="text-xs text-slate-500 mb-3">Create encrypted, tokenized access for independent adjusters, medical providers, or body shops to upload evidence.</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Target Claim *</label>
          <select id="cp-claim" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-semibold">
            ${claims.map((c) => `<option value="${c.id}">${esc(c.claim_number)} - ${esc(c.claimant_name)} (${esc(c.loss_type).toUpperCase()})</option>`).join("")}
          </select>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Recipient Name</label>
            <input id="cp-name" placeholder="e.g. Crawford &amp; Co TPA" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Recipient Email *</label>
            <input id="cp-email" type="email" placeholder="adjuster@crawford.com" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Recipient Role</label>
          <select id="cp-role" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
            <option value="independent_adjuster">Independent Adjuster (TPA)</option>
            <option value="policyholder">Policyholder / Claimant</option>
            <option value="repair_shop">Auto Body / Repair Shop</option>
            <option value="medical_provider">Medical Provider / Hospital</option>
          </select>
        </div>

        <div>
          <label class="block font-semibold mb-1">Access Password *</label>
          <input id="cp-pwd" type="password" placeholder="Enter secure portal password" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs bg-purple-600 hover:bg-purple-700" onclick="submitClaimPortal()">Generate Portal Link</button>
      </div>
    </div>
  `);
}

async function submitClaimPortal() {
  const claimId = parseInt(val("cp-claim"), 10);
  const email = val("cp-email");
  const pwd = val("cp-pwd");

  if (!claimId || !email || !pwd) {
    toast("Claim, email, and password are required.", "error");
    return;
  }

  try {
    const res = await apiFetch("/insurance/portals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        claim_id: claimId,
        recipient_email: email,
        recipient_name: val("cp-name") || undefined,
        recipient_role: val("cp-role"),
        password: pwd,
        expires_in_days: 14,
      }),
    });
    closeModal();
    toast(`Portal token generated! Token: ${res.token}`, "success");
    adminTab("insurance");
  } catch (e) {
    toast(`Portal generation failed: ${e.message}`, "error");
  }
}

/* =============================================================================
   HEALTHCARE & CLINICAL EDMS UI (MPI, DICOM, HL7/FHIR, BREAK-GLASS, CONSENT)
   ============================================================================= */

async function renderMedicalTab(content) {
  content.innerHTML = `<div class="p-4 text-xs text-slate-400"><i class="fa-solid fa-spinner fa-spin"></i> Loading Healthcare &amp; Clinical Center…</div>`;
  try {
    const patients = (await apiFetch("/medical/patients")) || [];
    const encounters = (await apiFetch("/medical/encounters")) || [];
    const dicomStudies = (await apiFetch("/medical/dicom")) || [];
    const breakGlassEvents = (await apiFetch("/medical/break-glass/events").catch(() => [])) || [];

    const activeAdmissions = encounters.filter((e) => e.status === "admitted").length;

    content.innerHTML = `
      <div style="padding:4px">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            <h3 class="font-bold text-base mb-0.5"><i class="fa-solid fa-notes-medical text-sky-600"></i> Healthcare EHR &amp; Clinical EDMS Hub</h3>
            <p class="text-xs text-slate-500">Master Patient Index (MPI), DICOM/PACS diagnostic imaging, HL7/FHIR interoperability, bedside digital consents, and emergency Break-Glass overrides.</p>
          </div>
          <div class="flex gap-2 flex-wrap">
            <button class="tb text-xs" onclick="openDicomViewerModal()"><i class="fa-solid fa-x-ray text-indigo-500"></i> DICOM &amp; PACS</button>
            <button class="tb text-xs" onclick="openHL7StudioModal()"><i class="fa-solid fa-network-wired text-emerald-500"></i> HL7 &amp; FHIR Studio</button>
            <button class="tb text-xs" onclick="openInformedConsentModal()"><i class="fa-solid fa-file-signature text-purple-500"></i> Bedside Consents</button>
            <button class="tb text-xs bg-rose-50 text-rose-700 border-rose-200" onclick="openBreakGlassModal()"><i class="fa-solid fa-triangle-exclamation text-rose-600"></i> Emergency Override</button>
            <button class="tb primary text-xs" onclick="openNewPatientModal()"><i class="fa-solid fa-user-plus"></i> Register Patient</button>
          </div>
        </div>

        <!-- Metrics Cards -->
        <div class="grid grid-cols-4 gap-3 mb-4">
          <div class="border rounded-lg p-3 bg-slate-50 dark:bg-slate-800">
            <div class="text-2xs uppercase text-slate-400 font-bold mb-1">Master Patient Index (MPI)</div>
            <div class="text-xl font-bold text-slate-800 dark:text-slate-100">${patients.length}</div>
            <div class="text-2xs text-slate-500 mt-1">Unique MRN patient records</div>
          </div>
          <div class="border rounded-lg p-3 bg-sky-50 dark:bg-sky-950/30 border-sky-200 dark:border-sky-800">
            <div class="text-2xs uppercase text-sky-600 dark:text-sky-400 font-bold mb-1">Active Inpatient Admissions</div>
            <div class="text-xl font-bold text-sky-700 dark:text-sky-300">${activeAdmissions}</div>
            <div class="text-2xs text-sky-600 dark:text-sky-400 mt-1">Bedside encounter active</div>
          </div>
          <div class="border rounded-lg p-3 bg-indigo-50 dark:bg-indigo-950/30 border-indigo-200 dark:border-indigo-800">
            <div class="text-2xs uppercase text-indigo-600 dark:text-indigo-400 font-bold mb-1">DICOM Diagnostic Studies</div>
            <div class="text-xl font-bold text-indigo-700 dark:text-indigo-300">${dicomStudies.length}</div>
            <div class="text-2xs text-indigo-600 dark:text-indigo-400 mt-1">CT, MRI, X-Ray studies stored</div>
          </div>
          <div class="border rounded-lg p-3 bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-800">
            <div class="text-2xs uppercase text-rose-600 dark:text-rose-400 font-bold mb-1">Emergency Break-Glass Overrides</div>
            <div class="text-xl font-bold text-rose-700 dark:text-rose-300">${breakGlassEvents.length}</div>
            <div class="text-2xs text-rose-600 dark:text-rose-400 mt-1">Audited emergency events</div>
          </div>
        </div>

        <!-- Master Patient Index Table -->
        <div class="border rounded-lg overflow-hidden bg-white dark:bg-slate-800 shadow-sm">
          <div class="p-3 bg-slate-50 dark:bg-slate-800/80 border-b flex items-center justify-between flex-wrap gap-2">
            <strong class="text-xs font-semibold">Master Patient Index (MPI) &amp; Medical Record Register</strong>
            <span class="text-2xs text-slate-400"><i class="fa-solid fa-lock"></i> HIPAA &amp; GDPR ABAC Security Active</span>
          </div>

          <table class="w-full text-xs text-left border-collapse">
            <thead class="bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold border-b">
              <tr>
                <th class="p-2.5">MRN #</th>
                <th class="p-2.5">Patient Name</th>
                <th class="p-2.5">DOB &amp; Gender</th>
                <th class="p-2.5">Blood Type</th>
                <th class="p-2.5">Primary Physician</th>
                <th class="p-2.5">Insurance / Payer</th>
                <th class="p-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-700">
              ${patients.map((p) => renderPatientRow(p)).join("") || `
                <tr>
                  <td colspan="7" class="p-8 text-center text-slate-400">
                    <i class="fa-solid fa-hospital-user text-3xl mb-2 text-slate-300 block"></i>
                    No patient records registered.<br>
                    <button class="tb primary text-xs mt-3" onclick="openNewPatientModal()"><i class="fa-solid fa-plus"></i> Register First Patient</button>
                  </td>
                </tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } catch (e) {
    content.innerHTML = `<div class="p-4 text-xs text-red-500">Failed to load medical suite: ${e.message}</div>`;
  }
}

function renderPatientRow(p) {
  const age = p.dob ? Math.floor((new Date() - new Date(p.dob)) / (365.25 * 24 * 60 * 60 * 1000)) : 'N/A';
  return `
    <tr class="hover:bg-slate-50 dark:hover:bg-slate-800/50">
      <td class="p-2.5 font-mono font-bold text-sky-700 dark:text-sky-400">
        ${esc(p.mrn)}
      </td>
      <td class="p-2.5 font-semibold text-slate-900 dark:text-slate-100">
        ${esc(p.first_name)} ${esc(p.last_name)}
      </td>
      <td class="p-2.5">
        <div>${p.dob ? p.dob.slice(0, 10) : 'N/A'} <span class="text-slate-400">(${age} yrs)</span></div>
        <span class="text-2xs font-mono uppercase text-slate-500">Gender: ${esc(p.gender)}</span>
      </td>
      <td class="p-2.5 font-mono">
        <span class="px-2 py-0.5 rounded text-2xs font-bold bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-400">${esc(p.blood_type || 'Unknown')}</span>
      </td>
      <td class="p-2.5 text-slate-700 dark:text-slate-300">
        ${esc(p.primary_physician || 'Attending Staff')}
      </td>
      <td class="p-2.5 text-2xs font-mono text-slate-500">
        ${esc(p.insurance_id || 'Self-Pay / Uninsured')}
      </td>
      <td class="p-2.5 text-right space-x-1">
        <button class="tb text-2xs" onclick="openPatientChartWorkspace(${p.id})"><i class="fa-solid fa-notes-medical text-sky-500"></i> Patient Chart</button>
        <button class="tb text-2xs" onclick="openInformedConsentModal(${p.id})"><i class="fa-solid fa-file-signature text-purple-500"></i> Consent</button>
      </td>
    </tr>
  `;
}

/* =============================================================================
   HEALTHCARE MODALS & WORKSPACES
   ============================================================================= */

async function openNewPatientModal() {
  showModal(`
    <div class="p-4" style="max-width:600px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-user-plus text-sky-600"></i> Register New Patient into Master Index (MPI)</h3>
      <p class="text-xs text-slate-500 mb-3">Generates unique MRN and initializes Electronic Health Record (EHR) file with HIPAA compliance.</p>

      <div class="space-y-3 text-xs">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Medical Record Number (MRN) *</label>
            <input id="pat-mrn" value="MRN-2026-${Math.floor(10000 + Math.random() * 90000)}" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono font-bold" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Date of Birth (DOB) *</label>
            <input id="pat-dob" type="date" value="1990-01-01" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">First Name *</label>
            <input id="pat-fn" placeholder="e.g. Eleanor" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Last Name *</label>
            <input id="pat-ln" placeholder="e.g. Vance" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
        </div>

        <div class="grid grid-cols-3 gap-3">
          <div>
            <label class="block font-semibold mb-1">Gender</label>
            <select id="pat-gender" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
              <option value="F">Female</option>
              <option value="M">Male</option>
              <option value="O">Other</option>
              <option value="U">Unknown</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1">Blood Type</label>
            <select id="pat-blood" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono">
              <option value="O+">O+</option>
              <option value="O-">O-</option>
              <option value="A+">A+</option>
              <option value="A-">A-</option>
              <option value="B+">B+</option>
              <option value="B-">B-</option>
              <option value="AB+">AB+</option>
              <option value="AB-">AB-</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1">Insurance / Payer ID</label>
            <input id="pat-ins" placeholder="e.g. BCBS-9988" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono" />
          </div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Primary Attending Physician</label>
          <input id="pat-doc" placeholder="e.g. Dr. Allison Cameron" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs" onclick="submitNewPatient()">Register Patient</button>
      </div>
    </div>
  `);
}

async function submitNewPatient() {
  const mrn = val("pat-mrn");
  const fn = val("pat-fn");
  const ln = val("pat-ln");
  const dob = val("pat-dob");

  if (!mrn || !fn || !ln || !dob) {
    toast("MRN, First Name, Last Name, and DOB are required.", "error");
    return;
  }

  try {
    const res = await apiFetch("/medical/patients", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mrn,
        first_name: fn,
        last_name: ln,
        dob: `${dob}T00:00:00`,
        gender: val("pat-gender"),
        blood_type: val("pat-blood"),
        primary_physician: val("pat-doc") || undefined,
        insurance_id: val("pat-ins") || undefined,
      }),
    });
    closeModal();
    toast(`Patient ${res.first_name} ${res.last_name} (MRN: ${res.mrn}) registered!`, "success");
    adminTab("medical");
  } catch (e) {
    toast(`Registration failed: ${e.message}`, "error");
  }
}

async function openPatientChartWorkspace(patientId) {
  const patient = await apiFetch(`/medical/patients/${patientId}`).catch(() => null);
  const encounters = (await apiFetch(`/medical/encounters?patient_id=${patientId}`).catch(() => [])) || [];
  const docs = (await apiFetch(`/medical/patients/${patientId}/documents`).catch(() => [])) || [];

  if (!patient) {
    toast("Failed to load patient chart.", "error");
    return;
  }

  showModal(`
    <div class="p-4" style="max-width:850px">
      <!-- Patient Banner -->
      <div class="flex items-center justify-between mb-3 border-b pb-2">
        <div>
          <h3 class="font-bold text-base"><i class="fa-solid fa-id-card-clip text-sky-600"></i> EHR Chart: ${esc(patient.first_name)} ${esc(patient.last_name)}</h3>
          <span class="text-xs text-slate-500 font-mono">MRN: <strong>${esc(patient.mrn)}</strong> · DOB: ${patient.dob ? patient.dob.slice(0, 10) : ''} · Blood: <strong>${esc(patient.blood_type || 'N/A')}</strong></span>
        </div>
        <div class="flex items-center gap-2">
          <button class="tb text-xs bg-rose-50 text-rose-700 border-rose-200" onclick="openBreakGlassModal(${patient.id})"><i class="fa-solid fa-triangle-exclamation text-rose-600"></i> Break-Glass Override</button>
          <button class="tb primary text-xs" onclick="openInformedConsentModal(${patient.id})"><i class="fa-solid fa-file-signature"></i> e-Consent</button>
        </div>
      </div>

      <!-- Encounters Section -->
      <div class="mb-4">
        <h4 class="font-bold text-xs mb-2"><i class="fa-solid fa-hospital-user text-blue-500"></i> Clinical Encounters &amp; Admissions (${encounters.length})</h4>
        <div class="space-y-1.5 max-h-36 overflow-y-auto">
          ${encounters.map((enc) => `
            <div class="p-2 border rounded bg-slate-50 dark:bg-slate-900 flex items-center justify-between text-xs">
              <div>
                <strong class="font-mono text-sky-600">${esc(enc.encounter_number)}</strong>
                <span class="ml-2 font-semibold">${esc(enc.department || 'General')} (${esc(enc.encounter_type).toUpperCase()})</span>
                <div class="text-2xs text-slate-400">${esc(enc.chief_complaint || 'Routine Encounter')} · Attending: ${esc(enc.attending_physician || 'N/A')}</div>
              </div>
              <span class="px-2 py-0.5 rounded text-2xs font-semibold uppercase ${enc.status === 'admitted' ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}">${esc(enc.status)}</span>
            </div>
          `).join("") || '<div class="text-xs text-slate-400 p-2 border rounded text-center">No active encounters.</div>'}
        </div>
      </div>

      <!-- Clinical Documents with ABAC Sensitivities -->
      <h4 class="font-bold text-xs mb-2"><i class="fa-solid fa-file-medical text-emerald-500"></i> Clinical Documents &amp; Diagnostic Records (${docs.length})</h4>
      <div class="space-y-2 max-h-56 overflow-y-auto">
        ${docs.map((d) => `
          <div class="p-2.5 border rounded-lg ${d.accessible ? 'bg-white dark:bg-slate-800' : 'bg-rose-50/50 dark:bg-rose-950/20 border-rose-200'} flex items-center justify-between text-xs">
            <div>
              <div class="font-semibold flex items-center gap-1.5">
                <span>${esc(d.title)}</span>
                <span class="px-1.5 py-0.5 rounded text-3xs font-bold uppercase ${d.sensitivity_level === 'psychiatric' ? 'bg-purple-100 text-purple-800' : 'bg-slate-100 text-slate-600'}">${esc(d.sensitivity_level)}</span>
                ${d.is_signed ? '<span class="px-1.5 py-0.5 rounded text-3xs font-bold uppercase bg-emerald-100 text-emerald-800">SIGNED</span>' : ''}
              </div>
              <div class="text-2xs text-slate-400 font-mono">Category: ${esc(d.clinical_category)} ${d.restriction_reason ? `· <span class="text-rose-600 font-semibold">${esc(d.restriction_reason)}</span>` : ''}</div>
            </div>
            <div>
              ${!d.accessible ? `<button class="tb text-2xs bg-rose-600 text-white" onclick="openBreakGlassModal(${patient.id}, ${d.document_id})"><i class="fa-solid fa-unlock"></i> Break-Glass</button>` : `<a href="/api/medical/fhir/DocumentReference/${d.id}" target="_blank" class="tb text-2xs"><i class="fa-solid fa-code text-sky-500"></i> FHIR JSON</a>`}
            </div>
          </div>
        `).join("") || '<div class="text-xs text-slate-400 p-4 text-center border rounded">No clinical documents attached.</div>'}
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
      </div>
    </div>
  `);
}

async function openBreakGlassModal(patientId, docId) {
  const patients = (await apiFetch("/medical/patients")) || [];
  showModal(`
    <div class="p-4" style="max-width:550px">
      <div class="flex items-center gap-2 mb-2 text-rose-600">
        <i class="fa-solid fa-triangle-exclamation text-xl"></i>
        <h3 class="font-bold text-base">Emergency Clinical "Break-Glass" Access Override</h3>
      </div>
      <p class="text-xs text-slate-600 dark:text-slate-300 mb-3">
        <strong class="text-rose-600">WARNING:</strong> This action immediately overrides HIPAA/GDPR privacy barriers to unlock restricted clinical records.
        A permanent, immutable security alert will be dispatched to the Hospital Compliance &amp; Security Officer.
      </p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Target Patient *</label>
          <select id="bg-patient" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-semibold">
            ${patients.map((p) => `<option value="${p.id}" ${patientId === p.id ? 'selected' : ''}>${esc(p.mrn)} - ${esc(p.first_name)} ${esc(p.last_name)}</option>`).join("")}
          </select>
        </div>

        <div>
          <label class="block font-semibold mb-1">Mandatory Acute Clinical Rationale *</label>
          <textarea id="bg-rationale" rows="3" placeholder="e.g. Code Blue / Cardiac Arrest in Trauma Bay 1. Emergency psychiatric history required for drug allergy check." class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-semibold text-rose-700"></textarea>
          <span class="text-3xs text-slate-400 mt-0.5 block">Must be an authentic, life-threatening clinical justification.</span>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs bg-rose-600 hover:bg-rose-700" onclick="submitBreakGlass(${docId || 'null'})"><i class="fa-solid fa-bolt"></i> Authorize Emergency Override</button>
      </div>
    </div>
  `);
}

async function submitBreakGlass(docId) {
  const patientId = parseInt(val("bg-patient"), 10);
  const rationale = val("bg-rationale");

  if (!patientId || !rationale || rationale.trim().length < 8) {
    toast("Clinical rationale is mandatory for emergency Break-Glass override.", "error");
    return;
  }

  try {
    const res = await apiFetch("/medical/break-glass", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patient_id: patientId,
        document_id: docId || undefined,
        emergency_rationale: rationale,
      }),
    });
    closeModal();
    toast(`Emergency Break-Glass override granted for Patient #${res.patient_id}! Compliance alerted.`, "success");
    openPatientChartWorkspace(patientId);
  } catch (e) {
    toast(`Override failed: ${e.message}`, "error");
  }
}

async function openDicomViewerModal() {
  const studies = (await apiFetch("/medical/dicom")) || [];
  showModal(`
    <div class="p-4" style="max-width:700px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-x-ray text-indigo-600"></i> DICOM &amp; PACS Medical Imaging Portfolio</h3>
      <p class="text-xs text-slate-500 mb-3">Diagnostic medical imaging studies (CT, MRI, X-Ray, Ultrasound) cross-referenced to EHR Patient MRN.</p>

      <div class="space-y-2 max-h-56 overflow-y-auto mb-4 text-xs">
        ${studies.map((s) => `
          <div class="p-2.5 border rounded-lg bg-slate-50 dark:bg-slate-900 flex justify-between items-center">
            <div>
              <div class="font-bold font-mono text-slate-800 dark:text-slate-200"><span class="px-1.5 py-0.5 rounded text-3xs font-bold uppercase bg-indigo-100 text-indigo-800">${esc(s.modality)}</span> ${esc(s.body_part_examined || 'STUDY')} - ${esc(s.study_instance_uid.slice(0, 24))}…</div>
              <div class="text-2xs text-slate-400">Patient ID #${s.patient_id} · Instances: ${s.instance_count} slices</div>
            </div>
            <span class="text-2xs font-mono text-slate-400">${s.created_at ? s.created_at.slice(0, 10) : ''}</span>
          </div>
        `).join("") || '<div class="text-slate-400 p-4 text-center border rounded">No DICOM studies stored yet.</div>'}
      </div>

      <div class="flex justify-end gap-2">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
      </div>
    </div>
  `);
}

async function openHL7StudioModal() {
  showModal(`
    <div class="p-4" style="max-width:650px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-network-wired text-emerald-600"></i> HL7 (v2.x) &amp; FHIR R4 Interoperability Studio</h3>
      <p class="text-xs text-slate-500 mb-3">Ingest incoming HL7 v2 messages (ADT^A01, ORU^R01, MDM^T02) and transform EHR records into FHIR JSON resources.</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">HL7 v2 Message Payload</label>
          <textarea id="hl7-msg" rows="6" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-mono text-2xs">MSH|^~\\&amp;|EPIC|HOSPITAL|NEWTON_EDMS|ARCHIVE|20260601120000||ADT^A01|MSG-998811|P|2.5&#10;PID|1||MRN-2026-9901||Vance^Eleanor||19900101|F&#10;PV1|1|I|CARDIOLOGY^01^02||||Dr^Chase^Robert|||||||||||ENC-2026-9901</textarea>
        </div>
      </div>

      <div id="hl7-results" class="border rounded p-3 bg-slate-50 dark:bg-slate-900 text-xs mt-3 hidden"></div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Close</button>
        <button class="tb primary text-xs" onclick="submitHL7Ingest()">Ingest &amp; Parse HL7</button>
      </div>
    </div>
  `);
}

async function submitHL7Ingest() {
  const msg = val("hl7-msg");
  if (!msg) {
    toast("Please enter HL7 message text.", "error");
    return;
  }

  const resultsBox = $("hl7-results");
  resultsBox.innerHTML = `<div class="text-slate-400"><i class="fa-solid fa-spinner fa-spin"></i> Processing HL7 message…</div>`;
  resultsBox.classList.remove("hidden");

  try {
    const res = await apiFetch("/medical/hl7/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hl7_message: msg }),
    });
    resultsBox.innerHTML = `<pre class="text-2xs font-mono overflow-x-auto">${esc(JSON.stringify(res.hl7_parsed, null, 2))}</pre>`;
    toast("HL7 message processed successfully!", "success");
    adminTab("medical");
  } catch (e) {
    resultsBox.innerHTML = `<div class="text-rose-600">HL7 error: ${e.message}</div>`;
  }
}

async function openInformedConsentModal(patientId) {
  const patients = (await apiFetch("/medical/patients")) || [];
  showModal(`
    <div class="p-4" style="max-width:550px">
      <h3 class="font-bold text-base mb-2"><i class="fa-solid fa-file-signature text-purple-600"></i> Bedside Digital Informed Consent</h3>
      <p class="text-xs text-slate-500 mb-3">Capture legally binding electronic signature for surgical procedures, anesthesia, or blood transfusions.</p>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold mb-1">Target Patient *</label>
          <select id="con-pat" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900 font-semibold">
            ${patients.map((p) => `<option value="${p.id}" ${patientId === p.id ? 'selected' : ''}>${esc(p.mrn)} - ${esc(p.first_name)} ${esc(p.last_name)}</option>`).join("")}
          </select>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Consent Type *</label>
            <select id="con-type" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
              <option value="surgical">Surgical Authorization</option>
              <option value="anesthesia">Anesthesia Administration</option>
              <option value="blood_transfusion">Blood Transfusion</option>
              <option value="hipaa_acknowledgment">HIPAA Privacy Notice</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1">Procedure Name *</label>
            <input id="con-proc" placeholder="e.g. Laparoscopic Appendectomy" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold mb-1">Signer Full Name *</label>
            <input id="con-signer" placeholder="e.g. Eleanor Vance" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
          </div>
          <div>
            <label class="block font-semibold mb-1">Relationship</label>
            <select id="con-rel" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900">
              <option value="patient">Patient Self</option>
              <option value="parent">Parent</option>
              <option value="legal_guardian">Legal Guardian</option>
              <option value="healthcare_proxy">Healthcare Proxy</option>
            </select>
          </div>
        </div>

        <div>
          <label class="block font-semibold mb-1">Witness Name</label>
          <input id="con-witness" placeholder="e.g. Nurse Jackie Peyton, RN" class="w-full border p-1.5 rounded bg-white dark:bg-slate-900" />
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="tb text-xs" onclick="closeModal()">Cancel</button>
        <button class="tb primary text-xs bg-purple-600 hover:bg-purple-700" onclick="submitInformedConsent()"><i class="fa-solid fa-signature"></i> Sign &amp; Generate PDF</button>
      </div>
    </div>
  `);
}

async function submitInformedConsent() {
  const patId = parseInt(val("con-pat"), 10);
  const proc = val("con-proc");
  const signer = val("con-signer");

  if (!patId || !proc || !signer) {
    toast("Patient, procedure name, and signer name are required.", "error");
    return;
  }

  try {
    const res = await apiFetch("/medical/consents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patient_id: patId,
        consent_type: val("con-type"),
        procedure_name: proc,
        signer_name: signer,
        signer_relationship: val("con-rel"),
        signature_data: "e-signed-touchpad-biometric-hash",
        witness_name: val("con-witness") || undefined,
      }),
    });
    closeModal();
    toast(`Informed consent recorded! Generating PDF certification…`, "success");

    // Download PDF
    const token = localStorage.getItem("newton_access_token") || localStorage.getItem("token");
    const pdfRes = await fetch(`/api/medical/consents/${res.id}/pdf`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (pdfRes.ok) {
      const blob = await pdfRes.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Consent_${res.id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    adminTab("medical");
  } catch (e) {
    toast(`Consent submission failed: ${e.message}`, "error");
  }
}
