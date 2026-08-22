/* NewtonEDMS User Manual — comprehensive docx generator.
 * Skill: R1 cover (DM-1), 3-section TOC architecture, 8 parts / 27 chapters. */
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, PageBreak, Header, Footer, PageNumber, NumberFormat,
  AlignmentType, HeadingLevel, WidthType, BorderStyle, ShadingType,
  TableLayoutType, SectionType, TableOfContents,
} = require("docx");
const fs = require("fs");
const path = require("path");
const { imageSize } = require("image-size");

const ROOT = path.join(__dirname, "..");
const SHOTS = path.join(ROOT, "screenshots");
const OUT = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(ROOT, "NewtonEDMS-User-Manual.docx");

/* ── Palette: DM-1 cover + Dawn Mist Tech body tokens ─────────────────── */
const P = {
  bg: "162235", accent: "37DCF2",
  titleColor: "FFFFFF", subtitleColor: "B0B8C0", metaColor: "90989F", footerColor: "687078",
  primary: "0A1628", body: "182030", secondary: "6878A0",
  table: { headerBg: "1B6B7A", headerText: "FFFFFF", accentLine: "1B6B7A", innerLine: "C8DDE2", surface: "EDF3F5" },
};

const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: NB, bottom: NB, left: NB, right: NB };
const allNoBorders = { top: NB, bottom: NB, left: NB, right: NB, insideHorizontal: NB, insideVertical: NB };

/* ── Cover layout helpers (from design-system.md) ─────────────────────── */
function splitTitleLines(title, charsPerLine) {
  if (title.length <= charsPerLine) return [title];
  const breakAfter = new Set([..."，。、；：！？", ..."的与和及之在于为", ..."-_—–·/", ..." \t"]);
  const lines = [];
  let remaining = title;
  while (remaining.length > charsPerLine) {
    let breakAt = -1;
    for (let i = charsPerLine; i >= Math.floor(charsPerLine * 0.6); i--) {
      if (i < remaining.length && breakAfter.has(remaining[i - 1])) { breakAt = i; break; }
    }
    if (breakAt === -1) {
      const limit = Math.min(remaining.length, Math.ceil(charsPerLine * 1.3));
      for (let i = charsPerLine + 1; i < limit; i++) {
        if (breakAfter.has(remaining[i - 1])) { breakAt = i; break; }
      }
    }
    if (breakAt === -1) breakAt = charsPerLine;
    lines.push(remaining.slice(0, breakAt).trim());
    remaining = remaining.slice(breakAt).trim();
  }
  if (remaining) lines.push(remaining);
  if (lines.length > 1 && lines[lines.length - 1].length <= 2) {
    const last = lines.pop();
    lines[lines.length - 1] += last;
  }
  return lines;
}
function calcTitleLayout(title, maxWidthTwips, preferredPt = 40, minPt = 24) {
  const charsPerLine = (pt) => Math.floor(maxWidthTwips / (pt * 20));
  let titlePt = preferredPt, lines;
  while (titlePt >= minPt) {
    const cpl = charsPerLine(titlePt);
    if (cpl < 2) { titlePt -= 2; continue; }
    lines = splitTitleLines(title, cpl);
    if (lines.length <= 3) break;
    titlePt -= 2;
  }
  if (!lines || lines.length > 3) { lines = splitTitleLines(title, charsPerLine(minPt)); titlePt = minPt; }
  return { titlePt, titleLines: lines };
}
function calcCoverSpacing(params) {
  const { titleLineCount = 1, titlePt = 36, hasSubtitle = false, hasEnglishLabel = false,
    metaLineCount = 0, fixedHeight = 800, pageHeight = 16838, marginTop = 0, marginBottom = 0 } = params;
  const SAFETY = 1200;
  const usableHeight = pageHeight - marginTop - marginBottom - SAFETY;
  const contentHeight = titleLineCount * (titlePt * 23 + 200) + (hasSubtitle ? (12 * 23 + 600) : 0)
    + (hasEnglishLabel ? (9 * 23 + 600) : 0) + metaLineCount * (10 * 23 + 100) + fixedHeight + 3 * 300;
  const safeRemaining = Math.max(usableHeight - contentHeight, 400);
  const FOOTER_MIN = 800;
  const rawTop = Math.floor(safeRemaining * 0.45);
  const rawBottom = Math.floor(safeRemaining * 0.45);
  const bottomSpacing = Math.max(rawBottom, FOOTER_MIN);
  const topSpacing = Math.max(rawTop - Math.max(0, FOOTER_MIN - rawBottom), 400);
  return { topSpacing, midSpacing: Math.max(safeRemaining - topSpacing - bottomSpacing, 0), bottomSpacing };
}

/* ── Cover Recipe R1 (Pure Paragraph Left) ────────────────────────────── */
function buildCoverR1(config) {
  const padL = 1200, padR = 800;
  const availableWidth = 11906 - padL - padR - 300;
  const { titlePt, titleLines } = calcTitleLayout(config.title, availableWidth, 40, 24);
  const titleSize = titlePt * 2;
  const spacing = calcCoverSpacing({
    titleLineCount: titleLines.length, titlePt,
    hasSubtitle: !!config.subtitle, hasEnglishLabel: !!config.englishLabel,
    metaLineCount: (config.metaLines || []).length, fixedHeight: 400,
  });
  const accentLeft = { style: BorderStyle.SINGLE, size: 8, color: P.accent, space: 12 };
  const children = [];
  children.push(new Paragraph({ spacing: { before: spacing.topSpacing } }));
  if (config.englishLabel) {
    children.push(new Paragraph({
      indent: { left: padL, right: padR }, spacing: { after: 500 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: P.accent, space: 8 } },
      children: [new TextRun({ text: config.englishLabel.split("").join("  "),
        size: 18, color: P.accent, font: { ascii: "Calibri", eastAsia: "SimHei" }, characterSpacing: 40 })],
    }));
  }
  for (let i = 0; i < titleLines.length; i++) {
    children.push(new Paragraph({
      indent: { left: padL },
      spacing: { after: i < titleLines.length - 1 ? 100 : 300, line: Math.ceil(titlePt * 23), lineRule: "atLeast" },
      children: [new TextRun({ text: titleLines[i], size: titleSize, bold: true,
        color: P.titleColor, font: { eastAsia: "SimHei", ascii: "Arial" } })],
    }));
  }
  if (config.subtitle) {
    children.push(new Paragraph({
      indent: { left: padL }, spacing: { after: 800 },
      children: [new TextRun({ text: config.subtitle, size: 24, color: P.subtitleColor,
        font: { eastAsia: "Microsoft YaHei", ascii: "Arial" } })],
    }));
  }
  for (const line of (config.metaLines || [])) {
    children.push(new Paragraph({
      indent: { left: padL + 200 }, spacing: { after: 80 }, border: { left: accentLeft },
      children: [new TextRun({ text: line, size: 24, color: P.metaColor,
        font: { eastAsia: "Microsoft YaHei", ascii: "Arial" } })],
    }));
  }
  children.push(new Paragraph({ spacing: { before: spacing.bottomSpacing } }));
  children.push(new Paragraph({
    indent: { left: padL, right: padR },
    border: { top: { style: BorderStyle.SINGLE, size: 2, color: P.accent, space: 8 } },
    spacing: { before: 200 },
    children: [
      new TextRun({ text: config.footerLeft || "", size: 16, color: P.footerColor, font: { ascii: "Arial" } }),
      new TextRun({ text: "                                        " }),
      new TextRun({ text: config.footerRight || "", size: 16, color: P.footerColor, font: { ascii: "Arial" } }),
    ],
  }));
  return [new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: allNoBorders,
    rows: [new TableRow({
      height: { value: 16838, rule: "exact" },
      children: [new TableCell({
        shading: { type: ShadingType.CLEAR, fill: P.bg }, borders: noBorders, children,
      })],
    })],
  })];
}

