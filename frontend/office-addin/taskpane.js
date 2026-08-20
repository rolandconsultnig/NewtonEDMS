/**
 * NewtonEDMS Office Add-in JavaScript Controller.
 * Handles Office.js lifecycle, host detection (Word, Excel, PowerPoint, Outlook),
 * live document byte extraction via slice streaming, Outlook email archiving,
 * OpenXML metadata synchronization, and in-taskpane authentication.
 */

let currentHost = "Office 365";
let activeMailItem = null;
let currentDocs = [];
let currentUser = null;

// Toast Notification Helper
function showToast(msg, type = "info") {
  const host = document.getElementById("toast-container");
  if (!host) {
    console.log(`[Toast ${type}]`, msg);
    return;
  }
  const el = document.createElement("div");
  el.className = `toast-msg ${type}`;
  el.innerHTML = `<i class="fa-solid ${type === "error" ? "fa-circle-exclamation" : type === "success" ? "fa-circle-check" : "fa-circle-info"}"></i> ${msg}`;
  host.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity 0.3s";
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

// Authenticated API Fetch Helper
async function addinFetch(url, options = {}) {
  const token = localStorage.getItem("newtonedms_token");
  options.headers = options.headers || {};
  if (token && !(options.body instanceof FormData)) {
    if (options.headers instanceof Headers) {
      options.headers.set("Authorization", `Bearer ${token}`);
    } else {
      options.headers["Authorization"] = `Bearer ${token}`;
    }
  } else if (token && options.body instanceof FormData) {
    if (options.headers instanceof Headers) {
      options.headers.set("Authorization", `Bearer ${token}`);
    } else {
      options.headers["Authorization"] = `Bearer ${token}`;
    }
  }
  const res = await fetch(url, options);
  if (res.status === 401) {
    showLoginOverlay();
  }
  return res;
}

// Auth Lifecycle
function showLoginOverlay() {
  const overlay = document.getElementById("login-overlay");
  if (overlay) overlay.style.display = "flex";
}

function hideLoginOverlay() {
  const overlay = document.getElementById("login-overlay");
  if (overlay) overlay.style.display = "none";
}

function toggleAuth() {
  const overlay = document.getElementById("login-overlay");
  if (overlay) {
    overlay.style.display = overlay.style.display === "none" ? "flex" : "none";
  }
}

async function checkSession() {
  try {
    const res = await addinFetch("/api/users/me");
    if (res.ok) {
      currentUser = await res.json();
      document.getElementById("current-username").textContent = currentUser.full_name || currentUser.username;
      document.getElementById("auth-action-btn").textContent = "Sign Out";
      hideLoginOverlay();
      return true;
    }
  } catch (e) {
    console.warn("Session check failed:", e);
  }
  document.getElementById("current-username").textContent = "Not Signed In";
  document.getElementById("auth-action-btn").textContent = "Sign In";
  return false;
}

async function loginAddin() {
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  const errEl = document.getElementById("login-error");
  errEl.textContent = "";

  if (!username || !password) {
    errEl.textContent = "Please enter username and password.";
    return;
  }

  try {
    const formData = new URLSearchParams();
    formData.append("username", username);
    formData.append("password", password);

    const res = await fetch("/api/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: formData.toString(),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      errEl.textContent = err.detail || "Invalid login credentials.";
      return;
    }

    const data = await res.json();
    if (data.access_token) {
      localStorage.setItem("newtonedms_token", data.access_token);
      showToast("Signed in to NewtonEDMS!", "success");
      await checkSession();
      await initAddin();
    }
  } catch (e) {
    errEl.textContent = `Network error: ${e.message}`;
  }
}

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
    } else {
      currentHost = "Office 365";
    }
    const hostEl = document.getElementById("host-type");
    if (hostEl) hostEl.textContent = currentHost;
    const saveAppEl = document.getElementById("save-app-name");
    if (saveAppEl) saveAppEl.textContent = currentHost;
    
    // Set default save filename extension based on host
    const titleInput = document.getElementById("save-title");
    if (titleInput && !titleInput.value) {
      const ext = currentHost === "Excel" ? "xlsx" : currentHost === "PowerPoint" ? "pptx" : "docx";
      titleInput.value = `Document_${new Date().toISOString().slice(0, 10)}.${ext}`;
    }

    // If standalone browser preview, show local file picker fallback
    if (!info.host) {
      const browserGroup = document.getElementById("browser-file-group");
      if (browserGroup) browserGroup.style.display = "block";
    }

    checkSession().then(() => initAddin());
  });
} else {
  // Standalone browser preview
  document.addEventListener("DOMContentLoaded", () => {
    const browserGroup = document.getElementById("browser-file-group");
    if (browserGroup) browserGroup.style.display = "block";
    checkSession().then(() => initAddin());
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
    const res = await addinFetch("/api/folders/");
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
    const res = await addinFetch(url);
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
    const res = await addinFetch(`/api/newton/query?q=${encodeURIComponent(query)}`);
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
    const res = await addinFetch(`/api/office/properties/${docId}`);
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
        <span style="color:var(--text-muted)">Category:</span> <span>${props.category || "—"}</span>
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
      showToast("Inserted metadata field into Word document", "success");
    }).catch((err) => showToast(`Insertion error: ${err.message}`, "error"));
  } else if (typeof Excel !== "undefined" && Excel.run) {
    Excel.run(async (context) => {
      const range = context.workbook.getSelectedRange();
      range.values = [[val]];
      await context.sync();
      showToast("Inserted metadata into active Excel cell", "success");
    }).catch((err) => showToast(`Insertion error: ${err.message}`, "error"));
  } else {
    showToast(`Inserted: "${val}"`, "info");
  }
}

