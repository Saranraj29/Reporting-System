import { Alert, Button, Chip, FormControlLabel, MenuItem, Paper, Stack, Switch, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import TimeOffCard from '../components/TimeOffCard'
import AiUsagePage from './AiUsage'
import { Empty, ErrorAlert, PageHeader } from '../components/ui'
import { fmtDateTime } from '../format'
import type { Page, ReminderConfig, RemindersSettings, Settings, TaskField } from '../types'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const ZONES = ['UTC', 'Asia/Kolkata', 'Asia/Singapore', 'Asia/Dubai', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Australia/Sydney']

export default function AdminSettings() {
  const [tab, setTab] = useState(0)
  return (
    <>
      <PageHeader title="Settings" subtitle="Everything here is configuration stored as data — no deployment needed" />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Company" /><Tab label="Reminders" /><Tab label="AI usage" /><Tab label="Task fields" /><Tab label="Notification log" />
      </Tabs>
      {tab === 0 && <><Company /><EmailCard /></>}
      {tab === 1 && <RemindersTab />}
      {tab === 2 && <AiUsagePage />}
      {tab === 3 && <Fields />}
      {tab === 4 && <Log />}
    </>
  )
}

function EmailCard() {
  const s = useQuery({ queryKey: ['settings'], queryFn: () => api.get<Settings>('/settings') })
  const test = useMutation({ mutationFn: () => api.post<{ ok: boolean; delivered: boolean; message: string }>('/settings/test-email') })
  const e = s.data?.email
  if (!e) return null
  const real = e.backend === 'smtp'
  return (
    <Paper sx={{ p: 3, maxWidth: 720, mt: 2.5 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Email delivery</Typography>
        <Chip size="small" color={real ? 'success' : 'warning'} variant="outlined" label={real ? 'Real email' : 'Development mode'} />
      </Stack>
      <Typography variant="body2" color="text.secondary">
        {real ? `Sent through ${e.host}:${e.port} (${e.security}) as ${e.from}.` : 'Emails are only written to the server log, nobody receives them. Set the mail server in the environment (EMAIL_BACKEND=smtp) to send real email.'}
      </Typography>
      {e.problems.map((p) => <Alert key={p} severity="warning" sx={{ mt: 1 }}>{p}</Alert>)}
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mt: 2 }}>
        <Button variant="outlined" onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? 'Sending…' : 'Send a test email to me'}</Button>
        <Typography variant="caption" color="text.secondary">Goes to your own address, right now.</Typography>
      </Stack>
      <ErrorAlert error={test.error} />
      {test.data && <Alert severity={test.data.delivered ? 'success' : 'info'} sx={{ mt: 1 }}>{test.data.message}</Alert>}
    </Paper>
  )
}

function Company() {
  const qc = useQueryClient()
  const s = useQuery({ queryKey: ['settings'], queryFn: () => api.get<Settings>('/settings') })
  const [f, setF] = useState({ name: '', timezone: 'UTC', report_email_enabled: true, report_email_day: 0, slack: '', ai_enabled: true })
  useEffect(() => {
    if (s.data) setF({ name: s.data.name, timezone: s.data.timezone, report_email_enabled: s.data.report_email_enabled, report_email_day: s.data.report_email_day ?? 0, slack: '', ai_enabled: s.data.ai_enabled })
  }, [s.data])
  const save = useMutation({
    mutationFn: (extra?: object) => api.patch('/settings', { name: f.name, timezone: f.timezone, report_email_enabled: f.report_email_enabled, report_email_day: f.report_email_enabled ? f.report_email_day : undefined, slack_webhook_url: f.slack || undefined, ai_enabled: f.ai_enabled, ...extra }),
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
        <Stack>
          <FormControlLabel control={<Switch checked={f.ai_enabled} onChange={(e) => setF({ ...f, ai_enabled: e.target.checked })} />} label="AI-written text" />
          <Typography variant="caption" color="text.secondary">When off, AI reports use the built-in layout and wording only. It takes effect within a minute; everything else keeps working.</Typography>
        </Stack>
        <ErrorAlert error={save.error} />
        {save.isSuccess && <Alert severity="success">Settings saved.</Alert>}
        <Button variant="contained" sx={{ alignSelf: 'flex-start' }} onClick={() => save.mutate(undefined)} disabled={save.isPending}>Save settings</Button>
      </Stack>
    </Paper>
  )
}

/** Settings → Reminders: the master switch, company holidays, and one card per reminder (who gets it, when, and the wording). */
function RemindersTab() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['reminders'], queryFn: () => api.get<RemindersSettings>('/settings/reminders') })
  const master = useMutation({ mutationFn: (on: boolean) => api.patch('/settings', { reminders_enabled: on }), onSuccess: () => { qc.invalidateQueries({ queryKey: ['reminders'] }); qc.invalidateQueries({ queryKey: ['settings'] }) } })
  const d = q.data
  if (!d) return <ErrorAlert error={q.error} />
  return (
    <Stack spacing={2.5} sx={{ maxWidth: 720 }}>
      <Paper sx={{ p: 3 }}>
        <FormControlLabel control={<Switch checked={d.reminders_enabled} onChange={(e) => master.mutate(e.target.checked)} disabled={master.isPending} />} label="Send reminders" />
        <Typography variant="caption" color="text.secondary" component="div">
          Master switch for the morning, end-of-day, due and team-overdue reminders (blocker alerts and report emails are not affected). Times are in the company timezone.
          Nothing is sent on a company holiday or to someone on leave. For each reminder below, choose which roles receive it and what it says.
        </Typography>
        <ErrorAlert error={master.error} />
      </Paper>
      <TimeOffCard title="Company holidays" help="No reminders are sent to anyone on these days." path="/holidays" noun="holidays" />
      {d.kinds.map((k) => <ReminderCard key={k.kind + JSON.stringify([k.subject, k.body, k.time, k.roles_off])} k={k} roles={d.roles} paused={!d.reminders_enabled} />)}
    </Stack>
  )
}

