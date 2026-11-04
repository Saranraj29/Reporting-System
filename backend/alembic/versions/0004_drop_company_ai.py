"""LLM provider is platform configuration (environment) only: drop the per-company columns added in 0003

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS ai_api_key, DROP COLUMN IF EXISTS ai_model, DROP COLUMN IF EXISTS ai_provider")


def downgrade() -> None:
    op.execute("ALTER TABLE companies ADD COLUMN ai_provider text, ADD COLUMN ai_model text, ADD COLUMN ai_api_key text")
