"""add_edit_sessions_table

Revision ID: 4a5f8744g90d
Revises: 3c4e7633f89c
Create Date: 2026-01-18 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "4a5f8744g90d"
down_revision = "3c4e7633f89c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create edit_sessions table
    op.create_table(
        "edit_sessions",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("timeline_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column(
            "messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "pending_patches",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.project_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["timeline_id"], ["timelines.timeline_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.session_id"]
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )

    # Create indexes
    op.create_index(
        op.f("ix_edit_sessions_session_id"),
        "edit_sessions",
        ["session_id"],
        unique=True,
    )
    op.create_index(
        "ix_edit_sessions_project_id",
        "edit_sessions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_edit_sessions_timeline_id",
        "edit_sessions",
        ["timeline_id"],
        unique=False,
    )
    op.create_index(
        "ix_edit_sessions_status",
        "edit_sessions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_edit_sessions_created_at",
        "edit_sessions",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_edit_sessions_created_at", table_name="edit_sessions")
    op.drop_index("ix_edit_sessions_status", table_name="edit_sessions")
    op.drop_index("ix_edit_sessions_timeline_id", table_name="edit_sessions")
    op.drop_index("ix_edit_sessions_project_id", table_name="edit_sessions")
    op.drop_index(op.f("ix_edit_sessions_session_id"), table_name="edit_sessions")

    # Drop table
    op.drop_table("edit_sessions")
