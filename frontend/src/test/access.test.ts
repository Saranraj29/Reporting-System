import { describe, expect, it } from 'vitest'
import { canOpen, type Who } from '../access'
import type { Me } from '../types'

const who = (perms: string[], owns = false): Who => {
  const set = new Set(perms)
  return {
    can: (k) => set.has(k),
    hasAny: (...bases) => bases.some((b) => set.has(b) || ['own', 'team', 'all'].some((s) => set.has(`${b}.${s}`))),
    me: { owns_projects: owns } as Me,
  }
}

const member = who(['task.view.own', 'task.edit.own', 'status.view.own', 'dashboard.view.own'])
const lead = who(['task.view.team', 'status.view.team', 'dashboard.view.team', 'report.weekly.view.team'])
const admin = who(['task.view.all', 'user.manage', 'role.manage', 'project.manage', 'settings.manage', 'report.weekly.view.all', 'report.ai.draft', 'status.view.all'])

describe('which pages a person may open', () => {
  it('a team member gets only the everyday pages', () => {
    for (const p of ['/', '/tasks', '/my-day', '/profile', '/preferences']) expect(canOpen(p, member), p).toBe(true)
    for (const p of ['/check-ins', '/reports', '/reports/runs/1', '/ai-reports', '/ai-reports/9', '/admin/users', '/admin/roles', '/admin/projects', '/admin/clients', '/admin/teams', '/admin/settings']) {
      expect(canOpen(p, member), p).toBe(false)
    }
  })

  it('a team lead sees check-ins and reports but no AI reports or administration', () => {
    expect(canOpen('/check-ins', lead)).toBe(true)
    expect(canOpen('/reports', lead)).toBe(true)
    expect(canOpen('/ai-reports', lead)).toBe(false)
    expect(canOpen('/admin/settings', lead)).toBe(false)
  })

  it('owning a project opens AI reports and the reports of that project', () => {
    expect(canOpen('/ai-reports', who(['task.view.own'], true))).toBe(true)
    expect(canOpen('/ai-reports/5', who(['task.view.own'], true))).toBe(true)
    expect(canOpen('/reports', who(['task.view.own'], true))).toBe(true)  // the server limits them to the projects they own
    expect(canOpen('/reports/runs/3', who(['task.view.own'], true))).toBe(true)
    expect(canOpen('/reports', who(['task.view.own'], false))).toBe(false)  // a plain member has no reports
  })

  it('an admin opens the administration pages their permissions allow', () => {
    for (const p of ['/admin/users', '/admin/roles', '/admin/projects', '/admin/teams', '/admin/settings', '/ai-reports', '/reports']) expect(canOpen(p, admin), p).toBe(true)
    expect(canOpen('/admin/settings', who(['user.manage']))).toBe(false)  // each page needs its own permission
  })

  it('matches whole path segments, not prefixes of a name', () => {
    expect(canOpen('/reports-archive', member)).toBe(true)  // not a /reports page, no rule applies
  })
})
