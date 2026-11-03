import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import DeleteIcon from '@mui/icons-material/DeleteOutline'
import DownloadIcon from '@mui/icons-material/Download'
import EditIcon from '@mui/icons-material/EditOutlined'
import SendIcon from '@mui/icons-material/SendOutlined'
import {
  Alert, Autocomplete, Box, Button, Checkbox, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Grid, IconButton,
  MenuItem, Paper, Stack, Step, StepLabel, Stepper, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { ConfirmDialog, Empty, ErrorAlert, PageHeader, ReportFrame, RunStatusChip } from '../components/ui'
import { fmtDate, fmtDateTime, titleCase } from '../format'
import type { Client, Contact, Page, RunDetail, RunSummary, Share, Template } from '../types'

const DEFAULT_SECTIONS = ['Summary', 'Work completed', 'Hours by area', 'Risks and blockers', 'Next week']

export default function ClientReports() {
  const { can } = useAuth()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [tab, setTab] = useState(0)
  const [edit, setEdit] = useState<Template | 'new' | null>(null)
  const [del, setDel] = useState<Template | null>(null)
  const templates = useQuery({ queryKey: ['templates'], queryFn: () => api.get<{ items: Template[] }>('/report-templates') })
  const runs = useQuery({ queryKey: ['report-runs', 'client'], queryFn: () => api.get<Page<RunSummary>>('/report-runs', { kind: 'client', limit: 50 }), refetchInterval: 6000 })
  const generate = useMutation({ mutationFn: (id: string) => api.post<{ id: string }>(`/report-templates/${id}/generate`), onSuccess: (r) => nav(`/client-reports/runs/${r.id}`) })
  const remove = useMutation({ mutationFn: (id: string) => api.del(`/report-templates/${id}`), onSuccess: () => { setDel(null); qc.invalidateQueries({ queryKey: ['templates'] }) } })

  return (
    <>
      <PageHeader title="Client reports" subtitle="AI drafts the narrative from your figures; a person approves before anything leaves the company"
        actions={can('report.template.manage') && <Button variant="contained" onClick={() => setEdit('new')}>New template</Button>} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label={`Templates${templates.data ? ` (${templates.data.items.length})` : ''}`} />
        <Tab label={`Reports${runs.data ? ` (${runs.data.total})` : ''}`} />
      </Tabs>
      <ErrorAlert error={templates.error ?? generate.error} />
      {tab === 0 && (
        <Grid container spacing={2.5}>
          {templates.data?.items.map((t) => (
            <Grid item xs={12} md={6} xl={4} key={t.id}>
              <Paper sx={{ p: 2.5, height: '100%', display: 'flex', flexDirection: 'column' }}>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                  <Box>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{t.name}</Typography>
                    <Typography variant="body2" color="text.secondary">{t.client_name ?? 'Internal'} · {titleCase(t.base_report)} · {titleCase(t.format)}</Typography>
                  </Box>
                  <Chip size="small" color={t.audience === 'client' ? 'primary' : 'default'} label={t.audience} />
                </Stack>
                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ my: 1.5 }}>
                  {t.sections.map((s) => <Chip key={s} size="small" variant="outlined" label={s} />)}
                </Stack>
                <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>
                  {t.tone_instructions || 'No tone instructions'} · Schedule: {t.schedule === 'none' ? 'manual' : t.schedule}
                </Typography>
                <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                  {can('report.ai.draft') && <Button variant="contained" size="small" startIcon={<AutoAwesomeIcon />} disabled={generate.isPending} onClick={() => generate.mutate(t.id)}>Generate</Button>}
                  {can('report.template.manage') && (
                    <>
                      <Tooltip title="Edit"><IconButton size="small" onClick={() => setEdit(t)} aria-label="Edit template"><EditIcon fontSize="small" /></IconButton></Tooltip>
                      <Tooltip title="Delete"><IconButton size="small" onClick={() => setDel(t)} aria-label="Delete template"><DeleteIcon fontSize="small" /></IconButton></Tooltip>
                    </>
                  )}
                </Stack>
              </Paper>
            </Grid>
          ))}
          {templates.data?.items.length === 0 && <Grid item xs={12}><Empty>No templates yet. Create one per client to get started.</Empty></Grid>}
        </Grid>
      )}
      {tab === 1 && (
        <Paper sx={{ overflow: 'hidden' }}>
          <Table>
            <TableHead><TableRow><TableCell>Report</TableCell><TableCell>Period</TableCell><TableCell>Status</TableCell><TableCell>Drafted by</TableCell><TableCell>Created</TableCell><TableCell /></TableRow></TableHead>
            <TableBody>
              {runs.data?.items.map((r) => (
                <TableRow key={r.id} hover>
                  <TableCell sx={{ fontWeight: 600 }}>{r.title}</TableCell>
                  <TableCell>{fmtDate(r.period_start)} – {fmtDate(r.period_end)}</TableCell>
                  <TableCell><RunStatusChip status={r.status} /></TableCell>
                  <TableCell>{r.ai_provider === 'anthropic' ? 'AI (Claude)' : r.ai_provider === 'figures_only' ? 'Figures only' : '—'}</TableCell>
                  <TableCell>{fmtDateTime(r.created_at)}</TableCell>
                  <TableCell align="right"><Button size="small" component={RouterLink} to={`/client-reports/runs/${r.id}`}>{r.status === 'drafted' ? 'Review' : 'Open'}</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {runs.data?.items.length === 0 && <Empty>No reports generated yet.</Empty>}
        </Paper>
      )}
      {edit && <TemplateDialog template={edit === 'new' ? null : edit} onClose={() => setEdit(null)} />}
      <ConfirmDialog open={!!del} danger title="Delete template?" confirmLabel="Delete" body={`“${del?.name}” will be removed. Existing reports keep their content.`} onClose={() => setDel(null)} onConfirm={() => del && remove.mutate(del.id)} />
    </>
  )
}

function TemplateDialog({ template, onClose }: { template: Template | null; onClose: () => void }) {
  const qc = useQueryClient()
  const clients = useQuery({ queryKey: ['clients'], queryFn: () => api.get<Page<Client>>('/clients', { limit: 200 }) })
  const [f, setF] = useState({
    name: template?.name ?? '', audience: template?.audience ?? 'client', base_report: template?.base_report ?? 'weekly', format: template?.format ?? 'narrative',
    client_id: template?.client_id ?? '', schedule: template?.schedule ?? 'none', tone_instructions: template?.tone_instructions ?? '',
  })
  const [sections, setSections] = useState<string[]>(template?.sections ?? DEFAULT_SECTIONS)
  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, client_id: f.client_id || null, sections }
      return template ? api.patch(`/report-templates/${template.id}`, body) : api.post('/report-templates', body)
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['templates'] }); onClose() },
  })
  const client = f.audience === 'client'
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{template ? 'Edit template' : 'New report template'}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ pt: 0.5 }}>
          <TextField label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Acme weekly client update" required />
          <Stack direction="row" spacing={2}>
            <TextField select fullWidth label="Audience" value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value as 'client' | 'internal', base_report: e.target.value === 'client' && f.base_report === 'performance' ? 'weekly' : f.base_report })}>
              <MenuItem value="client">Client (needs approval)</MenuItem>
              <MenuItem value="internal">Internal (download only)</MenuItem>
            </TextField>
            <TextField select fullWidth label="Base report" value={f.base_report} onChange={(e) => setF({ ...f, base_report: e.target.value })}>
              <MenuItem value="weekly">Weekly</MenuItem>
              <MenuItem value="monthly">Monthly</MenuItem>
              {!client && <MenuItem value="performance">Performance</MenuItem>}
            </TextField>
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField select fullWidth label="Format" value={f.format} onChange={(e) => setF({ ...f, format: e.target.value })}>
              <MenuItem value="narrative">Narrative (prose)</MenuItem>
              <MenuItem value="bullet_summary">Bullet summary</MenuItem>
              <MenuItem value="table_commentary">Table + commentary</MenuItem>
            </TextField>
            <TextField select fullWidth label="Schedule" value={f.schedule} onChange={(e) => setF({ ...f, schedule: e.target.value })}>
              <MenuItem value="none">Manual</MenuItem>
              <MenuItem value="weekly">Weekly (Fri 16:00)</MenuItem>
              <MenuItem value="monthly">Monthly (1st, 07:00)</MenuItem>
            </TextField>
          </Stack>
          <TextField select label="Client" value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })} required={client} helperText={client ? 'Only this client’s projects feed the report' : 'Optional for internal reports'}>
            <MenuItem value="">None</MenuItem>
            {clients.data?.items.map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
          </TextField>
          <Autocomplete multiple freeSolo options={DEFAULT_SECTIONS} value={sections} onChange={(_, v) => setSections(v as string[])} renderTags={(v, getTagProps) => v.map((o, i) => <Chip {...getTagProps({ index: i })} key={o} label={o} size="small" />)} renderInput={(p) => <TextField {...p} label="Sections" helperText="Press Enter to add; order is kept" />} />
          <TextField label="Tone instructions" multiline minRows={2} value={f.tone_instructions} onChange={(e) => setF({ ...f, tone_instructions: e.target.value })} placeholder="Formal, no internal names, round hours to the nearest half hour, keep it to one page" />
          <ErrorAlert error={save.error} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!f.name || sections.length === 0 || (client && !f.client_id) || save.isPending} onClick={() => save.mutate()}>Save template</Button>
      </DialogActions>
    </Dialog>
  )
}

