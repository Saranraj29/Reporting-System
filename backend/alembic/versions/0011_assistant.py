"""AI assistant (phase 1): permission key for every role, conversations and messages

Revision ID: 0011
Revises: 0010
"""

from alembic import context, op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = context.config.get_main_option("app_db_role") or "rs_app"
    if not role.replace("_", "").isalnum():
        raise ValueError("invalid app role name")
    c = op.get_bind()
    c.exec_driver_sql("INSERT INTO permissions (key, description) VALUES ('assistant.use', 'Use the AI assistant (answers only from data you may see)') ON CONFLICT DO NOTHING")
    c.exec_driver_sql(
        "INSERT INTO role_permissions (company_id, role_id, permission_key) SELECT company_id, id, 'assistant.use' FROM roles ON CONFLICT DO NOTHING"
    )
    c.exec_driver_sql("""
        CREATE TABLE ai_conversations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          summary jsonb NOT NULL DEFAULT '{}',      -- typed summary built by code: entity ids, period, assumptions
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )""")
    c.exec_driver_sql("""
        CREATE TABLE ai_messages (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          conversation_id uuid NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          role text NOT NULL CHECK (role IN ('user', 'assistant')),
          text text NOT NULL DEFAULT '',            -- assistant: only the sentences that passed the grounding check
          card jsonb,                               -- sources card built by code
          tool_calls jsonb,                         -- [{tool, args, rows, as_of}] summary, never row data
          created_at timestamptz NOT NULL DEFAULT now()
        )""")
    c.exec_driver_sql("CREATE INDEX ai_conversations_user_idx ON ai_conversations (user_id, updated_at DESC)")
    c.exec_driver_sql("CREATE INDEX ai_messages_conv_idx ON ai_messages (conversation_id, created_at)")
    c.exec_driver_sql("CREATE INDEX ai_messages_company_day_idx ON ai_messages (company_id, created_at)")
    for table in ("ai_conversations", "ai_messages"):
        c.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        c.exec_driver_sql(f"CREATE POLICY tenant_isolation ON {table} USING (company_id = current_company()) WITH CHECK (company_id = current_company())")
        c.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {role}")


def downgrade() -> None:
    c = op.get_bind()
    c.exec_driver_sql("DROP TABLE ai_messages")
    c.exec_driver_sql("DROP TABLE ai_conversations")
    c.exec_driver_sql("DELETE FROM role_permissions WHERE permission_key = 'assistant.use'")
    c.exec_driver_sql("DELETE FROM permissions WHERE key = 'assistant.use'")
