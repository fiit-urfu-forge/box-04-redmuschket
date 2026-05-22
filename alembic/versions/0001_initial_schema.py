"""Начальная схема CertGuard

Revision ID: 0001
Revises:
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- companies ---------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("email", name="uq_company_email"),
    )

    # --- admins ------------------------------------------------------------
    op.create_table(
        "admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="support"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email", name="uq_admin_email"),
        sa.CheckConstraint(
            "role IN ('super_admin', 'support')", name="ck_admin_role"
        ),
    )

    # --- certificates ------------------------------------------------------
    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=False,
                  server_default="Unknown"),
        sa.Column("certificate_number", sa.String(length=36), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("pdf_path", sa.String(length=512), nullable=False),
        sa.Column("hash_sha256", sa.String(length=64), nullable=False),
        sa.Column("tfidf_vector", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE",
            name="fk_certificate_company",
        ),
        sa.UniqueConstraint(
            "company_id", "certificate_number", name="uq_cert_company_number"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'damaged')", name="ck_certificate_status"
        ),
    )
    op.create_index("ix_certificates_company_id", "certificates", ["company_id"])
    op.create_index("ix_certificates_hash", "certificates", ["hash_sha256"])

    # --- verification_requests --------------------------------------------
    op.create_table(
        "verification_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("suspicious_file_path", sa.String(length=512), nullable=False),
        sa.Column("hash_sha256", sa.String(length=64), nullable=False),
        sa.Column("matched_certificate_id", sa.Integer(), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="pending"),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(
            ["matched_certificate_id"], ["certificates.id"], ondelete="SET NULL",
            name="fk_verification_certificate",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'no_match', 'corrupted', 'timeout')",
            name="ck_verification_status",
        ),
    )
    op.create_index(
        "ix_verification_hash", "verification_requests", ["hash_sha256"]
    )

    # --- alerts ------------------------------------------------------------
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("certificate_id", sa.Integer(), nullable=False),
        sa.Column("verification_request_id", sa.Integer(), nullable=False),
        sa.Column("delivery_method", sa.String(length=16), nullable=False,
                  server_default="email"),
        sa.Column("delivery_status", sa.String(length=16), nullable=False,
                  server_default="pending"),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE",
            name="fk_alert_company",
        ),
        sa.ForeignKeyConstraint(
            ["certificate_id"], ["certificates.id"], ondelete="CASCADE",
            name="fk_alert_certificate",
        ),
        sa.ForeignKeyConstraint(
            ["verification_request_id"], ["verification_requests.id"],
            ondelete="CASCADE", name="fk_alert_verification",
        ),
        sa.UniqueConstraint(
            "verification_request_id", name="uq_alert_verification"
        ),
        sa.CheckConstraint(
            "delivery_method IN ('email', 'telegram')", name="ck_alert_method"
        ),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'failed')", name="ck_alert_status"
        ),
    )

    # --- admin_notifications ----------------------------------------------
    op.create_table(
        "admin_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False,
                  server_default="ERROR"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("related_entity_id", sa.Integer(), nullable=True),
        sa.Column("is_resolved", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin_id"], ["admins.id"], ondelete="SET NULL",
            name="fk_notification_admin",
        ),
        sa.CheckConstraint(
            "severity IN ('WARNING', 'ERROR', 'CRITICAL')",
            name="ck_admin_notification_severity",
        ),
    )


def downgrade() -> None:
    op.drop_table("admin_notifications")
    op.drop_table("alerts")
    op.drop_index("ix_verification_hash", table_name="verification_requests")
    op.drop_table("verification_requests")
    op.drop_index("ix_certificates_hash", table_name="certificates")
    op.drop_index("ix_certificates_company_id", table_name="certificates")
    op.drop_table("certificates")
    op.drop_table("admins")
    op.drop_table("companies")
