"""project owners: a project owner sees every task in the project, whoever created or is assigned to it

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_members ADD COLUMN is_owner boolean NOT NULL DEFAULT false")
    op.execute("CREATE INDEX project_members_owner_idx ON project_members (user_id) WHERE is_owner")


def downgrade() -> None:
    op.execute("DROP INDEX project_members_owner_idx")
    op.execute("ALTER TABLE project_members DROP COLUMN is_owner")
