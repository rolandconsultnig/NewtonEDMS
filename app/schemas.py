"""Pydantic request/response schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RoleName = Literal["superadmin", "admin", "manager", "user"]


class Token(BaseModel):
    access_token: str
    token_type: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    role: str
    is_active: bool
    created_at: datetime | None
    totp_enabled: bool = False
    theme: str | None = "light"
    collective_id: int | None = None
    locale: str | None = "en"
    density: str | None = "standard"
    quota_bytes: int | None = 0
    last_login_at: datetime | None = None
    avatar: str | None = None


class SessionOut(BaseModel):
    user: UserOut | None = None


class UserCreate(BaseModel):
    username: str
    email: str | None = ""
    password: str
    role: RoleName = "user"


class UserUpdate(BaseModel):
    email: str | None = None
    role: RoleName | None = None
    is_active: bool | None = None


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None


class GroupCreate(BaseModel):
    name: str
    description: str | None = ""


class FolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: int | None
    is_public: bool
    created_by: int
    created_at: datetime | None
    kind: str | None = "folder"
    color: str | None = None
    quota_bytes: int | None = 0
    alias_of_id: int | None = None
    deleted_at: datetime | None = None
    collective_id: int | None = None


class FolderCreate(BaseModel):
    name: str
    parent_id: int
    is_public: bool = False


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    title: str
    folder_id: int
    current_version: int
    status: str
    checked_out_by: int | None
    size: int
    mime: str | None
    tags: str
    metadata: dict | None = Field(default_factory=dict, alias="metadata_json")
    created_by: int
    created_at: datetime | None
    updated_at: datetime | None
    content_hash: str | None = None
    correspondent_id: int | None = None
    concerning_id: int | None = None
    due_date: datetime | None = None
    item_date: datetime | None = None
    source: str | None = "upload"
    language: str | None = None
    notes: str | None = None
    processing_status: str | None = "pending"
    direction: str | None = None
    equipment: str | None = None
    custom_id: str | None = None
    duplicate_of: int | None = None
    deleted_at: datetime | None = None
    locked_by: int | None = None
    immutable: bool = False
    indexable: str | None = "indexable"
    rating: int | None = 0
    color: str | None = None
    page_count: int | None = 0
    alias_of_id: int | None = None
    file_password: bool = False
    confirmed: bool = False
    organization_id: int | None = None
    equipment_id: int | None = None
    source_id: int | None = None
    signed: bool = False
    legal_hold: bool = False
    case_id: int | None = None
    thumbnail_path: str | None = None
    pdf_file_path: str | None = None
    collective_id: int | None = None


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_number: int
    size: int
    comment: str | None
    created_by: int
    created_at: datetime | None


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    principal_type: str
    principal_id: int
    resource_type: str
    resource_id: int
    can_read: bool
    can_write: bool
    can_delete: bool
    can_manage: bool
    bits: int | None = 0


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    action: str
    resource_type: str | None
    resource_id: int | None
    details: str | None
    ip: str | None
    timestamp: datetime | None


class MetadataTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    fields: list | None
    created_by: int
    created_at: datetime | None


class MetadataTemplateCreate(BaseModel):
    name: str
    description: str | None = ""
    fields: list | None = []


class ImportFolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    local_path: str
    target_folder_id: int
    active: bool
    recursive: bool
    delete_after_import: bool
    created_by: int
    created_at: datetime | None
    last_scan: datetime | None
    protocol: str | None = "local"
    host: str | None = None
    port: int | None = None
    username: str | None = None
    remote_path: str | None = None


class ImportFolderCreate(BaseModel):
    name: str
    local_path: str = ""
    target_folder_id: int
    recursive: bool = True
    delete_after_import: bool = False
    protocol: str = "local"
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    remote_path: str | None = None


class EmailImportRequest(BaseModel):
    host: str
    port: int = 993
    username: str
    password: str
    mailbox: str = "INBOX"
    target_folder_id: int
    since_days: int = 30
    delete_after_import: bool = False


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    user_id: int
    username: str | None
    text: str
    page: int | None
    x: int | None
    y: int | None
    created_at: datetime | None
    author_name: str | None = None


class CommentCreate(BaseModel):
    text: str
    page: int | None = None
    x: int | None = None
    y: int | None = None


class ShareLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    document_id: int
    created_by: int
    expires_at: datetime | None
    max_downloads: int | None
    download_count: int
    created_at: datetime | None
    url: str | None
    name: str | None = None
    password_protected: bool = False
    kind: str = "download"


class RetentionPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    folder_id: int | None
    years: int
    action: str
    created_by: int
    created_at: datetime | None


class RetentionPolicyCreate(BaseModel):
    name: str
    folder_id: int | None = None
    years: int = 7
    action: str = "archive"


class ReportSummary(BaseModel):
    users: int
    groups: int
    folders: int
    documents: int
    total_size: int
    by_status: dict
    top_uploaders: list
    recent_downloads: int


class WorkflowStep(BaseModel):
    name: str
    assignee_role: str | None = None
    assignee_id: int | None = None
    assignee_ids: list[int] | None = []
    due_days: int | None = None
    sla_hours: int | None = None
    action: str | None = "approve"
    form_schema: list | None = []
    condition_expr: str | None = None


class WorkflowTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    routing_type: str | None = "sequential"
    steps: list | None
    graph: dict | None = None
    form_schema: list | None = None
    sla_hours: int | None = 24
    escalate_to_role: str | None = "manager"
    auto_approval_rule: str | None = None
    created_by: int
    created_at: datetime | None


class WorkflowTemplateCreate(BaseModel):
    name: str
    description: str | None = ""
    routing_type: str | None = "sequential"
    steps: list | None = []
    graph: dict | None = {}
    form_schema: list | None = []
    sla_hours: int | None = 24
    escalate_to_role: str | None = "manager"
    auto_approval_rule: str | None = None


class WorkflowInstanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    document_id: int
    status: str
    current_step: int
    current_node: str | None = None
    context: dict | None = None
    created_by: int
    created_at: datetime | None
    completed_at: datetime | None


class TaskCreate(BaseModel):
    title: str
    document_id: int | None = None
    assignee_id: int | None = None
    assignee_role: str | None = None
    due_at: datetime | None = None
    sla_hours: int | None = 24
    description: str | None = ""


class TaskAction(BaseModel):
    approved: bool = True
    action: str | None = "approve"  # 'approve', 'reject', 'reassign', 'delegate'
    comment: str | None = ""
    form_data: dict | None = {}
    signature: str | None = None
    reassign_to_id: int | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instance_id: int
    step_index: int
    step_name: str
    routing_type: str | None = "sequential"
    assignee_id: int | None
    assignee_role: str | None = None
    assignee_username: str | None
    document_id: int | None
    status: str
    action_taken: str | None = None
    comment: str | None
    form_data: dict | None = None
    form_schema: list | None = None
    signature: str | None = None
    sla_hours: int | None = None
    escalated: bool | None = False
    escalated_to_id: int | None = None
    escalated_at: datetime | None = None
    node_id: str | None = None
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime | None


class WorkflowTransitionLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instance_id: int
    document_id: int
    task_id: int | None = None
    from_state: str | None = None
    to_state: str | None = None
    action: str
    actor_id: int | None = None
    actor_name: str | None = None
    comment: str | None = None
    form_data: dict | None = None
    signature: str | None = None
    created_at: datetime | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    message: str
    read: bool
    created_at: datetime | None


class CalendarEventCreate(BaseModel):
    title: str
    description: str | None = ""
    start_at: datetime
    end_at: datetime | None = None
    document_id: int | None = None


class CalendarEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    start_at: datetime
    end_at: datetime | None
    document_id: int | None
    created_by: int
    created_at: datetime | None


class FacetsOut(BaseModel):
    total: int
    by_status: dict
    by_mime: dict
    by_tag: dict
    by_extension: dict
    by_correspondent: dict = Field(default_factory=dict)
    by_source: dict = Field(default_factory=dict)
    overdue: int = 0


class CollectiveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    created_at: datetime | None
    language: str | None = "eng"
    invite_code: str | None = None


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str | None
    organization: str | None
    kind: str
    notes: str | None
    created_by: int
    created_at: datetime | None
    concerning_only: bool = False
    websites: list | None = None
    emails: list | None = None
    organization_id: int | None = None


class ContactCreate(BaseModel):
    name: str
    email: str | None = ""
    organization: str | None = ""
    kind: str = "both"
    notes: str | None = ""
    concerning_only: bool = False
    websites: list | None = None
    emails: list | None = None
    organization_id: int | None = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str | None


class TagCreate(BaseModel):
    name: str
    category: str | None = ""


class CustomFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    label: str | None
    ftype: str
    required: bool
    created_by: int
    created_at: datetime | None


class CustomFieldCreate(BaseModel):
    name: str
    label: str | None = ""
    ftype: str = "text"
    required: bool = False


class CustomFieldValueIn(BaseModel):
    field_id: int
    value: str


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    name: str
    size: int
    mime: str | None
    role: str


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    document_id: int | None
    status: str
    priority: int
    progress: float | None
    message: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class BookmarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    query: str
    user_id: int
    created_at: datetime | None
    kind: str | None = "query"
    resource_id: int | None = None


class BookmarkCreate(BaseModel):
    name: str
    query: str = ""
    kind: str = "query"
    resource_id: int | None = None


class DashboardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    layout: list | None
    is_default: bool
    user_id: int
    created_at: datetime | None


class DashboardCreate(BaseModel):
    name: str
    layout: list | None = None
    is_default: bool = False


class AnonymousUploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    name: str
    folder_id: int
    tags: str
    correspondent_id: int | None
    enabled: bool
    max_files: int
    upload_count: int
    created_by: int
    created_at: datetime | None
    expires_at: datetime | None
    url: str | None = None
    skip_duplicates: bool = False
    priority: int = 0
    language: str | None = None


class AnonymousUploadCreate(BaseModel):
    name: str
    folder_id: int
    tags: str = ""
    correspondent_id: int | None = None
    max_files: int = 50
    expires_days: int | None = 30
    skip_duplicates: bool = False
    priority: int = 0
    language: str | None = None


class MailSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    kind: str
    name: str
    host: str
    port: int
    username: str | None
    use_ssl: bool
    mailbox: str | None
    created_at: datetime | None


class MailSettingsCreate(BaseModel):
    kind: Literal["smtp", "imap"]
    name: str
    host: str
    port: int = 587
    username: str | None = ""
    password: str | None = ""
    use_ssl: bool = True
    mailbox: str = "INBOX"


class SendMailRequest(BaseModel):
    document_ids: list[int]
    to: str
    cc: str | None = None
    subject: str
    body: str = ""
    settings_id: int | None = None
    attach_pdf: bool = False
    template_id: int | None = None


class NotificationRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    query: str
    channel: str
    interval_hours: int
    last_run: datetime | None
    enabled: bool
    created_at: datetime | None


class NotificationRuleCreate(BaseModel):
    name: str
    query: str
    channel: str = "inapp"
    interval_hours: int = 24


class AddonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    event: str
    webhook_url: str | None = ""
    enabled: bool
    created_by: int
    created_at: datetime | None
    trigger: str | None = "on_process"
    sandbox: str | None = "subprocess"


class AddonCreate(BaseModel):
    name: str
    event: str = "on_process"
    webhook_url: str = ""


class BulkEditRequest(BaseModel):
    ids: list[int]
    tags: str | None = None
    folder_id: int | None = None
    status: str | None = None
    correspondent_id: int | None = None
    concerning_id: int | None = None
    due_date: datetime | None = None
    notes: str | None = None


class MergeRequest(BaseModel):
    ids: list[int]
    title: str | None = None
    folder_id: int | None = None
    attachment_ids: list[int] | None = None


class QueryParseOut(BaseModel):
    filters: dict
    fulltext: str
    raw: str


class SuggestOut(BaseModel):
    tags: list[str]
    contacts: list[ContactOut]
    dates: list[str]
    language: str | None = None


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_url: str
    enabled: bool


class ThemeUpdate(BaseModel):
    theme: Literal["light", "dark"]


# =============================================================================
# Legal Practice Management & Corporate Legal Schemas
# =============================================================================


class MatterCreate(BaseModel):
    matter_number: str
    title: str
    client_name: str
    client_id: str | None = None
    practice_area: str = "General Litigation"
    lead_attorney_id: int | None = None
    court_name: str | None = None
    case_caption: str | None = None
    judge_name: str | None = None
    opposing_counsel: str | None = None
    billing_code: str | None = None
    description: str | None = None
    metadata_json: dict | None = None


class MatterUpdate(BaseModel):
    title: str | None = None
    client_name: str | None = None
    client_id: str | None = None
    practice_area: str | None = None
    lead_attorney_id: int | None = None
    status: str | None = None
    court_name: str | None = None
    case_caption: str | None = None
    judge_name: str | None = None
    opposing_counsel: str | None = None
    billing_code: str | None = None
    description: str | None = None
    metadata_json: dict | None = None


class MatterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    matter_number: str
    title: str
    client_name: str
    client_id: str | None = None
    practice_area: str
    lead_attorney_id: int | None = None
    status: str
    billing_code: str | None = None
    court_name: str | None = None
    case_caption: str | None = None
    judge_name: str | None = None
    opposing_counsel: str | None = None
    description: str | None = None
    metadata_json: dict | None = None
    created_by: int
    created_at: datetime | None = None
    closed_at: datetime | None = None


class MatterDocumentAttach(BaseModel):
    document_id: int
    category: str = "pleading"  # pleading, discovery, correspondence, contract, exhibit, court_order, memo
    confidentiality: str = "confidential"
    bates_range: str | None = None
    notes: str | None = None
    pinned: bool = False


class MatterDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    matter_id: int
    document_id: int
    category: str
    bates_range: str | None = None
    confidentiality: str
    pinned: bool
    notes: str | None = None
    added_by: int
    added_at: datetime | None = None


class EthicalWallCreate(BaseModel):
    matter_id: int
    walled_user_ids: list[int]
    reason: str
    walled_group_ids: list[int] | None = None
    client_name: str | None = None


class EthicalWallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    matter_id: int
    client_name: str | None = None
    walled_user_ids: list[int] | None = None
    walled_group_ids: list[int] | None = None
    reason: str
    active: bool
    created_by: int
    created_at: datetime | None = None


class LegalTemplateCreate(BaseModel):
    name: str
    category: str = "contract"
    description: str | None = None
    content_template: str
    fields_schema: list[dict] | None = None


class LegalTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    description: str | None = None
    content_template: str
    fields_schema: list[dict] | None = None
    created_by: int
    created_at: datetime | None = None


class LegalAssemblyRequest(BaseModel):
    template_id: int
    matter_id: int
    variables: dict = {}
    document_title: str | None = None
    output_format: str = "pdf"
    folder_id: int = 1


class BatesApplyRequest(BaseModel):
    matter_id: int
    document_ids: list[int]
    production_set: str = "PROD-001"
    prefix: str = "PLTF"
    suffix: str = ""
    start_number: int = 1
    pad_length: int = 6
    position: str = "bottom-right"
    disclaimer_text: str | None = None


class BatesProductionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    matter_id: int
    production_set: str
    prefix: str
    suffix: str | None = None
    start_number: int
    end_number: int
    total_pages: int
    position: str
    disclaimer_text: str | None = None
    document_ids: list[int] | None = None
    created_by: int
    created_at: datetime | None = None


class LegalCompareRequest(BaseModel):
    doc_id_a: int
    doc_id_b: int | None = None
    version_num_a: int | None = None
    version_num_b: int | None = None


class PermanentRedactRequest(BaseModel):
    patterns: list[str] | None = None
    builtin_presets: list[str] | None = None
    bounding_boxes: list[dict] | None = None
    save_as_new: bool = True


class EFilingPackageRequest(BaseModel):
    matter_id: int
    pleading_doc_id: int
    exhibit_doc_ids: list[int] = []
    package_name: str | None = None
    filing_jurisdiction: str | None = None


class SecurePortalCreate(BaseModel):
    matter_id: int
    document_ids: list[int]
    recipient_email: str
    recipient_name: str | None = None
    password: str | None = None
    watermark_text: str | None = "CONFIDENTIAL FOR CLIENT REVIEW"
    allow_download: bool = True
    expires_in_days: int = 7


class SecurePortalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    matter_id: int
    document_ids: list[int] | None = None
    recipient_email: str
    recipient_name: str | None = None
    watermark_text: str | None = None
    allow_download: bool
    expires_at: datetime | None = None
    access_count: int
    created_at: datetime | None = None


# =============================================================================
# ACCOUNTING & FINANCIAL EDMS SCHEMAS
# =============================================================================


class PurchaseOrderCreate(BaseModel):
    po_number: str
    vendor_name: str
    total_amount: float = 0.0
    currency: str = "USD"
    status: str = "issued"
    line_items: list[dict[str, Any]] = Field(default_factory=list)


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    po_number: str
    vendor_name: str
    total_amount: float
    currency: str
    status: str
    line_items: list[dict[str, Any]] | None = None
    created_at: datetime | None = None


class GoodsReceivedNoteCreate(BaseModel):
    grn_number: str
    po_number: str
    vendor_name: str
    received_date: datetime | None = None
    line_items: list[dict[str, Any]] = Field(default_factory=list)


class GoodsReceivedNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    grn_number: str
    po_number: str
    vendor_name: str
    received_date: datetime | None = None
    line_items: list[dict[str, Any]] | None = None
    created_at: datetime | None = None


class InvoiceRecordCreate(BaseModel):
    invoice_number: str
    vendor_name: str
    vendor_tax_id: str | None = None
    po_number: str | None = None
    grn_number: str | None = None
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total_amount: float = 0.0
    currency: str = "USD"
    invoice_date: datetime | None = None
    due_date: datetime | None = None
    gl_account: str | None = None
    cost_center: str | None = None
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    document_id: int | None = None


class InvoiceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_number: str
    vendor_name: str
    vendor_tax_id: str | None = None
    po_number: str | None = None
    grn_number: str | None = None
    subtotal: float
    tax_amount: float
    total_amount: float
    currency: str
    invoice_date: datetime | None = None
    due_date: datetime | None = None
    gl_account: str | None = None
    cost_center: str | None = None
    line_items: list[dict[str, Any]] | None = None
    matching_status: str
    matching_notes: str | None = None
    payment_status: str
    document_id: int | None = None
    is_duplicate: bool
    duplicate_of_id: int | None = None
    peppol_validated: bool
    created_at: datetime | None = None


class AuditorPortalCreate(BaseModel):
    auditor_name: str
    auditor_email: str
    firm_name: str | None = None
    sample_document_ids: list[int] = Field(default_factory=list)
    allowed_gl_accounts: list[str] = Field(default_factory=list)
    password: str
    expires_in_days: int = 14


class AuditorPortalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    auditor_name: str
    auditor_email: str
    firm_name: str | None = None
    sample_document_ids: list[int] | None = None
    allowed_gl_accounts: list[str] | None = None
    expires_at: datetime | None = None
    access_count: int
    created_at: datetime | None = None


class ERPIntegrationCreate(BaseModel):
    platform: str  # sap, netsuite, quickbooks, xero, sage
    company_id: str | None = None
    endpoint_url: str | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# INSURANCE & CLAIMS MANAGEMENT SCHEMAS
# =============================================================================


class InsurancePolicyCreate(BaseModel):
    policy_number: str
    insured_name: str
    policy_type: str = "auto"
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    premium: float = 0.0
    deductible: float = 500.0
    coverage_limit: float = 100000.0
    status: str = "active"
    master_policy_id: int | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class InsurancePolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    policy_number: str
    insured_name: str
    policy_type: str
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    premium: float
    deductible: float
    coverage_limit: float
    status: str
    master_policy_id: int | None = None
    metadata_json: dict[str, Any] | None = None
    created_at: datetime | None = None


class InsuranceClaimCreate(BaseModel):
    claim_number: str
    policy_id: int
    claimant_name: str
    loss_date: datetime | None = None
    loss_type: str = "collision"
    loss_location: str | None = None
    estimated_loss: float = 0.0
    notes: str | None = None


class InsuranceClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_number: str
    policy_id: int
    claimant_name: str
    loss_date: datetime | None = None
    loss_type: str
    loss_location: str | None = None
    estimated_loss: float
    settlement_amount: float
    assigned_adjuster_id: int | None = None
    status: str
    auto_approved: bool
    fraud_score: int
    fraud_flags: list[str] | None = None
    notes: str | None = None
    created_at: datetime | None = None


class ClaimEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_id: int
    document_id: int
    evidence_type: str
    exif_metadata: dict[str, Any] | None = None
    image_hash: str | None = None
    is_fraud_flagged: bool
    notes: str | None = None
    created_at: datetime | None = None


class ClaimPortalShareCreate(BaseModel):
    claim_id: int
    recipient_email: str
    recipient_name: str | None = None
    recipient_role: str = "policyholder"
    password: str
    expires_in_days: int = 14


class ClaimPortalShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    claim_id: int
    recipient_email: str
    recipient_name: str | None = None
    recipient_role: str
    expires_at: datetime | None = None
    access_count: int
    created_at: datetime | None = None


# =============================================================================
# HEALTHCARE & CLINICAL EDMS SCHEMAS
# =============================================================================


class PatientCreate(BaseModel):
    mrn: str
    first_name: str
    last_name: str
    dob: datetime
    gender: str = "U"
    blood_type: str | None = None
    primary_physician: str | None = None
    insurance_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mrn: str
    first_name: str
    last_name: str
    dob: datetime
    gender: str
    blood_type: str | None = None
    primary_physician: str | None = None
    insurance_id: str | None = None
    is_active: bool
    created_at: datetime | None = None


class PatientEncounterCreate(BaseModel):
    encounter_number: str
    patient_id: int
    encounter_type: str = "inpatient"
    admission_date: datetime | None = None
    department: str | None = None
    attending_physician: str | None = None
    chief_complaint: str | None = None


class PatientEncounterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    encounter_number: str
    patient_id: int
    encounter_type: str
    admission_date: datetime
    discharge_date: datetime | None = None
    department: str | None = None
    attending_physician: str | None = None
    chief_complaint: str | None = None
    status: str
    created_at: datetime | None = None


class MedicalDocumentCreate(BaseModel):
    patient_id: int
    encounter_id: int | None = None
    document_id: int
    clinical_category: str = "clinical_note"
    sensitivity_level: str = "standard"
    icd10_codes: list[str] = Field(default_factory=list)


class MedicalDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    encounter_id: int | None = None
    document_id: int
    clinical_category: str
    sensitivity_level: str
    icd10_codes: list[str] | None = None
    is_signed: bool
    signed_by_physician: str | None = None
    signed_at: datetime | None = None
    created_at: datetime | None = None


class DicomStudyCreate(BaseModel):
    study_instance_uid: str
    patient_id: int
    document_id: int
    modality: str = "CT"
    body_part_examined: str | None = None
    series_count: int = 1
    instance_count: int = 1
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class DicomStudyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_instance_uid: str
    patient_id: int
    document_id: int
    modality: str
    body_part_examined: str | None = None
    series_count: int
    instance_count: int
    metadata_json: dict[str, Any] | None = None
    created_at: datetime | None = None


class BreakGlassCreate(BaseModel):
    patient_id: int
    document_id: int | None = None
    emergency_rationale: str


class BreakGlassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clinician_id: int
    patient_id: int
    document_id: int | None = None
    emergency_rationale: str
    workstation_ip: str | None = None
    alert_sent: bool
    reviewed_by_compliance: bool
    timestamp: datetime


class InformedConsentCreate(BaseModel):
    patient_id: int
    encounter_id: int | None = None
    consent_type: str = "surgical"
    procedure_name: str
    signer_name: str
    signer_relationship: str = "patient"
    signature_data: str
    witness_name: str | None = None


class InformedConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    encounter_id: int | None = None
    consent_type: str
    procedure_name: str
    signer_name: str
    signer_relationship: str
    witness_name: str | None = None
    signed_at: datetime
