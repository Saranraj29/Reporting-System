export interface Me {
  id: string
  email: string
  name: string
  company: { id: string; name: string; timezone: string }
  roles: { id: string; name: string }[]
  permissions: string[]
  owns_projects?: boolean
  profile: { name: string; email: string; phone: string; job_title: string; location: string; bio: string }
  prefs: { email_reminders: boolean; start_page: string; compact_tables: boolean }
}
export interface Page<T> {
  items: T[]
  total: number
  page: number
  limit: number
}
export interface UserLite {
  id: string
  name: string
  email: string
  is_active: boolean
  roles: { id: string; name: string }[]
  email_verified?: boolean
}
export interface Assignee {
  id: string
  name: string
}
export interface Task {
  id: string
  project_id: string
  project_name: string
  team_id: string | null
  team_name: string | null
  title: string
  description: string
  activity_type: string
  priority: string
  status: string
  eta_hours: number | null
  actual_hours: number
  start_date: string | null
  due_date: string | null
  is_blocked: boolean
  overdue: boolean
  custom_fields: Record<string, unknown>
  assignees: Assignee[]
  can_edit?: boolean
}
export interface Project {
  id: string
  name: string
  client_id: string | null
  client_name: string | null
  status: string
  start_date: string | null
  end_date: string | null
  member_ids: string[]
  owner_ids: string[]
}
export interface Client {
  id: string
  name: string
  contact_name: string | null
  contact_email: string | null
}
export interface Contact {
  id: string
  name: string
  email: string
}
export interface Team {
  id: string
  name: string
  description: string
  lead_user_id: string | null
  member_ids: string[]
  open_tasks: number
  total_tasks: number
}
export interface TaskField {
  id: string
  key: string
  label: string
  type: 'text' | 'number' | 'date' | 'select'
  options: string[]
  required: boolean
  is_active: boolean
  is_builtin: boolean
}
export interface TimeEntry {
  id: string
  task_id: string
  task_title: string | null
  user_id: string
  user_name: string | null
  hours: number
  entry_date: string
  note: string
  started_at: string | null
  running: boolean
}
export interface DailyStatus {
  id: string
  user_id: string
  user_name: string | null
  status_date: string
  plan_today: string
  morning_at: string | null
  updated_at: string
  eod_at: string | null
  did_today: string
  next_up: string
  blockers: string
}
export interface Role {
  id: string
  name: string
  description: string
  permissions: string[]
  user_count: number
}
export interface ReportInfo {
  key: string
  title: string
  scope: string
  default_from: string
  default_to: string
}
export interface Template {
  id: string
  name: string
  audience: 'internal' | 'client'
  base_report: string
  format: string
  sections: string[]
  tone_instructions: string
  client_id: string | null
  client_name: string | null
  schedule: string
}
export interface RunSummary {
  id: string
  report_key: string
  status: string
  title: string
  template_id: string | null
  audience: string | null
  period_start: string
  period_end: string
  export_format: string | null
  error: string | null
  created_at: string
  approved_at: string | null
  ai_provider: string | null
  client_id: string | null
  person_filter: string | null
  downloads: { pdf: string | null; xlsx: string | null; docx: string | null; md: string | null }
}
export interface RunDetail extends RunSummary {
  figures: Record<string, any> | null
  ai_text: Record<string, any> | null
  sections: string[]
  tone_instructions: string | null
  redraft_note: string | null
}
export interface Share {
  id: string
  recipient_email: string
  expires_at: string
  viewed_at: string | null
  emailed_at: string | null
  revoked_at: string | null
}
export interface Dashboard {
  period: { from: string; to: string }
  tasks_by_status: Record<string, number>
  total_tasks: number
  overdue_count: number
  blocked_count: number
  total_hours: number
  hours_by_project: { project: string; hours: number }[]
  hours_by_activity: { activity_type: string; hours: number }[]
  hours_by_day: { date: string; hours: number }[]
  overdue_tasks: { id: string; title: string; priority: string; status: string; project: string; due_date: string | null; assignees: string }[]
  blockers: { id: string; title: string; priority: string; status: string; project: string; due_date: string | null; assignees: string }[]
  daily_status: {
    expected: number
    submitted_today: number
    morning_today: number
    eod_today: number
    missing_morning: string[]
    missing_eod: string[]
    blockers: { user: string; date: string; text: string }[]
  }
}
export interface Settings {
  name: string
  timezone: string
  email_domain: string
  report_email_enabled: boolean
  report_email_day: number | null
  slack_configured: boolean
  slack_webhook_hint?: string
  ai_enabled: boolean
}
export interface AiUsage {
  since: string
  status: string
  enabled: boolean
  calls: number
  errors: number
  tokens: { input: number; output: number; cached: number }
  budget_used_pct: number | null
  grounding_pass_rate: number | null
  fallback_rate: number | null
  repair_rate: number | null
  p95_latency_ms: number | null
  thumbs: { up: number; down: number }
  quota: { reports_per_day: number; turns_per_day: number }
}
export interface Comment {
  id: string
  user_id: string
  user_name: string
  body: string
  kind: 'comment' | 'system'
  is_internal: boolean
  created_at: string
}
export interface CheckInSummary {
  date: string
  expected: number
  morning_done: number
  eod_done: number
  missing_morning: string[]
  missing_eod: string[]
  blockers: { user: string; text: string }[]
}

export interface AiOutlineSection {
  id: string
  title: string
  scope: 'overall' | 'per_project'
  visual: 'table' | 'chart' | 'flow' | 'text'
  what: string
}
export interface AiReportSummary {
  id: string
  title: string
  request: string
  status: 'planning' | 'outline_ready' | 'generating' | 'ready' | 'failed'
  format_mode: 'auto' | 'visibility' | 'sample'
  period_start: string
  period_end: string
  error: string | null
  created_at: string
  written_by: 'ai' | 'builtin' | null
  downloads: Record<'md' | 'pdf' | 'docx' | 'xlsx', string | null>
}
export interface AiReportDetail extends AiReportSummary {
  created_by: string | null
  project_names: string[]
  people_names: string[]
  no_activity: string[]
  outline: { title: string; notes: string; sections: AiOutlineSection[]; per_project_count: number } | null
  missing_text: boolean
  builtin_sections: number
  my_feedback: 'up' | 'down' | null
}
export interface AiReportOptions {
  projects: { id: string; name: string }[]
  people: { id: string; name: string }[]
  all_projects: boolean
  ai_enabled: boolean
  ai_status: 'ready' | 'off' | 'not_configured' | 'provider_down'
  max_sample_chars: number
}

export interface AssistantCard {
  id: string
  title: string
  subtitle: string
  phase: number
  enabled: boolean
}
export interface SourcesCard {
  kind: 'sources'
  sources: { label: string; as_of: string | null; returned: number; total: number; items: { id: string; title: string }[] }[]
  handoff: { label: string; path: string; days: number | null; project_ids: string[] } | null
}
export interface AssistantMessage {
  id?: string
  role: 'user' | 'assistant'
  text: string
  card?: SourcesCard | null
  sentences?: { text: string; grounded: boolean }[]
  progress?: string
  error?: string
  created_at?: string
}
export interface AssistantStatus {
  status: 'ready' | 'unavailable'
  reason: 'off' | 'not_configured' | 'provider_down' | null
  input_enabled: boolean
  quick_actions_enabled: boolean
  cards: AssistantCard[]
  conversation_id: string | null
  messages: AssistantMessage[]
}
