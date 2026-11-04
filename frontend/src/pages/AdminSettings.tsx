import { Alert, Button, Chip, FormControlLabel, MenuItem, Paper, Stack, Switch, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { Empty, ErrorAlert, PageHeader } from '../components/ui'
import { fmtDateTime } from '../format'
import type { Page, Settings, TaskField } from '../types'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const ZONES = ['UTC', 'Asia/Kolkata', 'Asia/Singapore', 'Asia/Dubai', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Australia/Sydney']

export default function AdminSettings() {
  const [tab, setTab] = useState(0)
  return (
    <>
      <PageHeader title="Settings" subtitle="Everything here is configuration stored as data — no deployment needed" />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Company" /><Tab label="Task fields" /><Tab label="Notification log" />
      </Tabs>
      {tab === 0 && <Company />}
      {tab === 1 && <Fields />}
      {tab === 2 && <Log />}
    </>
  )
}

function Company() {
  const qc = useQueryClient()
  const s = useQuery({ queryKey: ['settings'], queryFn: () => api.get<Settings>('/settings') })
  const [f, setF] = useState({ name: '', timezone: 'UTC', report_email_enabled: true, report_email_day: 0, slack: '' })
  useEffect(() => {
    if (s.data) setF({ name: s.data.name, timezone: s.data.timezone, report_email_enabled: s.data.report_email_enabled, report_email_day: s.data.report_email_day ?? 0, slack: '' })
  }, [s.data])
  const save = useMutation({
    mutationFn: (extra?: object) => api.patch('/settings', { name: f.name, timezone: f.timezone, report_email_enabled: f.report_email_enabled, report_email_day: f.report_email_enabled ? f.report_email_day : undefined, slack_webhook_url: f.slack || undefined, ...extra }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings'] }); qc.invalidateQueries({ queryKey: ['me'] }) },
  })
  return (
    <Paper sx={{ p: 3, maxWidth: 720 }}>
      <Stack spacing={2.5}>
        <TextField label="Company name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <Stack direction="row" spacing={2}>
          <TextField label="Email domain" value={s.data?.email_domain ?? ''} disabled helperText="People who sign up with this domain join your company" fullWidth />
          <TextField select label="Timezone" value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} fullWidth helperText="Reminders and daily status cut-off use this">
            {[...new Set([f.timezone, ...ZONES])].map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
          </TextField>
        </Stack>
        <Stack direction="row" spacing={2} alignItems="center">
          <FormControlLabel control={<Switch checked={f.report_email_enabled} onChange={(e) => setF({ ...f, report_email_enabled: e.target.checked })} />} label="Email scheduled reports" />
          <TextField select size="small" label="Weekly report day" disabled={!f.report_email_enabled} value={f.report_email_day} onChange={(e) => setF({ ...f, report_email_day: Number(e.target.value) })} sx={{ minWidth: 170 }}>
            {DAYS.map((d, i) => <MenuItem key={d} value={i}>{d}, 07:00</MenuItem>)}
          </TextField>
          <Typography variant="caption" color="text.secondary">Monthly reports go out on the 1st.</Typography>
        </Stack>
        <Stack spacing={1}>
          <TextField label="Slack incoming webhook URL" type="password" value={f.slack} onChange={(e) => setF({ ...f, slack: e.target.value })} placeholder={s.data?.slack_configured ? 'Configured — paste a new URL to replace' : 'https://hooks.slack.com/services/…'} helperText="Stored encrypted. Blocker alerts and reminders are also posted to this channel." />
          {s.data?.slack_configured && <Stack direction="row" spacing={1} alignItems="center"><Chip size="small" color="success" label="Slack connected" /><Typography variant="caption" color="text.secondary">{s.data.slack_webhook_hint}</Typography><Button size="small" color="error" onClick={() => save.mutate({ clear_slack: true, slack_webhook_url: undefined })}>Disconnect</Button></Stack>}
        </Stack>
        <ErrorAlert error={save.error} />
        {save.isSuccess && <Alert severity="success">Settings saved.</Alert>}
        <Button variant="contained" sx={{ alignSelf: 'flex-start' }} onClick={() => save.mutate(undefined)} disabled={save.isPending}>Save settings</Button>
      </Stack>
    </Paper>
  )
}

function Fields() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['task-fields'], queryFn: () => api.get<{ items: TaskField[] }>('/task-fields') })
  const [f, setF] = useState({ key: '', label: '', type: 'text', options: '', required: false })
  const refresh = () => qc.invalidateQueries({ queryKey: ['task-fields'] })
  const add = useMutation({ mutationFn: () => api.post('/task-fields', { ...f, options: f.options.split(',').map((o) => o.trim()).filter(Boolean) }), onSuccess: () => { setF({ key: '', label: '', type: 'text', options: '', required: false }); refresh() } })
  const patch = useMutation({ mutationFn: (v: { id: string; body: object }) => api.patch(`/task-fields/${v.id}`, v.body), onSuccess: refresh })
  return (
    <Stack spacing={2.5}>
      <Paper sx={{ overflow: 'hidden' }}>
        <Table>
          <TableHead><TableRow><TableCell>Field</TableCell><TableCell>Type</TableCell><TableCell>Kind</TableCell><TableCell>Required</TableCell><TableCell align="right">Shown</TableCell></TableRow></TableHead>
          <TableBody>
            {q.data?.items.map((x) => (
              <TableRow key={x.id}>
                <TableCell><b>{x.label}</b> <Typography component="span" variant="caption" color="text.secondary">{x.key}</Typography></TableCell>
                <TableCell>{x.type}{x.type === 'select' ? ` (${x.options.length})` : ''}</TableCell>
                <TableCell>{x.is_builtin ? <Chip size="small" label="Built-in" /> : <Chip size="small" color="primary" variant="outlined" label="Custom" />}</TableCell>
                <TableCell>{x.is_builtin ? '—' : <Switch size="small" checked={x.required} onChange={(e) => patch.mutate({ id: x.id, body: { required: e.target.checked } })} />}</TableCell>
                <TableCell align="right"><Switch checked={x.is_active} onChange={(e) => patch.mutate({ id: x.id, body: { is_active: e.target.checked } })} inputProps={{ 'aria-label': `Show ${x.label}` }} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
      <ErrorAlert error={patch.error} />
      <Paper sx={{ p: 2.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>Add a custom field</Typography>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
          <TextField size="small" label="Label" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value, key: f.key || e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') })} />
          <TextField size="small" label="Key" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} helperText="lowercase, underscores" />
          <TextField select size="small" label="Type" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} sx={{ minWidth: 120 }}>{['text', 'number', 'date', 'select'].map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}</TextField>
          {f.type === 'select' && <TextField size="small" label="Options" placeholder="comma, separated" value={f.options} onChange={(e) => setF({ ...f, options: e.target.value })} />}
          <FormControlLabel control={<Switch checked={f.required} onChange={(e) => setF({ ...f, required: e.target.checked })} />} label="Required" />
          <Button variant="contained" disabled={!f.label || !f.key || add.isPending} onClick={() => add.mutate()}>Add</Button>
        </Stack>
        <ErrorAlert error={add.error} />
      </Paper>
    </Stack>
  )
}

function Log() {
  const q = useQuery({ queryKey: ['notifications'], queryFn: () => api.get<Page<{ id: string; kind: string; channel: string; status: string; error: string | null; sent_at: string }>>('/notifications', { limit: 50 }) })
  return (
    <Paper sx={{ overflow: 'hidden' }}>
      <Table size="small">
        <TableHead><TableRow><TableCell>When</TableCell><TableCell>Kind</TableCell><TableCell>Channel</TableCell><TableCell>Status</TableCell><TableCell>Error</TableCell></TableRow></TableHead>
        <TableBody>
          {q.data?.items.map((n) => (
            <TableRow key={n.id}>
              <TableCell>{fmtDateTime(n.sent_at)}</TableCell><TableCell>{n.kind}</TableCell><TableCell>{n.channel}</TableCell>
              <TableCell><Chip size="small" label={n.status} color={n.status === 'failed' ? 'error' : 'success'} variant="outlined" /></TableCell>
              <TableCell sx={{ color: 'error.main' }}>{n.error}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {q.data?.items.length === 0 && <Empty>No notifications yet. Failed sends stay here for an admin to see.</Empty>}
    </Paper>
  )
}
