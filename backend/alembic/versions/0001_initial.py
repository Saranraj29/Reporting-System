"""initial schema

Revision ID: 0001
"""

from pathlib import Path

from alembic import context, op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = context.config.get_main_option("app_db_role") or "rs_app"
    if not role.replace("_", "").isalnum():
        raise ValueError("invalid app role name")
    sql = (Path(__file__).with_suffix(".sql")).read_text().replace("{APP_ROLE}", role)
    op.get_bind().exec_driver_sql(sql.replace("%", "%%"), {})


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