/* ── Body component builders ──────────────────────────────────────────── */
const EN = { ascii: "Times New Roman", eastAsia: "SimSun" };

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 400, after: 180, line: 312 },
    children: [new TextRun({ text, bold: true, size: 32, color: P.primary, font: EN })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 140, line: 312 },
    children: [new TextRun({ text, bold: true, size: 28, color: P.primary, font: EN })],
  });
}
function part(text) {
  return [
    new Paragraph({ spacing: { before: 200 }, children: [] }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      border: { top: { style: BorderStyle.SINGLE, size: 6, color: P.table.accentLine, space: 10 } },
      spacing: { before: 300, after: 60 },
      children: [new TextRun({ text, bold: true, size: 22, color: P.table.accentLine, font: EN, characterSpacing: 40 })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: P.table.accentLine, space: 10 } },
      spacing: { after: 240 },
      children: [new TextRun({ text: " ", size: 8, font: EN })],
    }),
  ];
}
function p(text, opts = {}) {
  return new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: { after: 140, line: 312 },
    keepNext: opts.keepNext || false,
    children: [new TextRun({ text, size: 24, color: P.body, font: EN, italics: opts.italics || false })],
  });
}
function steps(items) {
  return items.map((t, i) => new Paragraph({
    spacing: { after: 80, line: 312 },
    indent: { left: 360, hanging: 360 },
    children: [
      new TextRun({ text: (i + 1) + ". ", bold: true, size: 24, color: P.body, font: EN }),
      new TextRun({ text: t, size: 24, color: P.body, font: EN }),
    ],
  }));
}
function bullet(text) {
  return new Paragraph({
    bullet: { level: 0 },
    spacing: { after: 80, line: 312 },
    children: [new TextRun({ text, size: 24, color: P.body, font: EN })],
  });
}

let figureNo = 0;
function figure(file, caption) {
  figureNo += 1;
  const buf = fs.readFileSync(path.join(SHOTS, file));
  const dim = imageSize(buf);
  const displayWidth = 560;
  const displayHeight = Math.round(displayWidth * (dim.height / dim.width));
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 60 },
      children: [new ImageRun({ data: buf, transformation: { width: displayWidth, height: displayHeight }, type: "png" })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { after: 200 },
      children: [new TextRun({ text: "Figure " + figureNo + " — " + caption, size: 20, color: P.secondary, font: EN, italics: true })],
    }),
  ];
}
function cell(text, opts = {}) {
  return new TableCell({
    children: [new Paragraph({
      spacing: { line: 276 },
      children: [new TextRun({ text, bold: opts.header || false, size: 21,
        color: opts.header ? P.table.headerText : P.body, font: EN })],
    })],
    shading: opts.header ? { type: ShadingType.CLEAR, fill: P.table.headerBg } : undefined,
    margins: { top: 60, bottom: 60, left: 120, right: 120 },
    width: opts.width ? { size: opts.width, type: WidthType.PERCENTAGE } : undefined,
  });
}
function table(headers, rows, widths) {
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: P.table.accentLine },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: P.table.accentLine },
      left: NB, right: NB,
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: P.table.innerLine },
      insideVertical: NB,
    },
    rows: [
      new TableRow({
        tableHeader: true, cantSplit: true,
        children: headers.map((t, i) => cell(t, { header: true, width: widths ? widths[i] : undefined })),
      }),
      ...rows.map(r => new TableRow({
        cantSplit: true,
        children: r.map((t, i) => cell(t, { width: widths ? widths[i] : undefined })),
      })),
    ],
  });
}
function tableTitle(text) {
  return new Paragraph({
    keepNext: true, spacing: { before: 120, after: 80 },
    children: [new TextRun({ text, bold: true, size: 21, color: P.secondary, font: EN })],
  });
}

/* ── Footers / header ─────────────────────────────────────────────────── */
const pageFooter = () => new Footer({
  children: [new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: P.secondary, font: EN })],
  })],
});
const bodyHeader = new Header({
  children: [new Paragraph({
    alignment: AlignmentType.RIGHT,
    border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: P.table.innerLine, space: 4 } },
    children: [new TextRun({ text: "NewtonEDMS User Manual", size: 18, color: P.secondary, font: EN })],
  })],
});

/* ═══════════════════════════════════════════════════════════════════════
 * BODY CONTENT — 8 parts, 27 chapters
 * ═══════════════════════════════════════════════════════════════════════ */
const body = [];

/* ── Part I ───────────────────────────────────────────────────────────── */
body.push(...part("PART I — GETTING STARTED"));

body.push(h1("1. Introduction"));
body.push(p("NewtonEDMS is an enterprise document management system. It combines a governed repository — hierarchical folders, roles, access control lists, versioning, retention, and a full audit trail — with an intelligent capture pipeline that reads incoming documents, recognizes text (including OCR for scans), and suggests tags, correspondents, and dates. People work together through shared links with differentiated permissions, review workflows, comments, and Microsoft Office integration, and documents can be digitally signed without leaving the system."));
body.push(p("This manual covers the whole product end to end. Part I gets you started; Part II explains organizing and capturing; Parts III and IV cover the document inspector, sharing, and Office; Part V documents governance features such as workflows, signing, search, retention, and audit; Parts VI and VII cover people, personal settings, and every administration area; Part VIII closes with integration interfaces, troubleshooting, and a glossary."));
body.push(p("Conventions used in this manual: user interface elements are written in bold (for example, click Upload), and step-by-step procedures are numbered. Screenshots were taken from a live installation; yours may differ slightly if your organization has customized branding or disabled certain modules."));

