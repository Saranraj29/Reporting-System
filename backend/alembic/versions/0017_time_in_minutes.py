"""Time entries keep minutes: hours with 4 decimals (a minute is 0.0167 h; two decimals rounded a 1-minute timer to 1.2 minutes)

Revision ID: 0017
Revises: 0016
"""

from alembic import context, op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _role() -> str:
    role = context.config.get_main_option("app_db_role") or "rs_app"
    if not role.replace("_", "").isalnum():
        raise ValueError("invalid app role name")
    return role


def _retype(hours_type: str, sum_type: str) -> None:
    c = op.get_bind()
    c.exec_driver_sql("DROP VIEW task_hours")  # the view reads the column, so it is rebuilt around the change
    c.exec_driver_sql(f"ALTER TABLE time_entries ALTER COLUMN hours TYPE {hours_type}")
    c.exec_driver_sql(f"""
        CREATE VIEW task_hours WITH (security_invoker = true) AS
          SELECT t.company_id, t.id AS task_id, COALESCE(SUM(e.hours), 0)::{sum_type} AS actual_hours
          FROM tasks t LEFT JOIN time_entries e ON e.task_id = t.id
          GROUP BY t.company_id, t.id""")
    c.exec_driver_sql(f"GRANT SELECT ON task_hours TO {_role()}")


def upgrade() -> None:
    _retype("numeric(8,4)", "numeric(12,4)")


def downgrade() -> None:
    _retype("numeric(6,2)", "numeric(10,2)")
