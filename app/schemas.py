"""Pydantic request/response schemas."""

from datetime import datetime
from typing import Literal

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
    due_days: int | None = None
    action: str | None = "approve"


class WorkflowTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    steps: list | None
    graph: dict | None = None
    created_by: int
    created_at: datetime | None


class WorkflowTemplateCreate(BaseModel):
    name: str
    description: str | None = ""
    steps: list | None = []


class WorkflowInstanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    document_id: int
    status: str
    current_step: int
    current_node: str | None = None
    created_by: int
    created_at: datetime | None
    completed_at: datetime | None


class TaskAction(BaseModel):
    approved: bool = True
    comment: str | None = ""


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instance_id: int
    step_index: int
    step_name: str
    assignee_id: int | None
    assignee_username: str | None
    document_id: int | None
    status: str
    comment: str | None
    node_id: str | None = None
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime | None


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
