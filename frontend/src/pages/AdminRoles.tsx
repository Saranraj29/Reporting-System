import AddIcon from '@mui/icons-material/Add'
import { Box, Button, Checkbox, FormControlLabel, Grid, List, ListItemButton, ListItemText, Paper, Stack, TextField, Typography } from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { ConfirmDialog, Empty, ErrorAlert, PageHeader, SearchBox } from '../components/ui'
import { titleCase } from '../format'
import { useSearch } from '../hooks'
import type { Role } from '../types'

export default function AdminRoles() {
  const { can } = useAuth()
  return (
    <>
      <PageHeader title="Roles & permissions" subtitle="A role is a named set of permissions — create as many as you need, no code changes" />
      <Roles canManage={can('role.manage')} />
    </>
  )
}

function groupOf(key: string) {
  const [area] = key.split('.')
  return { task: 'Tasks & time', status: 'Daily status', dashboard: 'Dashboard', report: key.includes('.view.') ? 'Reports' : 'Client reports', user: 'Administration', role: 'Administration', project: 'Administration', settings: 'Administration' }[area] ?? titleCase(area)
}

function Roles({ canManage }: { canManage: boolean }) {
  const qc = useQueryClient()
  const search = useSearch()
  const roles = useQuery({ queryKey: ['roles', search.term], queryFn: () => api.get<{ items: Role[] }>('/roles', { q: search.term }), placeholderData: keepPreviousData })
  const perms = useQuery({ queryKey: ['permissions'], queryFn: () => api.get<{ items: { key: string; description: string }[] }>('/permissions') })
  const [sel, setSel] = useState<string | 'new' | null>(null)
  const [draft, setDraft] = useState<{ name: string; description: string; permissions: string[] }>({ name: '', description: '', permissions: [] })
  const [del, setDel] = useState<Role | null>(null)
  const role = roles.data?.items.find((r) => r.id === sel)
  useEffect(() => {
    if (!sel && roles.data?.items.length) setSel(roles.data.items[0].id)
  }, [roles.data, sel])
  useEffect(() => {
    if (role) setDraft({ name: role.name, description: role.description, permissions: role.permissions })
    if (sel === 'new') setDraft({ name: '', description: '', permissions: [] })
  }, [sel, role?.id, role?.permissions.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    mutationFn: () => (sel === 'new' ? api.post<Role>('/roles', draft) : api.patch<Role>(`/roles/${sel}`, draft)),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['roles'] }); setSel(r.id) },
  })
  const remove = useMutation({ mutationFn: (id: string) => api.del(`/roles/${id}`), onSuccess: () => { setDel(null); setSel(null); qc.invalidateQueries({ queryKey: ['roles'] }) } })
  const groups: Record<string, { key: string; description: string }[]> = {}
  perms.data?.items.forEach((p) => (groups[groupOf(p.key)] ??= []).push(p))
  const toggle = (key: string) => setDraft((d) => ({ ...d, permissions: d.permissions.includes(key) ? d.permissions.filter((k) => k !== key) : [...d.permissions, key] }))

  return (
    <Grid container spacing={2.5}>
      <Grid item xs={12} md={4}>
        <SearchBox value={search.input} onChange={search.setInput} placeholder="Search roles" width="100%" />
        <Paper sx={{ mt: 1.5 }}>
          <List disablePadding>
            {roles.data?.items.map((r) => (
              <ListItemButton key={r.id} selected={sel === r.id} onClick={() => setSel(r.id)} divider>
                <ListItemText primary={r.name} secondary={`${r.user_count} user${r.user_count === 1 ? '' : 's'} · ${r.permissions.length} permissions`} primaryTypographyProps={{ fontWeight: 600 }} />
              </ListItemButton>
            ))}
            {canManage && <ListItemButton selected={sel === 'new'} onClick={() => setSel('new')}><AddIcon fontSize="small" sx={{ mr: 1 }} /><ListItemText primary="New role" /></ListItemButton>}
          </List>
        </Paper>
      </Grid>
      <Grid item xs={12} md={8}>
        {sel ? (
          <Paper sx={{ p: 3 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
              <TextField label="Role name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} disabled={!canManage} fullWidth />
              <TextField label="Description" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} disabled={!canManage} fullWidth />
            </Stack>
            {Object.entries(groups).map(([g, items]) => (
              <Box key={g} sx={{ mb: 2 }}>
                <Typography variant="overline" color="text.secondary">{g}</Typography>
                <Grid container>
                  {items.map((p) => (
                    <Grid item xs={12} sm={6} key={p.key}>
                      <FormControlLabel disabled={!canManage} control={<Checkbox size="small" checked={draft.permissions.includes(p.key)} onChange={() => toggle(p.key)} />} label={<Box><Typography variant="body2" sx={{ fontWeight: 600 }}>{p.key}</Typography><Typography variant="caption" color="text.secondary">{p.description}</Typography></Box>} sx={{ alignItems: 'flex-start', mb: 0.5 }} />
                    </Grid>
                  ))}
                </Grid>
              </Box>
            ))}
            <ErrorAlert error={save.error ?? remove.error} />
            {canManage && (
              <Stack direction="row" spacing={1} justifyContent="space-between">
                <Button color="error" disabled={sel === 'new' || !role} onClick={() => role && setDel(role)}>Delete role</Button>
                <Button variant="contained" disabled={!draft.name || save.isPending} onClick={() => save.mutate()}>{sel === 'new' ? 'Create role' : 'Save changes'}</Button>
              </Stack>
            )}
          </Paper>
        ) : <Empty>Select a role</Empty>}
      </Grid>
      <ConfirmDialog open={!!del} danger title="Delete role?" confirmLabel="Delete" body={`“${del?.name}” will be removed. Roles that still have users cannot be deleted.`} onClose={() => setDel(null)} onConfirm={() => del && remove.mutate(del.id)} />
    </Grid>
  )
}
