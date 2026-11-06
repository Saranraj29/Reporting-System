import AddIcon from '@mui/icons-material/Add'
import { Alert, Autocomplete, Avatar, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { ErrorAlert, PageHeader, SearchBox } from '../components/ui'
import { initials } from '../format'
import { useSearch } from '../hooks'
import type { Page, Role, UserLite } from '../types'

export default function AdminUsers() {
  const { can } = useAuth()
  return (
    <>
      <PageHeader title="Users" subtitle="People in your company, their roles and whether they can sign in. New people join as Team Member." />
      <Users canManage={can('user.manage')} />
    </>
  )
}

function Users({ canManage }: { canManage: boolean }) {
  const qc = useQueryClient()
  const search = useSearch()
  const users = useQuery({ queryKey: ['users', 'admin', search.term], queryFn: () => api.get<Page<UserLite>>('/users', { limit: 200, q: search.term }), placeholderData: keepPreviousData })
  const roles = useQuery({ queryKey: ['roles'], queryFn: () => api.get<{ items: Role[] }>('/roles') })
  const [dlg, setDlg] = useState<'create' | 'invite' | UserLite | null>(null)
  const toggle = useMutation({ mutationFn: (u: UserLite) => api.patch(`/users/${u.id}`, { is_active: !u.is_active }), onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }) })
  return (
    <>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2 }} justifyContent="space-between">
        <SearchBox value={search.input} onChange={search.setInput} placeholder="Search users by name or email" />
        {canManage && <Stack direction="row" spacing={1}><Button variant="contained" startIcon={<AddIcon />} onClick={() => setDlg('create')}>Add user</Button><Button variant="outlined" onClick={() => setDlg('invite')}>Invite by email</Button></Stack>}
      </Stack>
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
