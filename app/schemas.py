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


class ImportFolderCreate(BaseModel):
    name: str
    local_path: str
    target_folder_id: int
    recursive: bool = True
    delete_after_import: bool = False


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
