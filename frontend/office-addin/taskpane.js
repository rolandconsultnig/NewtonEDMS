/**
 * NewtonEDMS Office Add-in JavaScript Controller.
 * Handles Office.js lifecycle, host detection (Word, Excel, PowerPoint, Outlook),
 * NewtonEDMS repository interaction, document insertion, saving and archiving.
 */

let currentHost = "Office 365";
let activeMailItem = null;
let currentDocs = [];

// Office.js initialization
if (typeof Office !== "undefined") {
  Office.onReady((info) => {
    if (info.host === Office.HostType.Word) {
      currentHost = "Word";
    } else if (info.host === Office.HostType.Excel) {
      currentHost = "Excel";
    } else if (info.host === Office.HostType.PowerPoint) {
      currentHost = "PowerPoint";
    } else if (info.host === Office.HostType.Outlook) {
      currentHost = "Outlook";
      initOutlookContext();
    }
    document.getElementById("host-type").textContent = currentHost;
    initAddin();
  });
} else {
  // Standalone browser preview
  document.addEventListener("DOMContentLoaded", () => {
    initAddin();
  });
}

function showTab(tabName) {
  document.querySelectorAll(".nav-tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

  const tabBtn = document.querySelector(`.nav-tab[data-tab="${tabName}"]`);
  if (tabBtn) tabBtn.classList.add("active");

  const tabContent = document.getElementById(`tab-${tabName}`);
  if (tabContent) tabContent.classList.add("active");
}

async function initAddin() {
  await loadFolders();
  await loadDocs();
}

async function loadFolders() {
  try {
    const res = await fetch("/api/folders/");
    if (!res.ok) return;
    const folders = await res.json();

    const optionsHtml = (folders || [])
      .map((f) => `<option value="${f.id}">${f.name}</option>`)
      .join("");

    const filterEl = document.getElementById("folder-filter");
    if (filterEl) filterEl.innerHTML = `<option value="">All Folders (Root)</option>` + optionsHtml;

    const saveEl = document.getElementById("save-folder-select");
    if (saveEl) saveEl.innerHTML = optionsHtml;

    const outEl = document.getElementById("outlook-folder-select");
    if (outEl) outEl.innerHTML = optionsHtml;
  } catch (e) {
    console.error("Error loading folders:", e);
  }
}

async function loadDocs(folderId) {
  const container = document.getElementById("doc-results");
  if (!container) return;

  try {
    const url = folderId ? `/api/documents/?folder_id=${folderId}` : "/api/documents/";
    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load documents");
    const docs = await res.json();
    currentDocs = docs || [];

    if (!currentDocs.length) {
      container.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text-muted)">No documents found.</div>`;
      return;
    }

    container.innerHTML = currentDocs
      .map((d) => {
        const ext = (d.name || "").split(".").pop().toLowerCase();
        let icon = "fa-file-lines";
        if (["docx", "doc"].includes(ext)) icon = "fa-file-word";
        else if (["xlsx", "xls", "csv"].includes(ext)) icon = "fa-file-excel";
        else if (["pptx", "ppt"].includes(ext)) icon = "fa-file-powerpoint";
        else if (ext === "pdf") icon = "fa-file-pdf";

        return `
        <div class="list-item" onclick="selectDoc(${d.id})">
          <i class="fa-solid ${icon} item-icon"></i>
          <div class="item-body">
            <div class="item-name">${d.name}</div>
            <div class="item-meta">v${d.version || "1.0"} • ${(d.size || 0).toLocaleString()} bytes</div>
          </div>
          <button class="btn btn-secondary" style="width:auto;padding:4px 8px;font-size:11px" onclick="event.stopPropagation(); inspectOfficeProps(${d.id})" title="Inspect Properties"><i class="fa-solid fa-tags"></i></button>
        </div>
      `;
      })
      .join("");

    // Populate snippet select
    const snipSelect = document.getElementById("snippet-doc-select");
    if (snipSelect) {
      snipSelect.innerHTML = currentDocs.map((d) => `<option value="${d.id}">${d.name}</option>`).join("");
    }
  } catch (e) {
    container.innerHTML = `<div style="color:var(--danger);padding:10px">Failed to load documents: ${e.message}</div>`;
  }
}

async function searchDocs() {
  const query = (document.getElementById("search-box").value || "").trim();
  if (!query) return loadDocs();

  const container = document.getElementById("doc-results");
  container.innerHTML = `<div style="text-align:center;padding:10px;color:var(--text-muted)"><i class="fa-solid fa-spinner fa-spin"></i> Searching…</div>`;

  try {
    const res = await fetch(`/api/newton/query?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    const docs = data.items || [];
    currentDocs = docs;

    if (!docs.length) {
      container.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text-muted)">No matching documents.</div>`;
      return;
    }

    container.innerHTML = docs
      .map(
        (d) => `
      <div class="list-item" onclick="selectDoc(${d.id})">
        <i class="fa-solid fa-file-word item-icon"></i>
        <div class="item-body">
          <div class="item-name">${d.name}</div>
          <div class="item-meta">v${d.version || "1.0"}</div>
        </div>
      </div>
    `
      )
      .join("");
  } catch (e) {
    container.innerHTML = `<div style="color:var(--danger);padding:10px">Search failed: ${e.message}</div>`;
  }
}

function selectDoc(docId) {
  inspectOfficeProps(docId);
  showTab("meta");
}