body.push(h1("2. Signing In"));
body.push(p("Open the NewtonEDMS address in your browser, enter the username and password given to you by your administrator, and click Sign in."));
body.push(...figure("01-login.png", "The sign-in page"));
body.push(h2("2.1 Two-factor authentication"));
body.push(p("If your account has TOTP two-factor authentication enabled, a code field appears after you enter your credentials. Open your authenticator app (any RFC 6238 application works, such as Google Authenticator, Microsoft Authenticator, or Aegis), type the current six-digit code, and sign in. You can enable two-factor authentication yourself in Settings; see Chapter 25."));
body.push(h2("2.2 Single sign-on"));
body.push(p("If your organization configured OpenID Connect or SAML, sign-in links appear below the password form. Clicking one sends you to your identity provider; after successful authentication you return to NewtonEDMS already signed in. Your administrator decides whether SSO is mandatory for your account."));
body.push(h2("2.3 Locked accounts and Passwords"));
body.push(p("After several failed attempts your account is temporarily locked; wait for the lockout to expire or ask your administrator to unlock it. If you forget your password, contact your administrator — passwords are stored only as one-way hashes and cannot be recovered by anyone. Users can change their own password in Settings; administrators can never read them."));
body.push(h2("2.4 Getting an account"));
body.push(p("Accounts come from two places. Most organizations let administrators create users directly (Chapter 22). Where self-registration is enabled, the sign-in page offers a Create account form protected by a rate limit; in multi-tenant installations you also need the invite code of the collective you are joining (Chapter 24). New accounts always start with the plain user role — access to content must be granted separately through folder and document permissions."));

body.push(h1("3. The Workspace"));
body.push(...figure("02-dashboard.png", "The dashboard overview"));
body.push(p("After signing in you land on the dashboard: recent activity, your open tasks and notifications, due dates, and quick access to saved dashboards. The header bar is present on every page and is the main way to move around the product."));
body.push(tableTitle("Table 1 — Header areas"));
body.push(table(["Area", "What it does"], [
  ["Dashboard / Documents / Search", "Switch between the overview, the folder browser, and search results."],
  ["Search box", "Full-text and query-language search; press / anywhere to focus it."],
  ["Upload", "Opens the upload dialog from anywhere; U is the shortcut."],
  ["Tools menu", "Scanner capture, ask documents (AI), new folder, folder export, save search."],
  ["Account menu", "Settings, theme toggle, sign out, and your profile chip."],
], [32, 68]));
body.push(p("The application adapts its layout to what you are doing: the folder browser shows the folder tree on the left, search mode shows search parameters, saved searches, tags, and facets, and administration replaces the tree with the admin navigation rail. The status bar at the bottom always shows the signed-in user, the current folder, counts, and hints."));
body.push(p("Press Esc to close the inspector panel or any open dialog. The complete shortcut list is in Chapter 28."));

/* ── Part II ──────────────────────────────────────────────────────────── */
body.push(...part("PART II — ORGANIZING AND CAPTURING"));

body.push(h1("4. Folders"));
body.push(p("Click Documents in the header to open the repository browser. The folder tree on the left is the backbone of the repository: folders nest to any depth, every folder carries its own access list, and documents live in exactly one folder (plus optional aliases, see Chapter 7)."));
body.push(...figure("03-documents.png", "The documents view: folder tree, toolbar, and document list"));
body.push(h2("4.1 Creating, renaming, and deleting folders"));
body.push(...steps([
  "Select the parent folder in the tree. Folder tools appear below the tree.",
  "Click New, type the folder name, and optionally tick Public read to let all users read the folder.",
  "Click Create. Rename and Delete work the same way on the selected folder.",
]));
body.push(p("Deleting a folder moves it and its contents to the trash (Section 4.4). Administrators can also create reusable folder structures with folder templates (Chapter 26)."));
body.push(h2("4.2 Folder security"));
body.push(p("Click Security in the folder tools to grant access. Add a user or a group, choose the permission bits, and save. The same dialog shows every existing grant; remove grants with the x buttons."));
body.push(...figure("21-folder-security.png", "Folder security: granting a group read access"));
body.push(tableTitle("Table 2 — Permission bits"));
body.push(table(["Bit", "Allows"], [
  ["read", "See the folder and list its documents."],
  ["preview", "Open the in-browser preview."],
  ["download", "Download files."],
  ["write", "Edit metadata and upload new versions."],
  ["add", "Create subfolders and documents."],
  ["rename / move", "Rename, or move content in and out."],
  ["delete", "Move content to the trash."],
  ["security", "Manage the access list itself."],
  ["sign / archive / workflow / import / export / immutable", "Specialized actions; commonly bundled by the roles below."],
], [34, 66]));
body.push(p("Roles provide shortcuts: a user, a group, or everyone can be granted Reader, Editor, or Full access, which set sensible combinations of the bits. Document-level grants (Chapter 11) follow the same model and override the folder default."));
body.push(h2("4.3 Trash and restore"));
body.push(p("Deleted documents and folders are not destroyed immediately. Open the Trash section in the folder tree to see everything deleted, restore items to their original location, or empty the trash to destroy them permanently (administrators only). Documents under legal hold (Chapter 19) can never be purged."));
body.push(...figure("22-trash.png", "The trash with restore and empty actions"));
body.push(h2("4.4 Folder quotas and limits"));
body.push(p("Administrators can cap a folder in two ways: a storage quota (the total size of files it may hold) and a child limit (the maximum number of documents and subfolders). When a limit is reached, uploads into that folder are rejected with a clear error rather than silently spilling elsewhere — the folder tools and the administration console show current usage against the caps, so nearing a limit is visible before anyone is blocked."));

