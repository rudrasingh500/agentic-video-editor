"""add edit session activity events

Revision ID: 8e9j2188k34h
Revises: 7d8i1077j23g
Create Date: 2026-02-12 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "8e9j2188k34h"
down_revision = "7d8i1077j23g"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "edit_sessions",
        sa.Column(
            "activity_events",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("edit_sessions", "activity_events")