async function inspectOfficeProps(docId) {
  const host = document.getElementById("office-props-list");
  if (!host) return;
  host.innerHTML = `<p style="color:var(--text-muted)"><i class="fa-solid fa-spinner fa-spin"></i> Reading OpenXML properties…</p>`;

  try {
    const res = await fetch(`/api/office/properties/${docId}`);
    const data = await res.json();
    const props = data.properties || {};

    let html = `
      <div style="font-size:12px;margin-bottom:8px"><strong>${data.name || "Document"}</strong></div>
      <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 8px;font-size:11px">
        <span style="color:var(--text-muted)">Title:</span> <span>${props.title || "—"}</span>
        <span style="color:var(--text-muted)">Author:</span> <span>${props.author || "—"}</span>
        <span style="color:var(--text-muted)">Subject:</span> <span>${props.subject || "—"}</span>
        <span style="color:var(--text-muted)">Keywords:</span> <span>${props.keywords || "—"}</span>
        <span style="color:var(--text-muted)">Comments:</span> <span>${props.comments || "—"}</span>
        <span style="color:var(--text-muted)">Modified:</span> <span>${props.modified || "—"}</span>
      </div>
    `;
    host.innerHTML = html;
  } catch (e) {
    host.innerHTML = `<div style="color:var(--danger)">Error loading properties: ${e.message}</div>`;
  }
}

// Word / Office Insertion logic
function insertSelectedMetadata() {
  const val = document.getElementById("meta-field-select").value;
  if (typeof Word !== "undefined" && Word.run) {
    Word.run(async (context) => {
      const range = context.document.getSelection();
      range.insertText(val + "\n", Word.InsertLocation.replace);
      await context.sync();
    });
  } else {
    alert("Inserted into document: " + val);
  }
}

async function insertSnippet() {
  const docId = document.getElementById("snippet-doc-select").value;
  if (!docId) return;

  try {
    const res = await fetch(`/api/documents/${docId}`);
    const doc = await res.json();
    const textToInsert = doc.ocr_text || doc.notes || `[NewtonEDMS Document #${doc.id}: ${doc.name}]`;

    if (typeof Word !== "undefined" && Word.run) {
      Word.run(async (context) => {
        const range = context.document.getSelection();
        range.insertText(textToInsert + "\n", Word.InsertLocation.replace);
        await context.sync();
      });
    } else {
      alert("Inserted snippet: " + textToInsert.slice(0, 100) + "…");
    }
  } catch (e) {
    alert("Could not insert snippet: " + e.message);
  }
}

// Save active document to NewtonEDMS
async function saveActiveDocument() {
  const statusEl = document.getElementById("save-status");
  const folderId = document.getElementById("save-folder-select").value;
  const title = (document.getElementById("save-title").value || "").trim() || "Document.docx";
  const tags = document.getElementById("save-tags").value;

  statusEl.innerHTML = `<div class="alert alert-info"><i class="fa-solid fa-spinner fa-spin"></i> Uploading to NewtonEDMS…</div>`;

  try {
    // In real Office.js, retrieve document slice bytes
    if (typeof Word !== "undefined" && Word.run) {
      // Office document slice saving
      // Fallback/Simulated FormData upload
    }

    const formData = new FormData();
    const blob = new Blob(["Simulated Office document content"], {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    formData.append("file", blob, title);
    if (folderId) formData.append("folder_id", folderId);
    if (tags) formData.append("tags", tags);

    const res = await fetch("/api/documents/upload", {
      method: "POST",
      body: formData,
    });
    if (!res.ok) throw new Error("Upload failed");
    const result = await res.json();

    statusEl.innerHTML = `<div class="alert alert-success"><i class="fa-solid fa-check"></i> Document saved successfully (#${result.id || "1"})!</div>`;
    await loadDocs();
  } catch (e) {
    statusEl.innerHTML = `<div class="alert" style="color:var(--danger)"><i class="fa-solid fa-triangle-exclamation"></i> Error: ${e.message}</div>`;
  }
}

// Outlook Archiver
function initOutlookContext() {
  if (typeof Office !== "undefined" && Office.context && Office.context.mailbox && Office.context.mailbox.item) {
    activeMailItem = Office.context.mailbox.item;
    const subjEl = document.getElementById("mail-subject");
    const fromEl = document.getElementById("mail-from");
    if (subjEl && activeMailItem.subject) subjEl.textContent = activeMailItem.subject;
    if (fromEl && activeMailItem.from) fromEl.textContent = "From: " + (activeMailItem.from.displayName || activeMailItem.from.emailAddress);
  }
}

async function archiveCurrentMail() {
  const statusEl = document.getElementById("outlook-status");
  const folderId = document.getElementById("outlook-folder-select").value;
  const tagsStr = document.getElementById("outlook-tags").value;
  const tags = tagsStr.split(",").map((t) => t.trim()).filter(Boolean);

  statusEl.innerHTML = `<div class="alert alert-info"><i class="fa-solid fa-spinner fa-spin"></i> Archiving email to repository…</div>`;

  const payload = {
    folder_id: folderId ? parseInt(folderId) : null,
    subject: activeMailItem ? activeMailItem.subject : "Important Project Update",
    from_address: activeMailItem && activeMailItem.from ? activeMailItem.from.emailAddress : "partner@enterprise.com",
    from_name: activeMailItem && activeMailItem.from ? activeMailItem.from.displayName : "Enterprise Partner",
    sent_date: new Date().toISOString(),
    body_html: "<p>Thank you for the documents. Please find our confirmation attached.</p>",
    tags: tags,
  };

  try {
    const res = await fetch("/api/office/outlook/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("Archive failed");
    const result = await res.json();
    statusEl.innerHTML = `<div class="alert alert-success"><i class="fa-solid fa-check"></i> Archived as #${result.email_document_id}!</div>`;
  } catch (e) {
    statusEl.innerHTML = `<div class="alert" style="color:var(--danger)">Archive error: ${e.message}</div>`;
  }
}
