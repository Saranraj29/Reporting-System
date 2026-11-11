import DescriptionIcon from '@mui/icons-material/DescriptionOutlined'
import DeleteIcon from '@mui/icons-material/DeleteOutline'
import DownloadIcon from '@mui/icons-material/Download'
import ArticleIcon from '@mui/icons-material/ArticleOutlined'
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdfOutlined'
import TableChartIcon from '@mui/icons-material/TableChartOutlined'
import { Alert, Box, Button, CircularProgress, IconButton, LinearProgress, Paper, Stack, Tab, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import LinkedFilters from '../components/LinkedFilters'
import DeleteDialog from '../components/DeleteDialog'
import { Empty, ErrorAlert, PageHeader, ReportFrame, RunStatusChip } from '../components/ui'
import { NONE, type Sel } from '../filters'
import { fmtDate, fmtDateTime } from '../format'
import { useTeams } from '../hooks'
import type { Page, Project, ReportInfo, RunDetail, RunSummary, UserLite } from '../types'

export default function Reports() {
  const list = useQuery({ queryKey: ['reports'], queryFn: () => api.get<{ items: ReportInfo[] }>('/reports') })
  const { me, hasAny } = useAuth()
  const projects = useQuery({ queryKey: ['projects', 'all'], queryFn: () => api.get<Page<Project>>('/projects', { limit: 200 }) })
  // someone who only owns projects (no report permission) can run reports for those projects only
  const ownerOnly = !hasAny('report.weekly.view', 'report.monthly.view', 'report.performance.view', 'report.visibility.view')
  const reportable = (projects.data?.items ?? []).filter((p) => !ownerOnly || p.owner_ids.includes(me?.id ?? ''))
  const [tab, setTab] = useState(0)
  const [range, setRange] = useState<{ from: string; to: string } | null>(null)
  const [sel, setSel] = useState<Sel>(NONE)  // team / project / person narrow each other, see LinkedFilters
  const { team, project, user: person } = sel
  const teams = useTeams()
  const users = useQuery({ queryKey: ['users', 'all'], queryFn: () => api.get<Page<UserLite>>('/users', { limit: 200 }) })
  const info = list.data?.items[tab]
  useEffect(() => {
    if (info) setRange({ from: info.default_from, to: info.default_to })
  }, [info?.key]) // eslint-disable-line react-hooks/exhaustive-deps

  const report = useQuery({
    queryKey: ['report', info?.key, range, project, person, team],
    queryFn: () => api.get<{ html: string; figures: Record<string, any> }>(`/reports/${info!.key}`, { from: range!.from, to: range!.to, project, user: person, team }),
    enabled: !!info && !!range && range.from <= range.to,
    placeholderData: keepPreviousData, // old report stays visible while the new one loads
  })
  const [exportId, setExportId] = useState<string | null>(null)
  const exp = useMutation({
    mutationFn: (format: string) => api.post<{ id: string }>(`/reports/${info!.key}/export`, { from: range!.from, to: range!.to, project: project || null, user: person || null, team: team || null }, { format }),
    onSuccess: (r) => setExportId(r.id),
  })
  const [del, setDel] = useState<RunSummary | null>(null)
  const qc = useQueryClient()
  const recent = useQuery({ queryKey: ['report-runs', 'export'], queryFn: () => api.get<Page<RunSummary>>('/report-runs', { kind: 'export', limit: 8 }), refetchInterval: 5000 })

  if (list.isLoading) return <CircularProgress />
  if (!list.data?.items.length) return <Empty>You do not have access to any reports.</Empty>
  return (
    <>
      <PageHeader title="Reports" subtitle="Weekly, monthly and performance views — same template on screen, in PDF and in exports"
        actions={
          <>
            <Button startIcon={<PictureAsPdfIcon />} variant="outlined" onClick={() => exp.mutate('pdf')} disabled={exp.isPending}>PDF</Button>
            <Button startIcon={<TableChartIcon />} variant="outlined" onClick={() => exp.mutate('xlsx')} disabled={exp.isPending}>Excel</Button>
            <Button startIcon={<DescriptionIcon />} variant="outlined" onClick={() => exp.mutate('docx')} disabled={exp.isPending}>Word</Button>
            <Button startIcon={<ArticleIcon />} variant="outlined" onClick={() => exp.mutate('md')} disabled={exp.isPending}>Markdown</Button>
          </>
        } />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        {list.data.items.map((r) => <Tab key={r.key} label={`${r.title}${r.scope !== 'all' ? ` · ${r.scope}` : ''}`} />)}
      </Tabs>
      <Paper sx={{ p: 2, mb: 2.5 }}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
          <TextField size="small" type="date" label="From" InputLabelProps={{ shrink: true }} value={range?.from ?? ''} onChange={(e) => setRange({ from: e.target.value, to: range?.to ?? e.target.value })} />
          <TextField size="small" type="date" label="To" InputLabelProps={{ shrink: true }} value={range?.to ?? ''} onChange={(e) => setRange({ from: range?.from ?? e.target.value, to: e.target.value })} error={!!range && range.from > range.to} helperText={range && range.from > range.to ? 'To must be on or after From.' : undefined} />
          <LinkedFilters value={sel} onChange={setSel} teams={teams} projects={reportable} users={users.data?.items ?? []} everyone="Everyone in scope" widths={[160, 180, 190]} />
        </Stack>
      </Paper>
      <ErrorAlert error={report.error ?? exp.error} />
      {exportId && <ExportBanner id={exportId} onClose={() => setExportId(null)} />}
      {report.isFetching && report.data && <LinearProgress sx={{ mb: 1, borderRadius: 1 }} />}
      {report.isLoading ? <CircularProgress /> : report.data && <ReportFrame html={report.data.html} />}
      <Paper sx={{ p: 2.5, mt: 3 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>Your recent exports</Typography>
        {recent.data?.items.length ? recent.data.items.map((r) => (
          <Stack key={r.id} direction="row" alignItems="center" justifyContent="space-between" sx={{ py: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Typography variant="body2">{r.title} · {fmtDate(r.period_start)} – {fmtDate(r.period_end)} · {r.export_format?.toUpperCase()}</Typography>
            <Stack direction="row" spacing={1} alignItems="center">
              <RunStatusChip status={r.status} />
              <Button size="small" component={RouterLink} to={`/reports/runs/${r.id}`}>Open</Button>
              <Tooltip title="Delete export"><IconButton size="small" aria-label={`Delete ${r.title}`} onClick={() => setDel(r)}><DeleteIcon fontSize="small" /></IconButton></Tooltip>
            </Stack>
          </Stack>
        )) : <Typography variant="body2" color="text.secondary">Exports you request show up here.</Typography>}
      </Paper>
      {del && <DeleteDialog title="Delete this export?" description={`“${del.title}” (${fmtDate(del.period_start)} – ${fmtDate(del.period_end)}) and its files are removed. This cannot be undone.`} path={`/report-runs/${del.id}`} onClose={() => setDel(null)} onDeleted={() => { qc.invalidateQueries({ queryKey: ['report-runs'] }); qc.invalidateQueries({ queryKey: ['run'] }) }} />}
    </>
  )
}

function ExportBanner({ id, onClose }: { id: string; onClose: () => void }) {
  const run = useQuery({ queryKey: ['run', id], queryFn: () => api.get<RunDetail>(`/report-runs/${id}`), refetchInterval: (q) => (['queued'].includes(q.state.data?.status ?? 'queued') ? 1500 : false) })
  const r = run.data
  const url = r && Object.values(r.downloads).find(Boolean)
  return (
    <Alert severity={r?.status === 'failed' ? 'error' : r?.status === 'ready' ? 'success' : 'info'} onClose={onClose} sx={{ mb: 2 }}
      action={url ? <Button color="inherit" size="small" startIcon={<DownloadIcon />} href={url}>Download</Button> : undefined}>
      {!r || r.status === 'queued' ? 'Generating your export… this usually takes a few seconds.' : r.status === 'ready' ? 'Your export is ready.' : `Export failed: ${r.error}`}
    </Alert>
  )
}

/** /reports/runs/:id — where "report ready" emails point. */
export function ExportRun() {
  const { id } = useParams()
  const run = useQuery({ queryKey: ['run', id], queryFn: () => api.get<RunDetail>(`/report-runs/${id}`), refetchInterval: (q) => (q.state.data?.status === 'queued' ? 2000 : false) })
  const r = run.data
  const nav = useNavigate()
  const qc = useQueryClient()
  const [removing, setRemoving] = useState(false)
  return (
    <>
      <PageHeader title={r?.title ?? 'Report'} subtitle={r ? `${fmtDate(r.period_start)} – ${fmtDate(r.period_end)} · requested ${fmtDateTime(r.created_at)}` : undefined}
        actions={r && <Button color="error" startIcon={<DeleteIcon />} onClick={() => setRemoving(true)}>Delete</Button>} />
      {removing && r && <DeleteDialog title="Delete this report?" description="The report and its files are removed. This cannot be undone." path={`/report-runs/${r.id}`} onClose={() => setRemoving(false)} onDeleted={() => { qc.invalidateQueries({ queryKey: ['report-runs'] }); nav('/reports') }} />}
      <ErrorAlert error={run.error} />
      {r && (
        <Paper sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Box><RunStatusChip status={r.status} /></Box>
            {r.status === 'queued' && <Stack direction="row" spacing={1.5} alignItems="center"><CircularProgress size={20} /><Typography>Rendering…</Typography></Stack>}
            {r.error && <Alert severity="error">{r.error}</Alert>}
            <Stack direction="row" spacing={1}>
              {(['pdf', 'xlsx', 'docx', 'md'] as const).map((f) => r.downloads[f] && <Button key={f} variant="contained" startIcon={<DownloadIcon />} href={r.downloads[f]!}>{f === 'md' ? 'Markdown' : f.toUpperCase()}</Button>)}
            </Stack>
            <Typography variant="caption" color="text.secondary">Download links are signed and valid for one hour — reopen this page for a fresh one.</Typography>
          </Stack>
        </Paper>
      )}
    </>
  )
}