body.push(h1("5. Capturing Documents"));
body.push(p("NewtonEDMS ingests documents from many sources: interactive upload, drag and drop, the scanner capture, ZIP archives, e-mail mailboxes, watched hot folders, public upload links, and the Outlook add-in. All of them feed the same processing pipeline described in Section 5.3."));
body.push(h2("5.1 Upload dialog"));
body.push(p("Click Upload in the header, or in the toolbar of the folder you want to file into."));
body.push(...figure("05-upload.png", "The upload dialog"));
body.push(tableTitle("Table 3 — Upload dialog fields"));
body.push(table(["Field", "Purpose"], [
  ["Title", "Used when uploading a single file."],
  ["Tags", "Comma-separated tags applied on upload."],
  ["Template", "Optionally applies a metadata template with custom fields."],
  ["Metadata JSON", "Extra custom fields, for example {\"customer\": \"Acme\"}."],
  ["Upload as one item", "Combines multiple selected files into a single multi-file item."],
  ["Skip duplicates", "Files whose content hash is already known are ignored."],
], [30, 70]));
body.push(h2("5.2 Other capture routes"));
body.push(bullet("Drag and drop: drop files anywhere on the document list to upload into the current folder."));
body.push(bullet("Scanner: Tools, then Scanner uses your device camera to photograph and ingest pages."));
body.push(bullet("Import ZIP: the toolbar button unpacks an archive, creating one document per file."));
body.push(bullet("Paste: the Paste button ingests a file from the clipboard."));
body.push(bullet("E-mail: administrators connect mailboxes (Chapter 26) and NewtonEDMS imports messages and their attachments automatically."));
body.push(bullet("Hot folders: watched local or FTP directories are imported on a schedule (Chapter 26)."));
body.push(bullet("Public upload links: an anonymous URL where outside parties drop files; metadata is pre-applied (Chapter 26)."));
body.push(...figure("15-tools-menu.png", "The Tools menu with scanner, AI, folder, and search actions"));
body.push(h2("5.3 The processing pipeline"));
body.push(p("Every new document is queued to the background processor (JOEX). In order, it: keeps the untouched original; computes the SHA-256 content hash and links duplicates; extracts attachments from ZIP and EML files; extracts text from office files and PDFs and runs OCR on scans; recognizes barcodes and uses them to route and index captures; suggests tags, correspondents, and dates using the catalog and NLP; adds everything to the search index; and fires any enabled add-on webhooks. Processing usually completes in seconds; the Processing inbox (Chapter 6) shows items still being worked on, and you can re-run the pipeline any time with Re-run OCR in the inspector More menu."));
body.push(...figure("04-folder-documents.png", "A captured document with automatically suggested correspondent and tags"));

body.push(h1("6. The Document List"));
body.push(p("The document list is the working surface of the repository. Each card shows title, status, tags, correspondent, version, and date; click a card to open it in the inspector. The toolbar above the list covers everything you can do with selections:"));
body.push(tableTitle("Table 4 — Document list toolbar"));
body.push(table(["Button", "Action"], [
  ["Upload / New folder", "Capture into the current folder."],
  ["Export ZIP", "Download the whole folder as an archive."],
  ["Export to Excel / Word", "Styled .xlsx report or .docx dossier from the current results."],
  ["Processing inbox", "Items captured but not yet confirmed (below)."],
  ["Bulk edit / Merge", "Change metadata of every selected item, or merge selected items into one."],
  ["List / tiles", "Switch between dense list and tile grid."],
  ["Paste / Send mail / Import ZIP", "Clipboard capture, e-mail the document, archive import."],
], [34, 66]));
body.push(p("Select multiple documents with the checkboxes to enable bulk editing: set tags and status across the selection at once. Duplicate detection is automatic — uploading a file whose content hash already exists links the copies so you can clean them up in bulk."));
body.push(...figure("16-inbox.png", "The processing inbox showing unconfirmed items"));
body.push(h2("6.1 The confirmation flow"));
body.push(p("Captured items wait in the processing inbox until someone confirms them — the queue's way of separating machine suggestions from human decisions. Reviewing the queue is a three-action loop: Confirm accepts the item with its suggested metadata and files it; Mark as read acknowledges it without deciding; Next unconfirmed jumps to the following item, so a large inbox can be cleared quickly from the keyboard. Confirming is what typically triggers document_confirmed automation rules (Chapter 16). The inspector's More menu repeats all three actions for the open document, and Unconfirm returns a document to the inbox when something is found later."));

body.push(h1("7. Document Properties and Metadata"));
body.push(p("Every document carries a metadata card you can edit any time in the inspector Properties tab: title, status (draft, review, approved, published, archived), tags, rating, custom identifier, correspondents, notes, due date, and language. Custom fields defined by your administrator (Chapter 26) appear here too — typed fields with validation such as text, number, date, boolean, and money."));
body.push(p("Metadata templates bundle custom fields so recurring document classes (contracts, invoices, personnel files) get the same fields everywhere. Apply a template at upload time or later from Properties. Aliases let one document appear in several folders without copying; the Aliases tab in the inspector More menu manages them, and deleting an alias never deletes the document."));
body.push(p("Beyond correspondents, documents can be attributed to an organization and to equipment — useful when the repository also serves as a plant or fleet archive — and both are searchable with the organization, equipment, and direction filters of the query language (Chapter 18)."));

/* ── Part III ─────────────────────────────────────────────────────────── */
body.push(...part("PART III — THE DOCUMENT INSPECTOR"));

body.push(h1("8. Inspector Overview"));
body.push(p("Click any document to open the inspector, the panel on the right that accompanies every document task. It is organized into tabs; the More menu holds the rest."));
body.push(...figure("06-inspector-properties.png", "The inspector showing document properties"));
body.push(tableTitle("Table 5 — Inspector tabs"));
body.push(table(["Tab", "What you can do"], [
  ["Properties", "Rename, set status, tags, and rating, edit custom fields (Chapter 7)."],
  ["Preview", "View the document in the browser: PDF, images, and text."],
  ["Versions", "Browse history, add a version, restore (Chapter 9)."],
  ["Share", "Share links with permission levels, internal grants, ownership transfer (Chapter 12)."],
  ["Security", "Document-level access bits (Chapter 11)."],
  ["Workflow", "Start a review workflow on this document (Chapter 15)."],
  ["PDF / Sign", "Watermark, stamp, digital signatures, redaction (Chapter 17)."],
  ["More: Files", "Attachments — extra files on a multi-file item."],
  ["More: Office Props", "Inspect and synchronize OpenXML properties (Chapter 13)."],
  ["More: Notes", "Comments thread, including external reviewers (Chapter 10)."],
  ["More: Links / History / Aliases / Subscriptions / Folder", "Related documents, full change history, aliases, notifications, containing folder."],
], [30, 70]));
body.push(p("The footer holds the quick actions: Download (with per-version download in Versions), the Office button (Chapter 13), the check-out lock (Chapter 9), the More menu (confirm, mark as read, download original, re-run OCR, edit in Office Online, template merge), and Delete."));

body.push(h1("9. Versioning and Check-Out"));
body.push(p("Every change that replaces a file creates a new version. Nothing is ever overwritten: earlier versions remain listed and downloadable, so you can always prove what a document looked like at any point in time."));
body.push(...figure("09-versions.png", "The version history of a document"));
body.push(...steps([
  "To add a version: open the Versions tab, click Add version (check-in file), choose the file, and enter a comment such as Revised payment terms.",
  "To restore: click Restore on an earlier version. The current file is itself preserved as a new version, so restores are never destructive.",
  "To lock while editing: click the padlock in the inspector footer to check out. Other users see the lock and cannot replace the file until you check it back in.",
]));
body.push(p("Check-out integrates with Microsoft Office editing: launching a desktop edit checks the document out automatically and checks it back in when you save."));

