"""Pydantic request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Token(BaseModel):
    access_token: str
    token_type: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str]
    role: str
    is_active: bool
    created_at: Optional[datetime]


class UserCreate(BaseModel):
    username: str
    email: Optional[str] = ""
    password: str
    role: str = "user"


class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]


class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = ""


class FolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: Optional[int]
    is_public: bool
    created_by: int
    created_at: Optional[datetime]


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
    checked_out_by: Optional[int]
    size: int
    mime: Optional[str]
    tags: str
    metadata: Optional[dict] = Field(default_factory=dict, alias="metadata_json")
    created_by: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_number: int
    size: int
    comment: Optional[str]
    created_by: int
    created_at: Optional[datetime]


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
    user_id: Optional[int]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[int]
    details: Optional[str]
    ip: Optional[str]
    timestamp: Optional[datetime]


class MetadataTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    fields: Optional[list]
    created_by: int
    created_at: Optional[datetime]


class MetadataTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    fields: Optional[list] = []


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
    created_at: Optional[datetime]
    last_scan: Optional[datetime]


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
    username: Optional[str]
    text: str
    page: Optional[int]
    x: Optional[int]
    y: Optional[int]
    created_at: Optional[datetime]


class CommentCreate(BaseModel):
    text: str
    page: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None


class ShareLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    document_id: int
    created_by: int
    expires_at: Optional[datetime]
    max_downloads: Optional[int]
    download_count: int
    created_at: Optional[datetime]
    url: Optional[str]


class RetentionPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    folder_id: Optional[int]
    years: int
    action: str
    created_by: int
    created_at: Optional[datetime]


class RetentionPolicyCreate(BaseModel):
    name: str
    folder_id: Optional[int] = None
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
    assignee_role: Optional[str] = None
    assignee_id: Optional[int] = None
    due_days: Optional[int] = None
    action: Optional[str] = "approve"


class WorkflowTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    steps: Optional[list]
    created_by: int
    created_at: Optional[datetime]


class WorkflowTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    steps: Optional[list] = []


class WorkflowInstanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    document_id: int
    status: str
    current_step: int
    created_by: int
    created_at: Optional[datetime]
    completed_at: Optional[datetime]


class TaskAction(BaseModel):
    approved: bool = True
    comment: Optional[str] = ""


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instance_id: int
    step_index: int
    step_name: str
    assignee_id: Optional[int]
    assignee_username: Optional[str]
    document_id: Optional[int]
    status: str
    comment: Optional[str]
    due_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: Optional[datetime]


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    message: str
    read: bool
    created_at: Optional[datetime]


class CalendarEventCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    start_at: datetime
    end_at: Optional[datetime] = None
    document_id: Optional[int] = None


class CalendarEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str]
    start_at: datetime
    end_at: Optional[datetime]
    document_id: Optional[int]
    created_by: int
    created_at: Optional[datetime]


class FacetsOut(BaseModel):
    total: int
    by_status: dict
    by_mime: dict
    by_tag: dict
    by_extension: dict
