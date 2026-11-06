import { Alert, Avatar, Box, Button, Chip, Divider, Grid, Paper, Stack, TextField, Typography } from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { PasswordField } from '../components/PasswordField'
import { ErrorAlert, PageHeader } from '../components/ui'
import { initials } from '../format'

export default function Profile() {
  const { me, reload } = useAuth()
  const [f, setF] = useState({ name: '', phone: '', job_title: '', location: '', bio: '' })
  useEffect(() => {
    if (me) setF({ name: me.profile.name, phone: me.profile.phone, job_title: me.profile.job_title, location: me.profile.location, bio: me.profile.bio })
  }, [me?.profile]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({ mutationFn: () => api.patch('/me/profile', f), onSuccess: () => reload() })
  const [pw, setPw] = useState({ current: '', next: '', again: '' })
  const change = useMutation({
    mutationFn: () => api.post('/me/password', { current_password: pw.current, new_password: pw.next }),
    onSuccess: () => setPw({ current: '', next: '', again: '' }),
  })
  const mismatch = pw.again !== '' && pw.next !== pw.again
  if (!me) return null
  return (
    <>
      <PageHeader title="My profile" subtitle="Your details, visible to the people you work with" />
      <Grid container spacing={2.5}>
        <Grid item xs={12} md={7}>
          <Paper sx={{ p: 3 }}>
            <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2.5 }}>
              <Avatar sx={{ width: 56, height: 56, bgcolor: 'secondary.main', fontSize: 22 }}>{initials(f.name || me.name)}</Avatar>
              <Box>
                <Typography variant="h6" sx={{ fontWeight: 700 }}>{f.name || me.name}</Typography>
                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>{me.roles.map((r) => <Chip key={r.id} size="small" label={r.name} />)}</Stack>
              </Box>
            </Stack>
            <Stack spacing={2}>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                <TextField label="Full name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} fullWidth required />
                <TextField label="Email" value={me.email} fullWidth disabled helperText="Ask an admin to change your email" />
              </Stack>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                <TextField label="Job title" value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} fullWidth inputProps={{ maxLength: 120 }} />
                <TextField label="Phone" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} fullWidth inputProps={{ maxLength: 40 }} />
              </Stack>
              <TextField label="Location" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} inputProps={{ maxLength: 120 }} />
              <TextField label="About me" multiline minRows={3} value={f.bio} onChange={(e) => setF({ ...f, bio: e.target.value })} inputProps={{ maxLength: 1000 }} helperText={`${f.bio.length}/1000`} />
              <ErrorAlert error={save.error} />
              {save.isSuccess && <Alert severity="success">Profile saved.</Alert>}
              <Button variant="contained" sx={{ alignSelf: 'flex-start' }} disabled={!f.name.trim() || save.isPending} onClick={() => save.mutate()}>Save profile</Button>
            </Stack>
          </Paper>
        </Grid>
        <Grid item xs={12} md={5}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Change password</Typography>
            <Typography variant="caption" color="text.secondary">Other devices will be signed out.</Typography>
            <Divider sx={{ my: 1.5 }} />
            <Stack spacing={2} component="form" onSubmit={(e) => { e.preventDefault(); if (!mismatch && pw.next.length >= 8) change.mutate() }}>
              <PasswordField label="Current password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" required />
              <PasswordField label="New password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} helperText="At least 8 characters" autoComplete="new-password" required />
              <PasswordField label="Repeat new password" value={pw.again} onChange={(e) => setPw({ ...pw, again: e.target.value })} error={mismatch} helperText={mismatch ? 'Passwords do not match' : ' '} autoComplete="new-password" required />
              <ErrorAlert error={change.error} />
              {change.isSuccess && <Alert severity="success">Password changed.</Alert>}
              <Button type="submit" variant="outlined" disabled={change.isPending || !pw.current || pw.next.length < 8 || mismatch}>Change password</Button>
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    </>
  )
}
