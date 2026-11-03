import AddIcon from '@mui/icons-material/Add'
import { Autocomplete, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Paper, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { Empty, ErrorAlert, PageHeader } from '../components/ui'
import { fmtDate, titleCase } from '../format'
import type { Client, Contact, Page, Project, Team, UserLite } from '../types'

export default function AdminProjects() {
  const [tab, setTab] = useState(0)
  return (
    <>
      <PageHeader title="Projects & clients" subtitle="Projects belong to clients; teams decide who sees whose work" />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Projects" /><Tab label="Clients" /><Tab label="Teams" />
      </Tabs>
      {tab === 0 && <Projects />}
      {tab === 1 && <Clients />}
      {tab === 2 && <Teams />}
    </>
  )
}

function useUsers() {
  return useQuery({ queryKey: ['users', 'all'], queryFn: () => api.get<Page<UserLite>>('/users', { limit: 200 }) }).data?.items ?? []
}

function Projects() {
  const qc = useQueryClient()
  const projects = useQuery({ queryKey: ['projects', 'all'], queryFn: () => api.get<Page<Project>>('/projects', { limit: 200 }) })
  const clients = useQuery({ queryKey: ['clients'], queryFn: () => api.get<Page<Client>>('/clients', { limit: 200 }) })
  const users = useUsers()
  const [dlg, setDlg] = useState<Project | 'new' | null>(null)
  const [f, setF] = useState({ name: '', client_id: '', status: 'active', start_date: '', end_date: '' })
  const [members, setMembers] = useState<UserLite[]>([])
  const open = (p: Project | 'new') => {
    setDlg(p)
    setF(p === 'new' ? { name: '', client_id: '', status: 'active', start_date: '', end_date: '' } : { name: p.name, client_id: p.client_id ?? '', status: p.status, start_date: p.start_date ?? '', end_date: p.end_date ?? '' })
    setMembers(p === 'new' ? [] : users.filter((u) => p.member_ids.includes(u.id)))
  }
  const save = useMutation({
    mutationFn: async () => {
      const body = { ...f, client_id: f.client_id || null, start_date: f.start_date || null, end_date: f.end_date || null }
      const p = dlg === 'new' ? await api.post<Project>('/projects', body) : await api.patch<Project>(`/projects/${(dlg as Project).id}`, body)
      await api.put(`/projects/${p.id}/members`, { user_ids: members.map((m) => m.id) })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['projects'] }); setDlg(null) },
  })
  return (
    <>
      <Button variant="contained" startIcon={<AddIcon />} sx={{ mb: 2 }} onClick={() => open('new')}>New project</Button>
      <Paper sx={{ overflow: 'hidden' }}>
        <Table>
          <TableHead><TableRow><TableCell>Project</TableCell><TableCell>Client</TableCell><TableCell>Status</TableCell><TableCell>Dates</TableCell><TableCell>Members</TableCell></TableRow></TableHead>
          <TableBody>
            {projects.data?.items.map((p) => (
              <TableRow key={p.id} hover sx={{ cursor: 'pointer' }} onClick={() => open(p)}>
                <TableCell sx={{ fontWeight: 600 }}>{p.name}</TableCell>
                <TableCell>{p.client_name ?? '—'}</TableCell>
                <TableCell><Chip size="small" label={titleCase(p.status)} color={p.status === 'active' ? 'success' : 'default'} variant="outlined" /></TableCell>
                <TableCell>{fmtDate(p.start_date)} – {fmtDate(p.end_date)}</TableCell>
                <TableCell>{p.member_ids.length}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {projects.data?.items.length === 0 && <Empty>No projects yet.</Empty>}
      </Paper>
      {dlg && (
        <Dialog open onClose={() => setDlg(null)} fullWidth maxWidth="sm">
          <DialogTitle>{dlg === 'new' ? 'New project' : 'Edit project'}</DialogTitle>
          <DialogContent dividers>
            <Stack spacing={2} sx={{ pt: 0.5 }}>
              <TextField label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
              <Stack direction="row" spacing={2}>
                <TextField select fullWidth label="Client" value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })}><MenuItem value="">Internal</MenuItem>{clients.data?.items.map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}</TextField>
                <TextField select fullWidth label="Status" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>{['active', 'on_hold', 'completed', 'archived'].map((s) => <MenuItem key={s} value={s}>{titleCase(s)}</MenuItem>)}</TextField>
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField fullWidth type="date" label="Start" InputLabelProps={{ shrink: true }} value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} />
                <TextField fullWidth type="date" label="End" InputLabelProps={{ shrink: true }} value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} />
              </Stack>
              <Autocomplete multiple options={users} value={members} onChange={(_, v) => setMembers(v)} getOptionLabel={(u) => u.name} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(p) => <TextField {...p} label="Members" />} />
              <ErrorAlert error={save.error} />
            </Stack>
          </DialogContent>
          <DialogActions><Button onClick={() => setDlg(null)}>Cancel</Button><Button variant="contained" disabled={!f.name || save.isPending} onClick={() => save.mutate()}>Save</Button></DialogActions>
        </Dialog>
      )}
    </>
  )
}