// ----------------------------------------------------------------------------------------------
const STEPS = ['Drafted', 'Approved', 'Sent']
const stepIndex = (s: string) => ({ queued: -1, failed: -1, drafted: 0, approved: 1, sent: 2, ready: 2 }[s] ?? -1)

export function RunReview() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { can } = useAuth()
  const run = useQuery({ queryKey: ['run', id], queryFn: () => api.get<RunDetail>(`/report-runs/${id}`), refetchInterval: (q) => (['queued', 'approved'].includes(q.state.data?.status ?? '') ? 2000 : false) })
  const r = run.data
  const [text, setText] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)
  const [note, setNote] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [tab, setTab] = useState(0)
  useEffect(() => {
    if (r?.ai_text && !dirty) setText(Object.fromEntries(r.sections.map((s) => [s, String(r.ai_text?.[s] ?? '')])))
  }, [r?.ai_text, r?.sections, dirty])
  const preview = useQuery({ queryKey: ['run-preview', id, r?.status, r?.ai_text], queryFn: () => api.get<{ html: string }>(`/report-runs/${id}/preview`), enabled: tab === 1 && !!r?.figures })
  const invalidate = () => { qc.invalidateQueries({ queryKey: ['run', id] }); qc.invalidateQueries({ queryKey: ['report-runs'] }) }
  const save = useMutation({ mutationFn: () => api.patch(`/report-runs/${id}`, { ai_text: text }), onSuccess: () => { setDirty(false); invalidate() } })
  const redraft = useMutation({ mutationFn: (figures_only: boolean) => api.post(`/report-runs/${id}/redraft`, { note, figures_only }), onSuccess: () => { setDirty(false); setNote(''); invalidate() } })
  const approve = useMutation({ mutationFn: async () => { if (dirty) await api.patch(`/report-runs/${id}`, { ai_text: text }); return api.post(`/report-runs/${id}/approve`) }, onSuccess: () => { setConfirm(false); setDirty(false); invalidate() } })

  if (run.isLoading) return <CircularProgress />
  if (!r) return <ErrorAlert error={run.error} />
  const editable = r.status === 'drafted' && (can('report.ai.draft') || can('report.approve'))
  const f = r.figures
  const questions: string[] = (r.ai_text?._questions as string[] | undefined) ?? []
  return (
    <>
      <PageHeader title={r.title} subtitle={`${fmtDate(r.period_start)} – ${fmtDate(r.period_end)}`} actions={<RunStatusChip status={r.status} />} />
      <Paper sx={{ p: 2.5, mb: 2.5 }}>
        <Stepper activeStep={stepIndex(r.status)} alternativeLabel>{STEPS.map((s) => <Step key={s}><StepLabel>{s}</StepLabel></Step>)}</Stepper>
        {r.approved_at && <Typography variant="caption" color="text.secondary" display="block" align="center" sx={{ mt: 1 }}>Approved {fmtDateTime(r.approved_at)}</Typography>}
      </Paper>
      {r.status === 'queued' && <Alert severity="info" icon={<CircularProgress size={18} />} sx={{ mb: 2 }}>Drafting in the background — this page updates automatically.</Alert>}
      {r.status === 'failed' && (
        <Alert severity="error" sx={{ mb: 2 }} action={can('report.ai.draft') && <Stack direction="row" spacing={1}><Button color="inherit" size="small" onClick={() => redraft.mutate(false)}>Retry</Button><Button color="inherit" size="small" onClick={() => redraft.mutate(true)}>Figures only</Button></Stack>}>
          Drafting failed: {r.error}. You can retry, or send the update with figures only (no narrative).
        </Alert>
      )}
      {f && (
        <>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}><Tab label="Review & edit" /><Tab label="Preview" /></Tabs>
          {tab === 1 ? (preview.data ? <ReportFrame html={preview.data.html} /> : <CircularProgress />) : (
            <Grid container spacing={2.5}>
              <Grid item xs={12} md={5}>
                <Paper sx={{ p: 2.5 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>Figures the draft is built from</Typography>
                  <Grid container spacing={1} sx={{ mb: 2 }}>
                    {[['Hours', f.totals?.hours], ['Completed', f.totals?.tasks_completed], ['Open', f.totals?.tasks_open], ['Blocked', f.totals?.blocked_tasks], ['Overdue', f.totals?.overdue_tasks], ['Created', f.totals?.tasks_created]].map(([k, v]) => (
                      <Grid item xs={4} key={k as string}><Paper sx={{ p: 1.25, textAlign: 'center', bgcolor: '#f9fafc' }}><Typography variant="h6">{v ?? 0}</Typography><Typography variant="caption" color="text.secondary">{k}</Typography></Paper></Grid>
                    ))}
                  </Grid>
                  <Typography variant="subtitle2">By project</Typography>
                  <Table size="small" sx={{ mb: 2 }}>
                    <TableHead><TableRow><TableCell>Project</TableCell><TableCell align="right">Hours</TableCell><TableCell align="right">Done</TableCell><TableCell align="right">Open</TableCell></TableRow></TableHead>
                    <TableBody>{(f.projects ?? []).map((p: any) => <TableRow key={p.project}><TableCell>{p.project}</TableCell><TableCell align="right">{p.hours}</TableCell><TableCell align="right">{p.tasks_completed}</TableCell><TableCell align="right">{p.tasks_open}</TableCell></TableRow>)}</TableBody>
                  </Table>
                  <Typography variant="subtitle2">Completed work</Typography>
                  {(f.completed_tasks ?? []).length ? (f.completed_tasks as any[]).map((t) => <Typography key={t.title} variant="body2" sx={{ py: 0.4 }}>• {t.title} <Typography component="span" variant="caption" color="text.secondary">({t.project}, {t.hours}h)</Typography></Typography>) : <Typography variant="body2" color="text.secondary">None this period.</Typography>}
                  <Alert severity="info" sx={{ mt: 2 }} icon={false}>No names, comments or internal status text are sent to the AI — only these aggregated figures for this client’s projects.</Alert>
                </Paper>
              </Grid>
              <Grid item xs={12} md={7}>
                <Paper sx={{ p: 2.5 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Draft</Typography>
                    <Chip size="small" icon={<AutoAwesomeIcon />} label={r.ai_provider === 'anthropic' ? 'Drafted by AI' : 'Figures only — no AI narrative'} color={r.ai_provider === 'anthropic' ? 'secondary' : 'default'} />
                  </Stack>
                  {questions.length > 0 && <Alert severity="warning" sx={{ mb: 2 }}><b>Questions from the drafter</b><ul style={{ margin: '4px 0 0 18px', padding: 0 }}>{questions.map((q) => <li key={q}>{q}</li>)}</ul></Alert>}
                  <Stack spacing={2}>
                    {r.sections.map((s) => (
                      <TextField key={s} label={s} multiline minRows={3} fullWidth disabled={!editable} value={text[s] ?? ''} onChange={(e) => { setText({ ...text, [s]: e.target.value }); setDirty(true) }} />
                    ))}
                  </Stack>
                  <ErrorAlert error={save.error ?? approve.error ?? redraft.error} />
                  {editable && (
                    <>
                      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mt: 2.5 }}>
                        <TextField size="small" fullWidth placeholder="Ask for a redraft — “shorter”, “mention the delayed API work”" value={note} onChange={(e) => setNote(e.target.value)} />
                        <Button variant="outlined" disabled={redraft.isPending} onClick={() => redraft.mutate(false)} sx={{ whiteSpace: 'nowrap' }}>Redraft</Button>
                      </Stack>
                      <Stack direction="row" spacing={1} justifyContent="flex-end" sx={{ mt: 2 }}>
                        <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending}>Save edits</Button>
                        {can('report.approve') && <Button variant="contained" onClick={() => setConfirm(true)}>Approve</Button>}
                      </Stack>
                    </>
                  )}
                  {r.status === 'drafted' && !can('report.approve') && <Typography variant="caption" color="text.secondary">You need approval permission to approve this report.</Typography>}
                </Paper>
              </Grid>
            </Grid>
          )}
        </>
      )}
      {['approved', 'sent'].includes(r.status) && <SharePanel run={r} />}
      <ConfirmDialog open={confirm} title="Approve this report?" confirmLabel="Approve" body="Nothing is sent to the client yet. Approving locks the text and renders the final PDF, Word and Excel files. Your name and the time are recorded." onClose={() => setConfirm(false)} onConfirm={() => approve.mutate()} />
    </>
  )
}

