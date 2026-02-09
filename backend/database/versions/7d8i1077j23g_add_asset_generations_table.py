"""add asset generations table

Revision ID: 7d8i1077j23g
Revises: 6c7h0966i12f
Create Date: 2026-02-09 14:15:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "7d8i1077j23g"
down_revision = "6c7h0966i12f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_generations",
        sa.Column("generation_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("timeline_id", sa.UUID(), nullable=True),
        sa.Column("request_origin", sa.String(), nullable=False, server_default="user"),
        sa.Column("requestor", sa.String(), nullable=False, server_default="system"),
        sa.Column("provider", sa.String(), nullable=False, server_default="openrouter"),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("prompt", sa.String(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reference_asset_id", sa.UUID(), nullable=True),
        sa.Column("reference_snippet_id", sa.UUID(), nullable=True),
        sa.Column("reference_identity_id", sa.UUID(), nullable=True),
        sa.Column("reference_character_model_id", sa.UUID(), nullable=True),
        sa.Column("target_asset_id", sa.UUID(), nullable=True),
        sa.Column("frame_range", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("frame_indices", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generated_asset_id", sa.UUID(), nullable=True),
        sa.Column("applied_asset_id", sa.UUID(), nullable=True),
        sa.Column("request_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision_reason", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["timeline_id"], ["timelines.timeline_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reference_asset_id"], ["assets.asset_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reference_snippet_id"], ["snippets.snippet_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reference_identity_id"], ["snippet_identities.identity_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reference_character_model_id"], ["character_models.character_model_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_asset_id"], ["assets.asset_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generated_asset_id"], ["assets.asset_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["applied_asset_id"], ["assets.asset_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("generation_id"),
    )
    op.create_index(op.f("ix_asset_generations_generation_id"), "asset_generations", ["generation_id"], unique=True)
    op.create_index("ix_asset_generations_project", "asset_generations", ["project_id"], unique=False)
    op.create_index("ix_asset_generations_status", "asset_generations", ["status"], unique=False)
    op.create_index("ix_asset_generations_target_asset", "asset_generations", ["target_asset_id"], unique=False)
    op.create_index("ix_asset_generations_created_at", "asset_generations", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_asset_generations_created_at", table_name="asset_generations")
    op.drop_index("ix_asset_generations_target_asset", table_name="asset_generations")
    op.drop_index("ix_asset_generations_status", table_name="asset_generations")
    op.drop_index("ix_asset_generations_project", table_name="asset_generations")
    op.drop_index(op.f("ix_asset_generations_generation_id"), table_name="asset_generations")
    op.drop_table("asset_generations")
