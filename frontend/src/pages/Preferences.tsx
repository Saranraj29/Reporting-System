import { Alert, FormControlLabel, MenuItem, Paper, Stack, Switch, TextField, Typography } from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../auth'
import { ErrorAlert, PageHeader } from '../components/ui'
import type { Me } from '../types'

const START_PAGES = [['/', 'Dashboard (or your first available page)'], ['/tasks', 'Tasks'], ['/my-day', 'My day'], ['/check-ins', 'Check-ins'], ['/reports', 'Reports']]

export default function Preferences() {
  const { me, reload } = useAuth()
  const save = useMutation({ mutationFn: (patch: Partial<Me['prefs']>) => api.put('/me/preferences', patch), onSuccess: () => reload() })
  if (!me) return null
  const p = me.prefs
  return (
    <>
      <PageHeader title="Preferences" subtitle="How the app behaves for you. Changes apply immediately." />
      <Paper sx={{ p: 3, maxWidth: 640 }}>
        <Stack spacing={2.5}>
          <Stack>
            <FormControlLabel control={<Switch checked={p.email_reminders} onChange={(e) => save.mutate({ email_reminders: e.target.checked })} />} label="Email me reminders" />
            <Typography variant="caption" color="text.secondary">Morning-plan, end-of-day, due-date and team-overdue reminders. Account emails (verify email, password reset) are always sent.</Typography>
          </Stack>
          <Stack>
            <FormControlLabel control={<Switch checked={p.compact_tables} onChange={(e) => save.mutate({ compact_tables: e.target.checked })} />} label="Compact tables" />
            <Typography variant="caption" color="text.secondary">Tighter rows so more fit on screen.</Typography>
          </Stack>
          <TextField select label="Open this page after sign-in" value={p.start_page} onChange={(e) => save.mutate({ start_page: e.target.value })} sx={{ maxWidth: 360 }}>
            {START_PAGES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </TextField>
          <ErrorAlert error={save.error} />
          {save.isSuccess && <Alert severity="success" sx={{ py: 0 }}>Saved.</Alert>}
        </Stack>
      </Paper>
    </>
  )
}