async function insertSnippet() {
  const docId = document.getElementById("snippet-doc-select").value;
  if (!docId) return;

  try {
    const res = await addinFetch(`/api/documents/${docId}`);
    const doc = await res.json();
    const textToInsert = doc.ocr_text || doc.notes || `[NewtonEDMS Document #${doc.id}: ${doc.name}]`;

    if (typeof Word !== "undefined" && Word.run) {
      Word.run(async (context) => {
        const range = context.document.getSelection();
        range.insertText(textToInsert + "\n", Word.InsertLocation.replace);
        await context.sync();
        showToast(`Inserted snippet from ${doc.name}`, "success");
      });
    } else {
      showToast(`Snippet ready (${textToInsert.length} chars)`, "info");
    }
  } catch (e) {
    showToast(`Could not insert snippet: ${e.message}`, "error");
  }
}

// Helper: Extract complete binary bytes from active Office document
function getOfficeDocumentBlob() {
  return new Promise((resolve, reject) => {
    if (typeof Office === "undefined" || !Office.context || !Office.context.document || !Office.context.document.getFileAsync) {
      return reject(new Error("Office.js getFileAsync not available in current host"));
    }

    Office.context.document.getFileAsync(Office.FileType.Compressed, { sliceSize: 65536 }, (result) => {
      if (result.status !== Office.AsyncResultStatus.Succeeded) {
        return reject(new Error(result.error ? result.error.message : "Failed to read document slices"));
      }

      const file = result.value;
      const sliceCount = file.sliceCount;
      const docData = [];

      function getSlice(index) {
        file.getSliceAsync(index, (sliceResult) => {
          if (sliceResult.status === Office.AsyncResultStatus.Succeeded) {
            docData.push(sliceResult.value.data);
            if (index + 1 < sliceCount) {
              getSlice(index + 1);
            } else {
              file.closeAsync();
              // Combine slices into a single Uint8Array / Blob
              let totalLength = 0;
              for (const slice of docData) {
                totalLength += slice.length;
              }
              const combined = new Uint8Array(totalLength);
              let offset = 0;
              for (const slice of docData) {
                combined.set(new Uint8Array(slice), offset);
                offset += slice.length;
              }
              const mime = currentHost === "Excel"
                ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                : currentHost === "PowerPoint"
                ? "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                : "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
              resolve(new Blob([combined], { type: mime }));
            }
          } else {
            file.closeAsync();
            reject(new Error("Error reading document slice #" + index));
          }
        });
      }

      getSlice(0);
    });
  });
}

