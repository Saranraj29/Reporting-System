import DeleteIcon from '@mui/icons-material/DeleteOutline'
import { Autocomplete, Button, Chip, Dialog, DialogActions, DialogContent, IconButton, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip } from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useFab } from '../fab'
import DeleteDialog from '../components/DeleteDialog'
import { Empty, ErrorAlert, ModalTitle, PageHeader, SearchBox, clickable, keepOpen } from '../components/ui'
import { fmtDate, titleCase } from '../format'
import { useSearch, useTeams, useUsers } from '../hooks'
import type { Client, Page, Project, Team, UserLite } from '../types'

export default function AdminProjects() {
  return (
    <>
      <PageHeader title="Projects" subtitle="Each project belongs to a client (or is internal). Owners see every task in their project." />
      <Projects />
    </>
  )
}

function Projects() {
  const qc = useQueryClient()
  const search = useSearch()
  const teams = useTeams()
  const [params] = useSearchParams()  // /admin/projects?team=<id> comes from the Teams page
  const [teamFilter, setTeamFilter] = useState(params.get('team') ?? '')
  const projects = useQuery({ queryKey: ['projects', 'admin', search.term, teamFilter], queryFn: () => api.get<Page<Project>>('/projects', { limit: 200, q: search.term, team: teamFilter }), placeholderData: keepPreviousData })
  const clients = useQuery({ queryKey: ['clients'], queryFn: () => api.get<Page<Client>>('/clients', { limit: 200 }) })
  const users = useUsers()
  const [dlg, setDlg] = useState<Project | 'new' | null>(null)
  const [del, setDel] = useState<Project | null>(null)
  useFab('New project', () => open('new'))
  const [f, setF] = useState({ name: '', client_id: '', status: 'active', start_date: '', end_date: '' })
  const [projectTeams, setProjectTeams] = useState<Team[]>([])
  const [members, setMembers] = useState<UserLite[]>([])
  const [owners, setOwners] = useState<UserLite[]>([])
  const open = (p: Project | 'new') => {
    setDlg(p)
    setF(p === 'new' ? { name: '', client_id: '', status: 'active', start_date: '', end_date: '' } : { name: p.name, client_id: p.client_id ?? '', status: p.status, start_date: p.start_date ?? '', end_date: p.end_date ?? '' })
    setProjectTeams(p === 'new' ? [] : teams.filter((t) => p.team_ids.includes(t.id)))
    setMembers(p === 'new' ? [] : users.filter((u) => p.member_ids.includes(u.id) && !p.owner_ids.includes(u.id)))
    setOwners(p === 'new' ? [] : users.filter((u) => p.owner_ids.includes(u.id)))
  }
  const save = useMutation({
    mutationFn: async () => {
      const body = { ...f, client_id: f.client_id || null, team_ids: projectTeams.map((t) => t.id), start_date: f.start_date || null, end_date: f.end_date || null }
      const p = dlg === 'new' ? await api.post<Project>('/projects', body) : await api.patch<Project>(`/projects/${(dlg as Project).id}`, body)
      await api.put(`/projects/${p.id}/members`, { user_ids: members.map((m) => m.id), owner_ids: owners.map((m) => m.id) })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['projects'] }); setDlg(null) },
  })
  return (
    <>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2 }} justifyContent="space-between">
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
          <SearchBox value={search.input} onChange={search.setInput} placeholder="Search projects, clients or teams" />
          <TextField select size="small" label="Team" value={teamFilter} onChange={(e) => setTeamFilter(e.target.value)} sx={{ minWidth: 170 }}>
            <MenuItem value="">All teams</MenuItem>
            {teams.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
          </TextField>
        </Stack>
      </Stack>
      <Paper sx={{ overflow: 'hidden' }}>
        <Table>
          <TableHead><TableRow><TableCell>Project</TableCell><TableCell>Team</TableCell><TableCell>Client</TableCell><TableCell>Status</TableCell><TableCell>Dates</TableCell><TableCell>Owners</TableCell><TableCell>Members</TableCell><TableCell align="right" sx={{ width: 56 }}><span style={{ position: 'absolute', left: -9999 }}>Delete</span></TableCell></TableRow></TableHead>
          <TableBody>
            {projects.data?.items.map((p) => (
              <TableRow key={p.id} hover sx={{ cursor: 'pointer' }} {...clickable(() => open(p))} aria-label={`Edit project ${p.name}`}>
                <TableCell sx={{ fontWeight: 600 }}>{p.name}</TableCell>
                <TableCell>{p.team_name ?? '—'}</TableCell>
                <TableCell>{p.client_name ?? 'Internal'}</TableCell>
                <TableCell><Chip size="small" label={titleCase(p.status)} color={p.status === 'active' ? 'success' : 'default'} variant="outlined" /></TableCell>
                <TableCell>{fmtDate(p.start_date)} – {fmtDate(p.end_date)}</TableCell>
                <TableCell>{p.owner_ids.length ? p.owner_ids.map((id) => users.find((u) => u.id === id)?.name ?? '…').join(', ') : '—'}</TableCell>
                <TableCell>{p.member_ids.length}</TableCell>
                <TableCell align="right" onClick={(e) => e.stopPropagation()}><Tooltip title="Delete"><IconButton size="small" aria-label={`Delete ${p.name}`} onClick={() => setDel(p)}><DeleteIcon fontSize="small" /></IconButton></Tooltip></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {projects.data?.items.length === 0 && <Empty>No projects yet.</Empty>}
      </Paper>
      {del && <DeleteDialog title={`Delete ${del.name}?`} description="The project is removed. If it has tasks, you will see how many before anything is deleted. Archiving keeps the history." path={`/projects/${del.id}`} onClose={() => setDel(null)} onDeleted={() => { qc.invalidateQueries({ queryKey: ['projects'] }); qc.invalidateQueries({ queryKey: ['tasks'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }) }} />}
      {dlg && (
        <Dialog open onClose={keepOpen(() => setDlg(null))} fullWidth maxWidth="sm">
          <ModalTitle onClose={() => setDlg(null)}>{dlg === 'new' ? 'New project' : 'Edit project'}</ModalTitle>
          <DialogContent dividers>
            <Stack spacing={2} sx={{ pt: 0.5 }}>
              <TextField label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
              <Autocomplete multiple options={teams} value={projectTeams} onChange={(_, v) => setProjectTeams(v)} getOptionLabel={(t) => t.name} isOptionEqualToValue={(a, b) => a.id === b.id}
                renderInput={(p) => <TextField {...p} label="Teams" helperText="A project can have several teams; every task in it belongs to all of them" />} />
              <Stack direction="row" spacing={2}>
                <TextField select fullWidth label="Client" value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })}><MenuItem value="">Internal</MenuItem>{clients.data?.items.map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}</TextField>
                <TextField select fullWidth label="Status" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>{['active', 'on_hold', 'completed', 'archived'].map((s) => <MenuItem key={s} value={s}>{titleCase(s)}</MenuItem>)}</TextField>
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField fullWidth type="date" label="Start" InputLabelProps={{ shrink: true }} value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} />
                <TextField fullWidth type="date" label="End" InputLabelProps={{ shrink: true }} value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} />
              </Stack>
              <Autocomplete multiple options={users} value={owners} onChange={(_, v) => setOwners(v)} getOptionLabel={(u) => u.name} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(p) => <TextField {...p} label="Project owners" helperText="Owners can see every task in this project, whoever created it or is assigned to it" />} />
              <Autocomplete multiple options={users} value={members} onChange={(_, v) => setMembers(v)} getOptionLabel={(u) => u.name} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(p) => <TextField {...p} label="Other members" helperText="Owners are added as members automatically" />} />
              <ErrorAlert error={save.error} />
            </Stack>
          </DialogContent>
          <DialogActions><Button onClick={() => setDlg(null)}>Cancel</Button><Button variant="contained" disabled={!f.name || save.isPending} onClick={() => save.mutate()}>Save</Button></DialogActions>
        </Dialog>
      )}
    </>
  )
}
