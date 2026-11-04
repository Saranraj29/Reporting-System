"""per-company LLM settings (provider, model, encrypted API key)

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE companies ADD COLUMN ai_provider text CHECK (ai_provider IN ('anthropic','openai','gemini','none'))")
    op.execute("ALTER TABLE companies ADD COLUMN ai_model text")
    op.execute("ALTER TABLE companies ADD COLUMN ai_api_key text")  # encrypted with the platform key, like the Slack webhook


def downgrade() -> None:
    op.execute("ALTER TABLE companies DROP COLUMN ai_api_key, DROP COLUMN ai_model, DROP COLUMN ai_provider")