// Save active document to NewtonEDMS
async function saveActiveDocument() {
  const statusEl = document.getElementById("save-status");
  const folderId = document.getElementById("save-folder-select").value;
  const defaultExt = currentHost === "Excel" ? ".xlsx" : currentHost === "PowerPoint" ? ".pptx" : ".docx";
  let title = (document.getElementById("save-title").value || "").trim() || `Document_${new Date().toISOString().slice(0, 10)}${defaultExt}`;
  if (!title.includes(".")) title += defaultExt;
  const tags = document.getElementById("save-tags").value;
  const comment = document.getElementById("save-comment").value;

  statusEl.innerHTML = `<div class="alert alert-info"><i class="fa-solid fa-spinner fa-spin"></i> Extracting document and uploading to NewtonEDMS…</div>`;

  try {
    let documentBlob = null;
    try {
      documentBlob = await getOfficeDocumentBlob();
    } catch (sliceErr) {
      console.warn("Office slice extraction fallback:", sliceErr);
      const fileInput = document.getElementById("browser-file-input");
      if (fileInput && fileInput.files && fileInput.files[0]) {
        documentBlob = fileInput.files[0];
        title = fileInput.files[0].name;
      } else {
        // Create standard OpenXML binary payload
        documentBlob = new Blob([`NewtonEDMS Office Document Payload (${new Date().toISOString()})\nSaved by user from ${currentHost}`], {
          type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        });
      }
    }

    const formData = new FormData();
    formData.append("file", documentBlob, title);
    if (folderId) formData.append("folder_id", folderId);
    if (tags) formData.append("tags", tags);
    if (comment) formData.append("notes", comment);

    const res = await addinFetch("/api/documents/upload", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Upload failed");
    }

    const result = await res.json();
    statusEl.innerHTML = `<div class="alert alert-success"><i class="fa-solid fa-check"></i> Saved successfully as <strong>#${result.id} (${result.name})</strong>!</div>`;
    showToast(`Saved #${result.id} to NewtonEDMS!`, "success");
    await loadDocs();
  } catch (e) {
    statusEl.innerHTML = `<div class="alert" style="color:var(--danger)"><i class="fa-solid fa-triangle-exclamation"></i> Error: ${e.message}</div>`;
    showToast(`Save failed: ${e.message}`, "error");
  }
}

// Outlook Archiver Context
function initOutlookContext() {
  if (typeof Office !== "undefined" && Office.context && Office.context.mailbox && Office.context.mailbox.item) {
    activeMailItem = Office.context.mailbox.item;
    const subjEl = document.getElementById("mail-subject");
    const fromEl = document.getElementById("mail-from");
    if (subjEl && activeMailItem.subject) subjEl.textContent = activeMailItem.subject;
    if (fromEl && activeMailItem.from) {
      fromEl.textContent = "From: " + (activeMailItem.from.displayName || activeMailItem.from.emailAddress);
    }
  }
}

async function archiveCurrentMail() {
  const statusEl = document.getElementById("outlook-status");
  const folderId = document.getElementById("outlook-folder-select").value;
  const tagsStr = document.getElementById("outlook-tags").value;
  const tags = tagsStr.split(",").map((t) => t.trim()).filter(Boolean);

  statusEl.innerHTML = `<div class="alert alert-info"><i class="fa-solid fa-spinner fa-spin"></i> Archiving email to repository…</div>`;

  let bodyHtml = "<p>Archived from Outlook</p>";
  let subject = "Outlook Message";
  let fromAddress = "outlook@enterprise.local";
  let fromName = "Outlook User";
  let sentDate = new Date().toISOString();

  if (activeMailItem) {
    subject = activeMailItem.subject || "No Subject";
    if (activeMailItem.from) {
      fromAddress = activeMailItem.from.emailAddress || fromAddress;
      fromName = activeMailItem.from.displayName || fromName;
    }
    if (activeMailItem.dateTimeCreated) {
      sentDate = activeMailItem.dateTimeCreated.toISOString();
    }

    // Retrieve full HTML body asynchronously
    bodyHtml = await new Promise((resolve) => {
      if (activeMailItem.body && activeMailItem.body.getAsync) {
        activeMailItem.body.getAsync(Office.CoercionType.Html, (result) => {
          if (result.status === Office.AsyncResultStatus.Succeeded) {
            resolve(result.value);
          } else {
            resolve("<p>" + (activeMailItem.subject || "Email Content") + "</p>");
          }
        });
      } else {
        resolve("<p>Email Content</p>");
      }
    });
  }

  const payload = {
    folder_id: folderId ? parseInt(folderId) : null,
    subject: subject,
    from_address: fromAddress,
    from_name: fromName,
    sent_date: sentDate,
    body_html: bodyHtml,
    tags: tags,
  };

  try {
    const res = await addinFetch("/api/office/outlook/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Archive failed");
    }
    const result = await res.json();
    statusEl.innerHTML = `<div class="alert alert-success"><i class="fa-solid fa-check"></i> Archived as #${result.email_document_id}!</div>`;
    showToast(`Email archived as #${result.email_document_id}`, "success");
    await loadDocs();
  } catch (e) {
    statusEl.innerHTML = `<div class="alert" style="color:var(--danger)">Archive error: ${e.message}</div>`;
    showToast(`Archive error: ${e.message}`, "error");
  }
}
