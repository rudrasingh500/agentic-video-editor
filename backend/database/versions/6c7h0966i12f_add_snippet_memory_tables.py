"""add_snippet_memory_tables

Revision ID: 6c7h0966i12f
Revises: 5b6g9855h01e
Create Date: 2026-02-09 11:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


revision = "6c7h0966i12f"
down_revision = "5b6g9855h01e"
branch_labels = None
depends_on = None

EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.create_table(
        "snippets",
        sa.Column("snippet_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=True),
        sa.Column("snippet_type", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=True),
        sa.Column("timestamp_ms", sa.Integer(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("crop_blob_path", sa.String(), nullable=True),
        sa.Column("preview_blob_path", sa.String(), nullable=True),
        sa.Column("descriptor", sa.String(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snippet_id"),
    )
    op.create_index(op.f("ix_snippets_snippet_id"), "snippets", ["snippet_id"], unique=True)
    op.create_index("ix_snippets_project_id", "snippets", ["project_id"], unique=False)
    op.create_index("ix_snippets_asset_id", "snippets", ["asset_id"], unique=False)
    op.create_index("ix_snippets_type", "snippets", ["snippet_type"], unique=False)
    op.create_index("ix_snippets_source_type", "snippets", ["source_type"], unique=False)
    op.execute(
        """
        CREATE INDEX ix_snippets_embedding
        ON snippets
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )

    op.create_table(
        "snippet_identities",
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("identity_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("canonical_snippet_id", sa.UUID(), nullable=True),
        sa.Column("prototype_embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["canonical_snippet_id"], ["snippets.snippet_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merged_into_id"], ["snippet_identities.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("identity_id"),
    )
    op.create_index(op.f("ix_snippet_identities_identity_id"), "snippet_identities", ["identity_id"], unique=True)
    op.create_index("ix_snippet_identities_project_id", "snippet_identities", ["project_id"], unique=False)
    op.create_index("ix_snippet_identities_type", "snippet_identities", ["identity_type"], unique=False)
    op.create_index("ix_snippet_identities_status", "snippet_identities", ["status"], unique=False)
    op.create_index("ix_snippet_identities_merged", "snippet_identities", ["merged_into_id"], unique=False)
    op.execute(
        """
        CREATE INDEX ix_snippet_identities_embedding
        ON snippet_identities
        USING ivfflat (prototype_embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )

    op.create_table(
        "snippet_identity_links",
        sa.Column("link_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("snippet_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("link_source", sa.String(), nullable=False, server_default="system"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snippet_id"], ["snippets.snippet_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["identity_id"], ["snippet_identities.identity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("link_id"),
    )
    op.create_index(op.f("ix_snippet_identity_links_link_id"), "snippet_identity_links", ["link_id"], unique=True)
    op.create_index("ix_snippet_identity_links_project", "snippet_identity_links", ["project_id"], unique=False)
    op.create_index("ix_snippet_identity_links_snippet", "snippet_identity_links", ["snippet_id"], unique=False)
    op.create_index("ix_snippet_identity_links_identity", "snippet_identity_links", ["identity_id"], unique=False)

    op.create_table(
        "character_models",
        sa.Column("character_model_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("model_type", sa.String(), nullable=False, server_default="character"),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("canonical_prompt", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("canonical_snippet_id", sa.UUID(), nullable=True),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["canonical_snippet_id"], ["snippets.snippet_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merged_into_id"], ["character_models.character_model_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("character_model_id"),
    )
    op.create_index(op.f("ix_character_models_character_model_id"), "character_models", ["character_model_id"], unique=True)
    op.create_index("ix_character_models_project", "character_models", ["project_id"], unique=False)
    op.create_index("ix_character_models_type", "character_models", ["model_type"], unique=False)
    op.create_index("ix_character_models_status", "character_models", ["status"], unique=False)
    op.create_index("ix_character_models_merged", "character_models", ["merged_into_id"], unique=False)

    op.create_table(
        "character_model_snippet_links",
        sa.Column("link_id", sa.UUID(), nullable=False),
        sa.Column("character_model_id", sa.UUID(), nullable=False),
        sa.Column("snippet_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="reference"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["character_model_id"], ["character_models.character_model_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snippet_id"], ["snippets.snippet_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("link_id"),
    )
    op.create_index(op.f("ix_character_model_snippet_links_link_id"), "character_model_snippet_links", ["link_id"], unique=True)
    op.create_index("ix_character_model_snippet_links_model", "character_model_snippet_links", ["character_model_id"], unique=False)
    op.create_index("ix_character_model_snippet_links_snippet", "character_model_snippet_links", ["snippet_id"], unique=False)

    op.create_table(
        "character_model_identity_links",
        sa.Column("link_id", sa.UUID(), nullable=False),
        sa.Column("character_model_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="primary"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["character_model_id"], ["character_models.character_model_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["identity_id"], ["snippet_identities.identity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("link_id"),
    )
    op.create_index(op.f("ix_character_model_identity_links_link_id"), "character_model_identity_links", ["link_id"], unique=True)
    op.create_index("ix_character_model_identity_links_model", "character_model_identity_links", ["character_model_id"], unique=False)
    op.create_index("ix_character_model_identity_links_identity", "character_model_identity_links", ["identity_id"], unique=False)

    op.create_table(
        "identity_merge_events",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("source_identity_id", sa.UUID(), nullable=False),
        sa.Column("target_identity_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("actor", sa.String(), nullable=False, server_default="system"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_identity_id"], ["snippet_identities.identity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_identity_id"], ["snippet_identities.identity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(op.f("ix_identity_merge_events_event_id"), "identity_merge_events", ["event_id"], unique=True)
    op.create_index("ix_identity_merge_events_project", "identity_merge_events", ["project_id"], unique=False)
    op.create_index("ix_identity_merge_events_source", "identity_merge_events", ["source_identity_id"], unique=False)
    op.create_index("ix_identity_merge_events_target", "identity_merge_events", ["target_identity_id"], unique=False)

    op.create_table(
        "character_model_merge_events",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("source_model_id", sa.UUID(), nullable=False),
        sa.Column("target_model_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("actor", sa.String(), nullable=False, server_default="system"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_model_id"], ["character_models.character_model_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_model_id"], ["character_models.character_model_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(op.f("ix_character_model_merge_events_event_id"), "character_model_merge_events", ["event_id"], unique=True)
    op.create_index("ix_character_model_merge_events_project", "character_model_merge_events", ["project_id"], unique=False)
    op.create_index("ix_character_model_merge_events_source", "character_model_merge_events", ["source_model_id"], unique=False)
    op.create_index("ix_character_model_merge_events_target", "character_model_merge_events", ["target_model_id"], unique=False)

    op.create_table(
        "snippet_merge_suggestions",
        sa.Column("suggestion_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("snippet_id", sa.UUID(), nullable=False),
        sa.Column("candidate_identity_id", sa.UUID(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snippet_id"], ["snippets.snippet_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_identity_id"], ["snippet_identities.identity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("suggestion_id"),
    )
    op.create_index(op.f("ix_snippet_merge_suggestions_suggestion_id"), "snippet_merge_suggestions", ["suggestion_id"], unique=True)
    op.create_index("ix_snippet_merge_suggestions_project", "snippet_merge_suggestions", ["project_id"], unique=False)
    op.create_index("ix_snippet_merge_suggestions_snippet", "snippet_merge_suggestions", ["snippet_id"], unique=False)
    op.create_index("ix_snippet_merge_suggestions_identity", "snippet_merge_suggestions", ["candidate_identity_id"], unique=False)
    op.create_index("ix_snippet_merge_suggestions_decision", "snippet_merge_suggestions", ["decision"], unique=False)

    op.create_table(
        "generation_reference_anchors",
        sa.Column("anchor_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("timeline_id", sa.UUID(), nullable=True),
        sa.Column("anchor_type", sa.String(), nullable=False),
        sa.Column("snippet_id", sa.UUID(), nullable=True),
        sa.Column("identity_id", sa.UUID(), nullable=True),
        sa.Column("character_model_id", sa.UUID(), nullable=True),
        sa.Column("request_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["timeline_id"], ["timelines.timeline_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["snippet_id"], ["snippets.snippet_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["identity_id"], ["snippet_identities.identity_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["character_model_id"], ["character_models.character_model_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("anchor_id"),
    )
    op.create_index(op.f("ix_generation_reference_anchors_anchor_id"), "generation_reference_anchors", ["anchor_id"], unique=True)
    op.create_index("ix_generation_reference_anchors_project", "generation_reference_anchors", ["project_id"], unique=False)
    op.create_index("ix_generation_reference_anchors_timeline", "generation_reference_anchors", ["timeline_id"], unique=False)
    op.create_index("ix_generation_reference_anchors_type", "generation_reference_anchors", ["anchor_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_generation_reference_anchors_type", table_name="generation_reference_anchors")
    op.drop_index("ix_generation_reference_anchors_timeline", table_name="generation_reference_anchors")
    op.drop_index("ix_generation_reference_anchors_project", table_name="generation_reference_anchors")
    op.drop_index(op.f("ix_generation_reference_anchors_anchor_id"), table_name="generation_reference_anchors")
    op.drop_table("generation_reference_anchors")

    op.drop_index("ix_snippet_merge_suggestions_decision", table_name="snippet_merge_suggestions")
    op.drop_index("ix_snippet_merge_suggestions_identity", table_name="snippet_merge_suggestions")
    op.drop_index("ix_snippet_merge_suggestions_snippet", table_name="snippet_merge_suggestions")
    op.drop_index("ix_snippet_merge_suggestions_project", table_name="snippet_merge_suggestions")
    op.drop_index(op.f("ix_snippet_merge_suggestions_suggestion_id"), table_name="snippet_merge_suggestions")
    op.drop_table("snippet_merge_suggestions")

    op.drop_index("ix_character_model_merge_events_target", table_name="character_model_merge_events")
    op.drop_index("ix_character_model_merge_events_source", table_name="character_model_merge_events")
    op.drop_index("ix_character_model_merge_events_project", table_name="character_model_merge_events")
    op.drop_index(op.f("ix_character_model_merge_events_event_id"), table_name="character_model_merge_events")
    op.drop_table("character_model_merge_events")

    op.drop_index("ix_identity_merge_events_target", table_name="identity_merge_events")
    op.drop_index("ix_identity_merge_events_source", table_name="identity_merge_events")
    op.drop_index("ix_identity_merge_events_project", table_name="identity_merge_events")
    op.drop_index(op.f("ix_identity_merge_events_event_id"), table_name="identity_merge_events")
    op.drop_table("identity_merge_events")

    op.drop_index("ix_character_model_identity_links_identity", table_name="character_model_identity_links")
    op.drop_index("ix_character_model_identity_links_model", table_name="character_model_identity_links")
    op.drop_index(op.f("ix_character_model_identity_links_link_id"), table_name="character_model_identity_links")
    op.drop_table("character_model_identity_links")

    op.drop_index("ix_character_model_snippet_links_snippet", table_name="character_model_snippet_links")
    op.drop_index("ix_character_model_snippet_links_model", table_name="character_model_snippet_links")
    op.drop_index(op.f("ix_character_model_snippet_links_link_id"), table_name="character_model_snippet_links")
    op.drop_table("character_model_snippet_links")

    op.drop_index("ix_character_models_merged", table_name="character_models")
    op.drop_index("ix_character_models_status", table_name="character_models")
    op.drop_index("ix_character_models_type", table_name="character_models")
    op.drop_index("ix_character_models_project", table_name="character_models")
    op.drop_index(op.f("ix_character_models_character_model_id"), table_name="character_models")
    op.drop_table("character_models")

    op.drop_index("ix_snippet_identity_links_identity", table_name="snippet_identity_links")
    op.drop_index("ix_snippet_identity_links_snippet", table_name="snippet_identity_links")
    op.drop_index("ix_snippet_identity_links_project", table_name="snippet_identity_links")
    op.drop_index(op.f("ix_snippet_identity_links_link_id"), table_name="snippet_identity_links")
    op.drop_table("snippet_identity_links")

    op.execute("DROP INDEX IF EXISTS ix_snippet_identities_embedding")
    op.drop_index("ix_snippet_identities_merged", table_name="snippet_identities")
    op.drop_index("ix_snippet_identities_status", table_name="snippet_identities")
    op.drop_index("ix_snippet_identities_type", table_name="snippet_identities")
    op.drop_index("ix_snippet_identities_project_id", table_name="snippet_identities")
    op.drop_index(op.f("ix_snippet_identities_identity_id"), table_name="snippet_identities")
    op.drop_table("snippet_identities")

    op.execute("DROP INDEX IF EXISTS ix_snippets_embedding")
    op.drop_index("ix_snippets_source_type", table_name="snippets")
    op.drop_index("ix_snippets_type", table_name="snippets")
    op.drop_index("ix_snippets_asset_id", table_name="snippets")
    op.drop_index("ix_snippets_project_id", table_name="snippets")
    op.drop_index(op.f("ix_snippets_snippet_id"), table_name="snippets")
    op.drop_table("snippets")
