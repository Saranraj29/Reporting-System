export interface Me {
  id: string
  email: string
  name: string
  company: { id: string; name: string; timezone: string }
  roles: { id: string; name: string }[]
  permissions: string[]
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
  lead_user_id: string | null
  member_ids: string[]
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
  downloads: { pdf: string | null; xlsx: string | null; docx: string | null }
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
  daily_status: { expected: number; submitted_today: number; blockers: { user: string; date: string; text: string }[] }
}
export interface Settings {
  name: string
  timezone: string
  email_domain: string
  report_email_enabled: boolean
  report_email_day: number | null
  slack_configured: boolean
  slack_webhook_hint?: string
}
