"""A project can have several teams (projects.team_id becomes the project_teams join table)

Revision ID: 0018
Revises: 0017
"""

from alembic import context, op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def _role() -> str:
    role = context.config.get_main_option("app_db_role") or "rs_app"
    if not role.replace("_", "").isalnum():
        raise ValueError("invalid app role name")
    return role


def upgrade() -> None:
    role = _role()
    c = op.get_bind()
    c.exec_driver_sql("""
        CREATE TABLE project_teams (
          company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
          PRIMARY KEY (project_id, team_id)
        )""")
    c.exec_driver_sql("CREATE INDEX project_teams_team_idx ON project_teams (team_id)")
    c.exec_driver_sql("INSERT INTO project_teams (company_id, project_id, team_id) SELECT company_id, id, team_id FROM projects WHERE team_id IS NOT NULL")
    c.exec_driver_sql("ALTER TABLE project_teams ENABLE ROW LEVEL SECURITY")
    c.exec_driver_sql("CREATE POLICY tenant_isolation ON project_teams USING (company_id = current_company()) WITH CHECK (company_id = current_company())")
    c.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON project_teams TO {role}")
    c.exec_driver_sql("DROP INDEX IF EXISTS projects_team_idx")
    c.exec_driver_sql("ALTER TABLE projects DROP COLUMN team_id")


def downgrade() -> None:
    c = op.get_bind()
    c.exec_driver_sql("ALTER TABLE projects ADD COLUMN team_id uuid REFERENCES teams(id) ON DELETE SET NULL")
    c.exec_driver_sql("UPDATE projects p SET team_id = (SELECT pt.team_id FROM project_teams pt WHERE pt.project_id = p.id ORDER BY pt.team_id LIMIT 1)")
    c.exec_driver_sql("CREATE INDEX projects_team_idx ON projects (team_id) WHERE team_id IS NOT NULL")
    c.exec_driver_sql("DROP TABLE project_teams")
