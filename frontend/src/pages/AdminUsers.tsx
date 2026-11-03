import AddIcon from '@mui/icons-material/Add'
import { Alert, Autocomplete, Avatar, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Grid, List, ListItemButton, ListItemText, Paper, Stack, Switch, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { ConfirmDialog, Empty, ErrorAlert, PageHeader } from '../components/ui'
import { initials, titleCase } from '../format'
import type { Page, Role, UserLite } from '../types'

export default function AdminUsers() {
  const { can } = useAuth()
  const [tab, setTab] = useState(0)
  return (
    <>
      <PageHeader title="Users & roles" subtitle="A role is a named set of permissions — create as many as you need, no code changes" />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Users" />
        <Tab label="Roles & permissions" />
      </Tabs>
      {tab === 0 ? <Users canManage={can('user.manage')} /> : <Roles canManage={can('role.manage')} />}
    </>
  )
}

function Users({ canManage }: { canManage: boolean }) {
  const qc = useQueryClient()
  const users = useQuery({ queryKey: ['users', 'admin'], queryFn: () => api.get<Page<UserLite>>('/users', { limit: 200 }) })
  const roles = useQuery({ queryKey: ['roles'], queryFn: () => api.get<{ items: Role[] }>('/roles') })
  const [dlg, setDlg] = useState<'create' | 'invite' | UserLite | null>(null)
  const toggle = useMutation({ mutationFn: (u: UserLite) => api.patch(`/users/${u.id}`, { is_active: !u.is_active }), onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }) })
  return (
    <>
      {canManage && <Stack direction="row" spacing={1} sx={{ mb: 2 }}><Button variant="contained" startIcon={<AddIcon />} onClick={() => setDlg('create')}>Add user</Button><Button variant="outlined" onClick={() => setDlg('invite')}>Invite by email</Button></Stack>}
      <ErrorAlert error={users.error ?? toggle.error} />
      <Paper sx={{ overflow: 'hidden' }}>
        <Table>
          <TableHead><TableRow><TableCell>Name</TableCell><TableCell>Email</TableCell><TableCell>Roles</TableCell><TableCell>Status</TableCell><TableCell align="right">Active</TableCell></TableRow></TableHead>
          <TableBody>
            {users.data?.items.map((u) => (
              <TableRow key={u.id} hover sx={{ cursor: canManage ? 'pointer' : 'default', opacity: u.is_active ? 1 : 0.55 }} onClick={() => canManage && setDlg(u)}>
                <TableCell><Stack direction="row" spacing={1.5} alignItems="center"><Avatar sx={{ width: 32, height: 32, fontSize: 13, bgcolor: 'primary.light' }}>{initials(u.name)}</Avatar><Typography variant="body2" sx={{ fontWeight: 600 }}>{u.name}</Typography></Stack></TableCell>
                <TableCell>{u.email}</TableCell>
                <TableCell><Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>{u.roles.map((r) => <Chip key={r.id} size="small" label={r.name} />)}</Stack></TableCell>
                <TableCell>{u.email_verified === false ? <Chip size="small" color="warning" label="Unverified" /> : <Chip size="small" color="success" variant="outlined" label="Verified" />}</TableCell>
                <TableCell align="right" onClick={(e) => e.stopPropagation()}><Switch checked={u.is_active} disabled={!canManage} onChange={() => toggle.mutate(u)} inputProps={{ 'aria-label': `Toggle ${u.name}` }} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
      {dlg && <UserDialog mode={dlg} roles={roles.data?.items ?? []} onClose={() => setDlg(null)} />}
    </>
  )
}

function UserDialog({ mode, roles, onClose }: { mode: 'create' | 'invite' | UserLite; roles: Role[]; onClose: () => void }) {
  const qc = useQueryClient()
  const existing = typeof mode === 'object' ? mode : null
  const [f, setF] = useState({ name: existing?.name ?? '', email: existing?.email ?? '', password: '' })
  const [picked, setPicked] = useState<Role[]>(existing ? roles.filter((r) => existing.roles.some((x) => x.id === r.id)) : [])
  useEffect(() => {
    if (existing) setPicked(roles.filter((r) => existing.roles.some((x) => x.id === r.id)))
  }, [roles.length]) // eslint-disable-line react-hooks/exhaustive-deps
  const [link, setLink] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: async () => {
      if (existing) return api.patch(`/users/${existing.id}`, { name: f.name, role_ids: picked.map((r) => r.id) })
      if (mode === 'invite') return api.post<{ dev_invite_link?: string }>('/users/invite', { email: f.email, role_id: picked[0]?.id })
      return api.post('/users', { ...f, role_ids: picked.map((r) => r.id) })
    },
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ['users'] })
      qc.invalidateQueries({ queryKey: ['roles'] })
      if (mode === 'invite' && r?.dev_invite_link) setLink(r.dev_invite_link)
      else onClose()
    },
  })
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{existing ? `Edit ${existing.name}` : mode === 'invite' ? 'Invite by email' : 'Add user'}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ pt: 0.5 }}>
          {mode !== 'invite' && <TextField label="Full name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />}
          <TextField label="Email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} disabled={!!existing} required />
          {mode === 'create' && <TextField label="Initial password" type="password" helperText="Share it securely; at least 8 characters" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />}
          <Autocomplete multiple={mode !== 'invite'} options={roles} value={mode === 'invite' ? picked[0] ?? null : (picked as any)} onChange={(_, v: any) => setPicked(Array.isArray(v) ? v : v ? [v] : [])} getOptionLabel={(r) => r.name} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(p) => <TextField {...p} label={mode === 'invite' ? 'Role' : 'Roles'} helperText="Permissions are the union of all selected roles" />} />
          <ErrorAlert error={save.error} />
          {link && <Alert severity="success">Invite sent. Development link: <a href={link}>{link}</a></Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{link ? 'Done' : 'Cancel'}</Button>
        {!link && <Button variant="contained" disabled={save.isPending || !f.email || (mode === 'create' && (!f.name || f.password.length < 8))} onClick={() => save.mutate()}>{existing ? 'Save' : mode === 'invite' ? 'Send invite' : 'Create user'}</Button>}
      </DialogActions>
    </Dialog>
  )
}

// ------------------------------------------------------------------------------------------ roles
function groupOf(key: string) {
  const [area] = key.split('.')
  return { task: 'Tasks & time', status: 'Daily status', dashboard: 'Dashboard', report: key.includes('.view.') ? 'Reports' : 'Client reports', user: 'Administration', role: 'Administration', project: 'Administration', settings: 'Administration' }[area] ?? titleCase(area)
}

function Roles({ canManage }: { canManage: boolean }) {
  const qc = useQueryClient()
  const roles = useQuery({ queryKey: ['roles'], queryFn: () => api.get<{ items: Role[] }>('/roles') })
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
        <Paper>
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
