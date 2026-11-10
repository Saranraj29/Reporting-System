"""A title for each assistant conversation (shown in the history list; the person can rename it)

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE ai_conversations ADD COLUMN title text NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE ai_conversations DROP COLUMN title")
