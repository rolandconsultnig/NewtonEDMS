"""newtonedms fusion: collectives, contacts, joex, intelligence

Revision ID: a1b2c3d4e5f6
Revises: f76ef1590feb
Create Date: 2026-08-14 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f76ef1590feb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collectives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("collectives") as batch:
        batch.create_index(batch.f("ix_collectives_id"), ["id"], unique=False)
        batch.create_index(batch.f("ix_collectives_name"), ["name"], unique=True)

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("organization", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("contacts") as batch:
        batch.create_index(batch.f("ix_contacts_id"), ["id"], unique=False)
        batch.create_index(batch.f("ix_contacts_name"), ["name"], unique=False)

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tags") as batch:
        batch.create_index(batch.f("ix_tags_id"), ["id"], unique=False)
        batch.create_index(batch.f("ix_tags_name"), ["name"], unique=True)

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("collective_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("totp_secret", sa.String(), nullable=True))
        batch.add_column(sa.Column("totp_enabled", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("theme", sa.String(), nullable=True))
        batch.create_foreign_key("fk_users_collective", "collectives", ["collective_id"], ["id"])

    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("content_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("correspondent_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("concerning_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("due_date", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("item_date", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("source", sa.String(), nullable=True))
        batch.add_column(sa.Column("language", sa.String(), nullable=True))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("original_file_path", sa.String(), nullable=True))
        batch.add_column(sa.Column("pdf_file_path", sa.String(), nullable=True))
        batch.add_column(sa.Column("processing_status", sa.String(), nullable=True))
        batch.add_column(sa.Column("direction", sa.String(), nullable=True))
        batch.add_column(sa.Column("equipment", sa.String(), nullable=True))
        batch.add_column(sa.Column("custom_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("extracted_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("duplicate_of", sa.Integer(), nullable=True))
        batch.create_index(batch.f("ix_documents_content_hash"), ["content_hash"], unique=False)
        batch.create_index(batch.f("ix_documents_custom_id"), ["custom_id"], unique=False)
        batch.create_foreign_key("fk_documents_correspondent", "contacts", ["correspondent_id"], ["id"])
        batch.create_foreign_key("fk_documents_concerning", "contacts", ["concerning_id"], ["id"])
        batch.create_foreign_key("fk_documents_duplicate", "documents", ["duplicate_of"], ["id"])

    with op.batch_alter_table("share_links") as batch:
        batch.add_column(sa.Column("password_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("name", sa.String(), nullable=True))

    op.create_table(
        "document_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("mime", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "custom_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("ftype", sa.String(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("custom_fields") as batch:
        batch.create_index(batch.f("ix_custom_fields_name"), ["name"], unique=True)

    op.create_table(
        "custom_field_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["field_id"], ["custom_fields.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "dashboards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("layout", sa.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "anonymous_uploads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=False),
        sa.Column("tags", sa.String(), nullable=True),
        sa.Column("correspondent_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("max_files", sa.Integer(), nullable=True),
        sa.Column("upload_count", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["folder_id"], ["folders.id"]),
        sa.ForeignKeyConstraint(["correspondent_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("anonymous_uploads") as batch:
        batch.create_index(batch.f("ix_anonymous_uploads_token"), ["token"], unique=True)

    op.create_table(
        "mail_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("password_enc", sa.String(), nullable=True),
        sa.Column("use_ssl", sa.Boolean(), nullable=True),
        sa.Column("mailbox", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "notification_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("interval_hours", sa.Integer(), nullable=True),
        sa.Column("last_run", sa.DateTime(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "addons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("event", sa.String(), nullable=True),
        sa.Column("webhook_url", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("addons")
    op.drop_table("notification_rules")
    op.drop_table("mail_settings")
    op.drop_table("anonymous_uploads")
    op.drop_table("dashboards")
    op.drop_table("bookmarks")
    op.drop_table("processing_jobs")
    op.drop_table("custom_field_values")
    op.drop_table("custom_fields")
    op.drop_table("document_attachments")
    with op.batch_alter_table("share_links") as batch:
        batch.drop_column("name")
        batch.drop_column("password_hash")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("duplicate_of")
        batch.drop_column("extracted_text")
        batch.drop_column("custom_id")
        batch.drop_column("equipment")
        batch.drop_column("direction")
        batch.drop_column("processing_status")
        batch.drop_column("pdf_file_path")
        batch.drop_column("original_file_path")
        batch.drop_column("notes")
        batch.drop_column("language")
        batch.drop_column("source")
        batch.drop_column("item_date")
        batch.drop_column("due_date")
        batch.drop_column("concerning_id")
        batch.drop_column("correspondent_id")
        batch.drop_column("content_hash")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("theme")
        batch.drop_column("totp_enabled")
        batch.drop_column("totp_secret")
        batch.drop_column("collective_id")
    op.drop_table("tags")
    op.drop_table("contacts")
    op.drop_table("collectives")
