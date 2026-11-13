import type { Project, Team, UserLite } from './types'

/** The Team / Project / Person filters narrow each other (both ways), so a choice never leads to an impossible combination.
 *  - a team's projects are the projects it is one of the teams of; its people are its members and its lead
 *  - a project's people are its members and owners
 *  Pure functions: the options of one dropdown given the selection in the other two. */
export interface Sel {
  team: string
  project: string
  user: string
}
export const NONE: Sel = { team: '', project: '', user: '' }

interface Data {
  teams: Team[]
  projects: Project[]
  users?: UserLite[]
}

const teamPeople = (t: Team) => new Set([...t.member_ids, ...(t.lead_user_id ? [t.lead_user_id] : [])])
const projectPeople = (p: Project) => new Set([...p.member_ids, ...p.owner_ids])

export function projectOptions(d: Data, s: Sel): Project[] {
  return d.projects.filter((p) => (!s.team || p.team_ids.includes(s.team)) && (!s.user || projectPeople(p).has(s.user)))
}

export function teamOptions(d: Data, s: Sel): Team[] {
  const project = s.project ? d.projects.find((p) => p.id === s.project) : undefined
  return d.teams.filter((t) => (!s.project || !!project?.team_ids.includes(t.id)) && (!s.user || !!s.project || teamPeople(t).has(s.user)))
}

export function personOptions(d: Data, s: Sel): UserLite[] {
  const users = d.users ?? []
  const project = s.project ? d.projects.find((p) => p.id === s.project) : undefined
  const team = s.team ? d.teams.find((t) => t.id === s.team) : undefined
  if (project) return users.filter((u) => projectPeople(project).has(u.id))  // the project's people (a project can have several teams, so the team does not narrow it further)
  if (team) return users.filter((u) => teamPeople(team).has(u.id))
  return users
}

/** The new selection after the person changed `key`: the choice is kept, and any other filter it no longer fits is cleared. */
export function change(cur: Sel, key: keyof Sel, value: string, d: Data): Sel {
  const next: Sel = { ...cur, [key]: value }
  const valid: Record<keyof Sel, (s: Sel) => boolean> = {
    team: (s) => !s.team || teamOptions(d, s).some((t) => t.id === s.team),
    project: (s) => !s.project || projectOptions(d, s).some((p) => p.id === s.project),
    user: (s) => !s.user || !d.users || personOptions(d, s).some((u) => u.id === s.user),
  }
  for (const other of ['project', 'team', 'user'] as const) {  // project first: once it is cleared the team is judged without it
    if (other !== key && !valid[other](next)) next[other] = ''
  }
  return next
}
