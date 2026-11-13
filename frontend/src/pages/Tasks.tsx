import {
  Alert, Autocomplete, Box, Button, Dialog, DialogActions, DialogContent, Divider, FormControlLabel, Grid,
  LinearProgress, MenuItem, Pagination, Paper, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { useFab } from '../fab'
import { TaskPanel } from '../components/TaskPanel'
import { AssigneeAvatars, Empty, ErrorAlert, ModalTitle, PageHeader, PriorityChip, SearchBox, StatusChip, clickable, keepOpen } from '../components/ui'
import { change, personOptions, projectOptions, teamOptions, type Sel } from '../filters'
import { fmtDate, hours } from '../format'
import { useSearch } from '../hooks'
import { STATUS_LABELS } from '../theme'
import type { Page, Project, Task, TaskField, Team, UserLite } from '../types'

const PRIORITIES = ['low', 'medium', 'high', 'urgent']
const CAPS = { '& .MuiSelect-select': { textTransform: 'capitalize' } }  // "High" everywhere, not "high" in the form

function useLookups() {
  const projects = useQuery({ queryKey: ['projects', 'all'], queryFn: () => api.get<Page<Project>>('/projects', { limit: 200 }) })
  const users = useQuery({ queryKey: ['users', 'all'], queryFn: () => api.get<Page<UserLite>>('/users', { limit: 200 }) })
  const fields = useQuery({ queryKey: ['task-fields'], queryFn: () => api.get<{ items: TaskField[] }>('/task-fields') })
  const teams = useQuery({ queryKey: ['teams', ''], queryFn: () => api.get<{ items: Team[] }>('/teams') })
  return { projects: projects.data?.items ?? [], users: users.data?.items ?? [], fields: fields.data?.items ?? [], teams: teams.data?.items ?? [] }
}

export default function Tasks() {
  const { can, hasAny } = useAuth()
  const { projects, users, teams } = useLookups()
  const [params] = useSearchParams()  // /tasks?team=<id> comes from the Teams page
  const [page, setPage] = useState(1)
  const [f, setF] = useState({ project: '', team: params.get('team') ?? '', status: '', priority: '', assignee: '', overdue: false })
  const search = useSearch()  // the API is called only once 3+ characters are typed
  const upd = (patch: Partial<typeof f>) => {
    setF((prev) => ({ ...prev, ...patch }))
    setPage(1) // changing a filter goes back to page 1 in the same render (one request, no flicker)
  }
  useEffect(() => setPage(1), [search.term])
  const [dialog, setDialog] = useState<Task | 'new' | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const canEdit = hasAny('task.edit')
  useFab(canEdit ? 'New task' : null, () => setDialog('new'))
  const showPeople = (useAuth().me?.permissions ?? []).some((p) => p === 'task.view.team' || p === 'task.view.all')
  // team / project / assignee narrow each other (see filters.ts); picking one clears the others it no longer fits
  const sel: Sel = { team: f.team, project: f.project, user: f.assignee }
  const linked = { teams, projects, users: showPeople ? users : undefined }
  const link = (key: keyof Sel, value: string) => {
    const n = change(sel, key, value, linked)
    upd({ team: n.team, project: n.project, assignee: n.user })
  }
  const teamOpts = teamOptions(linked, sel)
  const projectOpts = projectOptions(linked, sel)
  const personOpts = personOptions(linked, sel)

  const q = useQuery({
    queryKey: ['tasks', page, f, search.term],
    queryFn: () => api.get<Page<Task>>('/tasks', { page, limit: 15, q: search.term, team: f.team, project: f.project, status: f.status, priority: f.priority, assignee: f.assignee, overdue: f.overdue || undefined }),
    placeholderData: keepPreviousData,
  })

  return (
    <>
      <PageHeader
        title="Tasks"
        subtitle={showPeople ? 'Everything your team is working on' : 'Tasks assigned to you'}
      />
      <Paper sx={{ p: 2, mb: 2.5 }}>
        <Grid container spacing={1.5} alignItems="center">
          <Grid item xs={12} md={3}>
            <SearchBox value={search.input} onChange={search.setInput} placeholder="Search tasks" width="100%" />
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField select size="small" fullWidth label="Project" value={f.project} onChange={(e) => link('project', e.target.value)}>
              <MenuItem value="">All</MenuItem>
              {projectOpts.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
              {projectOpts.length === 0 && <MenuItem disabled value="__none">No projects for this selection</MenuItem>}
            </TextField>
          </Grid>
          <Grid item xs={6} md={1.5}>
            <TextField select size="small" fullWidth label="Team" value={f.team} onChange={(e) => link('team', e.target.value)}>
              <MenuItem value="">All</MenuItem>
              {teamOpts.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
              {teamOpts.length === 0 && <MenuItem disabled value="__none">No teams for this selection</MenuItem>}
            </TextField>
          </Grid>
          <Grid item xs={6} md={1.5}>
            <TextField select size="small" fullWidth label="Status" value={f.status} onChange={(e) => upd({ status: e.target.value })}>
              <MenuItem value="">All</MenuItem>
              {Object.entries(STATUS_LABELS).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid item xs={6} md={1.5}>
            <TextField select size="small" fullWidth label="Priority" value={f.priority} onChange={(e) => upd({ priority: e.target.value })} sx={CAPS}>
              <MenuItem value="">All</MenuItem>
              {PRIORITIES.map((p) => <MenuItem key={p} value={p} sx={{ textTransform: 'capitalize' }}>{p}</MenuItem>)}
            </TextField>
          </Grid>
          {showPeople && (
            <Grid item xs={6} md={2}>
              <TextField select size="small" fullWidth label="Assignee" value={f.assignee} onChange={(e) => link('user', e.target.value)}>
                <MenuItem value="">Anyone</MenuItem>
                {personOpts.map((u) => <MenuItem key={u.id} value={u.id}>{u.name}</MenuItem>)}
                {personOpts.length === 0 && <MenuItem disabled value="__none">No people for this selection</MenuItem>}
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
          <Table size="medium" sx={{ minWidth: { xs: 0, md: 820 } }}>
            <TableHead>
              <TableRow>
                <TableCell>Task</TableCell>
                <TableCell>Status</TableCell>
                <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>Priority</TableCell>
                <TableCell>Due</TableCell>
                <TableCell sx={{ width: 170, display: { xs: 'none', md: 'table-cell' } }}>Hours (actual / ETA)</TableCell>
                <TableCell align="right">Assignees</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {q.data?.items.map((t) => (
                <TableRow key={t.id} hover sx={{ cursor: 'pointer' }} {...clickable(() => setOpenId(t.id))} aria-label={`Open task ${t.title}`}>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>{t.title}</Typography>
                    <Typography variant="caption" color="text.secondary">{t.project_name} · {t.activity_type}{t.team_name ? ` · ${t.team_name}` : ''}</Typography>
                  </TableCell>
                  <TableCell><StatusChip status={t.status} /></TableCell>
                  <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}><PriorityChip priority={t.priority} /></TableCell>
                  <TableCell sx={{ color: t.overdue ? 'error.main' : 'inherit', fontWeight: t.overdue ? 700 : 400 }}>{fmtDate(t.due_date)}</TableCell>
                  <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>
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
      <TaskPanel id={openId} onClose={() => setOpenId(null)} onEdit={(t) => { setOpenId(null); setDialog(t) }} canLog={can('task.edit.own') || can('task.edit.team') || can('task.edit.all')} />
    </>
  )
}

export function TaskDialog({ task, onClose }: { task: Task | null; onClose: () => void }) {
  const qc = useQueryClient()
  const { me } = useAuth()
  const { projects, fields } = useLookups()
  const defs = Object.fromEntries(fields.map((f) => [f.key, f]))
  const visible = (key: string) => defs[key]?.is_active !== false
  const [form, setForm] = useState({
    project_id: task?.project_id ?? '', title: task?.title ?? '', description: task?.description ?? '', activity_type: task?.activity_type ?? 'Development',
    priority: task?.priority ?? 'medium', status: task?.status ?? 'todo', eta_hours: task?.eta_hours?.toString() ?? '', start_date: task?.start_date ?? '', due_date: task?.due_date ?? '',
  })
  const [assignees, setAssignees] = useState<UserLite[]>(task ? task.assignees.map((a) => ({ id: a.id, name: a.name, email: '' }) as UserLite) : [])
  const [custom, setCustom] = useState<Record<string, unknown>>(task?.custom_fields ?? {})
  // who this person may give a task of the chosen project to: themselves, their team, or (project owner) the project's members
  const assignable = useQuery({
    queryKey: ['assignable-users', form.project_id],
    queryFn: () => api.get<{ can_add_tasks: boolean; items: UserLite[] }>(`/projects/${form.project_id}/assignable-users`),
    enabled: !!form.project_id,
  })
  const options = assignable.data?.items ?? []
  useEffect(() => {
    if (!assignable.data) return
    const allowed = new Set(assignable.data.items.map((u) => u.id))
    setAssignees((prev) => {
      const kept = prev.filter((a) => allowed.has(a.id))
      const mine = me ? assignable.data.items.filter((u) => u.id === me.id) : []
      return !task && kept.length === 0 ? mine : kept  // a new task starts assigned to me
    })
  }, [assignable.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        project_id: form.project_id, title: form.title, description: form.description, activity_type: form.activity_type, priority: form.priority, status: form.status,
        eta_hours: form.eta_hours === '' ? null : Number(form.eta_hours), start_date: form.start_date || null, due_date: form.due_date || null, custom_fields: custom,
      }
      if (task) {
        const saved = await api.patch<Task>(`/tasks/${task.id}`, { ...body, expected_updated_at: task.updated_at })
        await api.put(`/tasks/${task.id}/assignees`, { user_ids: assignees.map((a) => a.id), expected_updated_at: saved.updated_at })
        return saved
      }
      return api.post<Task>('/tasks', { ...body, assignee_ids: assignees.map((a) => a.id) })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      qc.invalidateQueries({ queryKey: ['task'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      onClose()
    },
    onError: () => { qc.invalidateQueries({ queryKey: ['task'] }); qc.invalidateQueries({ queryKey: ['tasks'] }) },  // somebody else saved first: the latest version is loaded behind this form
  })
  // told while typing, not after pressing Create
  const etaError = form.eta_hours !== '' && Number(form.eta_hours) < 0 ? 'The estimate cannot be negative.' : ''
  const dateError = form.start_date && form.due_date && form.due_date < form.start_date ? 'The due date cannot be before the start date.' : ''
  const activityOptions = defs.activity_type?.options?.length ? defs.activity_type.options : ['Development']
  const customFields = fields.filter((f) => !f.is_builtin && f.is_active)

  return (
    <Dialog open onClose={keepOpen(onClose)} fullWidth maxWidth="md">
      <ModalTitle onClose={onClose}>{task ? 'Edit task' : 'New task'}</ModalTitle>
      <DialogContent dividers>
        <Grid container spacing={2} sx={{ pt: 0.5 }}>
          <Grid item xs={12} md={8}>
            <TextField label="Title" fullWidth required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Grid>
          <Grid item xs={12} md={4}>
            <TextField select label="Project" fullWidth required value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })}
              helperText={form.project_id && projects.find((p) => p.id === form.project_id)?.team_name ? `Team: ${projects.find((p) => p.id === form.project_id)?.team_name} (from the project)` : ' '}>
              {projects.filter((p) => p.status !== 'archived' && (p.can_add_tasks !== false || p.id === task?.project_id)).map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
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
              <TextField select label="Priority" fullWidth value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} sx={CAPS}>
                {PRIORITIES.map((p) => <MenuItem key={p} value={p} sx={{ textTransform: 'capitalize' }}>{p}</MenuItem>)}
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
              <TextField label={defs.eta_hours?.label ?? 'ETA (hours)'} type="number" fullWidth value={form.eta_hours} onChange={(e) => setForm({ ...form, eta_hours: e.target.value })} inputProps={{ min: 0, step: 0.5 }} error={!!etaError} helperText={etaError || ' '} />
            </Grid>
          )}
          {visible('start_date') && (
            <Grid item xs={6} md={3}>
              <TextField label="Start date" type="date" fullWidth InputLabelProps={{ shrink: true }} value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} error={!!dateError} />
            </Grid>
          )}
          {visible('due_date') && (
            <Grid item xs={6} md={3}>
              <TextField label="Due date" type="date" fullWidth InputLabelProps={{ shrink: true }} value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} error={!!dateError} helperText={dateError || ' '} inputProps={{ min: form.start_date || undefined }} />
            </Grid>
          )}
          <Grid item xs={12} md={6}>
            <Autocomplete multiple options={options} value={assignees} onChange={(_, v) => setAssignees(v)} getOptionLabel={(u) => u.name} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(p) => <TextField {...p} label="Assignees" helperText={form.project_id ? (options.length > 1 ? 'One or more people' : 'You can assign tasks to yourself') : 'Choose a project first'} />} />
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
        <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending || !form.title || !form.project_id || assignees.length === 0 || !!etaError || !!dateError}>
          {task ? 'Save changes' : 'Create task'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
