import { describe, expect, it } from 'vitest'
import { change, NONE, personOptions, projectOptions, teamOptions } from '../filters'
import type { Project, Team, UserLite } from '../types'

const user = (id: string): UserLite => ({ id, name: id, email: `${id}@x.com` } as UserLite)
const team = (id: string, members: string[], lead: string | null = null): Team =>
  ({ id, name: id, description: '', lead_user_id: lead, member_ids: members, project_count: 0, open_tasks: 0, total_tasks: 0 })
const project = (id: string, teams: string[], members: string[], owners: string[] = []): Project =>
  ({ id, name: id, team_ids: teams, team_name: null, member_ids: members, owner_ids: owners } as unknown as Project)

// Data team: ann (lead), bob.   Web team: cy.   Apollo (Data): ann, bob + owner dee.   Hermes (Web): cy.   Orphan: no team, bob.
const d = {
  teams: [team('data', ['bob'], 'ann'), team('web', ['cy'])],
  projects: [project('apollo', ['data'], ['ann', 'bob'], ['dee']), project('hermes', ['web'], ['cy']), project('orphan', [], ['bob'])],
  users: ['ann', 'bob', 'cy', 'dee', 'eve'].map(user),
}
const ids = (xs: { id: string }[]) => xs.map((x) => x.id)

describe('linked Team / Project / Person filters', () => {
  it('offers everything when nothing is selected', () => {
    expect(ids(teamOptions(d, NONE))).toEqual(['data', 'web'])
    expect(ids(projectOptions(d, NONE))).toEqual(['apollo', 'hermes', 'orphan'])
    expect(ids(personOptions(d, NONE))).toEqual(['ann', 'bob', 'cy', 'dee', 'eve'])
  })

  it('a team narrows the projects to its own and the people to its members and lead', () => {
    const s = { ...NONE, team: 'data' }
    expect(ids(projectOptions(d, s))).toEqual(['apollo'])
    expect(ids(personOptions(d, s))).toEqual(['ann', 'bob'])
  })

  it('a project narrows the people to its members and owners, and the teams to its team', () => {
    const s = { ...NONE, project: 'apollo' }
    expect(ids(personOptions(d, s))).toEqual(['ann', 'bob', 'dee'])
    expect(ids(teamOptions(d, s))).toEqual(['data'])
    expect(ids(teamOptions(d, { ...NONE, project: 'orphan' }))).toEqual([])  // a project without a team: no team fits
  })

  it('works the other way round too: a person narrows the projects and the teams', () => {
    expect(ids(projectOptions(d, { ...NONE, user: 'bob' }))).toEqual(['apollo', 'orphan'])
    expect(ids(teamOptions(d, { ...NONE, user: 'cy' }))).toEqual(['web'])
    expect(ids(projectOptions(d, { ...NONE, user: 'eve' }))).toEqual([])  // someone on no project: an empty list, not a wrong one
  })

  it('keeps the new choice and clears the filters it no longer fits', () => {
    expect(change({ team: 'web', project: 'hermes', user: 'cy' }, 'team', 'data', d)).toEqual({ team: 'data', project: '', user: '' })
    expect(change({ team: 'data', project: '', user: 'bob' }, 'project', 'apollo', d)).toEqual({ team: 'data', project: 'apollo', user: 'bob' })  // bob is on Apollo: stays
    expect(change({ team: 'data', project: 'apollo', user: 'ann' }, 'user', 'cy', d)).toEqual({ team: '', project: '', user: 'cy' })
    expect(change({ team: 'data', project: 'apollo', user: 'bob' }, 'team', '', d)).toEqual({ team: '', project: 'apollo', user: 'bob' })  // "All teams" keeps the rest
  })

  it('a project with several teams is offered under each of them', () => {
    const shared = { ...d, projects: [...d.projects, project('portal', ['data', 'web'], ['cy'])] }
    expect(ids(projectOptions(shared, { ...NONE, team: 'data' }))).toEqual(['apollo', 'portal'])
    expect(ids(projectOptions(shared, { ...NONE, team: 'web' }))).toEqual(['hermes', 'portal'])
    expect(ids(teamOptions(shared, { ...NONE, project: 'portal' }))).toEqual(['data', 'web'])
  })

  it('a selected project keeps its team selectable even when the person is not a team member', () => {
    const s = { team: 'data', project: 'apollo', user: 'dee' }  // dee only owns Apollo
    expect(ids(teamOptions(d, s))).toEqual(['data'])
    expect(change(s, 'user', 'dee', d)).toEqual(s)
  })

  it('without a person list (people the user may not see) the person filter is ignored', () => {
    const noUsers = { teams: d.teams, projects: d.projects }
    expect(change({ team: '', project: '', user: 'x' }, 'team', 'data', noUsers).user).toBe('x')
  })
})