body.push(h1("10. Notes and Comments"));
body.push(p("The Notes tab (More menu) is the comment thread of a document. Internal comments show the author and timestamp; comments arriving through a View and comment share link show the external reviewer's chosen name marked via share (Chapter 12). Comments can be deleted by their author or by administrators."));
body.push(...figure("19-inspector-notes.png", "The Notes tab with the comment composer"));
body.push(p("The History tab records every change to the document — metadata edits, versions, downloads, share events — with user and timestamp, complementing the system-wide audit trail (Chapter 20)."));
body.push(h2("10.1 Related links"));
body.push(p("The Links tab relates documents to one another: an invoice to the purchase order it settles, an amendment to the contract it changes. Each link names its kind (related, attachment of, supersedes) so the relationship is explicit, and links are bidirectional — open either document and the other is one click away. Relations survive moves and renaming."));
body.push(h2("10.2 Subscriptions"));
body.push(p("Subscribe to a document (Subscriptions tab) to be notified when it changes: new versions, status changes, new comments, and share events raise a notification through your configured channels (Chapter 26). Subscriptions are per user, silent for the person making the change, and can be cancelled at any time — the practical way to watch a contract or a pending approval without polling it."));

body.push(h1("11. Document Security"));
body.push(p("The Security tab grants access to this specific document, independent of the folder it lives in (Chapter 4.2 explains the bit model). Typical uses: letting one user see a single salary document inside an otherwise restricted folder, or granting a group edit rights on one file."));
body.push(...figure("17-inspector-security.png", "Document security: per-principal permission bits"));
body.push(p("The Immutable flag (administrators) freezes a document entirely: no edits, no version replacement, no deletion until the flag is cleared — useful the moment a record must not change."));

/* ── Part IV ──────────────────────────────────────────────────────────── */
body.push(...part("PART IV — SHARING AND COLLABORATION"));

body.push(h1("12. Sharing Documents"));
body.push(p("Open the Share tab in the inspector to share a document with colleagues or with external people."));
body.push(...figure("07-share.png", "The Share tab: permission levels, internal grants, and ownership transfer"));
body.push(h2("12.1 Share links"));
body.push(p("Share links work for people without a NewtonEDMS account. When you create a link you choose a permission level:"));
body.push(tableTitle("Table 6 — Share link permission levels"));
body.push(table(["Level", "What recipients can do"], [
  ["View only", "Open a web page that shows the document in the browser. Downloading is disabled."],
  ["View & comment", "The same page plus a comment box; reviewers type their name and comment, and comments appear in the document's Notes tab marked via share."],
  ["Download", "A classic download link with an optional download counter."],
], [22, 78]));
body.push(p("Every link can carry an optional password, an expiry date (seven days by default), and a download cap for download links; any link can be revoked at any moment. View and comment pages render PDFs and images directly in the browser and never expose the repository behind them."));
body.push(h2("12.2 Internal access"));
body.push(p("Below the link section, Internal access grants a specific user or group View only or Edit rights on the document — the natural way to give the finance team access to an invoice. Grants are listed as chips and can be revoked with one click. This is the same mechanism as the Security tab, presented for quick sharing."));
body.push(h2("12.3 Ownership transfer"));
body.push(p("The Ownership transfer section, visible to the document owner and to administrators, hands the document to another user. The new owner also takes over any open check-out. This is the right tool when people change roles or leave the organization; the previous owner's other content is untouched."));

body.push(h1("13. Microsoft Office Integration"));
body.push(p("Click Office in the inspector footer to see the Office integration menu."));
body.push(...figure("20-office-modal.png", "The Microsoft Office integration menu"));
body.push(h2("13.1 Editing"));
body.push(bullet("Open in Desktop Office launches Word, Excel, or PowerPoint directly through the ms-word, ms-excel, and ms-powerpoint protocol handlers. The document is checked out to you while you edit and checked in on save, so versioning is automatic."));
body.push(bullet("Edit in Office Online (WOPI) opens collaborative editing in the browser through any WOPI-compatible suite configured by your administrator: Microsoft 365, Office Online Server, Collabora, or OnlyOffice."));
body.push(h2("13.2 Metadata and templates"));
body.push(bullet("OpenXML Property Inspector reads and writes core and custom properties of .docx, .xlsx, and .pptx files directly in the repository, keeping file metadata and NewtonEDMS metadata in step."));
body.push(bullet("Generate from Template merges a template document's {{placeholders}} — across paragraphs, tables, and worksheets — with data you supply, producing a new customized document, for example a filled contract."));
body.push(h2("13.3 Outlook add-in"));
body.push(p("Your administrator can distribute the NewtonEDMS task pane add-in for Word, Excel, PowerPoint, and Outlook (manifests are managed in Administration, Microsoft Office — see Chapter 26). The Outlook add-in archives an e-mail and its attachments into the repository with one click."));

body.push(h1("14. E-mail"));
body.push(p("The Send mail toolbar button composes a message from the document, optionally attaching a converted PDF copy. Outbound mail uses the SMTP account configured under Administration, SMTP / IMAP accounts. Inbound capture runs through mailbox import (Chapter 26). Stored account passwords are encrypted at rest."));

/* ── Part V ───────────────────────────────────────────────────────────── */
body.push(...part("PART V — AUTOMATION AND GOVERNANCE"));

body.push(h1("15. Workflows, Tasks, and the Calendar"));
body.push(p("A review workflow moves a document through approval steps. Start one from the inspector Workflow tab: pick a template published by your administrator and click Start."));
body.push(...figure("18-inspector-workflow.png", "Starting a workflow from the inspector"));
body.push(p("Each step creates a task for its assignee. Tasks arrive in the Tasks view and in notifications; open one to see the document, then Approve or Reject with an optional comment. Rejection can end the workflow or send it back, depending on the template. Administrators build templates in Administration, Review workflows, and can also model processes as BPMN cases with the built-in BPMN 2.0 engine."));
body.push(...figure("26-admin-workflows.png", "Administrating review workflow templates"));
body.push(...figure("24-tasks.png", "The Tasks view with approve and reject actions"));
body.push(p("The Calendar collects due dates, retention events, and your own entries; clicking a day adds an event. Messages is the internal mailbox between users, and the bell icon lists unread notifications."));
body.push(...figure("23-calendar.png", "The calendar view"));
body.push(h2("15.1 Internal messages"));
body.push(p("The Messages tab is the internal mailbox: compose to one or more colleagues, and read or reply in a threaded view. Unread counts appear on the tab badge, and messages support the same rich text as notes. Use messages for anything that should stay inside the audit boundary — unlike external e-mail, internal messages never leave the system, and their recipients are always named accounts."));
body.push(...figure("33-messages.png", "Internal messages between users"));

