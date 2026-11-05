"""AI reports: which model and prompt wrote them, token usage, grounding result

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE ai_reports ADD COLUMN model text, ADD COLUMN prompt_version text, ADD COLUMN usage jsonb, "
        "ADD COLUMN verification jsonb, ADD COLUMN latency_ms integer"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE ai_reports DROP COLUMN model, DROP COLUMN prompt_version, DROP COLUMN usage, DROP COLUMN verification, DROP COLUMN latency_ms")
