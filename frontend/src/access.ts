import type { Me } from './types'

/** Who may open which page. One table, used by the sidebar (what is shown), the router (what can be opened by typing the address)
 *  and the "open this page after sign-in" choice, so they can never disagree. The server enforces the same permissions on its data. */
export interface Who {
  can: (key: string) => boolean
  hasAny: (...bases: string[]) => boolean
  me: Me | null
}

const RULES: [string, (w: Who) => boolean][] = [
  ['/tasks', (w) => w.hasAny('task.view')],
  ['/my-day', (w) => w.hasAny('task.view', 'status.view')],
  ['/check-ins', (w) => w.can('status.view.team') || w.can('status.view.all')],
  ['/reports', (w) => w.hasAny('report.weekly.view', 'report.monthly.view', 'report.performance.view', 'report.visibility.view')],
  ['/ai-reports', (w) => w.can('report.ai.draft') || !!w.me?.owns_projects],
  ['/admin/users', (w) => w.can('user.manage')],
  ['/admin/roles', (w) => w.can('role.manage')],
  ['/admin/projects', (w) => w.can('project.manage')],
  ['/admin/clients', (w) => w.can('project.manage')],
  ['/admin/teams', (w) => w.can('project.manage')],
  ['/admin/settings', (w) => w.can('settings.manage')],
]

/** The Dashboard ('/'), profile and preferences are open to everyone signed in; every other page follows its rule. */
export function canOpen(path: string, who: Who): boolean {
  const rule = RULES.find(([p]) => path === p || path.startsWith(`${p}/`))
  return rule ? rule[1](who) : true
}
