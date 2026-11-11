import ArticleIcon from '@mui/icons-material/ArticleOutlined'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import BarChartIcon from '@mui/icons-material/BarChartOutlined'
import CheckIcon from '@mui/icons-material/CheckCircleOutline'
import DeleteIcon from '@mui/icons-material/DeleteOutline'
import ThumbDownIcon from '@mui/icons-material/ThumbDownAltOutlined'
import ThumbUpIcon from '@mui/icons-material/ThumbUpAltOutlined'
import DescriptionIcon from '@mui/icons-material/DescriptionOutlined'
import DownloadIcon from '@mui/icons-material/Download'
import NotesIcon from '@mui/icons-material/NotesOutlined'
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdfOutlined'
import AccountTreeIcon from '@mui/icons-material/AccountTreeOutlined'
import TableChartIcon from '@mui/icons-material/TableChartOutlined'
import UploadIcon from '@mui/icons-material/UploadFileOutlined'
import { Alert, Autocomplete, Box, Button, Chip, CircularProgress, Collapse, IconButton, Paper, Stack, TextField, Tooltip, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import DeleteDialog from '../components/DeleteDialog'
import { Empty, ErrorAlert, PageHeader, ReportFrame } from '../components/ui'
import { fmtDate } from '../format'
import type { AiOutlineSection, AiReportDetail, AiReportOptions, AiReportSummary } from '../types'

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const daysAgo = (n: number) => iso(new Date(Date.now() - n * 86400000))

const PRESETS: { label: string; range: () => [string, string] }[] = [
  { label: 'Last 7 days', range: () => [daysAgo(6), daysAgo(0)] },
  { label: 'Last 14 days', range: () => [daysAgo(13), daysAgo(0)] },
  { label: 'This month', range: () => { const n = new Date(); return [iso(new Date(n.getFullYear(), n.getMonth(), 1)), iso(n)] } },
  { label: 'Last month', range: () => { const n = new Date(); return [iso(new Date(n.getFullYear(), n.getMonth() - 1, 1)), iso(new Date(n.getFullYear(), n.getMonth(), 0))] } },
]

const FORMATS = [
  { value: 'auto', title: 'Default', text: 'No format needed — the AI builds a clean, well-structured, industry-standard management report.' },
  { value: 'visibility', title: 'Project Visibility Report', text: 'One section per project with goal, status charts, workflow and deliverables, then combined dashboards.' },
  { value: 'sample', title: 'Own format', text: 'Paste the sections you were asked for (or a sample report). The report follows exactly that structure.' },
] as const

type Option = { id: string; name: string }
const ALL = '__all__'

/** A multi-select whose first choice is "All …": picking it clears the rest, picking anything else drops it, empty falls back to it. */
function PickMany({ label, allLabel, options, value, onChange }: { label: string; allLabel: string; options: Option[]; value: Option[]; onChange: (v: Option[]) => void }) {
  const all: Option = { id: ALL, name: allLabel }
  const shown = value.length ? value : [all]
  return (
    <Autocomplete multiple size="small" disableCloseOnSelect sx={{ flex: 1, minWidth: 240 }} options={[all, ...options]} getOptionLabel={(o) => o.name} isOptionEqualToValue={(a, b) => a.id === b.id}
      value={shown} filterSelectedOptions={false}
      onChange={(_, v) => {
        const picked = v.filter((o) => o.id !== ALL)
        const justAll = v.length > 0 && v[v.length - 1].id === ALL && !shown.some((o) => o.id === ALL)
        onChange(justAll ? [] : picked)
      }}
      renderInput={(params) => <TextField {...params} label={label} />} />
  )
}

const STATUS_TEXT: Record<AiReportSummary['status'], string> = {
  planning: 'Preparing structure', outline_ready: 'Waiting for your OK', generating: 'Writing report', ready: 'Ready', failed: 'Failed',
}

function statusChip(s: AiReportSummary['status']) {
  const color = s === 'ready' ? 'success' : s === 'failed' ? 'error' : s === 'outline_ready' ? 'warning' : 'info'
  return <Chip size="small" color={color} variant={s === 'ready' ? 'filled' : 'outlined'} label={STATUS_TEXT[s]} />
}

// ---------------------------------------------------------------------------------------------- list + new request
export default function AiReports() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const options = useQuery({ queryKey: ['ai-options'], queryFn: () => api.get<AiReportOptions>('/ai-reports/options') })
  const list = useQuery({ queryKey: ['ai-reports'], queryFn: () => api.get<{ items: AiReportSummary[] }>('/ai-reports') })
  const [del, setDel] = useState<AiReportSummary | null>(null)
  const [request, setRequest] = useState('')
  const [projects, setProjects] = useState<Option[]>([])
  const [people, setPeople] = useState<Option[]>([])
  const [params] = useSearchParams()  // the assistant's "Open as full report" hands over the period and projects
  const [range, setRange] = useState<[string, string]>(() => {
    const d = Number(params.get('days'))
    return d >= 1 && d <= 400 ? [daysAgo(d - 1), daysAgo(0)] : PRESETS[0].range()
  })
  const [format, setFormat] = useState<'auto' | 'visibility' | 'sample'>('auto')
  const [sample, setSample] = useState('')
  const file = useRef<HTMLInputElement>(null)
  const create = useMutation({
    mutationFn: () => api.post<{ id: string }>('/ai-reports', {
      request, project_ids: projects.map((p) => p.id), person_ids: people.map((p) => p.id), period_start: range[0], period_end: range[1], format_mode: format, format_sample: format === 'sample' ? sample : '',
    }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['ai-reports'] }); nav(`/ai-reports/${r.id}`) },
  })
  useEffect(() => {
    const ids = (params.get('projects') ?? '').split(',').filter(Boolean)
    if (ids.length && options.data) setProjects(options.data.projects.filter((p) => ids.includes(p.id)))
  }, [options.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const max = options.data?.max_sample_chars ?? 20000
  const canSend = !create.isPending && range[0] <= range[1] && (format !== 'sample' || sample.trim().length >= 20)
  const onFile = async (f?: File) => {
    if (f) setSample((await f.text()).slice(0, max))
  }

  return (
    <>
      <PageHeader title="AI reports" subtitle="Tell us what you need. You will see the structure first — the report is only written after you say OK." />
      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack spacing={3}>
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>1 · What is this report for?</Typography>
            <TextField fullWidth multiline minRows={2} value={request} onChange={(e) => setRequest(e.target.value)} inputProps={{ 'aria-label': 'What is this report for' }} placeholder="Optional — e.g. Weekly update for the CTO, focus on delays and risks" />
          </Box>
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>2 · Projects and period</Typography>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} flexWrap="wrap" useFlexGap>
              <PickMany label="Projects" allLabel={options.data?.all_projects === false ? 'All my projects' : 'All projects'} options={options.data?.projects ?? []} value={projects} onChange={setProjects} />
              <PickMany label="People" allLabel="Everyone" options={options.data?.people ?? []} value={people} onChange={setPeople} />
              <TextField size="small" type="date" label="From" InputLabelProps={{ shrink: true }} value={range[0]} onChange={(e) => setRange([e.target.value, range[1]])} />
              <TextField size="small" type="date" label="To" InputLabelProps={{ shrink: true }} value={range[1]} onChange={(e) => setRange([range[0], e.target.value])} />
            </Stack>
            <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
              {PRESETS.map((p) => <Chip key={p.label} label={p.label} onClick={() => setRange(p.range())} variant="outlined" />)}
            </Stack>
          </Box>
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>3 · Which format?</Typography>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
              {FORMATS.map((f) => (
                <Paper key={f.value} role="radio" aria-checked={format === f.value} tabIndex={0} variant="outlined" onClick={() => setFormat(f.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFormat(f.value) } }}
                  sx={{ p: 2, flex: 1, cursor: 'pointer', borderWidth: 2, borderColor: format === f.value ? 'primary.main' : 'divider', bgcolor: format === f.value ? 'action.selected' : 'transparent' }}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                    {format === f.value && <CheckIcon color="primary" fontSize="small" />}
                    <Typography sx={{ fontWeight: 700 }}>{f.title}</Typography>
                  </Stack>
                  <Typography variant="body2" color="text.secondary">{f.text}</Typography>
                </Paper>
              ))}
            </Stack>
            <Collapse in={format === 'sample'} unmountOnExit>
              <Box sx={{ mt: 2 }}>
                <TextField fullWidth multiline minRows={6} maxRows={16} value={sample} onChange={(e) => setSample(e.target.value.slice(0, max))} inputProps={{ 'aria-label': 'Report format' }}
                  placeholder={'Paste the format here, for example:\n1. Executive summary\n2. Progress per project\n3. Risks\n4. Budget\n5. Next steps\n\nor paste a complete sample report.'}
                  helperText={`The AI copies the sections and their order. It uses the sample only as a layout — your real data fills it. ${sample.length}/${max}`} />
                <input ref={file} type="file" accept=".md,.txt,.markdown,text/plain,text/markdown" hidden onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = '' }} />
                <Button sx={{ mt: 1 }} size="small" startIcon={<UploadIcon />} onClick={() => file.current?.click()}>Upload a .md or .txt file instead</Button>
              </Box>
            </Collapse>
          </Box>
          <ErrorAlert error={create.error} />
          <Stack direction="row" spacing={2} alignItems="center">
            <Button variant="contained" size="large" startIcon={<AutoAwesomeIcon />} disabled={!canSend} onClick={() => create.mutate()}>
              {create.isPending ? 'Preparing…' : 'Show me the structure'}
            </Button>
            {options.data && !options.data.ai_enabled && <Typography variant="caption" color="text.secondary">{{ off: 'AI-written text is switched off — the built-in layout and wording will be used.', not_configured: 'AI is not connected yet — a built-in layout and wording will be used.', provider_down: 'The AI service is not answering right now — the built-in layout and wording will be used.', ready: '' }[options.data.ai_status]}</Typography>}
          </Stack>
        </Stack>
      </Paper>

      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>Previous reports</Typography>
      {list.data?.items.length ? (
        <Paper>
          {list.data.items.map((r) => (
            <Stack key={r.id} component={RouterLink} to={`/ai-reports/${r.id}`} direction="row" alignItems="center" justifyContent="space-between" spacing={2}
              sx={{ p: 2, color: 'inherit', textDecoration: 'none', borderBottom: '1px solid', borderColor: 'divider', '&:last-child': { borderBottom: 0 }, '&:hover': { bgcolor: 'action.hover' } }}>
              <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ fontWeight: 600 }} noWrap>{r.title}</Typography>
                <Typography variant="caption" color="text.secondary">{fmtDate(r.period_start)} – {fmtDate(r.period_end)}{r.request ? ` · ${r.request.slice(0, 80)}` : ''}</Typography>
              </Box>
              <Stack direction="row" spacing={0.5} alignItems="center">
                {statusChip(r.status)}
                <Tooltip title="Delete report">
                  <IconButton size="small" aria-label={`Delete ${r.title}`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); setDel(r) }}><DeleteIcon fontSize="small" /></IconButton>
                </Tooltip>
              </Stack>
            </Stack>
          ))}
        </Paper>
      ) : <Empty>No reports yet. Create the first one above.</Empty>}
      {del && <DeleteDialog title="Delete this report?" description={`“${del.title}” and its downloads are removed. This cannot be undone.`} path={`/ai-reports/${del.id}`} onClose={() => setDel(null)} onDeleted={() => qc.invalidateQueries({ queryKey: ['ai-reports'] })} />}
    </>
  )
}

