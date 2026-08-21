"""SQLAlchemy ORM models — LogicalDoc repository + Docspell intelligence."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base, now

user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("group_id", ForeignKey("groups.id"), primary_key=True),
)


class Collective(Base):
    """Docspell-style multi-account container (one org / household / team)."""

    __tablename__ = "collectives"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=now)
    language = Column(String, default="eng")
    classifier_config = Column(JSON, default=dict)
    invite_code = Column(String, unique=True, index=True)
    settings = Column(JSON, default=dict)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user", nullable=False)  # superadmin, admin, manager, user
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)
    groups = relationship("Group", secondary=user_groups, back_populates="users")
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=True)
    totp_secret = Column(String)
    totp_enabled = Column(Boolean, default=False)
    theme = Column(String, default="light")  # light | dark
    avatar = Column(String)
    locale = Column(String, default="en")
    density = Column(String, default="standard")  # compact | standard | comfortable
    quota_bytes = Column(Integer, default=0)  # 0 = unlimited
    last_login_at = Column(DateTime)
    working_hours = Column(JSON, default=dict)
    ldap_dn = Column(String)
    ui_settings = Column(JSON, default=dict)
    oidc_sub = Column(String, index=True)
    password_changed_at = Column(DateTime, default=now)
    failed_logins = Column(Integer, default=0)
    locked_until = Column(DateTime)


class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    description = Column(String)
    users = relationship("User", secondary=user_groups, back_populates="groups")


class Folder(Base):
    __tablename__ = "folders"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    is_public = Column(Boolean, default=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    parent = relationship("Folder", remote_side=[id], foreign_keys=[parent_id], backref="children")
    kind = Column(String, default="folder")  # folder | workspace
    color = Column(String)
    quota_bytes = Column(Integer, default=0)
    max_children = Column(Integer, default=0)
    deleted_at = Column(DateTime)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    alias_of_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    template_id = Column(Integer, nullable=True)
    interface_opts = Column(JSON, default=dict)
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=True)


class Contact(Base):
    """Address-book entry used as correspondent / concerning person (Docspell)."""

    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    email = Column(String)
    organization = Column(String)
    kind = Column(String, default="both")  # correspondent, concerning, both
    notes = Column(String)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    concerning_only = Column(Boolean, default=False)
    websites = Column(JSON, default=list)
    emails = Column(JSON, default=list)
    channels = Column(JSON, default=list)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=True)


class Tag(Base):
    """Canonical tag catalog used for auto-tagging from extracted text."""

    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    category = Column(String)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=True)


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    title = Column(String, nullable=False, default="")
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    current_version = Column(Integer, default=1)
    status = Column(String, default="draft")  # draft, review, approved, published, archived
    checked_out_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    size = Column(Integer, default=0)
    mime = Column(String)
    file_path = Column(String, nullable=False)
    tags = Column(String, default="")
    metadata_json = Column("metadata", JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
    # Docspell-inspired item metadata
    content_hash = Column(String, index=True)
    correspondent_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    concerning_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    due_date = Column(DateTime)
    item_date = Column(DateTime)
    source = Column(String, default="upload")  # upload, email, imap, scan, import, anonymous
    language = Column(String)
    notes = Column(Text)
    original_file_path = Column(String)  # untouched original (non-destructive)
    pdf_file_path = Column(String)
    processing_status = Column(String, default="pending")  # pending, processing, done, error
    direction = Column(String)  # incoming, outgoing
    equipment = Column(String)
    custom_id = Column(String, index=True)
    extracted_text = Column(Text)
    duplicate_of = Column(Integer, ForeignKey("documents.id"), nullable=True)
    deleted_at = Column(DateTime)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    locked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    immutable = Column(Boolean, default=False)
    file_password_hash = Column(String)
    indexable = Column(String, default="indexable")  # indexable | metadata | unindexable
    rating = Column(Integer, default=0)
    color = Column(String)
    page_count = Column(Integer, default=0)
    alias_of_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    signed = Column(Boolean, default=False)
    confirmed = Column(Boolean, default=False)
    confirmed_at = Column(DateTime)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=True)
    source_id = Column(Integer, ForeignKey("anonymous_uploads.id"), nullable=True)
    thumbnail_path = Column(String)
    legal_hold = Column(Boolean, default=False)
    case_id = Column(Integer, nullable=True)
    collab_rev = Column(Integer, default=0)
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    file_path = Column(String, nullable=False)
    size = Column(Integer, default=0)
    comment = Column(String)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class DocumentAttachment(Base):
    """Extra files attached to a document item (Docspell multi-file items)."""

    __tablename__ = "document_attachments"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    size = Column(Integer, default=0)
    mime = Column(String)
    role = Column(String, default="extracted")  # original, converted, extracted, preview
    created_at = Column(DateTime, default=now)


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True, index=True)
    principal_type = Column(String, nullable=False)  # user, group
    principal_id = Column(Integer, nullable=False)
    resource_type = Column(String, nullable=False)  # folder, document
    resource_id = Column(Integer, nullable=False)
    can_read = Column(Boolean, default=False)
    can_write = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)
    can_manage = Column(Boolean, default=False)
    bits = Column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    resource_type = Column(String)
    resource_id = Column(Integer)
    details = Column(Text)
    ip = Column(String)
    timestamp = Column(DateTime, default=now)


class MetadataTemplate(Base):
    __tablename__ = "metadata_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    description = Column(String)
    fields = Column(JSON, default=list)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class CustomField(Base):
    """Typed custom fields (Docspell) distinct from JSON metadata blobs."""

    __tablename__ = "custom_fields"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    label = Column(String)
    ftype = Column(String, default="text")  # text, number, date, bool, money
    required = Column(Boolean, default=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=True)


class CustomFieldValue(Base):
    __tablename__ = "custom_field_values"
    id = Column(Integer, primary_key=True, index=True)
    field_id = Column(Integer, ForeignKey("custom_fields.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    value = Column(String)


class ImportFolder(Base):
    __tablename__ = "import_folders"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    local_path = Column(String, nullable=False)
    target_folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    active = Column(Boolean, default=True)
    recursive = Column(Boolean, default=True)
    delete_after_import = Column(Boolean, default=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    last_scan = Column(DateTime)
    protocol = Column(String, default="local")  # local | ftp | smb
    host = Column(String)
    port = Column(Integer)
    username = Column(String)
    password_enc = Column(String)
    remote_path = Column(String)


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    page = Column(Integer)
    x = Column(Integer)
    y = Column(Integer)
    created_at = Column(DateTime, default=now)
    # Set when the comment arrived via a public share page; the account in
    # user_id is then the share creator, not the person who wrote it.
    author_name = Column(String)


class ShareLink(Base):
    __tablename__ = "share_links"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    max_downloads = Column(Integer, nullable=True)
    download_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)
    password_hash = Column(String)
    name = Column(String)
    kind = Column(String, default="download")  # download | view | comment


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    years = Column(Integer, default=7)
    action = Column(String, default="archive")  # archive or delete
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String)
    routing_type = Column(String, default="sequential")  # sequential, parallel_all, parallel_any, bpmn
    steps = Column(JSON, default=list)
    graph = Column(JSON, default=dict)
    form_schema = Column(JSON, default=list)  # dynamic form fields schema
    sla_hours = Column(Integer, default=24)
    escalate_to_role = Column(String, default="manager")
    auto_approval_rule = Column(String, nullable=True)  # condition expr for instant auto-approval
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("workflow_templates.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    status = Column(String, default="running")  # running, completed, rejected, cancelled, escalated
    current_step = Column(Integer, default=0)
    current_node = Column(String)
    tokens = Column(JSON, default=list)
    context = Column(JSON, default=dict)
    variables = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    completed_at = Column(DateTime)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("workflow_instances.id"), nullable=False)
    step_index = Column(Integer, nullable=False)
    step_name = Column(String, nullable=False)
    node_id = Column(String)
    routing_type = Column(String, default="sequential")
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assignee_role = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, approved, rejected, skipped, escalated
    action_taken = Column(String, nullable=True)
    comment = Column(String)
    form_data = Column(JSON, default=dict)
    form_schema = Column(JSON, default=list)
    signature = Column(String, nullable=True)
    sla_hours = Column(Integer, nullable=True)
    escalated = Column(Boolean, default=False)
    escalated_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    due_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=now)


class WorkflowTransitionLog(Base):
    __tablename__ = "workflow_transition_logs"
    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("workflow_instances.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    task_id = Column(Integer, nullable=True)
    from_state = Column(String)
    to_state = Column(String)
    action = Column(String, nullable=False)  # SUBMIT, APPROVE, REJECT, ESCALATE, AUTO_APPROVE, REASSIGN, DELEGATE
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_name = Column(String)
    comment = Column(String)
    form_data = Column(JSON, default=dict)
    signature = Column(String, nullable=True)
    created_at = Column(DateTime, default=now)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(String, nullable=False)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class RevokedToken(Base):
    """A JWT identifier (``jti``) that has been invalidated before its expiry (e.g. logout)."""

    __tablename__ = "revoked_tokens"
    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    expires_at = Column(DateTime, nullable=False)  # original token expiry (UTC, naive)
    revoked_at = Column(DateTime, default=now)


class ProcessingJob(Base):
    """JOEX job queue: OCR, conversion, NLP, indexing, housekeeping."""

    __tablename__ = "processing_jobs"
    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False)  # process_document, notify_due, scan_mailbox, webhook
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    status = Column(String, default="queued")  # queued, running, done, error, cancelled
    priority = Column(Integer, default=0)
    progress = Column(Float, default=0.0)
    message = Column(Text)
    payload = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    log_text = Column(Text, default="")


class Bookmark(Base):
    """Saved query or starred folder/document."""

    __tablename__ = "bookmarks"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    query = Column(String, nullable=False, default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    kind = Column(String, default="query")  # query | document | folder
    resource_id = Column(Integer)


class Dashboard(Base):
    __tablename__ = "dashboards"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    layout = Column(JSON, default=list)  # list of widget descriptors
    is_default = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=True)
    scope = Column(String, default="personal")  # personal | collective


class AnonymousUpload(Base):
    """Public upload URL with pre-applied metadata (Docspell anonymous upload)."""

    __tablename__ = "anonymous_uploads"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    tags = Column(String, default="")
    correspondent_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    enabled = Column(Boolean, default=True)
    max_files = Column(Integer, default=50)
    upload_count = Column(Integer, default=0)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    expires_at = Column(DateTime)
    skip_duplicates = Column(Boolean, default=False)
    priority = Column(Integer, default=0)
    language = Column(String)


class MailSettings(Base):
    """Per-user SMTP (send) or IMAP (scan) settings. Secrets are encrypted at rest."""

    __tablename__ = "mail_settings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String, nullable=False)  # smtp, imap
    name = Column(String, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, default=587)
    username = Column(String)
    password_enc = Column(String)
    use_ssl = Column(Boolean, default=True)
    mailbox = Column(String, default="INBOX")
    created_at = Column(DateTime, default=now)


class NotificationRule(Base):
    """Periodic query notification (due items / matching documents)."""

    __tablename__ = "notification_rules"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    query = Column(String, nullable=False)
    channel = Column(String, default="inapp")  # inapp, email
    interval_hours = Column(Integer, default=24)
    last_run = Column(DateTime)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)
    include_tags = Column(String, default="")
    exclude_tags = Column(String, default="")
    channel_id = Column(Integer, ForeignKey("notify_channels.id"), nullable=True)
    event = Column(String, default="query")  # query, item_created, tag_added, due_digest
    mini_query = Column(JSON, default=dict)
    digest = Column(Boolean, default=False)


class Addon(Base):
    """Webhook hook fired after document processing (Docspell addons, simplified)."""

    __tablename__ = "addons"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    event = Column(String, default="on_process")  # on_upload, on_process, manual, schedule
    webhook_url = Column(String)
    enabled = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    package_path = Column(String)
    descriptor = Column(JSON, default=dict)
    trigger = Column(String, default="on_process")
    sandbox = Column(String, default="subprocess")  # subprocess | docker | nix


class DocumentLink(Base):
    __tablename__ = "document_links"
    id = Column(Integer, primary_key=True, index=True)
    src_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    dst_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    kind = Column(String, default="related")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    resource_type = Column(String, nullable=False)
    resource_id = Column(Integer, nullable=False)
    events = Column(String, default="*")
    created_at = Column(DateTime, default=now)


class InternalMessage(Base):
    __tablename__ = "internal_messages"
    id = Column(Integer, primary_key=True, index=True)
    from_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    to_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, default="")
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    prefix = Column(String, nullable=False, index=True)
    key_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=now)
    last_used_at = Column(DateTime)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ip = Column(String)
    user_agent = Column(String)
    created_at = Column(DateTime, default=now)
    last_seen_at = Column(DateTime, default=now)
    expires_at = Column(DateTime)
    revoked = Column(Boolean, default=False)


class LoginHistory(Base):
    __tablename__ = "login_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String)
    ip = Column(String)
    user_agent = Column(String)
    success = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class TrustedDevice(Base):
    __tablename__ = "trusted_devices"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    fingerprint = Column(String, nullable=False)
    name = Column(String)
    created_at = Column(DateTime, default=now)
    last_seen_at = Column(DateTime, default=now)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key = Column(String, primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=now)


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    kind = Column(String, nullable=False)
    interval_minutes = Column(Integer, default=60)
    enabled = Column(Boolean, default=True)
    last_run = Column(DateTime)
    last_status = Column(String)
    last_message = Column(Text)


class StorageStore(Base):
    __tablename__ = "stores"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    kind = Column(String, default="fs")  # fs | db | s3
    path = Column(String, nullable=False, default="")
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)
    config = Column(JSON, default=dict)


class FolderTemplate(Base):
    __tablename__ = "folder_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    tree = Column(JSON, default=list)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class WorkflowTrigger(Base):
    __tablename__ = "workflow_triggers"
    id = Column(Integer, primary_key=True, index=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("workflow_templates.id"), nullable=False)
    event = Column(String, default="create")
    created_at = Column(DateTime, default=now)


class NamingScheme(Base):
    __tablename__ = "naming_schemes"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    pattern = Column(String, nullable=False)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    created_at = Column(DateTime, default=now)


class Organization(Base):
    """First-class organization matched by name, website, or email domain."""

    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    websites = Column(JSON, default=list)
    emails = Column(JSON, default=list)
    notes = Column(String)
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)


class Equipment(Base):
    """Named asset catalog matched during processing."""

    __tablename__ = "equipment"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    notes = Column(String)
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)


class CollectiveMember(Base):
    __tablename__ = "collective_members"
    id = Column(Integer, primary_key=True, index=True)
    collective_id = Column(Integer, ForeignKey("collectives.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="member")  # owner, member
    created_at = Column(DateTime, default=now)


class MailboxTask(Base):
    """Periodic IMAP scan with globs, move-after-import, and schedule."""

    __tablename__ = "mailbox_tasks"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    mail_settings_id = Column(Integer, ForeignKey("mail_settings.id"), nullable=False)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    imap_folders = Column(String, default="INBOX")
    received_since_hours = Column(Integer, default=72)
    subject_glob = Column(String, default="*")
    file_glob = Column(String, default="*")
    move_after_import = Column(String)
    direction_from_from = Column(Boolean, default=True)
    schedule_minutes = Column(Integer, default=15)
    start_once = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)
    last_run = Column(DateTime)
    last_uid = Column(String)
    source_id = Column(Integer, ForeignKey("anonymous_uploads.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class NotifyChannel(Base):
    """Matrix, Gotify, HTTP webhook, or email delivery channel."""

    __tablename__ = "notify_channels"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # matrix, gotify, http, email
    config = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)


class EventHook(Base):
    """Fire a channel when an event matches a mini-query filter."""

    __tablename__ = "event_hooks"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    event = Column(String, nullable=False)  # item_created, tag_added, item_confirmed, due
    channel_id = Column(Integer, ForeignKey("notify_channels.id"), nullable=False)
    mini_query = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)


class QueryShare(Base):
    """Public share whose contents are a live query (or a static id list)."""

    __tablename__ = "query_shares"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    query = Column(String, default="")
    static_ids = Column(JSON, default=list)
    publish_until = Column(DateTime)
    enabled = Column(Boolean, default=True)
    password_hash = Column(String)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class FileBlob(Base):
    """Database-backed file storage."""

    __tablename__ = "file_blobs"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)
    content = Column(LargeBinary, nullable=False)
    size = Column(Integer, default=0)
    mime = Column(String)
    created_at = Column(DateTime, default=now)


class JobLog(Base):
    __tablename__ = "job_logs"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("processing_jobs.id"), nullable=False, index=True)
    level = Column(String, default="info")
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=now)


class MailTemplate(Base):
    __tablename__ = "mail_templates"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    subject = Column(String, default="")
    body = Column(Text, default="")
    created_at = Column(DateTime, default=now)


class OidcState(Base):
    __tablename__ = "oidc_states"
    id = Column(Integer, primary_key=True, index=True)
    state = Column(String, unique=True, index=True, nullable=False)
    nonce = Column(String, nullable=False)
    created_at = Column(DateTime, default=now)
    expires_at = Column(DateTime, nullable=False)


class VectorChunk(Base):
    __tablename__ = "vector_chunks"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    ordinal = Column(Integer, default=0)
    text = Column(Text, default="")
    vector = Column(JSON, default=list)


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    event = Column(String, default="document_created")
    condition = Column(JSON, default=dict)
    actions = Column(JSON, default=list)
    enabled = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)


class CaptureForm(Base):
    __tablename__ = "capture_forms"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    schema_json = Column("schema", JSON, default=dict)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    enabled = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class FormSubmission(Base):
    __tablename__ = "form_submissions"
    id = Column(Integer, primary_key=True, index=True)
    form_id = Column(Integer, ForeignKey("capture_forms.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now)


class ZoneTemplate(Base):
    __tablename__ = "zone_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    zones = Column(JSON, default=list)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)


class LegalHold(Base):
    __tablename__ = "legal_holds"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    reason = Column(Text)
    active = Column(Boolean, default=True)
    until = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    released_at = Column(DateTime)


class LegalHoldItem(Base):
    __tablename__ = "legal_hold_items"
    id = Column(Integer, primary_key=True, index=True)
    hold_id = Column(Integer, ForeignKey("legal_holds.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)


class RedactionRule(Base):
    __tablename__ = "redaction_rules"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    patterns = Column(JSON, default=list)
    enabled = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)


class Case(Base):
    __tablename__ = "cases"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    status = Column(String, default="open")
    bpmn_id = Column(Integer, nullable=True)
    data = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    closed_at = Column(DateTime)


class CaseDocument(Base):
    __tablename__ = "case_documents"
    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)


class ReadingConfirmation(Base):
    __tablename__ = "reading_confirmations"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    confirmed_at = Column(DateTime, default=now)
    note = Column(String)


class ClusterNode(Base):
    __tablename__ = "cluster_nodes"
    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, default="api")
    host = Column(String)
    alive = Column(Boolean, default=True)
    last_seen = Column(DateTime, default=now)


class ReportDefinition(Base):
    __tablename__ = "report_definitions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    query = Column(String, default="")
    group_by = Column(String)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class BpmnDefinition(Base):
    __tablename__ = "bpmn_definitions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    xml = Column(Text, nullable=False)
    graph = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)


class ConnectorAccount(Base):
    __tablename__ = "connector_accounts"
    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False)  # azure, smb, gdrive, docusign, onlyoffice, outlook, gcal, sap
    name = Column(String, nullable=False)
    config = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)


class ArchiveLinkEntry(Base):
    __tablename__ = "archivelink_entries"
    id = Column(Integer, primary_key=True, index=True)
    cont_rep = Column(String, nullable=False, index=True)
    doc_id = Column(String, nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    file_path = Column(String)
    mime = Column(String)
    size = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)


class CollabOp(Base):
    __tablename__ = "collab_ops"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    rev = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    op = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now)


# =============================================================================
# Legal Practice Management & Corporate Legal Department Models
# =============================================================================


class Matter(Base):
    """Matter-centric case management container."""

    __tablename__ = "matters"
    id = Column(Integer, primary_key=True, index=True)
    matter_number = Column(String, unique=True, index=True, nullable=False)  # e.g. MAT-2026-001
    title = Column(String, nullable=False, index=True)
    client_name = Column(String, nullable=False, index=True)
    client_id = Column(String, index=True)
    practice_area = Column(String, default="General Litigation", index=True)  # Litigation, Corporate, IP, Employment, Real Estate, Regulatory
    lead_attorney_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="open", index=True)  # open, pending, closed, archived
    billing_code = Column(String)
    court_name = Column(String)  # e.g. U.S. District Court, Southern District of NY
    case_caption = Column(String)  # e.g. Acme Corp v. Beta LLC, Case No. 26-CV-10492
    judge_name = Column(String)
    opposing_counsel = Column(String)
    description = Column(Text)
    metadata_json = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)
    closed_at = Column(DateTime)


class MatterDocument(Base):
    """Associates documents with a specific matter, category, and Bates tracking."""

    __tablename__ = "matter_documents"
    id = Column(Integer, primary_key=True, index=True)
    matter_id = Column(Integer, ForeignKey("matters.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    category = Column(String, default="pleading", index=True)  # pleading, discovery, correspondence, contract, exhibit, court_order, memo, transcript
    bates_range = Column(String)  # e.g. PLTF-000001 - PLTF-000045
    confidentiality = Column(String, default="confidential")  # public, confidential, attorneys_eyes_only, highly_confidential
    pinned = Column(Boolean, default=False)
    notes = Column(Text)
    added_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    added_at = Column(DateTime, default=now)


class EthicalWall(Base):
    """Conflict-of-interest ethical walls isolating attorneys/staff from specific matters."""

    __tablename__ = "ethical_walls"
    id = Column(Integer, primary_key=True, index=True)
    matter_id = Column(Integer, ForeignKey("matters.id"), nullable=False, index=True)
    client_name = Column(String, index=True)
    walled_user_ids = Column(JSON, default=list)  # List of user IDs barred from access
    walled_group_ids = Column(JSON, default=list)  # List of group IDs barred
    reason = Column(Text, nullable=False)  # Prior adverse representation / lateral hire conflict
    active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class LegalTemplate(Base):
    """Master document assembly templates with dynamic placeholders."""

    __tablename__ = "legal_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    category = Column(String, default="contract")  # contract, pleading, nda, discovery, brief, letter
    description = Column(String)
    content_template = Column(Text, nullable=False)  # Markdown / HTML template with {{placeholders}}
    fields_schema = Column(JSON, default=list)  # Required and optional input variables
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class BatesProduction(Base):
    """Tracks discovery document productions stamped with sequential Bates numbers."""

    __tablename__ = "bates_productions"
    id = Column(Integer, primary_key=True, index=True)
    matter_id = Column(Integer, ForeignKey("matters.id"), nullable=False, index=True)
    production_set = Column(String, nullable=False)  # e.g. PROD-001-VOL1
    prefix = Column(String, default="PLTF")
    suffix = Column(String)
    start_number = Column(Integer, default=1)
    end_number = Column(Integer, default=1)
    total_pages = Column(Integer, default=0)
    position = Column(String, default="bottom-right")  # bottom-right, bottom-center, top-right
    disclaimer_text = Column(String)  # e.g. CONFIDENTIAL - ATTORNEYS' EYES ONLY
    document_ids = Column(JSON, default=list)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class SecureExtranetPortal(Base):
    """Time-limited, encrypted client/co-counsel extranet share."""

    __tablename__ = "secure_extranet_portals"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    matter_id = Column(Integer, ForeignKey("matters.id"), nullable=False, index=True)
    document_ids = Column(JSON, default=list)
    recipient_email = Column(String, nullable=False)
    recipient_name = Column(String)
    password_hash = Column(String)
    watermark_text = Column(String)  # e.g. CONFIDENTIAL - FOR CLIENT REVIEW ONLY
    allow_download = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


# =============================================================================
# ACCOUNTING & FINANCIAL EDMS MODELS
# =============================================================================


class PurchaseOrder(Base):
    """Purchase Order (PO) record for 2-way and 3-way matching."""

    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True, index=True)
    po_number = Column(String, unique=True, index=True, nullable=False)
    vendor_name = Column(String, index=True, nullable=False)
    total_amount = Column(Float, default=0.0)
    currency = Column(String, default="USD")
    status = Column(String, default="issued")  # draft, issued, partially_received, fulfilled, closed, cancelled
    line_items = Column(JSON, default=list)  # list of {"item_code", "description", "qty", "unit_price", "total"}
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class GoodsReceivedNote(Base):
    """Goods Received Note (GRN) warehouse receiving record."""

    __tablename__ = "goods_received_notes"
    id = Column(Integer, primary_key=True, index=True)
    grn_number = Column(String, unique=True, index=True, nullable=False)
    po_number = Column(String, index=True, nullable=False)
    vendor_name = Column(String, index=True, nullable=False)
    received_date = Column(DateTime, default=now)
    line_items = Column(JSON, default=list)  # list of {"item_code", "description", "received_qty", "accepted_qty"}
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class InvoiceRecord(Base):
    """Financial Vendor Invoice record with OCR data and matching audit trail."""

    __tablename__ = "invoice_records"
    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String, index=True, nullable=False)
    vendor_name = Column(String, index=True, nullable=False)
    vendor_tax_id = Column(String, index=True)  # VAT / EIN / Tax registration
    po_number = Column(String, index=True)
    grn_number = Column(String, index=True)
    subtotal = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)
    currency = Column(String, default="USD")
    invoice_date = Column(DateTime)
    due_date = Column(DateTime)
    gl_account = Column(String, index=True)  # e.g. "6010-Office Supplies"
    cost_center = Column(String, index=True)  # e.g. "CC-100-Operations"
    line_items = Column(JSON, default=list)  # list of {"description", "qty", "unit_price", "tax_rate", "total"}
    matching_status = Column(String, default="unmatched")  # unmatched, matched_2way, matched_3way, price_variance, quantity_variance, missing_po, missing_grn
    matching_notes = Column(Text)
    payment_status = Column(String, default="pending_approval")  # pending_approval, approved, paid, disputed, rejected
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    is_duplicate = Column(Boolean, default=False)
    duplicate_of_id = Column(Integer, ForeignKey("invoice_records.id"), nullable=True)
    peppol_validated = Column(Boolean, default=False)
    peppol_schema = Column(String)  # e.g. PEPPOL_BIS_3.0, UBL_2.1
    metadata_json = Column("metadata", JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class ERPIntegration(Base):
    """Configuration and sync history for ERP & GL platforms (SAP, NetSuite, QuickBooks, Xero, Sage)."""

    __tablename__ = "erp_integrations"
    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, nullable=False)  # sap, netsuite, quickbooks, xero, sage
    company_id = Column(String)
    endpoint_url = Column(String)
    sync_status = Column(String, default="configured")  # configured, syncing, active, error
    last_synced_at = Column(DateTime)
    config_json = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class AuditorPortal(Base):
    """Temporary, read-only restricted auditor review portal."""

    __tablename__ = "auditor_portals"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    auditor_name = Column(String, nullable=False)
    auditor_email = Column(String, nullable=False)
    firm_name = Column(String)
    sample_document_ids = Column(JSON, default=list)
    allowed_gl_accounts = Column(JSON, default=list)
    password_hash = Column(String)
    expires_at = Column(DateTime, nullable=True)
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


# =============================================================================
# INSURANCE & CLAIMS MANAGEMENT EDMS MODELS
# =============================================================================


class InsurancePolicy(Base):
    """Master Insurance Policy with endorsement and rider hierarchy."""

    __tablename__ = "insurance_policies"
    id = Column(Integer, primary_key=True, index=True)
    policy_number = Column(String, unique=True, index=True, nullable=False)
    insured_name = Column(String, index=True, nullable=False)
    policy_type = Column(String, index=True, nullable=False)  # auto, property, commercial, life, health, casualty
    effective_date = Column(DateTime, default=now)
    expiration_date = Column(DateTime, nullable=True)
    premium = Column(Float, default=0.0)
    deductible = Column(Float, default=0.0)
    coverage_limit = Column(Float, default=0.0)
    status = Column(String, default="active")  # active, endorsement, lapsed, cancelled, expired
    master_policy_id = Column(Integer, ForeignKey("insurance_policies.id"), nullable=True)  # Parent policy for endorsements
    metadata_json = Column("metadata", JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class InsuranceClaim(Base):
    """Insurance Claim lifecycle tracking (FNOL, investigation, settlement)."""

    __tablename__ = "insurance_claims"
    id = Column(Integer, primary_key=True, index=True)
    claim_number = Column(String, unique=True, index=True, nullable=False)  # e.g. CLM-2026-0001
    policy_id = Column(Integer, ForeignKey("insurance_policies.id"), nullable=False, index=True)
    claimant_name = Column(String, index=True, nullable=False)
    loss_date = Column(DateTime, default=now)
    loss_type = Column(String, index=True, nullable=False)  # collision, theft, water_damage, fire, bodily_injury, storm, liability
    loss_location = Column(String)
    estimated_loss = Column(Float, default=0.0)
    settlement_amount = Column(Float, default=0.0)
    assigned_adjuster_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="fnol_submitted")  # fnol_submitted, under_review, assessing, approved, settled, denied, subrogation
    auto_approved = Column(Boolean, default=False)
    fraud_score = Column(Integer, default=0)  # 0 to 100
    fraud_flags = Column(JSON, default=list)  # List of suspicious flags
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class ClaimEvidence(Base):
    """Multi-format evidence (dashcam video, photos, audio, drone scans, reports)."""

    __tablename__ = "claim_evidences"
    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("insurance_claims.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    evidence_type = Column(String, nullable=False)  # scene_photo, dashcam_video, audio_statement, drone_footage, police_report, repair_estimate, medical_bill
    exif_metadata = Column(JSON, default=dict)  # GPS, capture date, camera model, software
    image_hash = Column(String, index=True)  # Perceptual / SHA-256 hash for duplicate check
    is_fraud_flagged = Column(Boolean, default=False)
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class ClaimPortalShare(Base):
    """Encrypted upload & review portal for policyholders, adjusters, and repair shops."""

    __tablename__ = "claim_portal_shares"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    claim_id = Column(Integer, ForeignKey("insurance_claims.id"), nullable=False, index=True)
    recipient_email = Column(String, nullable=False)
    recipient_name = Column(String)
    recipient_role = Column(String, default="policyholder")  # policyholder, independent_adjuster, repair_shop, medical_provider
    password_hash = Column(String)
    expires_at = Column(DateTime, nullable=True)
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class InsuranceTemplate(Base):
    """Master templates for binder letters, settlement explanations, and policy schedules."""

    __tablename__ = "insurance_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    template_type = Column(String, nullable=False)  # binder_letter, policy_schedule, settlement_explanation, fnol_ack, denial_notice
    content = Column(Text, nullable=False)
    variables_schema = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


# =============================================================================
# HEALTHCARE & CLINICAL EDMS MODELS (HIPAA, DICOM, HL7/FHIR, BREAK-GLASS)
# =============================================================================


class Patient(Base):
    """Master Patient Index (MPI) and Electronic Health Record."""

    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    mrn = Column(String, unique=True, index=True, nullable=False)  # Medical Record Number e.g. MRN-2026-001
    first_name = Column(String, index=True, nullable=False)
    last_name = Column(String, index=True, nullable=False)
    dob = Column(DateTime, nullable=False)
    gender = Column(String, default="U")  # M, F, O, U
    blood_type = Column(String)  # A+, A-, B+, B-, AB+, AB-, O+, O-
    primary_physician = Column(String)
    insurance_id = Column(String)
    is_active = Column(Boolean, default=True)
    metadata_json = Column("metadata", JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class PatientEncounter(Base):
    """Clinical encounter / hospital admission / surgery event."""

    __tablename__ = "patient_encounters"
    id = Column(Integer, primary_key=True, index=True)
    encounter_number = Column(String, unique=True, index=True, nullable=False)  # ENC-2026-9001
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    encounter_type = Column(String, nullable=False)  # inpatient, outpatient, emergency, surgery, telehealth
    admission_date = Column(DateTime, default=now)
    discharge_date = Column(DateTime, nullable=True)
    department = Column(String, index=True)  # Emergency, Cardiology, Oncology, Psychiatry, Pediatrics, Surgery
    attending_physician = Column(String, index=True)
    chief_complaint = Column(Text)
    status = Column(String, default="admitted")  # admitted, in_progress, discharged, transferred, completed
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class MedicalDocument(Base):
    """Clinical record with granular ABAC sensitivity level and ICD-10 tagging."""

    __tablename__ = "medical_documents"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    encounter_id = Column(Integer, ForeignKey("patient_encounters.id"), nullable=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    clinical_category = Column(String, nullable=False)  # clinical_note, discharge_summary, lab_result, radiology_dicom, surgical_consent, physician_order, pathology_report
    sensitivity_level = Column(String, default="standard")  # standard, psychiatric, oncology, substance_use, sti, vip_confidential
    icd10_codes = Column(JSON, default=list)  # list of diagnosis ICD-10 strings
    is_signed = Column(Boolean, default=False)
    signed_by_physician = Column(String)
    signed_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class DicomStudy(Base):
    """DICOM & PACS Diagnostic Medical Imaging metadata."""

    __tablename__ = "dicom_studies"
    id = Column(Integer, primary_key=True, index=True)
    study_instance_uid = Column(String, unique=True, index=True, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    modality = Column(String, index=True, nullable=False)  # CT, MR, XR, US, NM, MG
    body_part_examined = Column(String)  # CHEST, HEAD, ABDOMEN, SPINE, PELVIS
    series_count = Column(Integer, default=1)
    instance_count = Column(Integer, default=1)
    metadata_json = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now)


class BreakGlassEvent(Base):
    """Emergency 'Break-Glass' clinical access override and HIPAA audit log."""

    __tablename__ = "break_glass_events"
    id = Column(Integer, primary_key=True, index=True)
    clinician_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    emergency_rationale = Column(Text, nullable=False)  # Mandatory acute clinical justification
    workstation_ip = Column(String)
    alert_sent = Column(Boolean, default=True)
    reviewed_by_compliance = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=now)


class InformedConsent(Base):
    """Bedside digital informed consent with cryptographic e-Signature."""

    __tablename__ = "informed_consents"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    encounter_id = Column(Integer, ForeignKey("patient_encounters.id"), nullable=True, index=True)
    consent_type = Column(String, nullable=False)  # surgical, anesthesia, blood_transfusion, hipaa_acknowledgment
    procedure_name = Column(String, nullable=False)
    signer_name = Column(String, nullable=False)
    signer_relationship = Column(String, default="patient")  # patient, parent, legal_guardian, healthcare_proxy
    signature_data = Column(Text, nullable=False)  # Base64 signature path/coordinates
    witness_name = Column(String)
    signed_at = Column(DateTime, default=now)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
