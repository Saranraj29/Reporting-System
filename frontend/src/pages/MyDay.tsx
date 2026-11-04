import DeleteIcon from '@mui/icons-material/DeleteOutline'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import StopIcon from '@mui/icons-material/Stop'
import { Alert, Autocomplete, Box, Button, Chip, Grid, IconButton, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { DailyStatusForm } from '../components/DailyStatusDialog'
import { useNow, useRunningTimer, useTimerActions } from '../timer'
import { Empty, ErrorAlert, PageHeader } from '../components/ui'
import { daysAgo, elapsed, fmtDate, hours, today } from '../format'
import type { DailyStatus, Page, Task, TimeEntry } from '../types'

export default function MyDay() {
  const { me, hasAny } = useAuth()
  const qc = useQueryClient()
  const now = useNow()

  const tasks = useQuery({ queryKey: ['tasks', 'mine'], queryFn: () => api.get<Page<Task>>('/tasks', { assignee: me?.id, limit: 100 }), enabled: !!me })
  const entries = useQuery({ queryKey: ['entries', 'mine'], queryFn: () => api.get<Page<TimeEntry>>('/time-entries', { user: me?.id, from: daysAgo(6), limit: 100 }), enabled: !!me })
  const statuses = useQuery({ queryKey: ['daily-status', 'week'], queryFn: () => api.get<Page<DailyStatus>>('/daily-status', { user: me?.id, from: daysAgo(6), limit: 50 }), enabled: !!me })
  const open = (tasks.data?.items ?? []).filter((t) => t.status !== 'done')
  const running = useRunningTimer().data
  const { start, stop } = useTimerActions()
  const [pick, setPick] = useState<Task | null>(null)
  const [manual, setManual] = useState({ hours: '', note: '', date: today() })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['entries'] })
    qc.invalidateQueries({ queryKey: ['tasks'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const add = useMutation({
    mutationFn: () => api.post('/time-entries', { task_id: pick!.id, hours: Number(manual.hours), entry_date: manual.date, note: manual.note }),
    onSuccess: () => { setManual({ ...manual, hours: '', note: '' }); refresh() },
  })
  const del = useMutation({ mutationFn: (id: string) => api.del(`/time-entries/${id}`), onSuccess: refresh })
  const todayTotal = (entries.data?.items ?? []).filter((e) => e.entry_date === today() && !e.running).reduce((s, e) => s + e.hours, 0)
  const weekTotal = (entries.data?.items ?? []).filter((e) => !e.running).reduce((s, e) => s + e.hours, 0)

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
                  <Autocomplete size="small" options={open} value={pick} onChange={(_, v) => setPick(v)} getOptionLabel={(t) => t.title} renderInput={(p) => <TextField {...p} label="Task" />} />
                </Grid>
                <Grid item xs={4} md={2}><TextField size="small" type="number" label="Hours" fullWidth value={manual.hours} onChange={(e) => setManual({ ...manual, hours: e.target.value })} inputProps={{ min: 0.25, max: 24, step: 0.25 }} /></Grid>
                <Grid item xs={8} md={3}><TextField size="small" type="date" label="Date" fullWidth InputLabelProps={{ shrink: true }} value={manual.date} onChange={(e) => setManual({ ...manual, date: e.target.value })} inputProps={{ max: today() }} /></Grid>
                <Grid item xs={12} md={2}><Button fullWidth variant="contained" disabled={!pick || !manual.hours || add.isPending} onClick={() => add.mutate()}>Add</Button></Grid>
                <Grid item xs={12}><TextField size="small" fullWidth label="Note (optional)" value={manual.note} onChange={(e) => setManual({ ...manual, note: e.target.value })} /></Grid>
              </Grid>
              <ErrorAlert error={add.error} />
            </Paper>

            <Paper sx={{ overflow: 'hidden' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, p: 2.5, pb: 1.5 }}>Last 7 days</Typography>
              {entries.data?.items.length ? (
                <Table size="small">
                  <TableHead><TableRow><TableCell>Date</TableCell><TableCell>Task</TableCell><TableCell>Note</TableCell><TableCell align="right">Hours</TableCell><TableCell /></TableRow></TableHead>
                  <TableBody>
                    {entries.data.items.map((e) => (
                      <TableRow key={e.id}>
                        <TableCell>{fmtDate(e.entry_date)}</TableCell>
                        <TableCell>{e.task_title}</TableCell>
                        <TableCell sx={{ color: 'text.secondary' }}>{e.note || '—'}</TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>{e.running ? 'running' : hours(e.hours)}</TableCell>
                        <TableCell align="right">{!e.running && <IconButton size="small" aria-label="Delete entry" onClick={() => del.mutate(e.id)}><DeleteIcon fontSize="small" /></IconButton>}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : <Empty>No time logged this week.</Empty>}
            </Paper>
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
