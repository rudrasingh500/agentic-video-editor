"""add_entity_linking_tables

Revision ID: 5b6g9855h01e
Revises: 4a5f8744g90d
Create Date: 2025-01-20 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = "5b6g9855h01e"
down_revision = "4a5f8744g90d"
branch_labels = None
depends_on = None

EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    # Create project_entities table
    op.create_table(
        "project_entities",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column(
            "source_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
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
            ["asset_id"], ["assets.asset_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["project_entities.entity_id"]
        ),
        sa.PrimaryKeyConstraint("entity_id"),
    )

    # Create indexes for project_entities
    op.create_index(
        op.f("ix_project_entities_entity_id"),
        "project_entities",
        ["entity_id"],
        unique=True,
    )
    op.create_index(
        "ix_project_entities_project_id",
        "project_entities",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_entities_asset_id",
        "project_entities",
        ["asset_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_entities_type",
        "project_entities",
        ["entity_type"],
        unique=False,
    )
    op.create_index(
        "ix_project_entities_merged",
        "project_entities",
        ["merged_into_id"],
        unique=False,
    )

    # Create vector index for similarity search
    op.execute("""
        CREATE INDEX ix_project_entities_embedding
        ON project_entities
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)

    # Create entity_similarities table
    op.create_table(
        "entity_similarities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity_a_id", sa.UUID(), nullable=False),
        sa.Column("entity_b_id", sa.UUID(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=True),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["entity_a_id"], ["project_entities.entity_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["entity_b_id"], ["project_entities.entity_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for entity_similarities
    op.create_index(
        op.f("ix_entity_similarities_id"),
        "entity_similarities",
        ["id"],
        unique=True,
    )
    op.create_index(
        "ix_entity_similarities_entity_a",
        "entity_similarities",
        ["entity_a_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_similarities_entity_b",
        "entity_similarities",
        ["entity_b_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_similarities_score",
        "entity_similarities",
        [sa.text("similarity_score DESC")],
        unique=False,
    )

    # Partial index for unconfirmed similarities (for efficient querying)
    op.execute("""
        CREATE INDEX ix_entity_similarities_unconfirmed
        ON entity_similarities (entity_a_id, entity_b_id)
        WHERE is_confirmed IS NULL
    """)


def downgrade() -> None:
    # Drop entity_similarities indexes
    op.execute("DROP INDEX IF EXISTS ix_entity_similarities_unconfirmed")
    op.drop_index("ix_entity_similarities_score", table_name="entity_similarities")
    op.drop_index("ix_entity_similarities_entity_b", table_name="entity_similarities")
    op.drop_index("ix_entity_similarities_entity_a", table_name="entity_similarities")
    op.drop_index(op.f("ix_entity_similarities_id"), table_name="entity_similarities")

    # Drop entity_similarities table
    op.drop_table("entity_similarities")

    # Drop project_entities indexes
    op.execute("DROP INDEX IF EXISTS ix_project_entities_embedding")
    op.drop_index("ix_project_entities_merged", table_name="project_entities")
    op.drop_index("ix_project_entities_type", table_name="project_entities")
    op.drop_index("ix_project_entities_asset_id", table_name="project_entities")
    op.drop_index("ix_project_entities_project_id", table_name="project_entities")
    op.drop_index(op.f("ix_project_entities_entity_id"), table_name="project_entities")

    # Drop project_entities table
    op.drop_table("project_entities")
