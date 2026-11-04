"""AI reports: request -> structure preview -> report (replaces the template/approve/share flow in the UI)

Revision ID: 0007
Revises: 0006
"""

from alembic import context, op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = context.config.get_main_option("app_db_role") or "rs_app"
    if not role.replace("_", "").isalnum():
        raise ValueError("invalid app role name")
    conn = op.get_bind()
    conn.exec_driver_sql("""
        CREATE TABLE ai_reports (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          created_by uuid REFERENCES users(id) ON DELETE SET NULL,
          title text NOT NULL DEFAULT '',
          request text NOT NULL DEFAULT '',
          project_ids jsonb,                         -- NULL = every project the requester may report on
          period_start date NOT NULL,
          period_end date NOT NULL,
          format_mode text NOT NULL DEFAULT 'auto' CHECK (format_mode IN ('auto','visibility','sample')),
          format_sample text NOT NULL DEFAULT '',    -- the requester's own sample / outline (mode 'sample')
          status text NOT NULL DEFAULT 'planning' CHECK (status IN ('planning','outline_ready','generating','ready','failed')),
          facts jsonb,                               -- every number in the report, computed by the system
          outline jsonb,                             -- the structure shown for approval
          narrative jsonb,                           -- AI-written text parts (people are codes while the model sees them)
          markdown text,
          note text,                                 -- the requester's last change request
          error text,
          ai_provider text,                          -- which engine wrote it, or 'builtin'
          file_url_md text, file_url_pdf text, file_url_docx text, file_url_xlsx text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )""")
    conn.exec_driver_sql("CREATE INDEX ai_reports_company_idx ON ai_reports (company_id, created_at DESC)")
    conn.exec_driver_sql("CREATE TRIGGER ai_reports_updated_at BEFORE UPDATE ON ai_reports FOR EACH ROW EXECUTE FUNCTION set_updated_at()")
    conn.exec_driver_sql("ALTER TABLE ai_reports ENABLE ROW LEVEL SECURITY")
    conn.exec_driver_sql("CREATE POLICY tenant_isolation ON ai_reports USING (company_id = current_company()) WITH CHECK (company_id = current_company())")
    conn.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ai_reports TO {role}")
    # admins can request AI reports too (project owners can for the projects they own, no permission needed)
    conn.exec_driver_sql(
        "INSERT INTO role_permissions (company_id, role_id, permission_key) "
        "SELECT company_id, id, 'report.ai.draft' FROM roles WHERE name = 'Company Admin' ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE ai_reports")