function ReminderCard({ k, roles, paused }: { k: ReminderConfig; roles: { id: string; name: string }[]; paused: boolean }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ subject: k.subject, body: k.body, time: k.time ?? '', off: k.roles_off })
  const save = useMutation({
    mutationFn: () => api.put(`/settings/reminders/${k.kind}`, { subject: f.subject, body: f.body, roles_off: f.off, time: k.time ? f.time : undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['reminders'] }); qc.invalidateQueries({ queryKey: ['settings'] }) },
  })
  const toggle = (id: string, on: boolean) => setF({ ...f, off: on ? f.off.filter((x) => x !== id) : [...f.off, id] })
  const isDefault = f.subject === k.default_subject && f.body === k.default_body
  return (
    <Paper sx={{ p: 3, opacity: paused ? 0.6 : 1 }}>
      <Stack spacing={1.5}>
        <div>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{k.label}</Typography>
          <Typography variant="body2" color="text.secondary">{k.description}</Typography>
        </div>
        <div>
          <Typography variant="caption" color="text.secondary">Sent to these roles</Typography>
          <Stack direction="row" flexWrap="wrap" useFlexGap columnGap={2}>
            {roles.map((r) => <FormControlLabel key={r.id} label={r.name} control={<Switch size="small" checked={!f.off.includes(r.id)} onChange={(e) => toggle(r.id, e.target.checked)} />} />)}
          </Stack>
        </div>
        {k.time !== null && <TextField size="small" type="time" label="Send time" InputLabelProps={{ shrink: true }} value={f.time} onChange={(e) => setF({ ...f, time: e.target.value })} sx={{ maxWidth: 160 }} />}
        <TextField size="small" label="Subject" value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} inputProps={{ maxLength: 150 }} />
        <TextField size="small" label="Message" multiline minRows={3} value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} inputProps={{ maxLength: 2000 }} />
        <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography variant="caption" color="text.secondary">Insert:</Typography>
          {k.placeholders.map((p) => <Chip key={p} size="small" variant="outlined" label={`{${p}}`} onClick={() => setF({ ...f, body: `${f.body}{${p}}` })} />)}
        </Stack>
        <ErrorAlert error={save.error} />
        {save.isSuccess && <Alert severity="success" sx={{ py: 0 }}>Saved.</Alert>}
        <Stack direction="row" spacing={1.5}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Save</Button>
          <Button onClick={() => setF({ ...f, subject: k.default_subject, body: k.default_body })} disabled={isDefault}>Reset wording</Button>
        </Stack>
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
                <TableCell>{x.is_builtin ? <Typography variant="body2" color="text.secondary">{x.required ? 'Always' : 'Optional'}</Typography> : <Switch size="small" checked={x.required} onChange={(e) => patch.mutate({ id: x.id, body: { required: e.target.checked } })} />}</TableCell>
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
      <ErrorAlert error={q.error} />
      {q.isLoading && <Empty>Loading…</Empty>}
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
