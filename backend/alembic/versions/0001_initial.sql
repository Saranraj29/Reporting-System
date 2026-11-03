-- Release 1 schema. Executed by 0001_initial.py. {APP_ROLE} is substituted by the migration.
-- Tenancy: every business table carries company_id and has a row-level-security policy
-- bound to the app.company_id setting. The application connects as a non-owner role, so
-- policies always apply; the owner role is used only for migrations and a handful of
-- SECURITY DEFINER lookup functions (login, domain check, shared report token, worker scan).

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION current_company() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('app.company_id', true), '')::uuid
$$ LANGUAGE sql STABLE;

-- ---------------------------------------------------------------- tenant
CREATE TABLE companies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  email_domain text NOT NULL UNIQUE,
  slack_webhook_url text,                     -- encrypted with the platform key
  report_email_day smallint DEFAULT 0 CHECK (report_email_day BETWEEN 0 AND 6),  -- NULL = scheduled report email off
  timezone text NOT NULL DEFAULT 'UTC',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- people
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  email text NOT NULL,
  password_hash text,
  google_id text,
  name text NOT NULL,
  email_verified_at timestamptz,
  is_active boolean NOT NULL DEFAULT true,
  refresh_version integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_key ON users (lower(email));
CREATE INDEX users_company_idx ON users (company_id);

CREATE TABLE teams (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name text NOT NULL,
  lead_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, name)
);

CREATE TABLE team_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (team_id, user_id)
);
CREATE INDEX team_members_user_idx ON team_members (user_id);

-- ---------------------------------------------------------------- access
CREATE TABLE permissions (
  key text PRIMARY KEY,
  description text NOT NULL DEFAULT ''
);

CREATE TABLE roles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, name)
);

CREATE TABLE role_permissions (
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_key text NOT NULL REFERENCES permissions(key) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_key)
);

CREATE TABLE user_roles (
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);
CREATE INDEX user_roles_role_idx ON user_roles (role_id);

-- ---------------------------------------------------------------- work
CREATE TABLE clients (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name text NOT NULL,
  contact_name text,
  contact_email text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, name)
);

CREATE TABLE client_contacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  name text NOT NULL,
  email text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (client_id, email)
);

CREATE TABLE projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name text NOT NULL,
  client_id uuid REFERENCES clients(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','on_hold','completed','archived')),
  start_date date,
  end_date date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, name)
);

CREATE TABLE project_members (
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  created_by uuid REFERENCES users(id) ON DELETE SET NULL,
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  activity_type text NOT NULL DEFAULT 'Development',
  priority text NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high','urgent')),
  status text NOT NULL DEFAULT 'todo' CHECK (status IN ('todo','in_progress','blocked','in_review','done')),
  eta_hours numeric(7,2),
  start_date date,
  due_date date,
  is_blocked boolean NOT NULL DEFAULT false,
  completed_at timestamptz,
  custom_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tasks_company_project_idx ON tasks (company_id, project_id);
CREATE INDEX tasks_company_status_idx ON tasks (company_id, status);
CREATE INDEX tasks_company_due_idx ON tasks (company_id, due_date);

CREATE TABLE task_assignees (
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, user_id)
);
CREATE INDEX task_assignees_user_task_idx ON task_assignees (user_id, task_id);

CREATE TABLE time_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  hours numeric(6,2) NOT NULL DEFAULT 0 CHECK (hours >= 0 AND hours <= 24),
  entry_date date NOT NULL,
  started_at timestamptz,
  stopped_at timestamptz,
  note text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX time_entries_user_date_idx ON time_entries (user_id, entry_date);
CREATE INDEX time_entries_task_idx ON time_entries (task_id);
CREATE INDEX time_entries_company_date_idx ON time_entries (company_id, entry_date);
-- at most one running timer per user
CREATE UNIQUE INDEX time_entries_one_running_idx ON time_entries (user_id)
  WHERE started_at IS NOT NULL AND stopped_at IS NULL;

CREATE TABLE task_comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  body text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX task_comments_task_idx ON task_comments (task_id);

CREATE TABLE daily_status (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status_date date NOT NULL,
  did_today text NOT NULL DEFAULT '',
  next_up text NOT NULL DEFAULT '',
  blockers text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, status_date)
);

-- ---------------------------------------------------------------- config
CREATE TABLE task_field_definitions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  key text NOT NULL,
  label text NOT NULL,
  type text NOT NULL CHECK (type IN ('text','number','date','select')),
  options jsonb NOT NULL DEFAULT '[]'::jsonb,
  required boolean NOT NULL DEFAULT false,
  is_active boolean NOT NULL DEFAULT true,
  is_builtin boolean NOT NULL DEFAULT false,   -- built-in BRD fields can be hidden, never dropped
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, key)
);

