/* NewtonEDMS completion UI: toasts, remaining admin APIs, zones, collab, polish. */
(function () {
  function toast(msg, kind) {
    let host = $("toast-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "toast-host";
      document.body.appendChild(host);
    }
    const el = document.createElement("div");
    el.className = "toast " + (kind || "ok");
    el.textContent = String(msg || "");
    host.appendChild(el);
    setTimeout(() => el.remove(), 4200);
    const st = $("status-ready");
    if (st) st.textContent = String(msg || "Ready");
  }
  window.toast = toast;
  const _alert = window.alert;
  window.alert = function (msg) { toast(msg); };

  function _parseObj(raw, fallback) {
    if (raw && typeof raw === "object") return raw;
    try { return JSON.parse(raw || ""); } catch (e) { return fallback || {}; }
  }
  function _bars(obj) {
    const entries = Object.entries(obj || {});
    if (!entries.length) return "<p class=\"text-xs text-gray-400\">None</p>";
    const max = Math.max(1, ...entries.map((e) => Number(e[1]) || 0));
    return entries.map(([k, v]) => `<div class="rpt-bar"><span class="rpt-lab">${esc(k)}</span><span class="rpt-fill" style="width:${(Number(v) / max) * 240}px"></span> ${v}</div>`).join("");
  }

  async function hideDeadSso() {
    try {
      const p = await apiFetch("/auth/providers");
      const oidc = $("sso-oidc");
      const saml = $("sso-saml");
      const hint = $("sso-links");
      if (oidc && p && !p.oidc) oidc.classList.add("is-hidden");
      if (saml && p && !p.saml) saml.classList.add("is-hidden");
      if (hint && p && !p.oidc && !p.saml) hint.classList.add("is-hidden");
    } catch (e) { /* login screen still works */ }
  }
  document.addEventListener("DOMContentLoaded", hideDeadSso);

  const ADMIN_HELP = {
    users: "Creates logins and assigns roles. Superadmin bypasses folder ACL and tenancy; admin has full ACL inside their collective. Quota limits that user’s stored files.",
    groups: "Groups are ACL principals. Grant a group read/write on a folder or document from the Security tab — membership is what those grants match.",
    sessions: "Live auth cookies. Revoke to force sign-out. Last logins is the audit of password/SSO attempts for your account (admins see all sessions).",
    intelligence: "Tag catalog used by search (tag:invoice) and the auto-tag classifier. Custom fields appear on the document Properties tab and parametric search.",
    templates: "On upload, a metadata template pre-fills custom field keys. It does not change file format.",
    "folder-templates": "A named tree of subfolders. Right-click a folder → Apply folder template to create that structure under it.",
    naming: "Pattern for automatic document IDs such as {folder}-{seq}. Applied when a folder has a scheme, not a global rename.",
    classifier: "Trains on existing tagged documents, then JOEX suggests tags on new uploads. Needs tagged examples first.",
    workflows: "Review/approve chains on a document. Designer edges and XOR conditions are what execution follows — not the JSON steps field.",
    bpmn: "Import BPMN XML, open a case with documents, then Run process. Completing tasks advances the graph and closes the case when it ends.",
    rules: "On document_created / processed / confirmed: if a tag/status/mime matches, then tag, set status, or start a workflow. Runs in JOEX, not in the browser.",
    forms: "Public capture URL (/forms/{token}) creates a document in the chosen folder from submitted fields. Barcode encodes that token.",
    zones: "PDF rectangles used by IDP Capture on the inspector Preview tab. Train IDP from tagged examples.",
    imports: "Watches a directory under storage/imports (or FTP). Scan copies files into the target folder. Empty EDMS_IMPORT_ROOT disables this.",
    "mailbox-tasks": "Repeating IMAP fetch into a folder. Requires an IMAP account on SMTP / IMAP accounts first, then Run or wait for the scheduler.",
    uploads: "Unauthenticated POST URL that files land in a folder with optional tags. Share the link; revoke to stop it.",
    "csv-import": "Each CSV row becomes a document (title/tags/fields) in the chosen folder.",
    scan: "Uploads an image or PDF into the current folder and queues OCR via JOEX. Camera capture uses the same /api/scan/ingest endpoint.",
    backup: "Zips the storage tree. Restore copies files back — it does not rebuild the SQLite database.",
    mail: "SMTP is used to send mail from the toolbar. IMAP accounts are sources for mailbox import. The SMTP gateway is an inbound listener (EDMS_SMTP_GATEWAY).",
    connectors: "Saved credentials for OnlyOffice, DocuSign, Drive, Outlook, GCal, Azure, SMB. Buttons below call those APIs using the enabled connector of that kind.",
    ldap: "LDAP bind on login maps directory groups onto Newton groups/roles. SAML ACS is /api/auth/saml/acs; unsigned assertions are rejected when Require signed assertions is on.",
    archivelink: "Maps a SAP content repository id (ContRep) to a folder. PUT /archivelink/{contRep}/{docId} then creates a real document in that folder.",
    protocols: "Machine APIs. WebDAV mounts the repository; CMIS browser can create/update/delete; SOAP covers create/download/checkout. Use Basic or cookie auth.",
    addons: "Webhook on process, or a zip with a descriptor+script. Run executes that addon against a document id.",
    stores: "Where new file bytes go. Filesystem path, or Azure Blob (account/container/key). Default store is used by persist().",
    ocr: "JOEX conversion pipeline. Installed binaries are used; missing ones are skipped. Language is passed to tesseract/ocrmypdf.",
    index: "Whoosh/FTS index behind Search. Rebuild walks all documents; new uploads are indexed by JOEX automatically.",
    jobs: "JOEX queue: hash, convert, OCR, extract, classify, index. Retry failed jobs; Run queued processes the backlog now.",
    scheduled: "Leader-only timers (retention, mailbox, backups). Followers skip these. Heartbeat is the exception.",
    cluster: "Nodes that have heartbeated. API nodes elect a leader for the scheduler. JOEX workers register separately and never become leader.",
    "security-policy": "Failed-login lockout, optional IP allow/deny, password max age. Applied on /api/auth/login, not on SSO.",
    holds: "Marks documents immutable and blocks GDPR erase and retention delete until released.",
    gdpr: "Export is a zip of that user’s documents and profile. Erase anonymises the account unless any of their files are on legal hold.",
    "redaction-rules": "Named regex lists. The inspector PDF tab can apply a rule; the file is burned in and marked immutable.",
    retention: "Archive or delete documents older than N years in a folder (or all). Skips legal hold. Apply now or wait for the scheduler.",
    audit: "Append-only log of security-relevant actions (login, ACL, delete, hold, sign).",
    compliance: "Live checks against this database (audit rows, 2FA users, retention policies, IP policy). Not a certification.",
    tickets: "Download URLs created from the inspector Share tab (max downloads, expiry). Not a helpdesk.",
    "query-shares": "Public /s/{token} page that runs a saved search for anyone with the link.",
    notify: "Channels (email/webhook), event hooks on document_created etc., and saved-search notification rules.",
    reports: "Counts from the live catalog: status, types, tags, locked, duplicates, trash.",
    "report-builder": "Saved query + group-by. Run returns grouped counts and a bar chart, plus optional id list.",
    rag: "Answers from indexed text. Uses EDMS_LLM_URL when set; otherwise hashing extractive search. Citations open the document.",
    logs: "Tail of the server log file. Restart hint does not kill the process — it tells you to recycle the service.",
  };

  function injectAdminHelp(tab) {
    const help = ADMIN_HELP[tab];
    const host = $("admin-content");
    if (!help || !host || host.querySelector(".admin-help")) return;
    host.insertAdjacentHTML("afterbegin", `<p class="admin-help">${help}</p>`);
  }

  window.openOfficeModal = function () {
    if (!currentDocId) return;
    const docName = (currentDoc && currentDoc.name) || `Document #${currentDocId}`;
    const el = $("office-modal-docname");
    if (el) el.textContent = `Selected: ${docName}`;
    openModal("office-modal");
  };

  window.openInOffice = function () {
    openOfficeModal();
  };

  window.launchDesktopOffice = async function () {
    if (!currentDocId) return;
    closeModal("office-modal");
    try {
      const r = await apiFetch(`/api/office/desktop-launch/${currentDocId}`);
      if (r && r.protocol_uri) {
        window.location.href = r.protocol_uri;
        toast(`Launching ${r.app_name || "Microsoft Office"}…`);
      } else {
        downloadDoc(currentDocId);
      }
    } catch (e) {
      toast(`Could not launch desktop Office: ${e.message}`, "error");
    }
  };

  window.openOfficeOnline = async function () {
    if (!currentDocId) return;
    closeModal("office-modal");
    window.open(`/api/office/wopi/frame/${currentDocId}?mode=edit`, "_blank");
    toast("Opening in Office Online / WOPI workspace…");
  };

  window.openOfficeTemplateModal = function () {
    if (!currentDocId) return;
    const name = (currentDoc && currentDoc.name) || "document.docx";
    const stem = name.replace(/\.[^/.]+$/, "");
    const ext = name.split(".").pop();
    const targetInput = $("tmpl-target-name");
    if (targetInput) targetInput.value = `Filled_${stem}_${new Date().toISOString().slice(0, 10)}.${ext}`;
    const ctxInput = $("tmpl-context");
    if (ctxInput) ctxInput.value = JSON.stringify({ title: "Custom Title", recipient: "Acme Corp", date: new Date().toISOString().slice(0, 10) }, null, 2);
    openModal("template-modal");
  };

  window.executeTemplateMerge = async function () {
    if (!currentDocId) return;
    const targetName = $("tmpl-target-name").value.trim();
    let ctx = {};
    try {
      ctx = JSON.parse($("tmpl-context").value || "{}");
    } catch (e) {
      toast("Invalid JSON data for template context", "error");
      return;
    }
    try {
      const res = await apiFetch(`/api/office/templates/${currentDocId}/merge`, {
        method: "POST",
        body: JSON.stringify({ target_name: targetName, context: ctx }),
      });
      closeModal("template-modal");
      toast(`Document generated: ${res.name || "Success"}`);
      if (typeof loadFolderDocs === "function") loadFolderDocs(currentFolderId);
    } catch (e) {
      toast(`Template merge error: ${e.message}`, "error");
    }
  };

  window.exportExcelReport = async function () {
    toast("Generating Excel export…");
    try {
      const payload = selectedDocIds.size ? { document_ids: Array.from(selectedDocIds) } : { folder_id: currentFolderId };
      const res = await fetch("/api/office/export/excel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `NewtonEDMS_Export_${new Date().toISOString().slice(0, 10)}.xlsx`;
      a.click();
      toast("Excel report downloaded!");
    } catch (e) {
      toast(`Export failed: ${e.message}`, "error");
    }
  };

  window.exportWordReport = async function () {
    toast("Generating Word dossier…");
    try {
      const payload = selectedDocIds.size ? { document_ids: Array.from(selectedDocIds) } : { folder_id: currentFolderId };
      const res = await fetch("/api/office/export/word", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `NewtonEDMS_Dossier_${new Date().toISOString().slice(0, 10)}.docx`;
      a.click();
      toast("Word dossier downloaded!");
    } catch (e) {
      toast(`Export failed: ${e.message}`, "error");
    }
  };

  window.renderOfficeProps = async function (host) {
    if (!currentDocId) return;
    host.innerHTML = `<div style="padding:16px;text-align:center"><i class="fa-solid fa-spinner fa-spin"></i> Reading OpenXML properties…</div>`;
    try {
      const res = await apiFetch(`/api/office/properties/${currentDocId}`);
      const p = (res && res.properties) || {};
      host.innerHTML = `
        <div style="padding:12px">
          <h4 style="font-size:13px;font-weight:700;margin-bottom:8px"><i class="fa-solid fa-file-word text-blue-500"></i> OpenXML Document Properties</h4>
          <p style="font-size:11px;color:var(--text-muted);margin-bottom:12px">Synchronize core and custom properties with Office OpenXML files.</p>
          <div style="display:flex;flex-direction:column;gap:8px;font-size:12px">
            <div><label style="font-weight:600;font-size:10px;text-transform:uppercase;color:var(--text-muted)">Title</label>
              <input id="op-title" value="${esc(p.title || "")}" style="width:100%;padding:6px;border:1px solid #cbd5e1;border-radius:4px" /></div>
            <div><label style="font-weight:600;font-size:10px;text-transform:uppercase;color:var(--text-muted)">Author / Creator</label>
              <input id="op-author" value="${esc(p.author || "")}" style="width:100%;padding:6px;border:1px solid #cbd5e1;border-radius:4px" /></div>
            <div><label style="font-weight:600;font-size:10px;text-transform:uppercase;color:var(--text-muted)">Subject</label>
              <input id="op-subject" value="${esc(p.subject || "")}" style="width:100%;padding:6px;border:1px solid #cbd5e1;border-radius:4px" /></div>
            <div><label style="font-weight:600;font-size:10px;text-transform:uppercase;color:var(--text-muted)">Keywords</label>
              <input id="op-keywords" value="${esc(p.keywords || "")}" style="width:100%;padding:6px;border:1px solid #cbd5e1;border-radius:4px" /></div>
            <div><label style="font-weight:600;font-size:10px;text-transform:uppercase;color:var(--text-muted)">Comments / Description</label>
              <textarea id="op-comments" rows="2" style="width:100%;padding:6px;border:1px solid #cbd5e1;border-radius:4px">${esc(p.comments || "")}</textarea></div>
            <button class="tb primary" style="margin-top:8px" onclick="saveOfficeProps()"><i class="fa-solid fa-save"></i> Save Properties to File</button>
          </div>
        </div>
      `;
    } catch (e) {
      host.innerHTML = `<div style="padding:12px;color:red">Failed to load Office properties: ${e.message}</div>`;
    }
  };

  window.saveOfficeProps = async function () {
    if (!currentDocId) return;
    const payload = {
      title: $("op-title").value,
      author: $("op-author").value,
      subject: $("op-subject").value,
      keywords: $("op-keywords").value,
      comments: $("op-comments").value,
    };
    try {
      await apiFetch(`/api/office/properties/${currentDocId}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      toast("Office properties saved into document file!");
    } catch (e) {
      toast(`Save error: ${e.message}`, "error");
    }
  };

  let _collabWs = null;
  window.startCollabNotes = function (textareaId) {
    if (!currentDocId) return;
    if (_collabWs) {
      try { _collabWs.close(); } catch (e) { /* */ }
    }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/collab/${currentDocId}`);
    _collabWs = ws;
    const el = $(textareaId);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.op && msg.op.notes != null && el && document.activeElement !== el) el.value = msg.op.notes;
      } catch (e) { /* */ }
    };
    if (el) {
      el.addEventListener("input", () => {
        if (ws.readyState === 1) ws.send(JSON.stringify({ notes: el.value }));
      });
    }
  };

  const _insp = typeof inspTab === "function" ? inspTab : null;
  inspTab = async function (tab) {
    if (tab === "preview" && currentDocId) {
      markInspTab(tab);
      await renderZonePreview($("insp-body"));
      return;
    }
    if (tab === "comments" && currentDocId) {
      markInspTab(tab);
      await renderCollabComments($("insp-body"));
      return;
    }
    if (tab === "officeprops" && currentDocId) {
      markInspTab(tab);
      await renderOfficeProps($("insp-body"));
      return;
    }
    if (_insp) return _insp(tab);
  };

  async function renderZonePreview(body) {
    const mime = (currentDoc && currentDoc.mime) || "";
    const isPdf = mime.includes("pdf") || /\.pdf$/i.test((currentDoc && currentDoc.name) || "");
    const text = await apiFetch(`/documents/${currentDocId}/text`).catch(() => ({ text: "" }));
    const q = ($("search-input") && $("search-input").value) || "";
    let highlights = "";
    if (q) {
      const h = await apiFetch(`/documents/${currentDocId}/highlight?q=${encodeURIComponent(q)}`).catch(() => null);
      if (h && h.snippets && h.snippets.length) highlights = `<div class="hl-snips text-xs bg-amber-50 p-2 mb-2">${h.snippets.map((s) => `<p>${s}</p>`).join("")}</div>`;
    }
    if (!isPdf) {
      body.innerHTML = `${highlights}<div id="preview-frame" class="preview-frame">Loading…</div>
        <pre class="whitespace-pre-wrap text-xs bg-slate-50 p-2 rounded max-h-40 overflow-y-auto">${esc((text && text.text) || "")}</pre>`;
      if (typeof loadBlobPreview === "function") loadBlobPreview(mime);
      return;
    }
    const tpls = (await apiFetch("/zones").catch(() => [])) || [];
    body.innerHTML = `${highlights}
      <div class="flex gap-1 mb-1 text-xs">
        <button class="tb" onclick="zonePage(-1)">Prev</button>
        <span>Page <input id="zn-page" type="number" min="1" value="${window._zonePage || 1}" class="w-12 border" /></span>
        <button class="tb" onclick="zonePage(1)">Next</button>
        <button class="tb primary" onclick="toggleZoneDraw()">Draw zone</button>
        <select id="zn-tpl">${tpls.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select>
        <button class="tb" onclick="applyDrawnZones()">Save template</button>
        <button class="tb" onclick="runIdpWithZones()">Capture</button>
      </div>
      <div id="zone-stage" class="zone-stage"><img id="zone-img" alt="page" /><canvas id="zone-cv"></canvas></div>
      <ul id="zone-list" class="text-xs mt-1"></ul>
      <pre class="whitespace-pre-wrap text-xs bg-slate-50 p-2 rounded max-h-24 overflow-y-auto">${esc((text && text.text) || "")}</pre>`;
    window._zonePage = window._zonePage || 1;
    window._drawnZones = window._drawnZones || [];
    await loadZonePage();
    paintZoneList();
  }
  window.zonePage = async function (delta) {
    window._zonePage = Math.max(1, (window._zonePage || 1) + delta);
    const inp = $("zn-page");
    if (inp) inp.value = window._zonePage;
    await loadZonePage();
  };
  async function loadZonePage() {
    const img = $("zone-img");
    const cv = $("zone-cv");
    if (!img || !cv) return;
    img.onload = () => {
      cv.width = img.naturalWidth;
      cv.height = img.naturalHeight;
      cv.style.width = img.clientWidth + "px";
      cv.style.height = img.clientHeight + "px";
      drawZones();
    };
    img.src = `/api/documents/${currentDocId}/page-image?page=${window._zonePage || 1}&t=${Date.now()}`;
  }
  function drawZones() {
    const cv = $("zone-cv");
    if (!cv) return;
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.strokeStyle = "#0284c7";
    ctx.lineWidth = 2;
    (window._drawnZones || []).filter((z) => (z.page || 1) === (window._zonePage || 1)).forEach((z) => {
      ctx.strokeRect(z.x, z.y, z.w, z.h);
      ctx.fillStyle = "rgba(2,132,199,0.12)";
      ctx.fillRect(z.x, z.y, z.w, z.h);
    });
  }
  window.toggleZoneDraw = function () {
    const cv = $("zone-cv");
    if (!cv) return;
    window._zoneDraw = !window._zoneDraw;
    toast(window._zoneDraw ? "Drag on the page to draw a zone" : "Draw mode off");
    let start = null;
    cv.onmousedown = (e) => {
      if (!window._zoneDraw) return;
      const r = cv.getBoundingClientRect();
      const sx = cv.width / r.width, sy = cv.height / r.height;
      start = { x: (e.clientX - r.left) * sx, y: (e.clientY - r.top) * sy };
    };
    cv.onmouseup = (e) => {
      if (!start || !window._zoneDraw) return;
      const r = cv.getBoundingClientRect();
      const sx = cv.width / r.width, sy = cv.height / r.height;
      const x2 = (e.clientX - r.left) * sx, y2 = (e.clientY - r.top) * sy;
      const z = {
        page: window._zonePage || 1,
        x: Math.min(start.x, x2),
        y: Math.min(start.y, y2),
        w: Math.abs(x2 - start.x),
        h: Math.abs(y2 - start.y),
        name: prompt("Field name", "field") || "field",
      };
      if (z.w > 4 && z.h > 4) window._drawnZones.push(z);
      start = null;
      drawZones();
      paintZoneList();
    };
  };
  function paintZoneList() {
    const el = $("zone-list");
    if (!el) return;
    el.innerHTML = (window._drawnZones || []).map((z, i) => `<li>${esc(z.name)} p${z.page} ${Math.round(z.x)},${Math.round(z.y)} <button onclick="_drawnZones.splice(${i},1); paintZoneList(); document.querySelector('#zone-cv') && (window._drawnZones=_drawnZones);">×</button></li>`).join("");
  }
  window.applyDrawnZones = async function () {
    const name = prompt("Template name", "Drawn zones") || "Drawn zones";
    await apiFetch("/zones", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, zones: window._drawnZones || [] }) });
    toast("Zone template saved");
  };
  window.runIdpWithZones = async function () {
    const tpl = val("zn-tpl");
    const r = await apiFetch(`/documents/${currentDocId}/idp${tpl ? "?zone_id=" + tpl : ""}`, { method: "POST" });
    toast(JSON.stringify(r.captured || r));
  };

  async function renderCollabComments(body) {
    const comments = (await apiFetch(`/documents/${currentDocId}/comments`)) || [];
    const roster = (await apiFetch(`/documents/${currentDocId}/reading-confirmations`).catch(() => [])) || [];
    body.innerHTML = `
      <textarea id="collab-notes" class="w-full border p-2 rounded mb-2" rows="5" placeholder="Live notes (broadcast to other editors)">${esc((currentDoc && currentDoc.notes) || "")}</textarea>
      <p class="text-xs text-gray-500 mb-2">Notes sync over WebSocket. Comments below are stored.</p>
      <ul class="mb-2">${comments.length ? comments.map((c) => `<li class="border-b py-1"><b>${esc(c.username)}</b>
        <span class="text-xs text-gray-400">${fmtDate(c.created_at)}</span>
        <button class="text-red-600 text-xs" onclick="deleteComment(${c.id})">delete</button>
        <div>${esc(c.text)}</div></li>`).join("") : '<li class="text-gray-400">No comments</li>'}</ul>
      <div class="flex gap-1"><input id="comment-text" class="flex-1 border p-1 rounded" placeholder="Add a comment" />
      <button onclick="addComment()" class="bg-blue-600 text-white px-2 rounded">Post</button></div>
      <h4 class="font-bold mt-3 text-xs">Reading roster</h4>
      <ul class="text-xs">${(roster || []).map((r) => `<li>user #${r.user_id} · ${fmtDate(r.confirmed_at)}</li>`).join("") || "<li>None</li>"}</ul>`;
    startCollabNotes("collab-notes");
  }
  window.deleteComment = async function (id) {
    await apiFetch(`/documents/${currentDocId}/comments/${id}`, { method: "DELETE" });
    inspTab("comments");
  };

  const EXTRA = new Set([
    "notify", "mailbox-tasks", "query-shares", "gdpr", "redaction-rules",
    "archivelink", "smtp-gateway", "csv-import", "scan", "classifier",
    "templates", "folder-templates", "reports", "groups", "intelligence", "compliance",
  ]);
  const _admin = typeof adminTab === "function" ? adminTab : null;
  adminTab = async function (tab) {
    document.querySelectorAll(".admin-item").forEach((b) => b.classList.toggle("active", b.dataset.admin === tab));
    if (tab === "tickets") {
      const rows = (await apiFetch("/tickets")) || [];
      $("admin-content").innerHTML = `<h3>Share links</h3>
        <table class="w-full text-sm"><thead><tr><th>Doc</th><th>Kind</th><th>Downloads</th><th>URL</th></tr></thead>
        <tbody>${rows.map((t) => `<tr><td>#${t.document_id}</td><td>${esc(t.kind)}</td><td>${t.download_count}/${t.max_downloads || "∞"}</td><td><a href="${t.url}" target="_blank">${esc((t.token || "").slice(0, 8))}…</a></td></tr>`).join("")}</tbody></table>`;
      injectAdminHelp(tab);
      return;
    }
    if (EXTRA.has(tab) || tab === "ocr" || tab === "ldap" || tab === "stores" || tab === "scheduled" || tab === "backup" || tab === "addons" || tab === "mail" || tab === "templates" || tab === "folder-templates" || tab === "protocols" || tab === "converters") {
      if (await renderCompleteAdmin(tab)) {
        injectAdminHelp(tab);
        return;
      }
    }
    if (_admin) await _admin(tab);
    injectAdminHelp(tab);
  };

  async function renderCompleteAdmin(tab) {
    const content = $("admin-content");
    if (tab === "ocr" || tab === "converters") {
      const [s, tools] = await Promise.all([apiFetch("/settings/ocr").catch(() => ({})), apiFetch("/converters").catch(() => [])]);
      const o = _parseObj(s && s.value, { lang: "eng", enabled: true });
      content.innerHTML = `<h3>OCR &amp; converters</h3>
        <p class="text-xs mb-2">JOEX runs these tools when a file is uploaded. Missing binaries are skipped, not errors.</p>
        <ul class="text-sm mb-3">${(tools || []).map((t) => `<li>${t.available ? "installed" : "not on PATH"} — ${esc(t.name)} <code class="text-xs">${esc(t.path || t.command || "")}</code></li>`).join("")}</ul>
        <label>OCR language (tesseract/ocrmypdf <code>-l</code>)</label>
        <input id="ocr-lang" class="w-full border p-1" value="${esc(o.lang || "eng")}" />
        <label class="block mt-2"><input type="checkbox" id="ocr-on" ${o.enabled !== false ? "checked" : ""} /> OCR images and scans during processing</label>
        <button class="tb primary mt-2" onclick="saveOcrForm()">Save OCR settings</button>`;
      return true;
    }
    if (tab === "protocols") {
      content.innerHTML = `<h3>WebDAV / CMIS / SOAP</h3>
        <p class="text-xs mb-2">Same repository as the UI. Authenticate with the user’s username/password (HTTP Basic) or the newton_token cookie.</p>
        <table class="w-full text-sm">
          <tr><td>WebDAV</td><td><code>${location.origin}/webdav/</code></td><td>Mount as a network drive. LOCK, MOVE, COPY, PUT, DELETE are implemented.</td></tr>
          <tr><td>CMIS browser</td><td><code>${location.origin}/cmis/browser</code></td><td>createDocument, createFolder, update, delete — not read-only.</td></tr>
          <tr><td>SOAP</td><td><code>${location.origin}/soap/document</code></td><td>createDocument (base64), download, checkout, checkin. Also /soap/folder, /soap/search, /soap/auth.</td></tr>
        </table>`;
      return true;
    }
    if (tab === "ldap") {
      const [ldap, saml] = await Promise.all([apiFetch("/settings/ldap").catch(() => ({})), apiFetch("/settings/saml").catch(() => ({}))]);
      const L = _parseObj(ldap && ldap.value, { url: "ldap://localhost", base_dn: "dc=example,dc=com", user_dn_pattern: "uid={username},{base}", group_base: "ou=groups,dc=example,dc=com", role_map: { admins: "admin" } });
      const S = _parseObj(saml && saml.value, { idp_sso_url: "", entity_id: "newtonedms", acs_url: "", idp_cert: "", require_signature: false });
      content.innerHTML = `<h3>LDAP</h3>
        <label>Server URL</label><input id="ldap-url" class="w-full border p-1" value="${esc(L.url || "")}" />
        <label>Base DN</label><input id="ldap-base" class="w-full border p-1" value="${esc(L.base_dn || "")}" />
        <label>User DN pattern</label><input id="ldap-pat" class="w-full border p-1" value="${esc(L.user_dn_pattern || "")}" />
        <label>Group base</label><input id="ldap-gbase" class="w-full border p-1" value="${esc(L.group_base || "")}" />
        <label>Role map JSON</label><input id="ldap-roles" class="w-full border p-1" value="${esc(JSON.stringify(L.role_map || {}))}" />
        <button class="tb primary mt-2" onclick="saveLdapForm()">Save LDAP</button>
        <button class="tb" onclick="testLdap()">Test bind</button>
        <h3 class="mt-4">SAML</h3>
        <label>IdP SSO URL</label><input id="saml-sso" class="w-full border p-1" value="${esc(S.idp_sso_url || "")}" />
        <label>Entity ID</label><input id="saml-ent" class="w-full border p-1" value="${esc(S.entity_id || "")}" />
        <label>ACS URL</label><input id="saml-acs" class="w-full border p-1" value="${esc(S.acs_url || "")}" />
        <label>IdP certificate (PEM)</label><textarea id="saml-cert" rows="5" class="w-full border">${esc(S.idp_cert || "")}</textarea>
        <label><input type="checkbox" id="saml-req" ${S.require_signature ? "checked" : ""} /> Require signed assertions</label>
        <button class="tb primary mt-2" onclick="saveSamlForm()">Save SAML</button>`;
      return true;
    }
    if (tab === "stores") {
      const rows = (await apiFetch("/stores")) || [];
      content.innerHTML = `<h3>Stores</h3>
        <div class="flex gap-2 mb-2"><input id="st-name" placeholder="Name" /><input id="st-path" placeholder="Path" class="flex-1" /><button class="tb primary" onclick="addStore()">Add filesystem</button></div>
        <h4 class="font-bold mt-3">Azure Blob wizard</h4>
        <div class="flex gap-2 flex-wrap mb-2">
          <input id="az-name" placeholder="Store name" value="Azure" />
          <input id="az-account" placeholder="Account" />
          <input id="az-container" placeholder="Container" />
          <input id="az-key" placeholder="Key or SAS" type="password" />
          <button class="tb primary" onclick="addAzureStore()">Create Azure store</button>
        </div>
        <ul>${rows.map((s) => `<li>${esc(s.name)} · ${esc(s.kind)} · ${esc(s.path || JSON.stringify(s.config || {}))} <button onclick="delStore(${s.id})">×</button></li>`).join("")}</ul>`;
      return true;
    }
    if (tab === "scheduled") {
      const rows = (await apiFetch("/tasks/scheduled")) || [];
      content.innerHTML = `<h3>Scheduled tasks</h3>
        <p class="text-xs mb-2">Only the cluster leader runs these (except heartbeat).</p>
        <table class="w-full text-sm"><thead><tr><th>Name</th><th>Every</th><th>Last</th><th></th></tr></thead>
        <tbody>${rows.map((t) => `<tr><td>${esc(t.name)}</td>
          <td><input id="sch-i-${t.id}" type="number" value="${t.interval_minutes}" class="w-16 border" /> m
            <label><input type="checkbox" id="sch-e-${t.id}" ${t.enabled ? "checked" : ""} /> on</label></td>
          <td>${esc(t.last_status || "")} ${esc(t.last_message || "")}</td>
          <td><button onclick="saveSched(${t.id})">Save</button> <button onclick="runSched(${t.id})">Run</button></td></tr>`).join("")}</tbody></table>`;
      return true;
    }
    if (tab === "backup") {
      const backups = (await apiFetch("/backup")) || [];
      content.innerHTML = `<h3>Backup</h3>
        <button onclick="runBackup()" class="px-3 py-1 bg-blue-600 text-white rounded mb-3">Create backup now</button>
        <ul>${backups.length ? backups.map((b) => `<li class="border-b p-2">${esc(b.file)} — ${formatBytes(b.size)}
          <button onclick="restoreBackup('${esc(b.file)}')">Restore files</button></li>`).join("") : '<li class="text-gray-400 p-2">No backups yet</li>'}</ul>`;
      return true;
    }
    if (tab === "addons") {
      const addons = (await apiFetch("/addons")) || [];
      content.innerHTML = `<h3>Addons</h3>
        <div class="flex gap-2 mb-3">
          <input id="ad-name" placeholder="Name" class="border p-2 rounded" />
          <input id="ad-url" placeholder="https://example/webhook" class="border p-2 rounded flex-1" />
          <button onclick="createAddon()" class="px-3 py-1 bg-blue-600 text-white rounded">Add webhook</button>
        </div>
        <p class="text-xs mb-2">Upload a zip package (descriptor + script) then run it on a document.</p>
        <input type="file" accept=".zip" onchange="uploadAddonZip(this)" />
        <ul>${addons.map((a) => `<li class="border-b p-2">${esc(a.name)} · ${esc(a.webhook_url || a.trigger || "")}
          <input id="ad-doc-${a.id}" type="number" placeholder="doc id" class="w-20 border" />
          <button onclick="runAddonNow(${a.id})">Run</button>
          <button class="text-red-600" onclick="delAddon(${a.id})">delete</button></li>`).join("") || '<li class="text-gray-400">None</li>'}</ul>`;
      return true;
    }
    if (tab === "mail") {
      const rows = (await apiFetch("/mail-settings")) || [];
      const gw = await apiFetch("/smtp-gateway").catch(() => ({}));
      content.innerHTML = `<h3>Outgoing mail</h3>
        <p class="text-xs mb-2">SMTP gateway: ${gw.enabled ? "enabled" : "disabled"} ${esc(gw.host || "")}:${gw.port || ""} ${gw.running ? "(running)" : ""}</p>
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
      return true;
    }
    if (tab === "notify") {
      const [ch, hooks, rules] = await Promise.all([
        apiFetch("/notify-channels").catch(() => []),
        apiFetch("/event-hooks").catch(() => []),
        apiFetch("/notify-rules").catch(() => apiFetch("/notification-rules").catch(() => [])),
      ]);
      content.innerHTML = `<h3>Notify channels</h3>
        <div class="flex gap-2 mb-2"><input id="nc-name" placeholder="Name" /><select id="nc-kind"><option>email</option><option>webhook</option><option>matrix</option></select>
          <input id="nc-cfg" placeholder='{"url":"https://..."}' class="flex-1" /><button class="tb primary" onclick="addNotifyCh()">Add</button></div>
        <ul>${(ch || []).map((c) => `<li>${esc(c.name)} · ${esc(c.kind)} <button onclick="apiFetch('/notify-channels/${c.id}',{method:'DELETE'}).then(()=>adminTab('notify'))">×</button></li>`).join("") || "<li>None</li>"}</ul>
        <h3 class="mt-3">Event hooks</h3>
        <div class="flex gap-2 mb-2"><input id="eh-event" placeholder="document_created" /><input id="eh-url" placeholder="https://..." class="flex-1" />
          <button class="tb" onclick="addEventHook()">Add</button></div>
        <ul>${(hooks || []).map((h) => `<li>${esc(h.event || h.name)} ${esc(h.url || h.webhook_url || "")}</li>`).join("") || "<li>None</li>"}</ul>
        <h3 class="mt-3">Notification rules</h3>
        <div class="flex gap-2 mb-2 flex-wrap">
          <input id="nr-name" placeholder="Name" /><input id="nr-q" placeholder="tag:invoice" class="flex-1" />
          <select id="nr-ch"><option value="inapp">in-app</option><option value="email">email</option></select>
          <button class="tb" onclick="addNotifyRule()">Add rule</button>
        </div>
        <ul>${(rules || []).map((r) => `<li>${esc(r.name)} · ${esc(r.query || r.event || "")}
          <button onclick="apiFetch('/notification-rules/${r.id}',{method:'DELETE'}).then(()=>adminTab('notify'))">×</button></li>`).join("") || "<li>None</li>"}</ul>`;
      return true;
    }
    if (tab === "mailbox-tasks") {
      const rows = (await apiFetch("/mailbox-tasks").catch(() => [])) || [];
      content.innerHTML = `<h3>Mailbox tasks</h3>
        <div class="flex gap-2 mb-2"><input id="mb-name" placeholder="Name" /><input id="mb-folder" type="number" placeholder="Folder id" />
          <button class="tb primary" onclick="addMailboxTask()">Add</button></div>
        <ul>${rows.map((r) => `<li>${esc(r.name || r.host || "#" + r.id)} <button onclick="apiFetch('/mailbox-tasks/${r.id}/run',{method:'POST'}).then(x=>toast(JSON.stringify(x)))">Run</button></li>`).join("") || "<li>None</li>"}</ul>`;
      return true;
    }
    if (tab === "query-shares") {
      const rows = (await apiFetch("/query-shares").catch(() => [])) || [];
      content.innerHTML = `<h3>Query shares</h3>
        <div class="flex gap-2 mb-2"><input id="qs-name" placeholder="Name" /><input id="qs-q" placeholder="tag:invoice" class="flex-1" />
          <button class="tb primary" onclick="addQueryShare()">Share query</button></div>
        <ul>${rows.map((r) => `<li>${esc(r.name)} · ${esc(r.query || "")}
          <code>${esc(r.url || "/s/" + (r.token || ""))}</code>
          <button onclick="copyShareUrl('${esc(r.url || "/s/" + (r.token || ""))}')">Copy URL</button>
          <button onclick="apiFetch('/query-shares/${r.id}/toggle',{method:'POST'}).then(()=>adminTab('query-shares'))">toggle</button></li>`).join("") || "<li>None</li>"}</ul>`;
      return true;
    }
    if (tab === "gdpr") {
      const users = (await apiFetch("/users")) || [];
      content.innerHTML = `<h3>GDPR export / erase</h3>
        <select id="gdpr-user">${users.map((u) => `<option value="${u.id}">${esc(u.username)}</option>`).join("")}</select>
        <button class="tb" onclick="gdprExport()">Export</button>
        <button class="tb" onclick="gdprErase()">Erase</button>
        <p class="text-xs mt-2">Export downloads a zip of the subject's documents and profile.</p>`;
      return true;
    }
    if (tab === "redaction-rules") {
      const rows = (await apiFetch("/redaction-rules")) || [];
      content.innerHTML = `<h3>Redaction rules</h3>
        <div class="flex gap-2 mb-2"><input id="rr-name" placeholder="Name" /><input id="rr-pat" placeholder="regex" class="flex-1" />
          <button class="tb primary" onclick="addRedactRule()">Add</button></div>
        <ul>${rows.map((r) => `<li>${esc(r.name)} · ${esc(JSON.stringify(r.patterns || []))}</li>`).join("") || "<li>None</li>"}</ul>`;
      return true;
    }
    if (tab === "archivelink") {
      content.innerHTML = `<h3>ArchiveLink → folder</h3>
        <p class="text-xs mb-2">Map SAP content repositories onto a NewtonEDMS folder.</p>
        <input id="al-rep" placeholder="ContRep" /><input id="al-folder" type="number" placeholder="Folder id" />
        <button class="tb primary" onclick="saveAlMap()">Save mapping</button>
        <pre class="text-xs mt-2">PUT/GET /archivelink/{contRep}/{docId}</pre>`;
      return true;
    }
    if (tab === "csv-import") {
      content.innerHTML = `<h3>CSV import</h3>
        <input id="csv-folder" type="number" placeholder="Folder id" value="${currentFolderId || ""}" />
        <input type="file" accept=".csv" onchange="importCsvFile(this)" />`;
      return true;
    }
    if (tab === "scan") {
      content.innerHTML = `<h3>In-app scanner</h3>
        <p class="text-xs mb-2">Ingests into the current folder (#${currentFolderId || "—"}) via <code>/api/scan/ingest</code>.</p>
        <input type="file" accept="image/*,.pdf" onchange="scanIngestFile(this)" />
        <button class="tb mt-2" onclick="openScanModal()">Camera capture</button>`;
      return true;
    }
    if (tab === "classifier") {
      const st = await apiFetch("/classifier/status").catch(() => ({}));
      content.innerHTML = `<h3>Classifier</h3>
        <pre class="text-xs mb-2">${esc(JSON.stringify(st, null, 2))}</pre>
        <button class="tb primary" onclick="apiFetch('/classifier/train',{method:'POST'}).then(x=>toast(JSON.stringify(x)))">Train now</button>
        <button class="tb" onclick="apiFetch('/idp/train',{method:'POST'}).then(x=>toast(JSON.stringify(x)))">Train IDP</button>`;
      return true;
    }
    if (tab === "templates") {
      const tpls = (await apiFetch("/metadata-templates")) || [];
      content.innerHTML = `<h3>Metadata templates</h3>
        <div class="flex gap-2 mb-2 flex-wrap">
          <input id="tpl-name" placeholder="Name" /><input id="tpl-desc" placeholder="Description" class="flex-1" />
          <button class="tb" onclick="tplAddField()">+ Field</button>
          <button class="tb primary" onclick="createTemplateBuilt()">Save</button>
        </div>
        <div id="tpl-fields" class="text-sm mb-2"></div>
        <table class="w-full text-sm"><tbody>${tpls.map((t) => `<tr class="border-b"><td class="p-2">${esc(t.name)}</td><td class="text-xs">${esc((t.fields || []).map((f) => f.key || f.name).join(", "))}</td>
          <td><button onclick="delTemplate(${t.id})" class="text-red-600">delete</button></td></tr>`).join("")}</tbody></table>`;
      window._tplFields = [];
      return true;
    }
    if (tab === "folder-templates") {
      const rows = (await apiFetch("/folder-templates")) || [];
      content.innerHTML = `<h3>Folder templates</h3>
        <input id="ft-name" placeholder="Template name" />
        <p class="text-xs">One folder name per line. Indent with two spaces for nesting.</p>
        <textarea id="ft-tree" rows="6" class="w-full border" placeholder="Inbox\n  Incoming\nArchive"></textarea>
        <button class="tb primary mt-2" onclick="addFolderTplBuilt()">Save</button>
        <ul>${rows.map((t) => `<li>${esc(t.name)} #${t.id}</li>`).join("") || "<li>None</li>"}</ul>`;
      return true;
    }
    if (tab === "reports") {
      const r = await apiFetch("/reports/summary");
      const facets = await apiFetch("/facets");
      content.innerHTML = `<h3>Reports</h3>
        <div class="grid grid-cols-4 gap-3 mb-4">
          ${[["Users", r.users], ["Groups", r.groups], ["Folders", r.folders], ["Documents", r.documents]].map(([k, v]) =>
            `<div class="bg-gray-50 border rounded p-3 text-center"><div class="text-2xl font-bold">${v}</div><div class="text-sm text-gray-500">${k}</div></div>`).join("")}
        </div>
        <p class="mb-2"><b>Storage:</b> ${formatBytes(r.total_size)} · <b>Downloads 30d:</b> ${r.recent_downloads} · <b>Overdue:</b> ${facets.overdue}</p>
        <h4 class="font-bold mt-3">Status</h4>${_bars(r.by_status || {})}
        <h4 class="font-bold mt-3">Types</h4>${_bars(facets.by_extension || {})}
        <h4 class="font-bold mt-3">Tags</h4>${_bars(facets.by_tag || {})}`;
      return true;
    }
    if (tab === "groups") {
      const [groups, users] = await Promise.all([apiFetch("/groups"), apiFetch("/users")]);
      const memberBlocks = [];
      for (const g of (groups || [])) {
        const mem = (await apiFetch(`/groups/${g.id}/users`).catch(() => [])) || [];
        memberBlocks.push(`<div class="border rounded p-2 mb-2"><div class="flex justify-between"><b>${esc(g.name)}</b>
          <span><button onclick="adminRenameGroup(${g.id}, '${esc(g.name)}')" class="text-blue-600 mr-2">rename</button>
          <button onclick="adminDeleteGroup(${g.id}, '${esc(g.name)}')" class="text-red-600">delete</button></span></div>
          <ul class="text-xs">${mem.map((u) => `<li>${esc(u.username)} <button onclick="adminRemoveMember(${g.id},${u.id})">remove</button></li>`).join("") || "<li>No members</li>"}</ul>
          <div class="flex gap-2 mt-2"><select id="gsel-${g.id}">${(users || []).map((u) => `<option value="${u.id}">${esc(u.username)}</option>`).join("")}</select>
          <button onclick="adminAddMember(${g.id})" class="text-blue-600 text-sm">Add member</button></div></div>`);
      }
      content.innerHTML = `<h3>Groups</h3>
        <div class="flex gap-2 mb-3"><input id="ng-name" placeholder="Name" /><input id="ng-desc" placeholder="Description" class="flex-1" />
          <button onclick="adminCreateGroup()" class="px-3 py-1 bg-blue-600 text-white rounded">Add</button></div>
        ${memberBlocks.join("")}`;
      return true;
    }
    if (tab === "intelligence") {
      const [tags, fields, st] = await Promise.all([apiFetch("/tags"), apiFetch("/custom-fields"), apiFetch("/classifier/status").catch(() => ({}))]);
      content.innerHTML = `<h3>Tag catalog & custom fields</h3>
        <div class="flex gap-2 mb-2"><input id="tg-name" placeholder="Tag" /><button onclick="createTag()" class="px-3 py-1 bg-blue-600 text-white rounded">Add tag</button></div>
        <p class="mb-3">${(tags || []).map((t) => `<span class="tag-chip">${esc(t.name)} <button onclick="delTag(${t.id})">×</button></span>`).join("")}</p>
        <div class="flex gap-2 mb-2"><input id="cf-name" placeholder="Field name" />
          <select id="cf-type"><option>text</option><option>number</option><option>date</option><option>bool</option></select>
          <button onclick="createField()" class="px-3 py-1 bg-blue-600 text-white rounded">Add field</button></div>
        <p>${(fields || []).map((f) => `${esc(f.name)} (${esc(f.ftype)}) <button class="text-red-600" onclick="delField(${f.id})">×</button>`).join(" · ")}</p>
        <h4 class="font-bold mt-4">Classifier / IDP</h4>
        <pre class="text-xs">${esc(JSON.stringify(st, null, 2))}</pre>
        <button class="tb primary" onclick="apiFetch('/classifier/train',{method:'POST'}).then(x=>toast(JSON.stringify(x)))">Train classifier</button>
        <button class="tb" onclick="apiFetch('/idp/train',{method:'POST'}).then(x=>toast(JSON.stringify(x)))">Train IDP</button>`;
      return true;
    }
    if (tab === "compliance") {
      const c = await apiFetch("/compliance");
      const EVIDENCE = {
        lawful_access_control: "security-policy",
        audit_logging: "audit",
        retention_policies: "retention",
        subject_export: "gdpr",
        erasure_with_hold_guard: "holds",
        encryption_in_transit: "security-policy",
        unique_user_ids: "users",
        emergency_access_roles: "users",
        audit_controls: "audit",
        integrity_hashing: "index",
        person_authentication_2fa: "users",
        transmission_security: "security-policy",
        A_5_policies: "security-policy",
        "A.5_policies": "security-policy",
        "A.8_asset_inventory": "stores",
        "A.8_access_control": "security-policy",
        "A.8_logging": "audit",
        "A.8_backup": "backup",
        "A.8_secure_development": "security-policy",
        ip_restriction: "security-policy",
        password_expiry: "security-policy",
      };
      const block = (name, pack) => `<div class="border rounded p-3"><h4 class="font-bold">${esc(name)}</h4>
        <p>${pack.passed}/${pack.total} controls</p>
        <ul class="text-xs">${Object.entries(pack.controls || {}).map(([k, v]) => {
          const dest = EVIDENCE[k];
          const link = dest ? `<a href="#" onclick="adminTab('${dest}');return false">${esc(k)}</a>` : esc(k);
          return `<li>${v ? "✓" : "✗"} ${link}</li>`;
        }).join("")}</ul></div>`;
      content.innerHTML = `<h3>GDPR / HIPAA / ISO 27001</h3>
        <div class="grid grid-cols-3 gap-3">${block("GDPR", c.gdpr)}${block("HIPAA", c.hipaa)}${block("ISO 27001", c.iso27001)}</div>`;
      return true;
    }
    return false;
  }

  window.saveSched = async function (id) {
    await apiFetch(`/tasks/scheduled/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: $("sch-e-" + id).checked, interval_minutes: parseInt($("sch-i-" + id).value, 10) }) });
    toast("Task saved");
  };
  window.restoreBackup = async function (file) {
    if (!confirm("Restore files from " + file + "?")) return;
    const r = await apiFetch("/backup/restore?file=" + encodeURIComponent(file), { method: "POST" });
    toast("Restored " + (r.files || 0) + " files");
  };
  window.addAzureStore = async function () {
    const cfg = { account: val("az-account"), container: val("az-container"), key: val("az-key") };
    await apiFetch("/stores", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("az-name") || "Azure", kind: "azure", path: "azure:" + cfg.container, config: cfg }) });
    await apiFetch("/connectors", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("az-name") || "Azure", kind: "azure", config: cfg }) });
    toast("Azure store created");
    adminTab("stores");
  };
  window.uploadAddonZip = async function (input) {
    const file = input.files[0];
    input.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", file.name);
    await apiFetch("/addons/package", { method: "POST", body: fd });
    toast("Addon package installed");
    adminTab("addons");
  };
  window.runAddonNow = async function (id) {
    const doc = parseInt(val("ad-doc-" + id), 10);
    await apiFetch(`/addons/${id}/run?document_id=${doc}`, { method: "POST" });
    toast("Addon queued");
  };
  window.addNotifyCh = async function () {
    await apiFetch("/notify-channels", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("nc-name"), kind: val("nc-kind"), config: JSON.parse(val("nc-cfg") || "{}") }) });
    adminTab("notify");
  };
  window.addEventHook = async function () {
    await apiFetch("/event-hooks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ event: val("eh-event"), url: val("eh-url") }) });
    adminTab("notify");
  };
  window.addMailboxTask = async function () {
    await apiFetch("/mailbox-tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("mb-name"), folder_id: parseInt(val("mb-folder"), 10) }) });
    adminTab("mailbox-tasks");
  };
  window.addQueryShare = async function () {
    await apiFetch("/query-shares", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("qs-name"), query: val("qs-q") }) });
    adminTab("query-shares");
  };
  window.gdprExport = async function () {
    const id = val("gdpr-user");
    window.open("/api/compliance/gdpr/" + id, "_blank");
  };
  window.gdprErase = async function () {
    if (!confirm("Erase this user?")) return;
    try {
      await apiFetch("/compliance/gdpr/" + val("gdpr-user") + "/erase", { method: "POST" });
      toast("Erased");
    } catch (e) {
      toast(String(e.message || e), "err");
    }
  };
  window.addRedactRule = async function () {
    await apiFetch("/redaction-rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("rr-name"), patterns: [val("rr-pat")] }) });
    adminTab("redaction-rules");
  };
  window.saveAlMap = async function () {
    await apiFetch("/settings/archivelink", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: JSON.stringify({ [val("al-rep")]: parseInt(val("al-folder"), 10) }) }) });
    toast("Mapping saved");
  };
  window.importCsvFile = async function (input) {
    const file = input.files[0];
    input.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("folder_id", val("csv-folder") || currentFolderId);
    const r = await apiFetch("/import/csv", { method: "POST", body: fd });
    toast("Imported " + (r.created || r.count || 0));
  };
  window.scanIngestFile = async function (input) {
    const file = input.files[0];
    input.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("folder_id", currentFolderId);
    await apiFetch("/scan/ingest", { method: "POST", body: fd });
    toast("Scanned");
    refreshCurrentList();
  };

  window.saveOcrForm = async function () {
    const obj = { lang: val("ocr-lang") || "eng", enabled: !!($("ocr-on") && $("ocr-on").checked) };
    await apiFetch("/settings/ocr", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: JSON.stringify(obj) }) });
    toast("OCR settings saved — they apply to the next JOEX job");
  };

  renderSettings = async function () {
    const quota = await apiFetch("/quota").catch(() => ({ used: 0, limit: 0 }));
    const keys = (await apiFetch("/apikeys").catch(() => [])) || [];
    const logins = (await apiFetch("/logins").catch(() => [])) || [];
    const devices = (await apiFetch("/devices").catch(() => [])) || [];
    const hours = (currentUser && currentUser.working_hours) || {};
    let coll = {};
    try { coll = await apiFetch("/collectives/current") || {}; } catch (e) { coll = {}; }
    const loc = (currentUser && currentUser.locale) || (uiSettings && uiSettings.locale) || "en";
    const den = (currentUser && currentUser.density) || "standard";
    const days = String(hours.days || "Mon-Fri");
    $("work-settings").innerHTML = `
      <h2>Settings</h2>
      <p class="set-lead">These controls change <b>your</b> account. Repository-wide tools (OCR, LDAP, stores, workflows) are under Administration.</p>
      <div class="set-grid">
        <section class="set-card">
          <h3>Account</h3>
          <p class="hint">Stored on your user record. Email is used for SMTP notifications when a channel is configured.</p>
          <label>Username</label><input value="${esc(currentUser.username || "")}" disabled />
          <label>Email</label><input id="set-email" value="${esc(currentUser.email || "")}" />
          <label>Avatar URL</label><input id="set-av" value="${esc(currentUser.avatar || "")}" />
          <button class="tb primary mt-2" onclick="saveAccountProfile()">Save account</button>
        </section>
        <section class="set-card">
          <h3>Password</h3>
          <p class="hint">Must include a letter and a digit. Current password is required.</p>
          <label>Current</label><input id="set-curpw" type="password" />
          <label>New</label><input id="set-newpw" type="password" />
          <button class="tb mt-2" onclick="changePassword()">Change password</button>
        </section>
        <section class="set-card">
          <h3>Appearance</h3>
          <p class="hint">Language loads <code>/api/i18n/{locale}</code> for chrome strings. Density and theme apply immediately.</p>
          <p><button class="tb" onclick="toggleTheme()">Toggle light / dark</button></p>
          <label>Interface language</label>
          <select id="set-locale">
            <option value="en" ${loc === "en" ? "selected" : ""}>English</option>
            <option value="de" ${loc === "de" ? "selected" : ""}>Deutsch</option>
            <option value="fr" ${loc === "fr" ? "selected" : ""}>Français</option>
            <option value="es" ${loc === "es" ? "selected" : ""}>Español</option>
          </select>
          <label>Density</label>
          <select id="set-den">
            <option value="compact" ${den === "compact" ? "selected" : ""}>compact</option>
            <option value="standard" ${den === "standard" ? "selected" : ""}>standard</option>
            <option value="comfortable" ${den === "comfortable" ? "selected" : ""}>comfortable</option>
          </select>
          <label><input type="checkbox" id="ui-power" ${uiSettings.powerSearch !== false ? "checked" : ""}/> Power search (tag include/exclude on the Search tab)</label>
          <label>Document list</label>
          <select id="ui-cards">
            <option value="cards" ${uiSettings.cardLayout === "cards" ? "selected" : ""}>Cards</option>
            <option value="list" ${uiSettings.cardLayout === "list" ? "selected" : ""}>List</option>
          </select>
          <label>Tags shown on a card</label>
          <input id="ui-tags" type="number" min="0" value="${uiSettings.tagCount || 8}" />
          <button class="tb primary mt-2" onclick="saveAppearance()">Save appearance</button>
        </section>
        <section class="set-card">
          <h3>Two-factor authentication</h3>
          <p class="hint">TOTP (authenticator app). Required at login after enable. Trusted devices skip the prompt on this browser.</p>
          <p>Status: <b>${currentUser.totp_enabled ? "enabled" : "disabled"}</b></p>
          <div id="totp-box"></div>
          ${currentUser.totp_enabled
            ? `<input id="totp-off" placeholder="Authenticator code" />
               <button class="tb" onclick="disableTotp()">Disable 2FA</button>`
            : `<button class="tb primary" onclick="setupTotp()">Set up 2FA</button>`}
        </section>
        <section class="set-card">
          <h3>Storage quota</h3>
          <p class="hint">Sum of your document file sizes. Admins set the cap on Users &amp; roles (quota). 0 means unlimited.</p>
          <p><b>${formatBytes(quota.used)}</b> used of <b>${quota.limit ? formatBytes(quota.limit) : "unlimited"}</b></p>
        </section>
        <section class="set-card">
          <h3>Working hours</h3>
          <p class="hint">Stored on your profile for calendar/overdue displays. It does not lock the server.</p>
          <label>Start</label><input id="wh-start" type="time" value="${esc(hours.start || "09:00")}" />
          <label>End</label><input id="wh-end" type="time" value="${esc(hours.end || "17:00")}" />
          <label>Days</label>
          <select id="wh-days">
            <option ${days === "Mon-Fri" ? "selected" : ""}>Mon-Fri</option>
            <option ${days === "Mon-Sun" ? "selected" : ""}>Mon-Sun</option>
            <option ${days === "Sat-Sun" ? "selected" : ""}>Sat-Sun</option>
          </select>
          <button class="tb mt-2" onclick="saveWorkingHoursForm()">Save hours</button>
        </section>
        <section class="set-card">
          <h3>API keys</h3>
          <p class="hint">Bearer token for /api. The secret is shown once. Same permissions as your user.</p>
          <div class="flex gap-1 mb-2"><input id="ak-name" placeholder="Key name" /><button class="tb primary" onclick="createApiKey()">Create</button></div>
          <ul>${keys.map((k) => `<li>${esc(k.name)} · ${esc(k.prefix)}… <button onclick="delApiKey(${k.id})">revoke</button></li>`).join("") || "<li>None</li>"}</ul>
        </section>
        <section class="set-card">
          <h3>This browser &amp; logins</h3>
          <p class="hint">Trust this browser so 2FA is not asked every time. Last logins is your authentication history.</p>
          <div class="flex gap-1 mb-2"><input id="dv-name" placeholder="This computer" /><button class="tb" onclick="trustDevice()">Trust this browser</button></div>
          <ul>${devices.map((d) => `<li>${esc(d.name || d.user_agent || "")} <button onclick="delDevice(${d.id})">forget</button></li>`).join("") || "<li>No trusted devices</li>"}</ul>
          <h4>Last logins</h4>
          <ul>${logins.slice(0, 8).map((l) => `<li>${l.success ? "ok" : "fail"} ${esc(l.ip || "")} ${fmtDate(l.created_at)}</li>`).join("") || "<li>None</li>"}</ul>
        </section>
        <section class="set-card">
          <h3>Collective (workspace)</h3>
          <p class="hint">A collective is the tenancy boundary. Folders and documents you create are stamped with it; other collectives cannot open them by id.</p>
          <p>Current: <b>${esc(coll.name || "—")}</b></p>
          <label>Switch to a collective you belong to</label>
          <select id="coll-switch"></select>
          <button class="tb" onclick="switchCollective()">Switch</button>
          <p>Invite code: <code>${esc(coll.invite_code || "")}</code> <button class="tb" onclick="rotateInvite()">Rotate</button></p>
          <label>Join with an invite code</label>
          <input id="invite-join" placeholder="Invite code" />
          <button class="tb" onclick="joinCollective()">Join</button>
        </section>
        <section class="set-card">
          <h3>Organizations</h3>
          <p class="hint">Correspondent companies on the document Properties tab and in power search (<code>corr.org:</code>).</p>
          <div id="org-list"></div>
          <input id="org-name" placeholder="Name" />
          <input id="org-emails" placeholder="Emails (comma)" />
          <button class="tb mt-1" onclick="addOrg()">Add</button>
        </section>
        <section class="set-card">
          <h3>Equipment</h3>
          <p class="hint">Optional asset catalog linked from Properties. Not a CMDB.</p>
          <div id="eq-list"></div>
          <input id="eq-name" placeholder="Name" />
          <button class="tb mt-1" onclick="addEq()">Add</button>
        </section>
      </div>`;
    if (typeof fillCatalogs === "function") fillCatalogs();
    try {
      const colls = await apiFetch("/collectives") || [];
      if ($("coll-switch")) {
        $("coll-switch").innerHTML = colls.map((c) => `<option value="${c.id}" ${c.id === coll.id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
      }
    } catch (e) { /* */ }
  };

  window.saveAccountProfile = async function () {
    await apiFetch("/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: val("set-email"), locale: val("set-locale"), density: val("set-den"), avatar: val("set-av") }) });
    currentUser.email = val("set-email");
    currentUser.locale = val("set-locale");
    currentUser.density = val("set-den");
    currentUser.avatar = val("set-av");
    document.documentElement.dataset.density = val("set-den");
    toast("Account saved");
  };
  window.saveAppearance = async function () {
    await saveAccountProfile();
    uiSettings.powerSearch = $("ui-power") ? $("ui-power").checked : true;
    uiSettings.cardLayout = val("ui-cards") || "cards";
    uiSettings.tagCount = parseInt(val("ui-tags"), 10) || 8;
    uiSettings.locale = val("set-locale") || "en";
    await apiFetch("/ui-settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(uiSettings) });
    if (typeof loadIntel === "function") await loadIntel();
    toast("Appearance saved");
  };
  window.saveWorkingHoursForm = async function () {
    await apiFetch("/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ working_hours: { start: val("wh-start"), end: val("wh-end"), days: val("wh-days") } }) });
    currentUser.working_hours = { start: val("wh-start"), end: val("wh-end"), days: val("wh-days") };
    toast("Working hours saved");
  };
  window.changePassword = async function () {
    try {
      await apiFetch("/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: val("set-curpw"), password: val("set-newpw") }) });
      toast("Password changed");
      $("set-curpw").value = "";
      $("set-newpw").value = "";
    } catch (e) { toast(String(e.message || e), "err"); }
  };
  window.saveLdapForm = async function () {
    let roleMap = {};
    try { roleMap = JSON.parse(val("ldap-roles") || "{}"); } catch (e) { roleMap = {}; }
    const obj = { url: val("ldap-url"), base_dn: val("ldap-base"), user_dn_pattern: val("ldap-pat"), group_base: val("ldap-gbase"), role_map: roleMap };
    await apiFetch("/settings/ldap", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: JSON.stringify(obj) }) });
    toast("LDAP saved");
  };
  window.saveSamlForm = async function () {
    const obj = { idp_sso_url: val("saml-sso"), entity_id: val("saml-ent"), acs_url: val("saml-acs"), idp_cert: val("saml-cert"), require_signature: !!($("saml-req") && $("saml-req").checked) };
    await apiFetch("/settings/saml", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: JSON.stringify(obj) }) });
    toast("SAML saved");
  };
  window.addNotifyRule = async function () {
    await apiFetch("/notification-rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("nr-name"), query: val("nr-q"), channel: val("nr-ch") || "inapp" }) });
    adminTab("notify");
  };
  window.copyShareUrl = function (path) {
    const url = (path || "").indexOf("http") === 0 ? path : (location.origin + path);
    if (navigator.clipboard) navigator.clipboard.writeText(url);
    toast("Copied " + url);
  };
  window.adminRemoveMember = async function (gid, uid) {
    await apiFetch(`/groups/${gid}/users/${uid}`, { method: "DELETE" });
    adminTab("groups");
  };
  window.tplAddField = function () {
    const key = prompt("Field key", "customer");
    if (!key) return;
    const type = prompt("Type (text/number/date)", "text") || "text";
    const def = prompt("Default", "") || "";
    window._tplFields = window._tplFields || [];
    window._tplFields.push({ key, type, default: def });
    const el = $("tpl-fields");
    if (el) el.innerHTML = window._tplFields.map((f) => `${esc(f.key)} (${esc(f.type)})`).join(" · ");
  };
  window.createTemplateBuilt = async function () {
    await apiFetch("/metadata-templates", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("tpl-name"), description: val("tpl-desc"), fields: window._tplFields || [] }) });
    window._tplFields = [];
    adminTab("templates");
  };
  window.addFolderTplBuilt = async function () {
    const lines = (val("ft-tree") || "").split(/\r?\n/).filter((l) => l.trim());
    const roots = [];
    const stack = [{ depth: -1, children: roots }];
    lines.forEach((line) => {
      const depth = (line.match(/^ */)[0].length) / 2;
      const node = { name: line.trim(), children: [] };
      while (stack.length && stack[stack.length - 1].depth >= depth) stack.pop();
      stack[stack.length - 1].children.push(node);
      stack.push({ depth, children: node.children });
    });
    await apiFetch("/folder-templates", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: val("ft-name"), tree: roots }) });
    adminTab("folder-templates");
  };

  window.ooOpen = async function () {
    if (!currentDocId) { toast("Open a document first"); return; }
    const r = await apiFetch(`/connectors/onlyoffice/${currentDocId}`);
    const server = r.documentServerUrl;
    if (!server) {
      toast("Configure an OnlyOffice connector URL first");
      const out = $("cn-out");
      if (out) out.textContent = JSON.stringify(r, null, 2);
      return;
    }
    let host = $("oo-overlay");
    if (!host) {
      host = document.createElement("div");
      host.id = "oo-overlay";
      host.innerHTML = `<div class="oo-frame"><button class="tb" onclick="$('oo-overlay').classList.add('is-hidden')">Close</button><div id="oo-placeholder"></div></div>`;
      document.body.appendChild(host);
    }
    host.classList.remove("is-hidden");
    const src = server.replace(/\/$/, "") + "/web-apps/apps/api/documents/api.js";
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => {
      try {
        new window.DocsAPI.DocEditor("oo-placeholder", r);
      } catch (e) { toast(e.message); }
    };
    document.body.appendChild(s);
  };
  window.gdImport = async function () {
    const files = (await apiFetch("/connectors/gdrive/files").catch(() => [])) || [];
    const out = $("cn-out");
    if (!files.length) {
      toast("No Drive files (set access_token on a gdrive connector)");
      if (out) out.textContent = "[]";
      return;
    }
    if (out) {
      out.innerHTML = files.map((f) => `<div><button class="tb" onclick="gdImportId('${esc(f.id)}')">${esc(f.name)}</button> <span class="text-xs">${esc(f.mimeType || "")}</span></div>`).join("");
    }
  };
  window.gdImportId = async function (fileId) {
    const fd = new FormData();
    fd.append("file_id", fileId);
    fd.append("folder_id", currentFolderId);
    const r = await apiFetch("/connectors/gdrive/import", { method: "POST", body: fd });
    toast("Imported #" + (r.id || ""));
  };
  window.olMail = async function () {
    const rows = (await apiFetch("/connectors/outlook/mail").catch(() => [])) || [];
    const out = $("cn-out");
    if (out) {
      out.innerHTML = (Array.isArray(rows) ? rows : (rows.value || [])).map((m) => {
        const id = m.id || m.message_id;
        const subj = m.subject || (m.subject && m.subject) || id;
        return `<div>${esc(subj)} <button onclick="olImport('${esc(id)}')">Import</button></div>`;
      }).join("") || JSON.stringify(rows, null, 2);
    }
  };
  window.olImport = async function (messageId) {
    const fd = new FormData();
    fd.append("message_id", messageId);
    fd.append("folder_id", currentFolderId);
    const r = await apiFetch("/connectors/outlook/import", { method: "POST", body: fd });
    toast("Imported " + JSON.stringify(r.imported || r));
  };
  window.runRag = async function () {
    const r = await apiFetch("/rag", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: val("rag-q") }) });
    const chat = $("rag-chat");
    if (chat) {
      const cites = (r.hits || []).map((h) => `<button class="text-blue-600" onclick="openDoc(${h.document_id})">#${h.document_id}</button>`).join(" ");
      chat.insertAdjacentHTML("beforeend", `<div class="border rounded p-2"><b>Q:</b> ${esc(val("rag-q"))}<br><b>A (${esc(r.backend || "hashing")}):</b> ${esc(r.answer || "")}<div class="text-xs mt-1">Sources: ${cites || "none"}</div></div>`);
    }
    if ($("rag-out")) $("rag-out").innerHTML = (r.hits || []).map((h) => `<div class="border-b py-1"><button class="text-blue-600" onclick="openDoc(${h.document_id})">#${h.document_id}</button> (${h.score}) ${esc((h.text || "").slice(0, 180))}</div>`).join("");
  };

  const _pdf = typeof renderPdfOps === "function" ? renderPdfOps : null;
  if (_pdf) {
    renderPdfOps = async function (body) {
      await _pdf(body);
      const rules = (await apiFetch("/redaction-rules").catch(() => [])) || [];
      if (!body) return;
      const extra = document.createElement("div");
      extra.innerHTML = `<select id="rd-rule" class="w-full border p-1 rounded mb-1"><option value="">Redaction rule…</option>${rules.map((r) => `<option value="${r.id}">${esc(r.name)}</option>`).join("")}</select>
        <button class="tb w-full mb-2" onclick="doRedactRule()">Redact with rule</button>
        <button class="tb w-full" onclick="verifyCurrentSig()">Verify signature</button>`;
      body.appendChild(extra);
    };
  }
  window.doRedactRule = async function () {
    const rid = val("rd-rule");
    await apiFetch(`/documents/${currentDocId}/redact`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rule_id: rid ? parseInt(rid, 10) : null, patterns: [val("rd-pat") || ""] }) });
    toast("Redacted");
  };
  window.verifyCurrentSig = async function () {
    const r = await apiFetch(`/documents/${currentDocId}/sign/verify`);
    toast(r.embedded ? "Embedded signature present" : (r.ok ? "Signature ok" : "No valid signature"));
  };

  const _cal = typeof renderCalendar === "function" ? renderCalendar : null;
  renderCalendar = async function () {
    if (_cal) await _cal();
    const el = $("work-calendar");
    if (el && !$("gcal-sync-btn")) {
      el.insertAdjacentHTML("afterbegin", `<button id="gcal-sync-btn" class="tb mb-2" onclick="gcalSync().then(()=>toast('Google Calendar synced'))">Sync Google Calendar</button>`);
    }
  };
  const _ct = typeof renderContacts === "function" ? renderContacts : null;
  renderContacts = async function () {
    if (_ct) await _ct();
    document.querySelectorAll("#work-contacts tbody tr").forEach((tr, i) => {
      const c = (typeof contacts !== "undefined" && contacts[i]) ? contacts[i] : null;
      if (!c) return;
      const td = tr.querySelector("td:last-child");
      if (td && !td.querySelector(".ct-edit")) {
        const b = document.createElement("button");
        b.className = "ct-edit text-blue-600 mr-2";
        b.textContent = "edit";
        b.onclick = () => editContact(c.id, c.name, c.organization || "", c.email || "");
        td.insertBefore(b, td.firstChild);
      }
    });
  };
  window.editContact = async function (id, name, org, email) {
    const n = prompt("Name", name); if (n == null) return;
    const o = prompt("Organization", org);
    const e = prompt("Email", email);
    await apiFetch(`/contacts/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: n, organization: o, email: e, kind: "both" }) });
    renderContacts();
  };

  window.openScanModal = function () {
    openModal("scan-modal");
    const folder = $("scan-folder");
    if (folder) folder.value = currentFolderId || "";
  };
  window.scanCapture = async function () {
    const video = $("scan-cam");
    const canvas = $("scan-shot");
    if (!video || !canvas) return;
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    canvas.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.92));
    const fd = new FormData();
    fd.append("folder_id", val("scan-folder") || currentFolderId);
    fd.append("title", val("scan-title") || "scan");
    fd.append("file", blob, "scan.jpg");
    await apiFetch("/scan/ingest", { method: "POST", body: fd });
    toast("Scanned");
    closeModal("scan-modal");
    refreshCurrentList();
  };
  window.startScanCam = async function () {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    $("scan-cam").srcObject = stream;
  };

  const _holdsList = typeof renderEntTab === "function" ? null : null;
  document.addEventListener("DOMContentLoaded", () => {
    const menu = document.querySelector("#insp-act-drop .drop-menu");
    if (menu && !$("insp-oo")) {
      const b = document.createElement("button");
      b.id = "insp-oo";
      b.textContent = "OnlyOffice";
      b.onclick = () => { closeDrops(); window.ooOpen(); };
      menu.appendChild(b);
    }
    hideDeadSso();
  });
})();
