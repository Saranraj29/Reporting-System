"""Reminder settings per company (on/off, three send times) and time off (company holidays + personal leave)

Revision ID: 0014
Revises: 0013
"""

from alembic import context, op

revision = "0014"
down_revision = "0013"
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
    # defaults equal the times that used to be hard-coded in the worker, so existing companies behave exactly as before
    c.exec_driver_sql("ALTER TABLE companies ADD COLUMN reminders_enabled boolean NOT NULL DEFAULT true")
    c.exec_driver_sql("ALTER TABLE companies ADD COLUMN reminder_morning_time time NOT NULL DEFAULT '10:00'")
    c.exec_driver_sql("ALTER TABLE companies ADD COLUMN reminder_eod_time time NOT NULL DEFAULT '17:30'")
    c.exec_driver_sql("ALTER TABLE companies ADD COLUMN reminder_due_time time NOT NULL DEFAULT '09:00'")
    c.exec_driver_sql("""
        CREATE TABLE time_off (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          user_id uuid REFERENCES users(id) ON DELETE CASCADE,   -- NULL = company holiday, otherwise that person's leave
          start_date date NOT NULL,
          end_date date NOT NULL CHECK (end_date >= start_date),
          note text NOT NULL DEFAULT '',
          created_by uuid REFERENCES users(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )""")
    c.exec_driver_sql("CREATE INDEX time_off_company_dates_idx ON time_off (company_id, start_date, end_date)")
    c.exec_driver_sql("CREATE INDEX time_off_user_idx ON time_off (user_id) WHERE user_id IS NOT NULL")
    c.exec_driver_sql("CREATE TRIGGER time_off_updated_at BEFORE UPDATE ON time_off FOR EACH ROW EXECUTE FUNCTION set_updated_at()")
    c.exec_driver_sql("ALTER TABLE time_off ENABLE ROW LEVEL SECURITY")
    c.exec_driver_sql("CREATE POLICY tenant_isolation ON time_off USING (company_id = current_company()) WITH CHECK (company_id = current_company())")
    c.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON time_off TO {role}")
    # the worker scan now also needs the reminder settings (a changed return type means drop + create)
    c.exec_driver_sql("DROP FUNCTION worker_companies()")
    c.exec_driver_sql("""
        CREATE FUNCTION worker_companies()
        RETURNS TABLE (id uuid, name text, timezone text, slack_webhook_url text, report_email_day smallint,
                       reminders_enabled boolean, reminder_morning_time time, reminder_eod_time time, reminder_due_time time)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT c.id, c.name, c.timezone, c.slack_webhook_url, c.report_email_day,
                 c.reminders_enabled, c.reminder_morning_time, c.reminder_eod_time, c.reminder_due_time FROM companies c
        $$""")
    c.exec_driver_sql("REVOKE ALL ON FUNCTION worker_companies() FROM PUBLIC")
    c.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION worker_companies() TO {role}")


def downgrade() -> None:
    role = _role()
    c = op.get_bind()
    c.exec_driver_sql("DROP FUNCTION worker_companies()")
    c.exec_driver_sql("""
        CREATE FUNCTION worker_companies()
        RETURNS TABLE (id uuid, name text, timezone text, slack_webhook_url text, report_email_day smallint)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT c.id, c.name, c.timezone, c.slack_webhook_url, c.report_email_day FROM companies c
        $$""")
    c.exec_driver_sql("REVOKE ALL ON FUNCTION worker_companies() FROM PUBLIC")
    c.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION worker_companies() TO {role}")
    c.exec_driver_sql("DROP TABLE time_off")
    c.exec_driver_sql("ALTER TABLE companies DROP COLUMN reminder_due_time, DROP COLUMN reminder_eod_time, "
                      "DROP COLUMN reminder_morning_time, DROP COLUMN reminders_enabled")
