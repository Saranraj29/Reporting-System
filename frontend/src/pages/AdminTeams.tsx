import AddIcon from '@mui/icons-material/Add'
import { Autocomplete, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack, TextField, Typography } from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { api } from '../api'
import { Empty, ErrorAlert, PageHeader, SearchBox } from '../components/ui'
import { useSearch, useUsers } from '../hooks'
import type { Team, UserLite } from '../types'

export default function AdminTeams() {
  const qc = useQueryClient()
  const users = useUsers()
  const search = useSearch()
  const teams = useQuery({ queryKey: ['teams', search.term], queryFn: () => api.get<{ items: Team[] }>('/teams', { q: search.term }), placeholderData: keepPreviousData })
  const [dlg, setDlg] = useState<Team | 'new' | null>(null)
  const [f, setF] = useState({ name: '', description: '' })
  const [lead, setLead] = useState<UserLite | null>(null)
  const [members, setMembers] = useState<UserLite[]>([])
  const open = (t: Team | 'new') => {
    setDlg(t)
    setF(t === 'new' ? { name: '', description: '' } : { name: t.name, description: t.description })
    setLead(t === 'new' ? null : users.find((u) => u.id === t.lead_user_id) ?? null)
    setMembers(t === 'new' ? [] : users.filter((u) => t.member_ids.includes(u.id)))
  }
  const save = useMutation({
    mutationFn: async () => {
      const body = { name: f.name, description: f.description, lead_user_id: lead?.id ?? null }
      const t = dlg === 'new' ? await api.post<Team>('/teams', body) : await api.patch<Team>(`/teams/${(dlg as Team).id}`, body)
      await api.put(`/teams/${t.id}/members`, { user_ids: members.map((m) => m.id) })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['teams'] }); setDlg(null) },
  })
  const name = (id: string | null) => users.find((u) => u.id === id)?.name
  return (
    <>
      <PageHeader title="Teams" subtitle="A team works like a department: tasks can be assigned to a team, and team leads see their team's work" />
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2 }} justifyContent="space-between">
        <SearchBox value={search.input} onChange={search.setInput} placeholder="Search teams" />
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => open('new')}>New team</Button>
      </Stack>
      <Stack spacing={1.5}>
        {teams.data?.items.map((t) => (
          <Paper key={t.id} sx={{ p: 2.5, cursor: 'pointer', '&:hover': { borderColor: 'primary.main' } }} variant="outlined" onClick={() => open(t)}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between">
              <div>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{t.name}</Typography>
                <Typography variant="body2" color="text.secondary">{t.description || 'No description yet'}</Typography>
                <Typography variant="caption" color="text.secondary">Lead: {name(t.lead_user_id) ?? '—'} · {t.member_ids.length} member{t.member_ids.length === 1 ? '' : 's'}</Typography>
              </div>
              <Stack direction="row" spacing={1} alignItems="center" onClick={(e) => e.stopPropagation()}>
                <Chip size="small" label={`${t.open_tasks} open`} color={t.open_tasks ? 'primary' : 'default'} variant="outlined" />
                <Chip size="small" label={`${t.total_tasks} total tasks`} variant="outlined" />
                <Button size="small" component={RouterLink} to={`/tasks?team=${t.id}`}>View tasks</Button>
              </Stack>
            </Stack>
          </Paper>
        ))}
        {teams.data?.items.length === 0 && <Empty>{search.term ? 'No team matches your search.' : 'No teams yet. Create the first one.'}</Empty>}
      </Stack>
      {dlg && (
        <Dialog open onClose={() => setDlg(null)} fullWidth maxWidth="sm">
          <DialogTitle>{dlg === 'new' ? 'New team' : `Edit ${dlg.name}`}</DialogTitle>
          <DialogContent dividers>
            <Stack spacing={2} sx={{ pt: 0.5 }}>
              <TextField label="Team name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required autoFocus />
              <TextField label="What does this team do?" multiline minRows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} inputProps={{ maxLength: 500 }} />
              <Autocomplete options={users} value={lead} onChange={(_, v) => setLead(v)} getOptionLabel={(u) => u.name} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(p) => <TextField {...p} label="Team lead" />} />
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