// ---------------------------------------------------------------------------------------------- one report
const VISUAL_ICON: Record<AiOutlineSection['visual'], JSX.Element> = {
  table: <TableChartIcon fontSize="small" />, chart: <BarChartIcon fontSize="small" />, flow: <AccountTreeIcon fontSize="small" />, text: <NotesIcon fontSize="small" />,
}
const VISUAL_LABEL: Record<AiOutlineSection['visual'], string> = { table: 'Table', chart: 'Chart', flow: 'Flow diagram', text: 'Written by AI' }

function StructurePreview({ r, onApprove, approving }: { r: AiReportDetail; onApprove: () => void; approving: boolean }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [changing, setChanging] = useState(false)
  const [note, setNote] = useState('')
  const change = useMutation({
    mutationFn: () => api.post(`/ai-reports/${r.id}/change-structure`, { note }),
    onSuccess: () => { setChanging(false); setNote(''); qc.invalidateQueries({ queryKey: ['ai-report', r.id] }) },
  })
  const remove = useMutation({ mutationFn: () => api.del(`/ai-reports/${r.id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ['ai-reports'] }); nav('/ai-reports') } })
  const o = r.outline!
  const n = r.project_names.length
  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>Here is how your report will look</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        “{o.title}” · {r.project_names.join(', ') || 'no projects'}{r.people_names.length ? ` · work by ${r.people_names.join(', ')}` : ''} · {fmtDate(r.period_start)} – {fmtDate(r.period_end)}. Nothing is written yet — check the sections and say OK.
      </Typography>
      {o.notes && <Alert severity="info" icon={false} sx={{ mb: 2 }}>{o.notes}</Alert>}
      <Box component="ol" aria-label="Report structure" sx={{ m: 0, p: 0, listStyle: 'none' }}>
        {o.sections.map((s, i) => (
          <Stack component="li" key={s.id} direction="row" spacing={2} alignItems="center" sx={{ py: 1.25, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Box sx={{ width: 28, height: 28, borderRadius: '50%', bgcolor: 'primary.main', color: 'primary.contrastText', display: 'grid', placeItems: 'center', fontSize: 13, fontWeight: 700, flexShrink: 0 }}>{i + 1}</Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={{ fontWeight: 600 }}>{s.title.replace('{project}', '‹project›')}</Typography>
              <Typography variant="caption" color="text.secondary">{s.what}</Typography>
            </Box>
            <Stack direction="row" spacing={0.75} sx={{ flexShrink: 0 }}>
              {s.scope === 'per_project' && <Chip size="small" variant="outlined" color="primary" label={n > 1 ? `Repeats for each of ${n} projects` : 'Per project'} />}
              <Chip size="small" variant="outlined" icon={VISUAL_ICON[s.visual]} label={VISUAL_LABEL[s.visual]} />
            </Stack>
          </Stack>
        ))}
      </Box>
      <Collapse in={changing} unmountOnExit>
        <Stack spacing={1.5} sx={{ mt: 2 }}>
          <TextField autoFocus multiline minRows={2} value={note} onChange={(e) => setNote(e.target.value)} label="What should change?" inputProps={{ 'aria-label': 'What should change' }}
            placeholder="e.g. Add a budget section, remove the effort charts, put risks first" />
          <ErrorAlert error={change.error} />
          <Stack direction="row" spacing={1}>
            <Button variant="contained" disabled={note.trim().length < 3 || change.isPending} onClick={() => change.mutate()}>Update the structure</Button>
            <Button onClick={() => setChanging(false)}>Cancel</Button>
          </Stack>
        </Stack>
      </Collapse>
      <ErrorAlert error={remove.error} />
      <Stack direction="row" spacing={1.5} sx={{ mt: 3 }} flexWrap="wrap" useFlexGap>
        <Button variant="contained" size="large" startIcon={<CheckIcon />} onClick={onApprove} disabled={approving}>Looks good — create the report</Button>
        {!changing && <Button variant="outlined" size="large" onClick={() => setChanging(true)}>Change something</Button>}
        <Button color="inherit" startIcon={<DeleteIcon />} onClick={() => remove.mutate()} disabled={remove.isPending}>Start over</Button>
      </Stack>
    </Paper>
  )
}

function Working({ text, sub }: { text: string; sub: string }) {
  return (
    <Paper sx={{ p: 5, textAlign: 'center' }} role="status">
      <CircularProgress sx={{ mb: 2 }} />
      <Typography variant="h6" sx={{ fontWeight: 700 }}>{text}</Typography>
      <Typography color="text.secondary">{sub}</Typography>
    </Paper>
  )
}

function Feedback({ r }: { r: AiReportDetail }) {
  const qc = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')
  const vote = useMutation({
    mutationFn: (v: { rating: 'up' | 'down'; reason?: string }) => api.post(`/ai-reports/${r.id}/feedback`, v),
    onSuccess: () => { setAsking(false); qc.invalidateQueries({ queryKey: ['ai-report', r.id] }) },
  })
  return (
    <Box sx={{ mt: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="body2" color="text.secondary">Was this report useful?</Typography>
        <Button size="small" variant={r.my_feedback === 'up' ? 'contained' : 'outlined'} startIcon={<ThumbUpIcon />} onClick={() => vote.mutate({ rating: 'up' })} aria-pressed={r.my_feedback === 'up'}>Yes</Button>
        <Button size="small" variant={r.my_feedback === 'down' ? 'contained' : 'outlined'} startIcon={<ThumbDownIcon />} onClick={() => setAsking(true)} aria-pressed={r.my_feedback === 'down'}>No</Button>
      </Stack>
      <Collapse in={asking} unmountOnExit>
        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
          <TextField size="small" fullWidth autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What was wrong? (optional)" inputProps={{ 'aria-label': 'What was wrong' }} />
          <Button variant="contained" onClick={() => vote.mutate({ rating: 'down', reason })} disabled={vote.isPending}>Send</Button>
        </Stack>
      </Collapse>
      <ErrorAlert error={vote.error} />
    </Box>
  )
}

function Result({ r }: { r: AiReportDetail }) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const [open, setOpen] = useState(false)
  const html = useQuery({ queryKey: ['ai-preview', r.id, r.written_by, r.created_at, r.status], queryFn: () => api.get<{ html: string }>(`/ai-reports/${r.id}/preview`) })
  const rewrite = useMutation({
    mutationFn: () => api.post(`/ai-reports/${r.id}/rewrite`, { note }),
    onSuccess: () => { setOpen(false); setNote(''); qc.invalidateQueries({ queryKey: ['ai-report', r.id] }) },
  })
  const downloads: [keyof AiReportSummary['downloads'], string, JSX.Element][] = [
    ['pdf', 'PDF', <PictureAsPdfIcon key="p" />], ['docx', 'Word', <DescriptionIcon key="d" />], ['xlsx', 'Excel', <TableChartIcon key="x" />], ['md', 'Markdown', <ArticleIcon key="m" />],
  ]
  return (
    <Stack spacing={2}>
      <Paper sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'center' }} justifyContent="space-between">
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>Your report is ready</Typography>
            <Typography variant="body2" color="text.secondary">Download it in the format you need.</Typography>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {downloads.map(([k, label, icon]) => r.downloads[k] && <Button key={k} variant="contained" startIcon={icon} endIcon={<DownloadIcon />} href={r.downloads[k]!}>{label}</Button>)}
          </Stack>
        </Stack>
        {r.builtin_sections > 0 && <Alert severity="info" sx={{ mt: 2 }}>{r.builtin_sections} {r.builtin_sections === 1 ? 'section uses' : 'sections use'} standard wording: the AI text there could not be checked against your data. Use “Rewrite the text” to try again.</Alert>}
        {r.no_activity.length > 0 && <Alert severity="warning" sx={{ mt: 2 }}>No activity in this period for: {r.no_activity.join(', ')}.</Alert>}
        <Feedback r={r} />
        <Box sx={{ mt: 2 }}>
          {!open && <Button variant="outlined" onClick={() => setOpen(true)}>Rewrite the text</Button>}
          <Collapse in={open} unmountOnExit>
            <Stack spacing={1.5}>
              <TextField autoFocus multiline minRows={2} value={note} onChange={(e) => setNote(e.target.value)} label="How should it change?" inputProps={{ 'aria-label': 'How should the text change' }} placeholder="e.g. Shorter, mention the delay in Apollo, more formal" />
              <ErrorAlert error={rewrite.error} />
              <Stack direction="row" spacing={1}>
                <Button variant="contained" disabled={note.trim().length < 3 || rewrite.isPending} onClick={() => rewrite.mutate()}>Rewrite</Button>
                <Button onClick={() => setOpen(false)}>Cancel</Button>
              </Stack>
            </Stack>
          </Collapse>
        </Box>
      </Paper>
      {html.isLoading ? <CircularProgress /> : html.data && <ReportFrame html={html.data.html} height={820} />}
    </Stack>
  )
}

export function AiReportPage() {
  const { id } = useParams()
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['ai-report', id], queryFn: () => api.get<AiReportDetail>(`/ai-reports/${id}`),
    refetchInterval: (query) => (['planning', 'generating'].includes(query.state.data?.status ?? '') ? 1500 : false),
  })
  const approve = useMutation({ mutationFn: () => api.post(`/ai-reports/${id}/approve`), onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-report', id] }) })
  const retry = useMutation({ mutationFn: () => api.post(`/ai-reports/${id}/retry`), onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-report', id] }) })
  const r = q.data
  return (
    <>
      <PageHeader title={r?.title ?? 'AI report'} subtitle={r ? `${fmtDate(r.period_start)} – ${fmtDate(r.period_end)}${r.written_by === 'builtin' ? ' · built-in wording' : ''}` : undefined}
        actions={<Button component={RouterLink} to="/ai-reports" color="inherit">← All reports</Button>} />
      <ErrorAlert error={q.error ?? approve.error} />
      {q.isLoading && <CircularProgress />}
      {r?.status === 'planning' && <Working text="Preparing the structure…" sub="This takes a few seconds." />}
      {r?.status === 'outline_ready' && r.outline && <StructurePreview r={r} onApprove={() => approve.mutate()} approving={approve.isPending} />}
      {r?.status === 'generating' && <Working text="Writing your report…" sub="Numbers come straight from your project data; the AI writes the text." />}
      {r?.status === 'ready' && <Result r={r} />}
      {r?.status === 'failed' && (
        <Paper sx={{ p: 3 }}>
          <Alert severity="error" sx={{ mb: 2 }}>{r.error || 'Something went wrong while preparing this report.'}</Alert>
          <Button variant="contained" onClick={() => retry.mutate()} disabled={retry.isPending}>Try again</Button>
        </Paper>
      )}
    </>
  )
}
