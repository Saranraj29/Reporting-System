import AddIcon from '@mui/icons-material/Add'
import CloseIcon from '@mui/icons-material/Close'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import StopIcon from '@mui/icons-material/Stop'
import SearchIcon from '@mui/icons-material/Search'
import {
  Alert, Autocomplete, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Divider, Drawer, FormControlLabel, Grid, IconButton,
  InputAdornment, LinearProgress, MenuItem, Pagination, Paper, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { AssigneeAvatars, Empty, ErrorAlert, PageHeader, PriorityChip, StatusChip } from '../components/ui'
import { elapsed, fmtDate, fmtDateTime, hours, today } from '../format'
import { STATUS_LABELS } from '../theme'
import { useNow, useRunningTimer, useTimerActions } from '../timer'
import type { Page, Project, Task, TaskField, TimeEntry, UserLite } from '../types'

const PRIORITIES = ['low', 'medium', 'high', 'urgent']

function useLookups() {
  const projects = useQuery({ queryKey: ['projects', 'all'], queryFn: () => api.get<Page<Project>>('/projects', { limit: 200 }) })
  const users = useQuery({ queryKey: ['users', 'all'], queryFn: () => api.get<Page<UserLite>>('/users', { limit: 200 }) })
  const fields = useQuery({ queryKey: ['task-fields'], queryFn: () => api.get<{ items: TaskField[] }>('/task-fields') })
  return { projects: projects.data?.items ?? [], users: users.data?.items ?? [], fields: fields.data?.items ?? [] }
}

export default function Tasks() {
  const { can, hasAny } = useAuth()
  const { projects, users } = useLookups()
  const [page, setPage] = useState(1)
  const [f, setF] = useState({ q: '', project: '', status: '', priority: '', assignee: '', overdue: false })
  const [search, setSearch] = useState('')
  const upd = (patch: Partial<typeof f>) => {
    setF((prev) => ({ ...prev, ...patch }))
    setPage(1) // changing a filter goes back to page 1 in the same render (one request, no flicker)
  }
  useEffect(() => {
    const t = setTimeout(() => search !== f.q && upd({ q: search }), 300) // debounce typing
    return () => clearTimeout(t)
  }, [search]) // eslint-disable-line react-hooks/exhaustive-deps
  const [dialog, setDialog] = useState<Task | 'new' | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const canEdit = hasAny('task.edit')
  const showPeople = (useAuth().me?.permissions ?? []).some((p) => p === 'task.view.team' || p === 'task.view.all')

  const q = useQuery({
    queryKey: ['tasks', page, f],
    queryFn: () => api.get<Page<Task>>('/tasks', { page, limit: 15, q: f.q, project: f.project, status: f.status, priority: f.priority, assignee: f.assignee, overdue: f.overdue || undefined }),
    placeholderData: keepPreviousData,
  })

  return (
    <>
      <PageHeader
        title="Tasks"
        subtitle={showPeople ? 'Everything your team is working on' : 'Tasks assigned to you'}
        actions={canEdit && <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialog('new')}>New task</Button>}
      />
      <Paper sx={{ p: 2, mb: 2.5 }}>
        <Grid container spacing={1.5} alignItems="center">
          <Grid item xs={12} md={3}>
            <TextField size="small" fullWidth placeholder="Search tasks" value={search} onChange={(e) => setSearch(e.target.value)} InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField select size="small" fullWidth label="Project" value={f.project} onChange={(e) => upd({ project: e.target.value })}>
              <MenuItem value="">All</MenuItem>
              {projects.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField select size="small" fullWidth label="Status" value={f.status} onChange={(e) => upd({ status: e.target.value })}>
              <MenuItem value="">All</MenuItem>
              {Object.entries(STATUS_LABELS).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid item xs={6} md={1.5}>
            <TextField select size="small" fullWidth label="Priority" value={f.priority} onChange={(e) => upd({ priority: e.target.value })}>
              <MenuItem value="">All</MenuItem>
              {PRIORITIES.map((p) => <MenuItem key={p} value={p}>{p}</MenuItem>)}
            </TextField>
          </Grid>
          {showPeople && (
            <Grid item xs={6} md={2}>
              <TextField select size="small" fullWidth label="Assignee" value={f.assignee} onChange={(e) => upd({ assignee: e.target.value })}>
                <MenuItem value="">Anyone</MenuItem>
                {users.map((u) => <MenuItem key={u.id} value={u.id}>{u.name}</MenuItem>)}
              </TextField>
            </Grid>
          )}
          <Grid item xs={12} md="auto">
            <FormControlLabel control={<Switch size="small" checked={f.overdue} onChange={(e) => upd({ overdue: e.target.checked })} />} label="Overdue" />
          </Grid>
        </Grid>
      </Paper>
      <ErrorAlert error={q.error} />
      <Paper sx={{ overflow: 'hidden' }}>
        {q.isFetching && <LinearProgress />}
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="medium" sx={{ minWidth: 820 }}>
            <TableHead>
              <TableRow>
                <TableCell>Task</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Priority</TableCell>
                <TableCell>Due</TableCell>
                <TableCell sx={{ width: 170 }}>Hours (actual / ETA)</TableCell>
                <TableCell align="right">Assignees</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {q.data?.items.map((t) => (
                <TableRow key={t.id} hover sx={{ cursor: 'pointer' }} onClick={() => setOpenId(t.id)}>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>{t.title}</Typography>
                    <Typography variant="caption" color="text.secondary">{t.project_name} · {t.activity_type}</Typography>
                  </TableCell>
                  <TableCell><StatusChip status={t.status} /></TableCell>
                  <TableCell><PriorityChip priority={t.priority} /></TableCell>
                  <TableCell sx={{ color: t.overdue ? 'error.main' : 'inherit', fontWeight: t.overdue ? 700 : 400 }}>{fmtDate(t.due_date)}</TableCell>
                  <TableCell>
                    <Typography variant="caption">{hours(t.actual_hours)} / {t.eta_hours != null ? hours(t.eta_hours) : '—'}</Typography>
                    {t.eta_hours ? <LinearProgress variant="determinate" value={Math.min(100, (t.actual_hours / t.eta_hours) * 100)} color={t.actual_hours > t.eta_hours ? 'error' : 'primary'} sx={{ height: 5, borderRadius: 3, mt: 0.5 }} /> : null}
                  </TableCell>
                  <TableCell align="right"><AssigneeAvatars people={t.assignees} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
        {q.data && q.data.items.length === 0 && <Empty>No tasks match these filters.</Empty>}
        {q.data && q.data.total > q.data.limit && (
          <Stack alignItems="center" sx={{ p: 2 }}>
            <Pagination count={Math.ceil(q.data.total / q.data.limit)} page={page} onChange={(_, p) => setPage(p)} color="primary" />
          </Stack>
        )}
      </Paper>
      {dialog && <TaskDialog task={dialog === 'new' ? null : dialog} onClose={() => setDialog(null)} />}
      <TaskDrawer id={openId} onClose={() => setOpenId(null)} onEdit={(t) => { setOpenId(null); setDialog(t) }} canLog={can('task.edit.own') || can('task.edit.team') || can('task.edit.all')} />
    </>
  )
}

export function TaskDialog({ task, onClose }: { task: Task | null; onClose: () => void }) {
  const qc = useQueryClient()
  const { me } = useAuth()
  const { projects, users, fields } = useLookups()
  const defs = Object.fromEntries(fields.map((f) => [f.key, f]))
  const visible = (key: string) => defs[key]?.is_active !== false
  const [form, setForm] = useState({
    project_id: task?.project_id ?? '', title: task?.title ?? '', description: task?.description ?? '', activity_type: task?.activity_type ?? 'Development',
    priority: task?.priority ?? 'medium', status: task?.status ?? 'todo', eta_hours: task?.eta_hours?.toString() ?? '', start_date: task?.start_date ?? '', due_date: task?.due_date ?? '',
  })
  const [assignees, setAssignees] = useState<UserLite[]>([])
  const [custom, setCustom] = useState<Record<string, unknown>>(task?.custom_fields ?? {})
  useEffect(() => {
    if (task) setAssignees(users.filter((u) => task.assignees.some((a) => a.id === u.id)))
    else if (me) setAssignees(users.filter((u) => u.id === me.id))
  }, [users.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        project_id: form.project_id, title: form.title, description: form.description, activity_type: form.activity_type, priority: form.priority, status: form.status,
        eta_hours: form.eta_hours === '' ? null : Number(form.eta_hours), start_date: form.start_date || null, due_date: form.due_date || null, custom_fields: custom,
      }
      if (task) {
        const saved = await api.patch<Task>(`/tasks/${task.id}`, body)
        await api.put(`/tasks/${task.id}/assignees`, { user_ids: assignees.map((a) => a.id) })
        return saved
      }
      return api.post<Task>('/tasks', { ...body, assignee_ids: assignees.map((a) => a.id) })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      onClose()
    },
  })
  const activityOptions = defs.activity_type?.options?.length ? defs.activity_type.options : ['Development']
  const customFields = fields.filter((f) => !f.is_builtin && f.is_active)

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>{task ? 'Edit task' : 'New task'}</DialogTitle>
      <DialogContent dividers>
        <Grid container spacing={2} sx={{ pt: 0.5 }}>
          <Grid item xs={12} md={8}>
            <TextField label="Title" fullWidth required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Grid>
          <Grid item xs={12} md={4}>
            <TextField select label="Project" fullWidth required value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })}>
              {projects.filter((p) => p.status !== 'archived').map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
            </TextField>
          </Grid>
          {visible('description') && (
            <Grid item xs={12}>
              <TextField label={defs.description?.label ?? 'Description'} multiline minRows={2} fullWidth value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Grid>
          )}
          {visible('activity_type') && (
            <Grid item xs={6} md={3}>
              <TextField select label={defs.activity_type?.label ?? 'Activity type'} fullWidth value={form.activity_type} onChange={(e) => setForm({ ...form, activity_type: e.target.value })}>
                {activityOptions.map((a) => <MenuItem key={a} value={a}>{a}</MenuItem>)}
              </TextField>
            </Grid>
          )}
          {visible('priority') && (
            <Grid item xs={6} md={3}>
              <TextField select label="Priority" fullWidth value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {PRIORITIES.map((p) => <MenuItem key={p} value={p}>{p}</MenuItem>)}
              </TextField>
            </Grid>
          )}
          <Grid item xs={6} md={3}>
            <TextField select label="Status" fullWidth value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              {Object.entries(STATUS_LABELS).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
            </TextField>
          </Grid>
          {visible('eta_hours') && (
            <Grid item xs={6} md={3}>
              <TextField label={defs.eta_hours?.label ?? 'ETA (hours)'} type="number" fullWidth value={form.eta_hours} onChange={(e) => setForm({ ...form, eta_hours: e.target.value })} inputProps={{ min: 0, step: 0.5 }} />
            </Grid>
          )}
          {visible('start_date') && (
            <Grid item xs={6} md={3}>
              <TextField label="Start date" type="date" fullWidth InputLabelProps={{ shrink: true }} value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
            </Grid>
          )}
          {visible('due_date') && (
            <Grid item xs={6} md={3}>
              <TextField label="Due date" type="date" fullWidth InputLabelProps={{ shrink: true }} value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
            </Grid>
          )}
          <Grid item xs={12} md={6}>
            <Autocomplete multiple options={users} value={assignees} onChange={(_, v) => setAssignees(v)} getOptionLabel={(u) => u.name} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(p) => <TextField {...p} label="Assignees" helperText="One or more people" />} />
          </Grid>
          {customFields.length > 0 && (
            <>
              <Grid item xs={12}><Divider textAlign="left"><Typography variant="caption" color="text.secondary">Company fields</Typography></Divider></Grid>
              {customFields.map((cf) => (
                <Grid item xs={12} md={6} key={cf.id}>
                  {cf.type === 'select' ? (
                    <TextField select fullWidth label={cf.label} required={cf.required} value={(custom[cf.key] as string) ?? ''} onChange={(e) => setCustom({ ...custom, [cf.key]: e.target.value })}>
                      {cf.options.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
                    </TextField>
                  ) : (
                    <TextField fullWidth label={cf.label} required={cf.required} type={cf.type === 'number' ? 'number' : cf.type === 'date' ? 'date' : 'text'} InputLabelProps={cf.type === 'date' ? { shrink: true } : undefined}
                      value={(custom[cf.key] as string | number) ?? ''} onChange={(e) => setCustom({ ...custom, [cf.key]: cf.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value })} />
                  )}
                </Grid>
              ))}
            </>
          )}
        </Grid>
        {save.error && <Alert severity="error" sx={{ mt: 2 }}>{errorMessage(save.error)}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending || !form.title || !form.project_id || assignees.length === 0}>
          {task ? 'Save changes' : 'Create task'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function TaskDrawer({ id, onClose, onEdit, canLog }: { id: string | null; onClose: () => void; onEdit: (t: Task) => void; canLog: boolean }) {
  const qc = useQueryClient()
  const task = useQuery({ queryKey: ['task', id], queryFn: () => api.get<Task>(`/tasks/${id}`), enabled: !!id })
  const comments = useQuery({ queryKey: ['comments', id], queryFn: () => api.get<{ items: { id: string; user_name: string; body: string; created_at: string }[] }>(`/tasks/${id}/comments`), enabled: !!id })
  const entries = useQuery({ queryKey: ['entries', id], queryFn: () => api.get<Page<TimeEntry>>('/time-entries', { task: id, limit: 50 }), enabled: !!id })
  const [comment, setComment] = useState('')
  const [log, setLog] = useState({ hours: '', note: '' })
  const t = task.data
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['task', id] })
    qc.invalidateQueries({ queryKey: ['tasks'] })
    qc.invalidateQueries({ queryKey: ['entries', id] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const addComment = useMutation({ mutationFn: () => api.post(`/tasks/${id}/comments`, { body: comment }), onSuccess: () => { setComment(''); qc.invalidateQueries({ queryKey: ['comments', id] }) } })
  const setStatus = useMutation({ mutationFn: (status: string) => api.patch(`/tasks/${id}`, { status }), onSuccess: refresh })
  const logTime = useMutation({ mutationFn: () => api.post('/time-entries', { task_id: id, hours: Number(log.hours), entry_date: today(), note: log.note }), onSuccess: () => { setLog({ hours: '', note: '' }); refresh() } })
  const running = useRunningTimer().data
  const { start, stop } = useTimerActions()
  const now = useNow()
  const runningHere = !!running && running.task_id === id

  return (
    <Drawer anchor="right" open={!!id} onClose={onClose} PaperProps={{ sx: { width: { xs: '100%', sm: 480 }, p: 3 } }}>
      {t && (
        <Stack spacing={2.5}>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
            <Typography variant="h6" sx={{ pr: 2 }}>{t.title}</Typography>
            <IconButton onClick={onClose} aria-label="Close"><CloseIcon /></IconButton>
          </Stack>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <StatusChip status={t.status} />
            <PriorityChip priority={t.priority} />
            {t.overdue && <Typography variant="caption" color="error" sx={{ alignSelf: 'center', fontWeight: 700 }}>OVERDUE</Typography>}
          </Stack>
          {t.description && <Typography variant="body2" color="text.secondary">{t.description}</Typography>}
          <Grid container spacing={1.5}>
            {[['Project', t.project_name], ['Activity', t.activity_type], ['Start', fmtDate(t.start_date)], ['Due', fmtDate(t.due_date)], ['ETA', t.eta_hours != null ? hours(t.eta_hours) : '—'], ['Actual', hours(t.actual_hours)]].map(([k, v]) => (
              <Grid item xs={6} key={k}><Typography variant="caption" color="text.secondary">{k}</Typography><Typography variant="body2" sx={{ fontWeight: 600 }}>{v}</Typography></Grid>
            ))}
          </Grid>
          <Box><Typography variant="caption" color="text.secondary">Assignees</Typography><AssigneeAvatars people={t.assignees} max={6} /></Box>
          {t.can_edit && (
            <Stack direction="row" spacing={1}>
              <TextField select size="small" label="Move to" value="" onChange={(e) => setStatus.mutate(e.target.value)} sx={{ minWidth: 150 }}>
                {Object.entries(STATUS_LABELS).filter(([k]) => k !== t.status).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
              </TextField>
              <Button variant="outlined" onClick={() => onEdit(t)}>Edit</Button>
            </Stack>
          )}
          {setStatus.error && <Alert severity="error">{errorMessage(setStatus.error)}</Alert>}
          <Divider />
          {canLog && t.assignees.length > 0 && (
            <Stack spacing={1}>
              <Typography variant="subtitle2">Log time</Typography>
              <Stack direction="row" spacing={1}>
                <TextField size="small" type="number" label="Hours" value={log.hours} onChange={(e) => setLog({ ...log, hours: e.target.value })} sx={{ width: 100 }} inputProps={{ min: 0.25, max: 24, step: 0.25 }} />
                <TextField size="small" label="Note" value={log.note} onChange={(e) => setLog({ ...log, note: e.target.value })} fullWidth />
                <Button variant="contained" disabled={!log.hours || logTime.isPending} onClick={() => logTime.mutate()}>Add</Button>
              </Stack>
              {(logTime.error || start.error || stop.error) && <Alert severity="error">{errorMessage(logTime.error ?? start.error ?? stop.error)}</Alert>}
              <Paper sx={{ p: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, bgcolor: runningHere ? '#fff5f5' : '#f9fafc', borderColor: runningHere ? '#ffc9c9' : undefined }}>
                {runningHere && running?.started_at ? (
                  <>
                    <Box><Typography variant="caption" color="error" sx={{ fontWeight: 700 }}>TIMER RUNNING</Typography><Typography variant="h6" sx={{ fontVariantNumeric: 'tabular-nums' }}>{elapsed(running.started_at, now)}</Typography></Box>
                    <Button variant="contained" color="error" startIcon={<StopIcon />} disabled={stop.isPending} onClick={() => stop.mutate(running.id)}>Stop timer</Button>
                  </>
                ) : running ? (
                  <>
                    <Typography variant="body2">A timer is already running on <b>{running.task_title}</b>.</Typography>
                    <Button variant="outlined" color="error" size="small" startIcon={<StopIcon />} disabled={stop.isPending} onClick={() => stop.mutate(running.id)}>Stop it</Button>
                  </>
                ) : (
                  <>
                    <Typography variant="body2" color="text.secondary">Track time as you work</Typography>
                    <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={start.isPending} onClick={() => start.mutate(id!)}>Start timer</Button>
                  </>
                )}
              </Paper>
            </Stack>
          )}
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Time entries</Typography>
            {entries.data?.items.length ? entries.data.items.map((e) => (
              <Stack key={e.id} direction="row" justifyContent="space-between" sx={{ py: 0.75, borderBottom: '1px solid', borderColor: 'divider' }}>
                <Typography variant="body2">{e.user_name} · {fmtDate(e.entry_date)}{e.note ? ` · ${e.note}` : ''}</Typography>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>{e.running ? 'running' : hours(e.hours)}</Typography>
              </Stack>
            )) : <Typography variant="body2" color="text.secondary">No time logged yet.</Typography>}
          </Box>
          <Divider />
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Comments</Typography>
            <Stack spacing={1.25}>
              {comments.data?.items.map((c) => (
                <Paper key={c.id} sx={{ p: 1.5, bgcolor: '#f9fafc' }}>
                  <Typography variant="caption" color="text.secondary">{c.user_name} · {fmtDateTime(c.created_at)}</Typography>
                  <Typography variant="body2">{c.body}</Typography>
                </Paper>
              ))}
              <Stack direction="row" spacing={1}>
                <TextField size="small" fullWidth placeholder="Add a comment" value={comment} onChange={(e) => setComment(e.target.value)} />
                <Button variant="outlined" disabled={!comment.trim()} onClick={() => addComment.mutate()}>Post</Button>
              </Stack>
            </Stack>
          </Box>
        </Stack>
      )}
    </Drawer>
  )
}