function Clients() {
  const qc = useQueryClient()
  const clients = useQuery({ queryKey: ['clients'], queryFn: () => api.get<Page<Client>>('/clients', { limit: 200 }) })
  const [sel, setSel] = useState<Client | null>(null)
  const [f, setF] = useState({ name: '', contact_name: '', contact_email: '' })
  const [creating, setCreating] = useState(false)
  const contacts = useQuery({ queryKey: ['contacts', sel?.id], queryFn: () => api.get<{ items: Contact[] }>(`/clients/${sel!.id}/contacts`), enabled: !!sel })
  const [c, setC] = useState({ name: '', email: '' })
  const create = useMutation({ mutationFn: () => api.post('/clients', { name: f.name, contact_name: f.contact_name || null, contact_email: f.contact_email || null }), onSuccess: () => { setCreating(false); setF({ name: '', contact_name: '', contact_email: '' }); qc.invalidateQueries({ queryKey: ['clients'] }) } })
  const addContact = useMutation({ mutationFn: () => api.post(`/clients/${sel!.id}/contacts`, c), onSuccess: () => { setC({ name: '', email: '' }); qc.invalidateQueries({ queryKey: ['contacts', sel?.id] }) } })
  const delContact = useMutation({ mutationFn: (id: string) => api.del(`/clients/${sel!.id}/contacts/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ['contacts', sel?.id] }) })
  return (
    <Stack direction={{ xs: 'column', md: 'row' }} spacing={2.5} alignItems="flex-start">
      <Paper sx={{ flex: 1, width: '100%', overflow: 'hidden' }}>
        <Table>
          <TableHead><TableRow><TableCell>Client</TableCell><TableCell>Primary contact</TableCell></TableRow></TableHead>
          <TableBody>
            {clients.data?.items.map((cl) => (
              <TableRow key={cl.id} hover selected={sel?.id === cl.id} sx={{ cursor: 'pointer' }} onClick={() => setSel(cl)}>
                <TableCell sx={{ fontWeight: 600 }}>{cl.name}</TableCell>
                <TableCell>{cl.contact_name ? `${cl.contact_name} · ${cl.contact_email}` : '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Stack direction="row" spacing={1} sx={{ p: 2 }}>
          {creating ? (
            <>
              <TextField size="small" label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
              <TextField size="small" label="Contact name" value={f.contact_name} onChange={(e) => setF({ ...f, contact_name: e.target.value })} />
              <TextField size="small" label="Contact email" value={f.contact_email} onChange={(e) => setF({ ...f, contact_email: e.target.value })} />
              <Button variant="contained" disabled={!f.name} onClick={() => create.mutate()}>Add</Button>
            </>
          ) : <Button startIcon={<AddIcon />} onClick={() => setCreating(true)}>New client</Button>}
        </Stack>
        <ErrorAlert error={create.error} />
      </Paper>
      <Paper sx={{ p: 2.5, width: { xs: '100%', md: 380 } }}>
        {sel ? (
          <>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{sel.name} · report recipients</Typography>
            <Typography variant="caption" color="text.secondary">Approved client reports can only be shared with these contacts.</Typography>
            {contacts.data?.items.map((ct) => <Stack key={ct.id} direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 0.75, borderBottom: '1px solid', borderColor: 'divider' }}><Typography variant="body2">{ct.name} · {ct.email}</Typography><Button size="small" color="error" onClick={() => delContact.mutate(ct.id)}>Remove</Button></Stack>)}
            <Stack spacing={1} sx={{ mt: 2 }}>
              <TextField size="small" label="Name" value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} />
              <TextField size="small" label="Email" value={c.email} onChange={(e) => setC({ ...c, email: e.target.value })} />
              <Button variant="outlined" disabled={!c.name || !c.email} onClick={() => addContact.mutate()}>Add contact</Button>
              <ErrorAlert error={addContact.error} />
            </Stack>
          </>
        ) : <Empty>Select a client to manage its contacts.</Empty>}
      </Paper>
    </Stack>
  )
}

function Teams() {
  const qc = useQueryClient()
  const teams = useQuery({ queryKey: ['teams'], queryFn: () => api.get<{ items: Team[] }>('/teams') })
  const users = useUsers()
  const [name, setName] = useState('')
  const create = useMutation({ mutationFn: () => api.post('/teams', { name }), onSuccess: () => { setName(''); qc.invalidateQueries({ queryKey: ['teams'] }) } })
  const update = useMutation({
    mutationFn: async (v: { team: Team; lead?: UserLite | null; members?: UserLite[] }) => {
      if (v.lead !== undefined) await api.patch(`/teams/${v.team.id}`, { lead_user_id: v.lead?.id ?? null })
      if (v.members) await api.put(`/teams/${v.team.id}/members`, { user_ids: v.members.map((m) => m.id) })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['teams'] }),
  })
  return (
    <Stack spacing={2}>
      <ErrorAlert error={create.error ?? update.error} />
      {teams.data?.items.map((t) => (
        <Paper key={t.id} sx={{ p: 2.5 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>{t.name}</Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
            <Autocomplete sx={{ minWidth: 260 }} options={users} value={users.find((u) => u.id === t.lead_user_id) ?? null} onChange={(_, v) => update.mutate({ team: t, lead: v })} getOptionLabel={(u) => u.name} renderInput={(p) => <TextField {...p} size="small" label="Team lead" />} />
            <Autocomplete multiple fullWidth options={users} value={users.filter((u) => t.member_ids.includes(u.id))} onChange={(_, v) => update.mutate({ team: t, members: v })} getOptionLabel={(u) => u.name} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(p) => <TextField {...p} size="small" label="Members" />} />
          </Stack>
        </Paper>
      ))}
      <Stack direction="row" spacing={1}>
        <TextField size="small" label="New team name" value={name} onChange={(e) => setName(e.target.value)} />
        <Button variant="contained" disabled={!name} onClick={() => create.mutate()}>Create team</Button>
      </Stack>
    </Stack>
  )
}