function SharePanel({ run }: { run: RunDetail }) {
  const qc = useQueryClient()
  const { can } = useAuth()
  const contacts = useQuery({ queryKey: ['contacts', run.client_id], queryFn: () => api.get<{ items: Contact[] }>(`/clients/${run.client_id}/contacts`), enabled: !!run.client_id })
  const shares = useQuery({ queryKey: ['shares', run.id], queryFn: () => api.get<{ items: Share[] }>(`/report-runs/${run.id}/shares`), refetchInterval: 6000 })
  const [picked, setPicked] = useState<string[]>([])
  const share = useMutation({ mutationFn: () => api.post(`/report-runs/${run.id}/share`, { contact_ids: picked }), onSuccess: () => { setPicked([]); qc.invalidateQueries({ queryKey: ['shares', run.id] }); qc.invalidateQueries({ queryKey: ['run', run.id] }) } })
  const revoke = useMutation({ mutationFn: (sid: string) => api.del(`/report-runs/${run.id}/shares/${sid}`), onSuccess: () => qc.invalidateQueries({ queryKey: ['shares', run.id] }) })
  return (
    <Paper sx={{ p: 2.5, mt: 2.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>Final files & sharing</Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
        {(['pdf', 'docx', 'xlsx'] as const).map((k) => run.downloads[k] ? <Button key={k} size="small" variant="outlined" startIcon={<DownloadIcon />} href={run.downloads[k]!}>{k.toUpperCase()}</Button> : <Chip key={k} size="small" label={`${k.toUpperCase()} rendering…`} />)}
      </Stack>
      {can('report.share.client') ? (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Recipients are the client’s contacts. They get a read-only link (no login, expires after 30 days) with the PDF attached.</Typography>
          <Stack direction="row" flexWrap="wrap" useFlexGap>
            {contacts.data?.items.map((c) => (
              <FormControlLabel key={c.id} control={<Checkbox checked={picked.includes(c.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, c.id] : picked.filter((x) => x !== c.id))} />} label={`${c.name} <${c.email}>`} />
            ))}
          </Stack>
          {contacts.data?.items.length === 0 && <Alert severity="warning">This client has no contacts yet. Add one under Projects & clients.</Alert>}
          <ErrorAlert error={share.error} />
          <Button variant="contained" startIcon={<SendIcon />} sx={{ mt: 1.5 }} disabled={!picked.length || !run.downloads.pdf || share.isPending} onClick={() => share.mutate()}>Share with client</Button>
        </>
      ) : <Typography variant="body2" color="text.secondary">You do not have permission to share reports with clients.</Typography>}
      {shares.data && shares.data.items.length > 0 && (
        <Table size="small" sx={{ mt: 2 }}>
          <TableHead><TableRow><TableCell>Recipient</TableCell><TableCell>Emailed</TableCell><TableCell>Viewed</TableCell><TableCell>Expires</TableCell><TableCell /></TableRow></TableHead>
          <TableBody>
            {shares.data.items.map((s) => (
              <TableRow key={s.id}>
                <TableCell>{s.recipient_email}</TableCell>
                <TableCell>{s.emailed_at ? fmtDateTime(s.emailed_at) : 'sending…'}</TableCell>
                <TableCell>{s.viewed_at ? fmtDateTime(s.viewed_at) : '—'}</TableCell>
                <TableCell>{s.revoked_at ? <Chip size="small" label="Revoked" color="error" /> : fmtDate(s.expires_at)}</TableCell>
                <TableCell align="right">{!s.revoked_at && can('report.share.client') && <Button size="small" color="error" onClick={() => revoke.mutate(s.id)}>Revoke</Button>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Paper>
  )
}
