"""Markdown report downloads and the project visibility report permission

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

GRANTS = {"Team Lead": "team", "Manager": "all", "CEO / CTO": "all", "Company Admin": "all"}  # same reach as the weekly report


def upgrade() -> None:
    op.execute("ALTER TABLE report_runs ADD COLUMN file_url_md text")
    op.execute(
        "INSERT INTO permissions (key, description) VALUES "
        "('report.visibility.view.team', 'Project visibility report (team)'), "
        "('report.visibility.view.all', 'Project visibility report (company)') ON CONFLICT DO NOTHING"
    )
    for role, scope in GRANTS.items():  # existing companies get the key on the seeded roles; custom roles are left alone
        op.execute(
            f"INSERT INTO role_permissions (company_id, role_id, permission_key) "
            f"SELECT company_id, id, 'report.visibility.view.{scope}' FROM roles WHERE name = '{role}' ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission_key LIKE 'report.visibility.%'")
    op.execute("DELETE FROM permissions WHERE key LIKE 'report.visibility.%'")
    op.execute("ALTER TABLE report_runs DROP COLUMN file_url_md")
