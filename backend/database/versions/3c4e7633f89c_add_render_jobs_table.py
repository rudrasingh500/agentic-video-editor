"""add_render_jobs_table

Revision ID: 3c4e7633f89c
Revises: 2b3d6522e78b
Create Date: 2026-01-15 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "3c4e7633f89c"
down_revision = "2b3d6522e78b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create render_jobs table
    op.create_table(
        "render_jobs",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("timeline_id", sa.UUID(), nullable=False),
        sa.Column("timeline_version", sa.Integer(), nullable=False),
        # Job type and status
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, default="pending"),
        # Progress tracking
        sa.Column("progress", sa.Integer(), nullable=False, default=0),
        sa.Column("current_frame", sa.Integer(), nullable=True),
        sa.Column("total_frames", sa.Integer(), nullable=True),
        # Render settings
        sa.Column("preset", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # Output details
        sa.Column("output_filename", sa.String(), nullable=True),
        sa.Column("output_url", sa.String(), nullable=True),
        sa.Column("output_size_bytes", sa.Integer(), nullable=True),
        # Error handling
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Cloud Run integration
        sa.Column("cloud_run_job_name", sa.String(), nullable=True),
        sa.Column("cloud_run_execution_id", sa.String(), nullable=True),
        # Timestamps
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        # Additional metadata
        sa.Column(
            "job_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, default={}
        ),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.project_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["timeline_id"], ["timelines.timeline_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )

    # Create indexes
    op.create_index(
        op.f("ix_render_jobs_job_id"), "render_jobs", ["job_id"], unique=True
    )
    op.create_index(
        "ix_render_jobs_project_id", "render_jobs", ["project_id"], unique=False
    )
    op.create_index(
        "ix_render_jobs_status", "render_jobs", ["status"], unique=False
    )
    op.create_index(
        "ix_render_jobs_created_at", "render_jobs", ["created_at"], unique=False
    )
    op.create_index(
        "ix_render_jobs_project_status",
        "render_jobs",
        ["project_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_render_jobs_project_status", table_name="render_jobs")
    op.drop_index("ix_render_jobs_created_at", table_name="render_jobs")
    op.drop_index("ix_render_jobs_status", table_name="render_jobs")
    op.drop_index("ix_render_jobs_project_id", table_name="render_jobs")
    op.drop_index(op.f("ix_render_jobs_job_id"), table_name="render_jobs")
    
    # Drop table
    op.drop_table("render_jobs")
