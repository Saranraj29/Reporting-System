import { Alert, FormControlLabel, MenuItem, Paper, Stack, Switch, TextField, Typography } from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { canOpen } from '../access'
import { useAuth } from '../auth'
import TimeOffCard from '../components/TimeOffCard'
import { ErrorAlert, PageHeader } from '../components/ui'
import type { Me } from '../types'

const START_PAGES = [['/', 'Dashboard (or your first available page)'], ['/tasks', 'Tasks'], ['/my-day', 'My day'], ['/check-ins', 'Check-ins'], ['/reports', 'Reports']]

export default function Preferences() {
  const { me, reload, can, hasAny } = useAuth()
  const [pending, setPending] = useState<Partial<Me['prefs']>>({})  // shown at once; the saved value replaces it when the server answers
  const save = useMutation({
    mutationFn: (patch: Partial<Me['prefs']>) => api.put('/me/preferences', patch),
    onSuccess: async () => { await reload(); setPending({}) },
    onError: () => setPending({}),
  })
  const change = (patch: Partial<Me['prefs']>) => { setPending((p) => ({ ...p, ...patch })); save.mutate(patch) }
  if (!me) return null
  const p = { ...me.prefs, ...pending }
  return (
    <>
      <PageHeader title="Preferences" subtitle="How the app behaves for you. Changes apply immediately." />
      <Paper sx={{ p: 3, maxWidth: 640 }}>
        <Stack spacing={2.5}>
          <Stack>
            <FormControlLabel control={<Switch checked={p.compact_tables} onChange={(e) => change({ compact_tables: e.target.checked })} />} label="Compact tables" />
            <Typography variant="caption" color="text.secondary">Tighter rows so more fit on screen.</Typography>
          </Stack>
          <TextField select label="Open this page after sign-in" value={p.start_page} onChange={(e) => change({ start_page: e.target.value })} sx={{ maxWidth: 360 }}>
            {START_PAGES.filter(([v]) => v === p.start_page || canOpen(v, { can, hasAny, me })).map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </TextField>
          <ErrorAlert error={save.error} />
          {save.isSuccess && <Alert severity="success" sx={{ py: 0 }}>Saved.</Alert>}
        </Stack>
      </Paper>
      <TimeOffCard title="My leave" help="Days you are away. You get no reminders on these days. Which reminders you receive is set by your admin (Settings → Reminders), per role." path="/leave" noun="leave" />
    </>
  )
}
