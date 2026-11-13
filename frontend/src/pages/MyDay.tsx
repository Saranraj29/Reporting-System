import DeleteIcon from '@mui/icons-material/DeleteOutline'
import EditIcon from '@mui/icons-material/EditOutlined'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import StopIcon from '@mui/icons-material/Stop'
import { Alert, Autocomplete, Box, Button, Chip, Dialog, DialogActions, DialogContent, Grid, IconButton, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableHead, TablePagination, TableRow, TextField, Typography } from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { DailyStatusForm } from '../components/DailyStatusDialog'
import DurationField, { durationHours } from '../components/DurationField'
import { useNow, useRunningTimer, useTimerActions } from '../timer'
import { Empty, ErrorAlert, ModalTitle, PageHeader, keepOpen } from '../components/ui'
import { daysAgo, elapsed, fmtDate, hours, isoDay, today } from '../format'
import type { DailyStatus, Page, Project, Task, TimeEntry } from '../types'

type EntryPage = Page<TimeEntry> & { total_hours: number }  // total_hours covers everything the filter matches, not only this page

const PRESETS: Record<string, { label: string; range: () => { from: string; to: string } }> = {
  week: { label: 'Last 7 days', range: () => ({ from: daysAgo(6), to: '' }) },
  month: { label: 'This month', range: () => { const n = new Date(); return { from: isoDay(new Date(n.getFullYear(), n.getMonth(), 1)), to: '' } } },
  last30: { label: 'Last 30 days', range: () => ({ from: daysAgo(29), to: '' }) },
  all: { label: 'All time', range: () => ({ from: '', to: '' }) },
}

