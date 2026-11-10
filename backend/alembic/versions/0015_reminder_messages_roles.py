"""Reminder wording and per-role on/off switches (company setting, JSON)

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # {"morning_plan": {"subject": "...", "body": "...", "roles_off": ["<role id>", ...]}, ...}; nothing stored = built-in wording, every role on
    op.get_bind().exec_driver_sql("ALTER TABLE companies ADD COLUMN reminder_config jsonb NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE companies DROP COLUMN reminder_config")
