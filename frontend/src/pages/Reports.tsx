import DescriptionIcon from '@mui/icons-material/DescriptionOutlined'
import DownloadIcon from '@mui/icons-material/Download'
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdfOutlined'
import TableChartIcon from '@mui/icons-material/TableChartOutlined'
import { Alert, Box, Button, CircularProgress, MenuItem, Paper, Stack, Tab, Tabs, TextField, Typography } from '@mui/material'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import { api } from '../api'
import { Empty, ErrorAlert, PageHeader, ReportFrame, RunStatusChip } from '../components/ui'
import { fmtDate, fmtDateTime } from '../format'
import type { Page, Project, ReportInfo, RunDetail, RunSummary } from '../types'

export default function Reports() {
  const list = useQuery({ queryKey: ['reports'], queryFn: () => api.get<{ items: ReportInfo[] }>('/reports') })
  const projects = useQuery({ queryKey: ['projects', 'all'], queryFn: () => api.get<Page<Project>>('/projects', { limit: 200 }) })
  const [tab, setTab] = useState(0)
  const [range, setRange] = useState<{ from: string; to: string } | null>(null)
  const [project, setProject] = useState('')
  const info = list.data?.items[tab]
  useEffect(() => {
    if (info) setRange({ from: info.default_from, to: info.default_to })
  }, [info?.key]) // eslint-disable-line react-hooks/exhaustive-deps

  const report = useQuery({
    queryKey: ['report', info?.key, range, project],
    queryFn: () => api.get<{ html: string; figures: Record<string, any> }>(`/reports/${info!.key}`, { from: range!.from, to: range!.to, project }),
    enabled: !!info && !!range,
  })
  const [exportId, setExportId] = useState<string | null>(null)
  const exp = useMutation({
    mutationFn: (format: string) => api.post<{ id: string }>(`/reports/${info!.key}/export`, { from: range!.from, to: range!.to, project: project || null }, { format }),
    onSuccess: (r) => setExportId(r.id),
  })
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
          </>
        } />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        {list.data.items.map((r) => <Tab key={r.key} label={`${r.title}${r.scope !== 'all' ? ` · ${r.scope}` : ''}`} />)}
      </Tabs>
      <Paper sx={{ p: 2, mb: 2.5 }}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
          <TextField size="small" type="date" label="From" InputLabelProps={{ shrink: true }} value={range?.from ?? ''} onChange={(e) => setRange({ from: e.target.value, to: range?.to ?? e.target.value })} />
          <TextField size="small" type="date" label="To" InputLabelProps={{ shrink: true }} value={range?.to ?? ''} onChange={(e) => setRange({ from: range?.from ?? e.target.value, to: e.target.value })} />
          <TextField select size="small" label="Project" value={project} onChange={(e) => setProject(e.target.value)} sx={{ minWidth: 180 }}>
            <MenuItem value="">All projects</MenuItem>
            {projects.data?.items.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
          </TextField>
        </Stack>
      </Paper>
      <ErrorAlert error={report.error ?? exp.error} />
      {exportId && <ExportBanner id={exportId} onClose={() => setExportId(null)} />}
      {report.isLoading ? <CircularProgress /> : report.data && <ReportFrame html={report.data.html} />}
      <Paper sx={{ p: 2.5, mt: 3 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>Your recent exports</Typography>
        {recent.data?.items.length ? recent.data.items.map((r) => (
          <Stack key={r.id} direction="row" alignItems="center" justifyContent="space-between" sx={{ py: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Typography variant="body2">{r.title} · {fmtDate(r.period_start)} – {fmtDate(r.period_end)} · {r.export_format?.toUpperCase()}</Typography>
            <Stack direction="row" spacing={1} alignItems="center">
              <RunStatusChip status={r.status} />
              <Button size="small" component={RouterLink} to={`/reports/runs/${r.id}`}>Open</Button>
            </Stack>
          </Stack>
        )) : <Typography variant="body2" color="text.secondary">Exports you request show up here.</Typography>}
      </Paper>
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
  return (
    <>
      <PageHeader title={r?.title ?? 'Report'} subtitle={r ? `${fmtDate(r.period_start)} – ${fmtDate(r.period_end)} · requested ${fmtDateTime(r.created_at)}` : undefined} />
      <ErrorAlert error={run.error} />
      {r && (
        <Paper sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Box><RunStatusChip status={r.status} /></Box>
            {r.status === 'queued' && <Stack direction="row" spacing={1.5} alignItems="center"><CircularProgress size={20} /><Typography>Rendering…</Typography></Stack>}
            {r.error && <Alert severity="error">{r.error}</Alert>}
            <Stack direction="row" spacing={1}>
              {(['pdf', 'xlsx', 'docx'] as const).map((f) => r.downloads[f] && <Button key={f} variant="contained" startIcon={<DownloadIcon />} href={r.downloads[f]!}>{f.toUpperCase()}</Button>)}
            </Stack>
            <Typography variant="caption" color="text.secondary">Download links are signed and valid for one hour — reopen this page for a fresh one.</Typography>
          </Stack>
        </Paper>
      )}
    </>
  )
}