export default function MyDay() {
  const { me, hasAny } = useAuth()
  const qc = useQueryClient()
  const now = useNow()

  const tasks = useQuery({ queryKey: ['tasks', 'mine'], queryFn: () => api.get<Page<Task>>('/tasks', { assignee: me?.id, limit: 200 }), enabled: !!me })
  const projects = useQuery({ queryKey: ['projects', 'all'], queryFn: () => api.get<Page<Project>>('/projects', { limit: 200 }) }).data?.items ?? []
  // the time log: every entry of mine, narrowed by what the person picks (dates, project, task / note text), a page at a time
  const [preset, setPreset] = useState('week')
  const [range, setRange] = useState(PRESETS.week.range())
  const [project, setProject] = useState('')
  const [text, setText] = useState('')
  const [pageNo, setPageNo] = useState(0)
  const [rows, setRows] = useState(25)
  const filters = { user: me?.id, from: range.from, to: range.to, project, q: text.trim() }
  const entries = useQuery({
    queryKey: ['entries', 'mine', filters, pageNo, rows],
    queryFn: () => api.get<EntryPage>('/time-entries', { ...filters, page: pageNo + 1, limit: rows }),
    enabled: !!me, placeholderData: keepPreviousData,
  })
  const todayHours = useQuery({ queryKey: ['entries', 'mine', 'today'], queryFn: () => api.get<EntryPage>('/time-entries', { user: me?.id, from: today(), limit: 1 }), enabled: !!me })
  const weekHours = useQuery({ queryKey: ['entries', 'mine', 'week'], queryFn: () => api.get<EntryPage>('/time-entries', { user: me?.id, from: daysAgo(6), limit: 1 }), enabled: !!me })
  const filtered = preset !== 'week' || !!project || !!text.trim() || !!range.to
  const pickPreset = (k: string) => { setPreset(k); setRange(PRESETS[k].range()); setPageNo(0) }
  const resetFilters = () => { pickPreset('week'); setProject(''); setText('') }
  const statuses = useQuery({ queryKey: ['daily-status', 'week'], queryFn: () => api.get<Page<DailyStatus>>('/daily-status', { user: me?.id, from: daysAgo(6), limit: 50 }), enabled: !!me })
  const mine = [...(tasks.data?.items ?? [])].sort((a, b) => Number(a.status === 'done') - Number(b.status === 'done'))  // open first (the groups need them together)
  const open = mine.filter((t) => t.status !== 'done')
  const running = useRunningTimer().data
  const { start, stop } = useTimerActions()
  const [pick, setPick] = useState<Task | null>(null)  // the timer's task
  const [logPick, setLogPick] = useState<Task | null>(null)  // the task for a manual entry: any of mine, finished ones too (for time worked earlier)
  const [manual, setManual] = useState({ hours: '', note: '', date: today() })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['entries'] })
    qc.invalidateQueries({ queryKey: ['tasks'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const add = useMutation({
    mutationFn: () => api.post('/time-entries', { task_id: logPick!.id, hours: durationHours(manual.hours), entry_date: manual.date, note: manual.note }),
    onSuccess: () => { setManual({ ...manual, hours: '', note: '' }); refresh() },
  })
  const del = useMutation({ mutationFn: (id: string) => api.del(`/time-entries/${id}`), onSuccess: refresh })
  const [editing, setEditing] = useState<TimeEntry | null>(null)
  const [edit, setEdit] = useState({ hours: '', note: '', date: today() })
  const startEdit = (e: TimeEntry) => { setEditing(e); setEdit({ hours: hours(e.hours), note: e.note ?? '', date: e.entry_date }) }
  const save = useMutation({
    mutationFn: () => api.patch(`/time-entries/${editing!.id}`, { hours: durationHours(edit.hours), note: edit.note, entry_date: edit.date }),
    onSuccess: () => { setEditing(null); refresh() },
  })
  const hoursOk = (v: string) => durationHours(v) !== null
  const todayTotal = todayHours.data?.total_hours ?? 0
  const weekTotal = weekHours.data?.total_hours ?? 0
  const logDone = logPick?.status === 'done'
  const logBlocked = logDone && manual.date >= today()  // a finished task takes no time for today, only for the days before

  return (
    <>
      <PageHeader title="My day" subtitle="Track time and tell your team how the day went" actions={<><Chip label={`Today ${hours(todayTotal)}`} color="primary" /><Chip label={`7 days ${hours(weekTotal)}`} variant="outlined" /></>} />
      <ErrorAlert error={tasks.error ?? entries.error} />
      <Grid container spacing={2.5}>
        <Grid item xs={12} lg={7}>
          <Stack spacing={2.5}>
            <Paper sx={{ p: 3, background: running ? 'linear-gradient(135deg,#2b3f9e,#3b5bdb)' : undefined, color: running ? '#fff' : undefined }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>Timer</Typography>
              {running ? (
                <Stack direction="row" alignItems="center" justifyContent="space-between">
                  <Box>
                    <Typography variant="h3" sx={{ fontVariantNumeric: 'tabular-nums', fontWeight: 800 }}>{running.started_at ? elapsed(running.started_at, now) : '00:00:00'}</Typography>
                    <Typography sx={{ opacity: 0.9 }}>{running.task_title}</Typography>
                  </Box>
                  <Button variant="contained" color="inherit" sx={{ color: 'error.main', bgcolor: '#fff' }} startIcon={<StopIcon />} onClick={() => stop.mutate(running.id)} disabled={stop.isPending}>Stop</Button>
                </Stack>
              ) : (
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                  <Autocomplete fullWidth size="small" options={open} value={pick} onChange={(_, v) => setPick(v)} getOptionLabel={(t) => `${t.title} — ${t.project_name}`} renderInput={(p) => <TextField {...p} label="Pick a task" />} />
                  <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={!pick || start.isPending} onClick={() => start.mutate(pick!.id)}>Start</Button>
                </Stack>
              )}
              <ErrorAlert error={start.error ?? stop.error} />
            </Paper>

            <Paper sx={{ p: 3 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>Log time manually</Typography>
              <Grid container spacing={1.5}>
                <Grid item xs={12} md={5}>
                  <Autocomplete size="small" options={mine} value={logPick} onChange={(_, v) => setLogPick(v)} groupBy={(t) => (t.status === 'done' ? 'Finished tasks' : 'Open tasks')} getOptionLabel={(t) => `${t.title} — ${t.project_name}`} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(p) => <TextField {...p} label="Task" />} />
                </Grid>
                <Grid item xs={4} md={2}><DurationField value={manual.hours} onChange={(v) => setManual({ ...manual, hours: v })} /></Grid>
                <Grid item xs={8} md={3}><TextField size="small" type="date" label="Date" fullWidth InputLabelProps={{ shrink: true }} value={manual.date} onChange={(e) => setManual({ ...manual, date: e.target.value })} inputProps={{ max: today() }} /></Grid>
                <Grid item xs={12} md={2}><Button fullWidth variant="contained" disabled={!logPick || logBlocked || !hoursOk(manual.hours) || add.isPending} onClick={() => add.mutate()}>Add</Button></Grid>
                <Grid item xs={12}><TextField size="small" fullWidth label="Note (optional)" value={manual.note} onChange={(e) => setManual({ ...manual, note: e.target.value })} /></Grid>
              </Grid>
              {logBlocked && <Alert severity="info" sx={{ mt: 1.5 }}>“{logPick?.title}” is finished. Pick an earlier date to add time you worked on it before it was done, or reopen the task.</Alert>}
              <ErrorAlert error={add.error} />
            </Paper>

            <Paper sx={{ overflow: 'hidden' }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" sx={{ p: 2.5, pb: 1.5, gap: 1 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Time log</Typography>
                <Typography variant="body2" color="text.secondary">
                  {entries.data ? `${entries.data.total} ${entries.data.total === 1 ? 'entry' : 'entries'} · ${hours(entries.data.total_hours)}` : ''}
                </Typography>
              </Stack>
              <Stack spacing={1.5} sx={{ px: 2.5, pb: 2 }}>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {Object.entries(PRESETS).map(([k, v]) => <Chip key={k} size="small" label={v.label} color={preset === k && !range.to ? 'primary' : 'default'} variant={preset === k && !range.to ? 'filled' : 'outlined'} onClick={() => pickPreset(k)} />)}
                </Stack>
                <Grid container spacing={1.5}>
                  <Grid item xs={6} md={3}><TextField size="small" fullWidth type="date" label="From" InputLabelProps={{ shrink: true }} value={range.from} onChange={(e) => { setPreset('custom'); setRange({ ...range, from: e.target.value }); setPageNo(0) }} inputProps={{ max: range.to || today() }} /></Grid>
                  <Grid item xs={6} md={3}><TextField size="small" fullWidth type="date" label="To" InputLabelProps={{ shrink: true }} value={range.to} onChange={(e) => { setPreset('custom'); setRange({ ...range, to: e.target.value }); setPageNo(0) }} inputProps={{ min: range.from || undefined, max: today() }} /></Grid>
                  <Grid item xs={12} md={3}>
                    <TextField select size="small" fullWidth label="Project" value={project} onChange={(e) => { setProject(e.target.value); setPageNo(0) }}>
                      <MenuItem value="">All projects</MenuItem>
                      {projects.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
                    </TextField>
                  </Grid>
                  <Grid item xs={12} md={3}><TextField size="small" fullWidth label="Task or note" value={text} onChange={(e) => { setText(e.target.value); setPageNo(0) }} /></Grid>
                </Grid>
                {filtered && <Box><Button size="small" onClick={resetFilters}>Reset filters</Button></Box>}
              </Stack>
              {entries.data?.items.length ? (
                <>
                  <Table size="small">
                    <TableHead><TableRow><TableCell>Date</TableCell><TableCell>Task</TableCell><TableCell>Note</TableCell><TableCell align="right">Hours</TableCell><TableCell /></TableRow></TableHead>
                    <TableBody>
                      {entries.data.items.map((e) => (
                        <TableRow key={e.id}>
                          <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(e.entry_date)}</TableCell>
                          <TableCell>{e.task_title}{e.project_name && <Typography variant="caption" color="text.secondary" component="div">{e.project_name}</Typography>}</TableCell>
                          <TableCell sx={{ color: 'text.secondary' }}>{e.note || '—'}</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{e.running ? 'running' : hours(e.hours)}</TableCell>
                          <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{!e.running && <><IconButton size="small" aria-label={`Edit time entry on ${e.task_title}`} onClick={() => startEdit(e)}><EditIcon fontSize="small" /></IconButton><IconButton size="small" aria-label={`Delete time entry on ${e.task_title}`} onClick={() => del.mutate(e.id)}><DeleteIcon fontSize="small" /></IconButton></>}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <TablePagination component="div" count={entries.data.total} page={pageNo} onPageChange={(_, n) => setPageNo(n)} rowsPerPage={rows} onRowsPerPageChange={(e) => { setRows(Number(e.target.value)); setPageNo(0) }} rowsPerPageOptions={[25, 50, 100]} />
                </>
              ) : <Empty>{filtered ? 'No time logged for these filters.' : 'No time logged in the last 7 days.'}</Empty>}
            </Paper>
            <ErrorAlert error={del.error} />
            {editing && (
              <Dialog open onClose={keepOpen(() => setEditing(null))} maxWidth="xs" fullWidth>
                <ModalTitle onClose={() => setEditing(null)}>Edit time on “{editing.task_title}”</ModalTitle>
                <DialogContent>
                  <Stack spacing={2} sx={{ pt: 1 }}>
                    <DurationField value={edit.hours} onChange={(v) => setEdit({ ...edit, hours: v })} autoFocus />
                    <TextField size="small" type="date" label="Date" InputLabelProps={{ shrink: true }} value={edit.date} onChange={(e) => setEdit({ ...edit, date: e.target.value })} inputProps={{ max: today() }} />
                    <TextField size="small" label="Note (optional)" value={edit.note} onChange={(e) => setEdit({ ...edit, note: e.target.value })} />
                    <ErrorAlert error={save.error} />
                  </Stack>
                </DialogContent>
                <DialogActions>
                  <Button onClick={() => setEditing(null)}>Cancel</Button>
                  <Button variant="contained" disabled={!hoursOk(edit.hours) || save.isPending} onClick={() => save.mutate()}>Save</Button>
                </DialogActions>
              </Dialog>
            )}
          </Stack>
        </Grid>

        <Grid item xs={12} lg={5}>
          <Stack spacing={2.5}>
            {hasAny('status.view') && (
              <Paper sx={{ p: 3 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 2 }}>Daily check-in · {fmtDate(today())}</Typography>
                <DailyStatusForm />
              </Paper>
            )}
            <Paper sx={{ p: 3 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>Recent statuses</Typography>
              {statuses.data?.items.length ? statuses.data.items.map((s) => (
                <Box key={s.id} sx={{ py: 1.25, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="caption" color="text.secondary">{fmtDate(s.status_date)}</Typography>
                  {s.plan_today && <Typography variant="body2"><b>Plan:</b> {s.plan_today}</Typography>}
                  <Typography variant="body2"><b>Done:</b> {s.did_today || '—'}</Typography>
                  {s.blockers && <Alert severity="warning" sx={{ mt: 0.75, py: 0 }}>{s.blockers}</Alert>}
                </Box>
              )) : <Empty>No statuses yet.</Empty>}
            </Paper>
          </Stack>
        </Grid>
      </Grid>
    </>
  )
}
