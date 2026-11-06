"""A team belongs to a project (tasks inherit it) instead of to each task

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    c = op.get_bind()
    c.exec_driver_sql("ALTER TABLE projects ADD COLUMN team_id uuid REFERENCES teams(id) ON DELETE SET NULL")
    c.exec_driver_sql("CREATE INDEX projects_team_idx ON projects (team_id) WHERE team_id IS NOT NULL")
    # tasks that already had a team: their project gets the team most of its tasks used
    c.exec_driver_sql(
        "UPDATE projects p SET team_id = (SELECT t.team_id FROM tasks t WHERE t.project_id = p.id AND t.team_id IS NOT NULL "
        "GROUP BY t.team_id ORDER BY count(*) DESC LIMIT 1)"
    )
    c.exec_driver_sql("DROP INDEX IF EXISTS tasks_team_idx")
    c.exec_driver_sql("ALTER TABLE tasks DROP COLUMN team_id")


def downgrade() -> None:
    c = op.get_bind()
    c.exec_driver_sql("ALTER TABLE tasks ADD COLUMN team_id uuid REFERENCES teams(id) ON DELETE SET NULL")
    c.exec_driver_sql("UPDATE tasks t SET team_id = (SELECT p.team_id FROM projects p WHERE p.id = t.project_id)")
    c.exec_driver_sql("CREATE INDEX tasks_team_idx ON tasks (team_id) WHERE team_id IS NOT NULL")
    c.exec_driver_sql("DROP INDEX projects_team_idx")
    c.exec_driver_sql("ALTER TABLE projects DROP COLUMN team_id")