-- ---------------------------------------------------------------- reports
CREATE TABLE report_templates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name text NOT NULL,
  audience text NOT NULL DEFAULT 'client' CHECK (audience IN ('internal','client')),
  base_report text NOT NULL DEFAULT 'weekly',
  format text NOT NULL DEFAULT 'narrative' CHECK (format IN ('narrative','bullet_summary','table_commentary')),
  sections jsonb NOT NULL DEFAULT '[]'::jsonb,
  tone_instructions text NOT NULL DEFAULT '',
  client_id uuid REFERENCES clients(id) ON DELETE SET NULL,
  schedule text NOT NULL DEFAULT 'none' CHECK (schedule IN ('weekly','monthly','none')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE report_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  template_id uuid REFERENCES report_templates(id) ON DELETE SET NULL,
  report_key text NOT NULL,                   -- base report module key
  params jsonb NOT NULL DEFAULT '{}'::jsonb,  -- filters for plain exports (project, user, ...)
  scope_user_ids jsonb,                       -- snapshot of the requester's visibility (NULL = all)
  period_start date NOT NULL,
  period_end date NOT NULL,
  requested_by uuid REFERENCES users(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','drafted','approved','sent','ready','failed')),
  export_format text,
  figures jsonb,
  ai_text jsonb,
  ai_provider text,
  redraft_note text,
  error text,
  approved_by uuid REFERENCES users(id) ON DELETE SET NULL,
  approved_at timestamptz,
  file_url_pdf text,
  file_url_xlsx text,
  file_url_docx text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX report_runs_company_idx ON report_runs (company_id, created_at DESC);

CREATE TABLE report_shares (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  report_run_id uuid NOT NULL REFERENCES report_runs(id) ON DELETE CASCADE,
  client_id uuid REFERENCES clients(id) ON DELETE SET NULL,
  recipient_email text NOT NULL,
  token text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  viewed_at timestamptz,
  revoked_at timestamptz,
  emailed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE notification_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  kind text NOT NULL,
  channel text NOT NULL CHECK (channel IN ('email','slack')),
  status text NOT NULL DEFAULT 'sent' CHECK (status IN ('sent','failed')),
  error text,
  sent_at timestamptz NOT NULL DEFAULT now(),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notification_log_company_idx ON notification_log (company_id, sent_at DESC);

-- ---------------------------------------------------------------- job queue (infrastructure, no tenant RLS)
CREATE TABLE jobs (
  id bigserial PRIMARY KEY,
  kind text NOT NULL,
  company_id uuid,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  run_at timestamptz NOT NULL DEFAULT now(),
  locked_at timestamptz,
  last_error text,
  dedupe_key text UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX jobs_due_idx ON jobs (run_at) WHERE status = 'queued';

-- ---------------------------------------------------------------- views
-- Time spent is derived, never stored on the task. security_invoker keeps RLS in force.
CREATE VIEW task_hours WITH (security_invoker = true) AS
  SELECT t.company_id, t.id AS task_id, COALESCE(SUM(e.hours), 0)::numeric(10,2) AS actual_hours
  FROM tasks t LEFT JOIN time_entries e ON e.task_id = t.id
  GROUP BY t.company_id, t.id;

-- ---------------------------------------------------------------- triggers
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['companies','users','teams','team_members','roles','clients','client_contacts',
      'projects','tasks','time_entries','task_comments','daily_status','task_field_definitions',
      'report_templates','report_runs','report_shares','notification_log'])
  LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
                   t || '_updated_at', t);
  END LOOP;
END $$;

-- ---------------------------------------------------------------- row level security
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['users','teams','team_members','roles','role_permissions','user_roles','clients',
      'client_contacts','projects','project_members','tasks','task_assignees','time_entries','task_comments',
      'daily_status','task_field_definitions','report_templates','report_runs','report_shares','notification_log'])
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (company_id = current_company()) WITH CHECK (company_id = current_company())', t);
  END LOOP;
END $$;

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON companies USING (id = current_company()) WITH CHECK (id = current_company());

-- ---------------------------------------------------------------- SECURITY DEFINER lookups
-- These run as the owner so they can see across tenants; each returns the minimum needed.
CREATE OR REPLACE FUNCTION auth_user_by_email(p_email text)
RETURNS TABLE (id uuid, company_id uuid, email text, password_hash text, google_id text, name text,
               email_verified_at timestamptz, is_active boolean, refresh_version integer)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT u.id, u.company_id, u.email, u.password_hash, u.google_id, u.name,
         u.email_verified_at, u.is_active, u.refresh_version
  FROM users u WHERE lower(u.email) = lower(p_email) LIMIT 1
$$;

CREATE OR REPLACE FUNCTION auth_company_by_domain(p_domain text)
RETURNS TABLE (id uuid, name text)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT c.id, c.name FROM companies c WHERE c.email_domain = lower(p_domain) LIMIT 1
$$;

CREATE OR REPLACE FUNCTION shared_share_by_token(p_token text)
RETURNS TABLE (id uuid, company_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT s.id, s.company_id FROM report_shares s WHERE s.token = p_token LIMIT 1
$$;

CREATE OR REPLACE FUNCTION worker_companies()
RETURNS TABLE (id uuid, name text, timezone text, slack_webhook_url text, report_email_day smallint)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT c.id, c.name, c.timezone, c.slack_webhook_url, c.report_email_day FROM companies c
$$;

REVOKE ALL ON FUNCTION auth_user_by_email(text), auth_company_by_domain(text),
  shared_share_by_token(text), worker_companies() FROM PUBLIC;

-- ---------------------------------------------------------------- grants for the application role
GRANT USAGE ON SCHEMA public TO {APP_ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
GRANT EXECUTE ON FUNCTION auth_user_by_email(text), auth_company_by_domain(text),
  shared_share_by_token(text), worker_companies() TO {APP_ROLE};