body.push(h1("16. Automation Rules and Capture Forms"));
body.push(p("Automation rules remove routine decisions: when a document is created, processed, or confirmed, a rule that matches its tag, status, or file type can set a tag, change the status, or start a workflow. For example: if tag is invoice, then set status review. Rules are managed under Administration, Automation rules."));
body.push(p("Capture forms put a public face on ingestion: a form defines fields that outside submitters fill in, and files they attach arrive pre-tagged and pre-described. Forms are reachable at their public URL, printable as QR codes, and managed under Administration, Capture forms."));

body.push(h1("17. Signing and PDF Tools"));
body.push(p("Open the inspector's PDF / Sign tab."));
body.push(...figure("08-sign.png", "The PDF / Sign tab with signature status and actions"));
body.push(p("The status box at the top shows whether the document is already signed, by whom, and when. To sign, enter a reason (for example, Approved for payment) and click Sign document. NewtonEDMS applies a visible signature stamp and embeds a cryptographic PAdES signature inside the PDF, which readers such as Adobe Acrobat can verify independently. The Verify signature button re-checks the embedded signature at any time."));
body.push(p("The same tab offers Watermark (diagonal text across pages), Digital stamp (corner stamp with barcode), Auto-redact (removes text matching patterns such as account numbers), Split pages (one PDF per page), and IDP capture (extracts values from fixed zones of recurring forms — zones are drawn in Administration, IDP zones)."));

body.push(h1("18. Search"));
body.push(p("Type in the header search box and press Enter, or open the Search tab for full-text and parameter forms: status, tags, custom field values, locked, and immutable filters. The search covers titles, names, notes, tags, custom fields, and the extracted full text, including OCR results from scans."));
body.push(...figure("12-search.png", "Search results for the query tag:invoice"));
body.push(p("The search box accepts structured filters that can be combined freely; remaining words are matched against the full text."));
body.push(tableTitle("Table 7 — Query language fields"));
body.push(table(["Field", "Meaning"], [
  ["tag:", "Has this tag."],
  ["correspondent: / concerning:", "Linked contact."],
  ["status:", "draft, review, approved, published, or archived."],
  ["folder:", "Folder identifier."],
  ["due:", "overdue, none, or a year and month such as 2026-09."],
  ["source:", "Where the document came from: upload, email, scan, and so on."],
  ["lang: / id: / name: / hash: / notes: / custom: / direction: / equipment:", "Search a specific field, identifier, or content hash."],
  ["inbox", "Only unprocessed items."],
], [46, 54]));
body.push(p("Save frequent searches with Tools, Save search; they appear under Bookmarks in the folder browser and can be shared as read-only query shares (Administration, Query shares). The Search tab also lists facets — clickable counts by status and tag — and Tags offers the tag cloud; tags can be grouped into categories by your administrator so the catalog stays navigable as it grows. Ask documents (Tools menu) answers questions over your documents with citations, using the built-in retrieval engine."));
body.push(h2("18.1 Ask documents (AI retrieval)"));
body.push(p("Ask documents opens a chat panel over the repository: type a question in plain language and the retrieval engine finds the passages that answer it, listing the source documents with their identifiers so every claim can be verified. Answers are extracted from your own indexed content — nothing is invented and nothing leaves the system — which makes it safe for contract questions, policy lookups, and finding the one paragraph that matters across hundreds of files."));
body.push(...figure("34-rag.png", "The Ask documents panel"));

body.push(h1("19. Retention, Legal Hold, and GDPR"));
body.push(p("Retention policies decide how long documents live: a policy binds a folder to a retention period in years, after which the content is either destroyed defensibly or archived, according to the policy. Destruction skips anything under legal hold and is recorded in the audit trail."));
body.push(...figure("28-admin-retention.png", "Retention policies in the administration console"));
body.push(p("Legal hold freezes individual documents against any deletion — set from the inspector or in bulk by administrators under Administration, Legal hold. Typical use: preserving everything related to a dispute."));
body.push(p("The GDPR tools (Administration, GDPR export / erase) produce a complete export of one person's data or erase it, respecting holds. Together with the audit trail and compliance posture checks (Chapter 20), these features support GDPR, HIPAA, and ISO 27001 obligations."));

body.push(h1("20. Audit Trail and Compliance"));
body.push(p("Every security-relevant action is recorded: logins, permission changes, downloads, shares created and revoked, versions, signatures, deletions, and administrative changes — each with user, timestamp, and target. Open Administration, Audit log to browse and filter the trail; administrators can export it."));
body.push(...figure("29-admin-audit.png", "The audit log"));
body.push(p("The Compliance page runs standing checks against GDPR, HIPAA, and ISO 27001 expectations (for example: are retention policies defined, is 2FA widespread, are holds respected) and reports the posture so gaps can be closed before an audit."));

/* ── Part VI ──────────────────────────────────────────────────────────── */
body.push(...part("PART VI — PEOPLE"));

body.push(h1("21. Address Book"));
body.push(p("Open Dashboard, then People. The Address book sub-tab manages correspondents and concerning parties: the people and organizations your documents are about. The capture pipeline uses the address book to suggest contacts when new documents arrive, and the query language searches it (correspondent:acme). Contacts carry name, organization, e-mail, kind (correspondent, concerning, or both), and notes."));

body.push(h1("22. Users and Roles"));
body.push(p("The Users sub-tab (administrators only) is the user registry of the system."));
body.push(...figure("10-people-users.png", "People — user management"));
body.push(...steps([
  "Click Add user after filling username, e-mail, initial password, and role.",
  "Adjust the role any time with the row's drop-down; set a storage quota with quota (megabytes, zero means unlimited).",
  "Disable an account to block login without deleting anything — the account's documents keep their provenance.",
]));
body.push(tableTitle("Table 8 — Roles"));
body.push(table(["Role", "Powers"], [
  ["user", "Works with documents and folders they can access; personal settings."],
  ["manager", "Additionally manages shared areas, workflows, and classification for their scope."],
  ["admin", "Full administration console access except other superadmins' core settings."],
  ["superadmin", "Unrestricted, including security policy and cluster settings."],
], [20, 80]));
body.push(p("Deleting a user is refused while they own documents, folders, or versions — deactivate instead so history stays attributable. For your own account the disable and delete buttons are locked: deactivating yourself would lock you out of the system. The Sessions and logins administration page shows active sessions and recent sign-ins."));

