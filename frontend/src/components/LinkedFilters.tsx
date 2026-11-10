import { MenuItem, TextField } from '@mui/material'
import { change, personOptions, projectOptions, teamOptions, type Sel } from '../filters'
import type { Project, Team, UserLite } from '../types'

/** Team, Project and Person dropdowns that narrow each other: pick a team and only its projects and people are offered, and so on.
 *  An empty list says so ("No projects") instead of showing a blank dropdown. Leave `users` out to hide the Person filter. */
export default function LinkedFilters({ value, onChange, teams, projects, users, everyone = 'Everyone', widths = [150, 150, 160] }: {
  value: Sel
  onChange: (s: Sel) => void
  teams: Team[]
  projects: Project[]
  users?: UserLite[]
  everyone?: string
  widths?: [number, number, number] | number[]
}) {
  const data = { teams, projects, users }
  const set = (key: keyof Sel) => (e: React.ChangeEvent<HTMLInputElement>) => onChange(change(value, key, e.target.value, data))
  const t = teamOptions(data, value)
  const p = projectOptions(data, value)
  const u = personOptions(data, value)
  return (
    <>
      {teams.length > 0 && (
        <TextField select size="small" label="Team" value={value.team} onChange={set('team')} sx={{ minWidth: widths[0] }}>
          <MenuItem value="">All teams</MenuItem>
          {t.map((x) => <MenuItem key={x.id} value={x.id}>{x.name}</MenuItem>)}
          {t.length === 0 && <MenuItem disabled value="__none">No teams for this selection</MenuItem>}
        </TextField>
      )}
      <TextField select size="small" label="Project" value={value.project} onChange={set('project')} sx={{ minWidth: widths[1] }}>
        <MenuItem value="">All projects</MenuItem>
        {p.map((x) => <MenuItem key={x.id} value={x.id}>{x.name}</MenuItem>)}
        {p.length === 0 && <MenuItem disabled value="__none">No projects for this selection</MenuItem>}
      </TextField>
      {users && (
        <TextField select size="small" label="Person" value={value.user} onChange={set('user')} sx={{ minWidth: widths[2] }}>
          <MenuItem value="">{everyone}</MenuItem>
          {u.map((x) => <MenuItem key={x.id} value={x.id}>{x.name}</MenuItem>)}
          {u.length === 0 && <MenuItem disabled value="__none">No people for this selection</MenuItem>}
        </TextField>
      )}
    </>
  )
}
