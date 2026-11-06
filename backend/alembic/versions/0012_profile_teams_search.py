"""Profiles and preferences on users, teams as departments (description) and tasks that belong to a team; Team Members lose the AI assistant key

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    c = op.get_bind()
    c.exec_driver_sql(
        "ALTER TABLE users ADD COLUMN phone text NOT NULL DEFAULT '', ADD COLUMN job_title text NOT NULL DEFAULT '', "
        "ADD COLUMN location text NOT NULL DEFAULT '', ADD COLUMN bio text NOT NULL DEFAULT '', ADD COLUMN prefs jsonb NOT NULL DEFAULT '{}'"
    )
    c.exec_driver_sql("ALTER TABLE teams ADD COLUMN description text NOT NULL DEFAULT ''")
    c.exec_driver_sql("ALTER TABLE tasks ADD COLUMN team_id uuid REFERENCES teams(id) ON DELETE SET NULL")
    c.exec_driver_sql("CREATE INDEX tasks_team_idx ON tasks (team_id) WHERE team_id IS NOT NULL")
    # a plain user does not get the AI assistant by default (it can still be granted to any role in Roles & permissions)
    c.exec_driver_sql(
        "DELETE FROM role_permissions WHERE permission_key = 'assistant.use' AND role_id IN (SELECT id FROM roles WHERE name = 'Team Member')"
    )


def downgrade() -> None:
    c = op.get_bind()
    c.exec_driver_sql("DROP INDEX tasks_team_idx")
    c.exec_driver_sql("ALTER TABLE tasks DROP COLUMN team_id")
    c.exec_driver_sql("ALTER TABLE teams DROP COLUMN description")
    c.exec_driver_sql("ALTER TABLE users DROP COLUMN phone, DROP COLUMN job_title, DROP COLUMN location, DROP COLUMN bio, DROP COLUMN prefs")