body.push(h1("23. Groups"));
body.push(p("Groups bundle users for permission grants. Create a group with a name and description, add members from the drop-down, and remove them with the chips."));
body.push(...figure("11-people-groups.png", "People — group management"));
body.push(p("Groups pay off wherever permissions are set: folder security (Chapter 4), document grants (Chapters 11 and 12), and workflow assignment. One grant then covers everyone in the group, and membership changes propagate instantly."));

body.push(h1("24. Collectives and Multi-Tenancy"));
body.push(p("A collective is an isolated tenant inside one NewtonEDMS installation: its own users, groups, folders, documents, tags, custom fields, dashboards, and address book. Content stamped with a collective is invisible to members of other collectives, which makes collectives the natural boundary when one system serves several departments, client organizations, or legal entities that must not see each other's records."));
body.push(p("Every user belongs to exactly one collective and works inside it for their whole session — there is no cross-collective search, sharing, or browsing. Administrators can, however, administer every collective from the console. Superadministrators decide the collective structure when the system is planned; splitting later requires migration, so model it along the strongest isolation requirement (typically the client or legal entity)."));
body.push(p("Membership grows in two ways: an administrator creates users directly inside a collective (Chapter 22), or people join themselves with an invite code issued for that collective. Invite codes are single-purpose random tokens handed to the person who should join; when self-registration is disabled system-wide, codes are the only way in. On first sign-in, new members see only the folders their collective shares with them."));

/* ── Part VII ─────────────────────────────────────────────────────────── */
body.push(...part("PART VII — PERSONAL SETTINGS AND ADMINISTRATION"));

body.push(h1("25. Personal Settings"));
body.push(p("Open the account menu at the top right, then Settings."));
body.push(...figure("14-settings.png", "Personal settings"));
body.push(bullet("Account: display name, e-mail (used for notifications), avatar, password change (current password required)."));
body.push(bullet("Two-factor authentication: enable TOTP by scanning the secret into any authenticator app and confirming one code; disable requires a valid code."));
body.push(bullet("Quota: how much of your storage allowance you have used."));
body.push(bullet("API keys: create and revoke tokens for scripted access (Chapter 27)."));
body.push(bullet("Trusted devices and recent logins for account security."));
body.push(bullet("Working hours: your daily availability window (start, end, working days), used by task assignment and calendar features to time notifications sensibly."));
body.push(bullet("Appearance: light or dark theme, language, and density."));

body.push(h1("26. Administration"));
body.push(p("Administrators see an extra Administration tab. The left rail groups every settings area; the filter box at the top jumps straight to any of them."));
body.push(...figure("13-admin.png", "The administration console"));
body.push(h2("25.1 People"));
body.push(p("Users and roles mirrors Chapter 22; Groups mirrors Chapter 23; Sessions and logins lists active sessions and login history for intrusion review."));
body.push(h2("25.2 Classification"));
body.push(p("Tags and fields manages the tag catalog and typed custom fields (text, number, date, boolean, money). Tags group into categories so large catalogs stay navigable, and the category shows in the tag cloud and when tagging documents. Metadata templates bundle fields for document classes. Folder templates define reusable folder structures, and folders can carry the quotas and child limits described in Chapter 4. Document numbering issues sequence numbers to documents. The auto-tag classifier learns from existing documents and proposes tags for new ones."));
body.push(...figure("25-admin-intelligence.png", "Tags and custom fields"));
body.push(h2("25.3 Process"));
body.push(p("Review workflows defines multi-step approval templates (who approves, in which order, what happens on rejection). BPMN cases runs processes modeled in BPMN 2.0. Automation rules applies tag, status, and workflow actions on document events. Capture forms publishes public ingestion forms. IDP zones draws the extraction zones used by IDP capture (Chapter 17)."));
body.push(h2("25.4 Ingest"));
body.push(p("Hot folders watches local or FTP directories and imports their files on a schedule. Mailbox import connects IMAP mailboxes for e-mail capture. Anonymous upload URLs creates public drop points with pre-applied metadata: the visitor opens the link, sees only the fields you defined (never the repository), drops files, and each file arrives in the target folder already tagged, titled, and owned by the link's creator — after which the normal processing pipeline and confirmation queue apply. CSV import loads documents and metadata from spreadsheets. Scanner configures capture defaults, and Backup and restore creates and restores full system backups."));
body.push(...figure("27-admin-imports.png", "Watched import folders"));
body.push(h2("25.5 Integrations"));
body.push(p("SMTP / IMAP accounts configures outbound and inbound mail. Microsoft Office manages WOPI clients and the Office add-in manifests (sideloading instructions included). Connectors syncs with external suites (Google Calendar and others). LDAP / SAML wires corporate sign-on. SAP ArchiveLink exposes the repository to SAP systems. WebDAV / CMIS / SOAP documents the protocol endpoints (Chapter 27). Addons manages webhook extensions and uploadable add-on packages that run on document events; packaged add-ons execute in an isolated subprocess rather than inside the application, so a faulty add-on cannot take the repository down."));
body.push(h2("25.6 Storage and jobs"));
body.push(p("File stores defines where files live — the local store plus optional Azure Blob stores created by a guided wizard. OCR and converters shows which external tools (Tesseract, OCRmyPDF, LibreOffice) are installed and sets OCR language. Search index manages the full-text index and its backend (built-in engine, SQLite FTS5, PostgreSQL, or Solr). Processing jobs lists the job queue with retry and cancel. Scheduled tasks runs periodic maintenance on the elected cluster leader. Cluster shows node membership, heartbeats, and leader election for load-balanced deployments."));
body.push(...figure("30-admin-jobs.png", "The processing job queue"));
body.push(h2("25.7 Security and retention"));
body.push(p("Login and IP policy sets IP allow and deny lists, failed-login lockout, and password aging. Legal hold, GDPR export / erase, Redaction rules (automatic removal of patterns such as account numbers on ingest), Retention, Audit log, and Compliance posture complete the governance suite (Chapters 19 and 20)."));
body.push(h2("25.8 Sharing and insights"));
body.push(p("Share links lists every link in the repository with revoke. Query shares manages shared saved searches. Notifications configures delivery channels (e-mail, webhook, Matrix, Gotify) and notification rules with digests. Reports and the Report builder produce usage and repository statistics, including custom reports saved from query results. Ask documents tunes the retrieval settings. Server log streams the application log for support.")); 
body.push(...figure("32-admin-reports.png", "Reports"));
body.push(...figure("31-admin-office.png", "The Microsoft Office administration page"));

