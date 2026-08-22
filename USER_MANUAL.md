# NewtonEDMS — Enterprise Document Management System
## Comprehensive User Manual & Administrator Guide

Welcome to the official User Manual for **NewtonEDMS**, a modern, high-performance, and secure enterprise document management system built with Python FastAPI, SQLite/PostgreSQL, and ultra-modern web technologies.

---

## Table of Contents
1. [System Overview & Architecture](#1-system-overview--architecture)
2. [Authentication & Biometrics Security](#2-authentication--biometrics-security)
3. [Dashboard & Operational Analytics](#3-dashboard--operational-analytics)
4. [Document Management & Repository Workspace](#4-document-management--repository-workspace)
5. [Workflows, Tasks & Approvals Engine](#5-workflows-tasks--approvals-engine)
6. [Specialized Industry Enterprise Suites](#6-specialized-industry-enterprise-suites)
7. [Enterprise Protocols & Integrations](#7-enterprise-protocols--integrations)
8. [Administration, Security & Auditing](#8-administration-security--auditing)

---

## 1. System Overview & Architecture

NewtonEDMS is engineered to provide end-to-end lifecycle management for enterprise documents, records, and business workflows across all industries.

![Enterprise Overview](/static/img/manual_dashboard.jpg)

### Core Capabilities
- **High-Throughput Ingestion**: Batch drag-and-drop, scanner capture, email-to-folder gateway, and automated hot folder polling.
- **Deep Search & Intelligence**: OCR engine (Tesseract), full-text token search, vector embeddings, and AI RAG document question answering.
- **Collaboration & Office Integration**: Microsoft Office 365 WOPI editor, Office Desktop Add-in, WebDAV file mounts, and real-time live presence.
- **Compliance & Security**: Biometric FIDO2/WebAuthn authentication, AES-256 encrypted storage, full audit trails, and strict path traversal protection.

---

## 2. Authentication & Biometrics Security

NewtonEDMS features enterprise security protocols to defend against unauthorized intrusion, credential theft, and brute-force attacks.

### 2.1 Passwordless Biometric Login (WebAuthn / Passkeys)
Users can enroll their device's built-in biometric sensors (such as **Windows Hello**, **Apple Touch ID / Face ID**, **Android Biometrics**, or **YubiKey hardware tokens**) for seamless, unphishable passwordless login.

#### How to Enroll Biometrics:
1. Log into your account and open **Settings** from the user avatar menu.
2. Locate the **Biometrics & Passkeys** section.
3. Click **"+ Register This Device"**.
4. When prompted by your operating system or browser, confirm with your fingerprint, face scan, or security key PIN.
5. Your passkey is instantly registered and bound to your hardware.

#### How to Sign In with Biometrics:
1. On the login screen, click **"Sign in with Biometrics / Passkey"**.
2. Perform the biometric verification prompt on your device.
3. You will immediately be authenticated into your workspace without typing any password.

### 2.2 Security Hardening & Breach Protection
- **Account Lockout Protection**: Automatic exponential lockout after 5 consecutive failed authentication attempts.
- **Path Traversal Protection**: Multi-layer inspection blocking directory escape attempts (e.g. `../` and `%2e%2e`).
- **Defensive HTTP Headers**: Content-Security-Policy (CSP), Strict-Transport-Security (HSTS), X-Frame-Options (`DENY`/`SAMEORIGIN`), X-Content-Type-Options (`nosniff`), and strict Referrer Policies.
- **Two-Factor Authentication (TOTP)**: Google Authenticator and Microsoft Authenticator support.

---

## 3. Dashboard & Operational Analytics

The Dashboard delivers real-time visibility into document repository volume, pending approvals, and scheduled events.

### Key Components:
- **Repository Metrics**: Live count of total documents, storage consumption, active folders, and classification status.
- **Task Pipeline Queue**: Fast-action cards allowing one-click review, approval, or rejection of pending workflow items.
- **Interactive Calendar & Scheduler**: Click any date in the calendar to view scheduled deadlines or click **"+ Add Event"** to schedule multiple events, meetings, or retention deadlines on a single date.
- **Real-Time Notification Bell**: Located at the top right of the navigation header, displaying unread workflow alerts and audit events.

---

## 4. Document Management & Repository Workspace

The Document Repository provides an intuitive three-pane interface for browsing, searching, previewing, and managing files.

![Document Management Workspace](/static/img/manual_documents.jpg)

### 4.1 Folder Navigation & Tree
- **Hierarchy Tree**: Expandable left navigation pane supporting nested workspaces, departmental folders, and shared collections.
- **Folder Actions**: Right-click or use the action bar to create new subfolders, set custom colors, assign access permissions (ACLs), or export as a ZIP archive.

### 4.2 Document Operations & Preview
- **Uploads**: Drag and drop any file format (PDF, Word, Excel, PowerPoint, Images, Audio, Video, DICOM).
- **Document Inspector Panel**:
  - **Properties**: File size, MIME type, owner, creation date, and last modified date.
  - **Metadata & Tags**: Custom metadata fields, confidentiality ratings, and keyword tags.
  - **Version History**: View past versions, download historical snapshots, or restore previous drafts.
  - **Live Office Editing**: Click "Edit in Office" to open Microsoft 365 Word/Excel/PowerPoint directly in the browser via WOPI.

---

## 5. Workflows, Tasks & Approvals Engine

Automate document review, validation, and multi-stage sign-offs with built-in SLA tracking.

![Workflow & Approvals](/static/img/manual_workflows.jpg)

### 5.1 Creating a Custom Task
1. Navigate to the **Tasks** tab in the top navigation bar.
2. Click the **"+ Add New Task"** button in the top right.
3. Fill out the task details:
   - **Task Title & Description**: State the objective (e.g., "Review Q3 Vendor Agreement").
   - **Assignee / Role**: Select a specific team member or entire department role (e.g., `legal`, `manager`, `accounting`).
   - **Linked Document**: Optionally select the document requiring review.
   - **Priority**: Set as `Low`, `Medium`, `High`, or `Urgent`.
   - **SLA Due Date**: Set target completion date and time.
4. Click **Create Task**. The assignee receives an immediate notification alert.

### 5.2 Approving & Completing Tasks
- Reviewers can view task details, examine the attached document, leave review comments, and click **Approve** or **Reject**.
- All workflow actions are recorded in the immutable audit log.

---

## 6. Specialized Industry Enterprise Suites

NewtonEDMS includes ready-to-deploy vertical industry suites accessible under the **Administration** hub.

![Industry Enterprise Suites](/static/img/manual_suites.jpg)

### 6.1 Legal Suite
- **Matter Management**: Organize case records, depositions, and exhibits by legal matter.
- **Bates Stamping**: Automated multi-page sequential Bates numbering with customizable prefix, suffix, and placement.
- **Privilege Logs & Holds**: Apply legal hold protection preventing modification or deletion of sensitive evidence.

### 6.2 Accounting & Finance Suite
- **3-Way Invoice Matching**: Automated verification matching Purchase Orders (PO), Goods Receipts, and Vendor Invoices.
- **AP Processing**: Approval routing, payment authorization, and ledger export.

### 6.3 Healthcare Suite (PACS / HL7)
- **DICOM Viewer**: Native web-based medical imaging viewer for X-rays, CT scans, and MRIs.
- **HL7 & FHIR Studio**: Ingest and process patient clinical messages, observations, and electronic health records.

### 6.4 Insurance Claims Suite
- **FNOL Intake**: First Notice of Loss incident intake with policy binding, photos, and police reports.
- **Claims Portfolio**: Reserve estimation, adjuster assignment, and settlement tracking.

---

## 7. Enterprise Protocols & Integrations

NewtonEDMS exposes standard enterprise protocol endpoints for integration with existing corporate infrastructure:

| Protocol / Standard | Endpoint | Description |
| :--- | :--- | :--- |
| **Microsoft WOPI** | `/wopi/files/{id}` | High-fidelity Office 365, Teams, and OnlyOffice document co-authoring. |
| **WebDAV** | `/webdav/` | Mount NewtonEDMS as a native network drive in Windows Explorer and macOS Finder. |
| **CMIS 1.1** | `/cmis/atom` & `/cmis/browser` | OASIS Content Management Interoperability Services standard. |
| **SOAP Web Services** | `/soap/` | Legacy ERP / SAP / enterprise system integration. |
| **REST API** | `/api/` | Full modern OpenAPI 3.0 documented REST API (interactive docs at `/docs`). |

---

## 8. Administration, Security & Auditing

Administrators have granular control over system configuration, user identity, and compliance monitoring.

- **User & Group RBAC**: Create users, define role privileges (`superadmin`, `admin`, `manager`, `user`), and assign department groups.
- **Audit Trails**: Real-time logging of all document views, downloads, uploads, permission modifications, and biometric logins.
- **Automated Backup & Export**: Scheduled retention policies, trash purge, and full repository archive exports.

---

### Need Further Assistance?
- **API Reference**: Access the interactive Swagger UI at `/docs` or ReDoc at `/redoc`.
- **System Health**: Check real-time service health at `/api/system/health`.
