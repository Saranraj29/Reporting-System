"""AI harness operations: per-company switches and quotas, job lanes, one row per model call, report feedback

Revision ID: 0010
Revises: 0009
"""

from alembic import context, op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = context.config.get_main_option("app_db_role") or "rs_app"
    if not role.replace("_", "").isalnum():
        raise ValueError("invalid app role name")
    c = op.get_bind()
    c.exec_driver_sql(
        "ALTER TABLE companies ADD COLUMN ai_enabled boolean NOT NULL DEFAULT true, ADD COLUMN ai_assistant_enabled boolean NOT NULL DEFAULT true, "
        "ADD COLUMN ai_daily_report_quota integer NOT NULL DEFAULT 50, ADD COLUMN ai_daily_turn_quota integer NOT NULL DEFAULT 500"
    )
    c.exec_driver_sql("ALTER TABLE jobs ADD COLUMN queue text NOT NULL DEFAULT 'default'")
    c.exec_driver_sql("CREATE INDEX jobs_queue_idx ON jobs (queue, status, run_at)")
    c.exec_driver_sql("""
        CREATE TABLE ai_calls (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          surface text NOT NULL,                    -- report.plan | report.write | assistant | brief
          provider text NOT NULL, model text NOT NULL, prompt_version text NOT NULL,
          input_tokens integer NOT NULL DEFAULT 0, output_tokens integer NOT NULL DEFAULT 0, cached_tokens integer NOT NULL DEFAULT 0,
          latency_ms integer NOT NULL DEFAULT 0,
          repaired boolean NOT NULL DEFAULT false,
          verifier jsonb,                           -- {checked, failed}; never text
          fallback boolean NOT NULL DEFAULT false,  -- built-in wording was used for any part
          error_code text,                          -- null = the provider answered
          created_at timestamptz NOT NULL DEFAULT now()
        )""")
    c.exec_driver_sql("CREATE INDEX ai_calls_company_idx ON ai_calls (company_id, created_at DESC)")
    c.exec_driver_sql("""
        CREATE TABLE ai_feedback (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          target_type text NOT NULL CHECK (target_type IN ('report', 'answer', 'brief')),
          target_id uuid NOT NULL,
          rating smallint NOT NULL CHECK (rating IN (-1, 1)),
          reason text NOT NULL DEFAULT '',
          created_by uuid REFERENCES users(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (target_type, target_id, created_by)
        )""")
    for table in ("ai_calls", "ai_feedback"):
        c.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        c.exec_driver_sql(f"CREATE POLICY tenant_isolation ON {table} USING (company_id = current_company()) WITH CHECK (company_id = current_company())")
        c.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {role}")


def downgrade() -> None:
    c = op.get_bind()
    c.exec_driver_sql("DROP TABLE ai_feedback")
    c.exec_driver_sql("DROP TABLE ai_calls")
    c.exec_driver_sql("DROP INDEX jobs_queue_idx")
    c.exec_driver_sql("ALTER TABLE jobs DROP COLUMN queue")
    c.exec_driver_sql("ALTER TABLE companies DROP COLUMN ai_enabled, DROP COLUMN ai_assistant_enabled, DROP COLUMN ai_daily_report_quota, DROP COLUMN ai_daily_turn_quota")