body.push(h1("27. Integration Interfaces"));
body.push(p("Everything the web interface does is available over protocols, so other systems can work with the repository directly."));
body.push(tableTitle("Table 9 — Integration endpoints"));
body.push(table(["Interface", "Use"], [
  ["REST API", "The complete API under /api with interactive documentation at /docs. Authenticate with the session cookie or an API key (Chapter 25)."],
  ["WebDAV", "Mount the repository as a network drive at /webdav/ — drag files in and out with lock support."],
  ["CMIS", "Standard browser binding at /cmis/browser for ECM-compatible clients: createDocument, createFolder, update, delete."],
  ["SOAP", "Document, folder, search, and auth services under /soap/ for legacy integrations."],
  ["SAP ArchiveLink", "ArchiveLink protocol for SAP systems."],
  ["Office add-ins", "Word, Excel, PowerPoint, and Outlook task pane add-ins; manifests from Administration, Microsoft Office."],
  ["Webhooks / addons", "HTTP callbacks on document events; packaged add-ons run at processing time."],
  ["Health endpoint", "GET /api/system/health reports database and storage status as JSON, for load balancers and monitoring."],
], [24, 76]));
body.push(p("API keys carry the same permissions as their owner. Treat them like passwords: rotate them, and revoke keys when scripts are retired."));
body.push(p("For operations, the health endpoint is the liveness probe of record — a 200 with status ok means the database and storage are reachable; anything else should page the administrator. Combined with scheduled backups (Chapter 26), cluster heartbeats, and the audit trail, it gives operations the four signals that matter: is it up, is it backed up, is it consistent, and who did what."));

/* ── Part VIII ────────────────────────────────────────────────────────── */
body.push(...part("PART VIII — REFERENCE"));

body.push(h1("28. Shortcuts, Troubleshooting, and Glossary"));
body.push(tableTitle("Table 10 — Keyboard shortcuts"));
body.push(table(["Key", "Action"], [
  ["/", "Focus the search box."],
  ["U", "Open the upload dialog."],
  ["Esc", "Close the inspector and dialogs."],
], [20, 80]));
body.push(h2("27.1 Troubleshooting"));
body.push(bullet("Cannot sign in: check the username and password; after repeated failures the account locks temporarily. If 2FA codes are rejected, ensure the device clock is correct; otherwise ask your administrator to reset 2FA."));
body.push(bullet("A document is missing: check the trash (Chapter 4.3), search by title or content (Chapter 18), and remember access rules — you only see folders and documents you can read."));
body.push(bullet("Cannot edit a document: it may be checked out by someone else (Chapter 9), immutable (Chapter 11), or you may lack write permission (Chapters 4 and 11)."));
body.push(bullet("Preview shows no text in a scan: OCR may still be running (Processing inbox) or was not installed on the server (Administration, OCR and converters)."));
body.push(bullet("A share link does not work: it may have expired, hit its download cap, or been revoked (Chapter 12)."));
body.push(bullet("Upload rejected: the file type may be blocked by policy or exceed your quota (Settings shows usage)."));
body.push(h2("27.2 Glossary"));
body.push(tableTitle("Table 11 — Glossary"));
body.push(table(["Term", "Meaning"], [
  ["ACL", "Access control list: the grants that decide who can read, write, or manage a folder or document."],
  ["Check-out", "A lock taken while editing so nobody else replaces the file; released on check-in."],
  ["Collective", "A tenant: an isolated workspace with its own users and settings."],
  ["Confirmation queue", "The processing inbox where captured items wait for a human to confirm their metadata."],
  ["Hot folder", "A watched directory whose files are imported into the repository automatically."],
  ["Invite code", "A token that lets a person join a specific collective by self-registration."],
  ["IDP", "Intelligent document processing: extracting values from zones of recurring forms."],
  ["JOEX", "The background job executor that runs the processing pipeline."],
  ["Legal hold", "A freeze that prevents deletion of specific documents."],
  ["PAdES", "The standard for cryptographic signatures embedded in PDF files."],
  ["Retention", "A policy defining how long documents are kept before archival or defensible destruction."],
  ["Share link", "A tokenized URL giving external people view, comment, or download access."],
  ["TOTP", "Time-based one-time passwords: six-digit codes from an authenticator app."],
  ["Version", "A numbered, immutable snapshot of a document's file."],
  ["WOPI", "The protocol that lets Office Online, Collabora, or OnlyOffice edit repository files."],
], [22, 78]));
body.push(p("NewtonEDMS — every file, found and governed."));

/* ── Assemble document ────────────────────────────────────────────────── */
const pgSize = { width: 11906, height: 16838 };
const pgMargin = { top: 1440, bottom: 1440, left: 1701, right: 1417 };

const doc = new Document({
  styles: {
    default: {
      document: {
        run: { font: EN, size: 24, color: P.body },
        paragraph: { spacing: { line: 312 } },
      },
      heading1: {
        run: { font: EN, size: 32, bold: true, color: P.primary },
        paragraph: { spacing: { before: 400, after: 180, line: 312 }, outlineLevel: 0 },
      },
      heading2: {
        run: { font: EN, size: 28, bold: true, color: P.primary },
        paragraph: { spacing: { before: 280, after: 140, line: 312 }, outlineLevel: 1 },
      },
    },
  },
  sections: [
    { /* Section 1: cover — no page number, no footer */
      properties: { page: { size: pgSize, margin: { top: 0, bottom: 0, left: 0, right: 0 } } },
      children: buildCoverR1({
        title: "NewtonEDMS User Manual",
        subtitle: "Every file, found and governed",
        englishLabel: "USER MANUAL",
        metaLines: [
          "Version 2.1 — August 2026",
          "Complete reference: capture, governance, sharing, administration",
          "For users and administrators",
        ],
        footerLeft: "NewtonEDMS",
        footerRight: "Documentation",
      }),
    },
    { /* Section 2: front matter (TOC) — Roman numerals */
      properties: {
        type: SectionType.NEXT_PAGE,
        page: { size: pgSize, margin: pgMargin, pageNumbers: { start: 1, formatType: NumberFormat.UPPER_ROMAN } },
      },
      footers: { default: pageFooter() },
      children: [
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { before: 480, after: 360 },
          children: [new TextRun({ text: "Table of Contents", bold: true, size: 32, font: EN, color: P.primary })],
        }),
        new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
        new Paragraph({
          spacing: { before: 200 },
          children: [new TextRun({
            text: "Note: This Table of Contents is generated via field codes. To ensure page number accuracy after editing, please right-click the TOC and select \"Update Field.\"",
            italics: true, size: 18, color: "888888", font: EN,
          })],
        }),
      ],
    },
    { /* Section 3: body — Arabic numerals from 1 */
      properties: {
        type: SectionType.NEXT_PAGE,
        page: { size: pgSize, margin: pgMargin, pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL } },
      },
      headers: { default: bodyHeader },
      footers: { default: pageFooter() },
      children: body,
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("Wrote " + OUT + " (" + buf.length + " bytes, " + figureNo + " figures)");
});
