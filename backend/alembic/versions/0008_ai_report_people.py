"""AI reports: optional filter on people

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE ai_reports ADD COLUMN person_ids jsonb")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE ai_reports DROP COLUMN person_ids")
