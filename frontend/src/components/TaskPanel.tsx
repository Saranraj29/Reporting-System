import CheckCircleIcon from '@mui/icons-material/CheckCircleOutline'
import CloseIcon from '@mui/icons-material/Close'
import CodeIcon from '@mui/icons-material/Code'
import FormatBoldIcon from '@mui/icons-material/FormatBold'
import FormatItalicIcon from '@mui/icons-material/FormatItalic'
import FormatListBulletedIcon from '@mui/icons-material/FormatListBulleted'
import FormatListNumberedIcon from '@mui/icons-material/FormatListNumbered'
import FormatQuoteIcon from '@mui/icons-material/FormatQuote'
import FormatStrikethroughIcon from '@mui/icons-material/FormatStrikethrough'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import LinkIcon from '@mui/icons-material/Link'
import LockIcon from '@mui/icons-material/LockOutlined'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ReplayIcon from '@mui/icons-material/Replay'
import StopIcon from '@mui/icons-material/Stop'
import TaskAltIcon from '@mui/icons-material/TaskAlt'
import DeleteIcon from '@mui/icons-material/DeleteOutline'
import {
  Alert, Autocomplete, Avatar, Box, Button, Checkbox, Divider, Drawer, FormControlLabel, IconButton, LinearProgress, MenuItem, Paper, Select, Stack, Tab, Tabs,
  TextField, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState } from 'react'
import { api, errorMessage } from '../api'
import DeleteDialog from './DeleteDialog'
import DurationField, { durationHours } from './DurationField'
import { ago, elapsed, fmtDate, fmtDateTime, hours, initials, today } from '../format'
import { STATUS_COLORS, STATUS_LABELS } from '../theme'
import { useNow, useRunningTimer, useTimerActions } from '../timer'
import type { Comment, Page, Task, TaskField, TimeEntry, UserLite } from '../types'
import { Markdown } from './Markdown'
import { PriorityChip, StatusChip } from './ui'

const PRIORITIES = ['low', 'medium', 'high', 'urgent']
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

function SideLabel({ children }: { children: React.ReactNode }) {
  return <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', mb: 0.75 }}>{children}</Typography>
}

function Person({ name }: { name: string }) {
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <Avatar sx={{ width: 24, height: 24, fontSize: 11, bgcolor: 'primary.light' }}>{initials(name)}</Avatar>
      <Typography variant="body2">{name}</Typography>
    </Stack>
  )
}

// ----------------------------------------------------------------------------------------------- comment editor
type Wrap = { before: string; after?: string; block?: boolean; placeholder: string }
const TOOLS: { label: string; icon: React.ReactNode; wrap: Wrap }[] = [
  { label: 'Bold', icon: <FormatBoldIcon fontSize="small" />, wrap: { before: '**', after: '**', placeholder: 'bold text' } },
  { label: 'Italic', icon: <FormatItalicIcon fontSize="small" />, wrap: { before: '_', after: '_', placeholder: 'italic text' } },
  { label: 'Strikethrough', icon: <FormatStrikethroughIcon fontSize="small" />, wrap: { before: '~~', after: '~~', placeholder: 'struck text' } },
  { label: 'Quote', icon: <FormatQuoteIcon fontSize="small" />, wrap: { before: '> ', block: true, placeholder: 'quote' } },
  { label: 'Code', icon: <CodeIcon fontSize="small" />, wrap: { before: '`', after: '`', placeholder: 'code' } },
  { label: 'Link', icon: <LinkIcon fontSize="small" />, wrap: { before: '[', after: '](https://)', placeholder: 'link text' } },
  { label: 'Bulleted list', icon: <FormatListBulletedIcon fontSize="small" />, wrap: { before: '- ', block: true, placeholder: 'list item' } },
  { label: 'Numbered list', icon: <FormatListNumberedIcon fontSize="small" />, wrap: { before: '1. ', block: true, placeholder: 'list item' } },
  { label: 'Checklist', icon: <TaskAltIcon fontSize="small" />, wrap: { before: '- [ ] ', block: true, placeholder: 'to do' } },
]

function CommentEditor({
  taskId, done, canEdit, onChanged,
}: { taskId: string; done: boolean; canEdit: boolean; onChanged: () => void }) {
  const qc = useQueryClient()
  const ref = useRef<HTMLTextAreaElement>(null)
  const [text, setText] = useState('')
  const [preview, setPreview] = useState(false)
  const [internal, setInternal] = useState(false)

  const apply = ({ before, after = '', block, placeholder }: Wrap) => {
    const el = ref.current
    const start = el?.selectionStart ?? text.length
    const end = el?.selectionEnd ?? text.length
    const selected = text.slice(start, end) || placeholder
    const lead = block && start > 0 && text[start - 1] !== '\n' ? '\n' : ''
    const next = text.slice(0, start) + lead + before + selected + after + text.slice(end)
    setText(next)
    requestAnimationFrame(() => {
      el?.focus()
      const pos = start + lead.length + before.length
      el?.setSelectionRange(pos, pos + selected.length)
    })
  }

  const post = useMutation({
    mutationFn: () => api.post<Comment>(`/tasks/${taskId}/comments`, { body: text.trim(), is_internal: internal }),
    onSuccess: () => {
      setText('')
      setInternal(false)
      setPreview(false)
      qc.invalidateQueries({ queryKey: ['comments', taskId] })
    },
  })
  const close = useMutation({
    mutationFn: async () => {
      if (text.trim()) await api.post(`/tasks/${taskId}/comments`, { body: text.trim(), is_internal: internal })
      await api.patch(`/tasks/${taskId}`, { status: done ? 'todo' : 'done' })
    },
    onSuccess: () => {
      setText('')
      setInternal(false)
      qc.invalidateQueries({ queryKey: ['comments', taskId] })
      onChanged()
    },
  })
  const busy = post.isPending || close.isPending

  return (
    <Box>
      <Paper sx={{ overflow: 'hidden', borderColor: '#c9d1e0' }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 0.75, py: 0.25, bgcolor: '#f9fafc', borderBottom: '1px solid #e4e8f0' }}>
          <Stack direction="row" alignItems="center" flexWrap="wrap">
            {TOOLS.map((t) => (
              <Tooltip key={t.label} title={t.label}>
                <span>
                  <IconButton size="small" aria-label={t.label} disabled={preview} onClick={() => apply(t.wrap)}>{t.icon}</IconButton>
                </span>
              </Tooltip>
            ))}
          </Stack>
          <Tabs value={preview ? 1 : 0} onChange={(_, v) => setPreview(v === 1)} sx={{ minHeight: 34, '& .MuiTab-root': { minHeight: 34, py: 0, fontSize: 13 } }}>
            <Tab label="Write" />
            <Tab label="Preview" />
          </Tabs>
        </Stack>
        {preview ? (
          <Box sx={{ p: 1.75, minHeight: 130 }}>{text.trim() ? <Markdown text={text} /> : <Typography variant="body2" color="text.secondary">Nothing to preview yet.</Typography>}</Box>
        ) : (
          <TextField
            inputRef={ref} multiline minRows={5} maxRows={14} fullWidth placeholder="Write a comment or drag your files here…" value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && text.trim() && !busy) post.mutate() }}
            sx={{ '& fieldset': { border: 'none' }, '& textarea': { fontSize: 14 } }}
            inputProps={{ 'aria-label': 'Comment' }}
          />
        )}
        <Box sx={{ px: 1.5, py: 0.5, bgcolor: '#f9fafc', borderTop: '1px solid #e4e8f0' }}>
          <Typography variant="caption" color="text.secondary">Markdown is supported · Ctrl+Enter to post</Typography>
        </Box>
      </Paper>
      <Stack direction="row" alignItems="center" sx={{ mt: 1 }}>
        <FormControlLabel control={<Checkbox size="small" checked={internal} onChange={(e) => setInternal(e.target.checked)} />} label="Make this an internal note" />
        <Tooltip title="Internal notes are visible to the author, team leads, managers, admins and the project's owners. People who only see their own tasks cannot read them.">
          <HelpOutlineIcon fontSize="small" color="primary" />
        </Tooltip>
      </Stack>
      {(post.error || close.error) && <Alert severity="error" sx={{ mt: 1 }}>{errorMessage(post.error ?? close.error)}</Alert>}
      <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
        <Button variant="contained" disabled={!text.trim() || busy} onClick={() => post.mutate()}>{internal ? 'Add internal note' : 'Comment'}</Button>
        {canEdit && (
          <Button variant="outlined" color={done ? 'primary' : 'inherit'} startIcon={done ? <ReplayIcon /> : <CheckCircleIcon />} disabled={busy} onClick={() => close.mutate()}>
            {done ? 'Reopen issue' : 'Close issue'}
          </Button>
        )}
      </Stack>
    </Box>
  )
}

// ----------------------------------------------------------------------------------------------- activity feed
function Activity({ taskId, done, canEdit, onChanged }: { taskId: string; done: boolean; canEdit: boolean; onChanged: () => void }) {
  const comments = useQuery({ queryKey: ['comments', taskId], queryFn: () => api.get<{ items: Comment[] }>(`/tasks/${taskId}/comments`) })
  const [filter, setFilter] = useState<'all' | 'comment' | 'system'>('all')
  const [order, setOrder] = useState<'asc' | 'desc'>('asc')
  const items = useMemo(() => {
    const list = (comments.data?.items ?? []).filter((c) => filter === 'all' || c.kind === filter)
    return order === 'asc' ? list : [...list].reverse()
  }, [comments.data, filter, order])
  const compact = { height: 32, fontSize: 13, '& .MuiSelect-select': { py: 0.5 } }

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
        <Typography variant="h6">Activity</Typography>
        <Stack direction="row" spacing={1}>
          <Select size="small" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} sx={compact} inputProps={{ 'aria-label': 'Filter activity' }}>
            <MenuItem value="all">All activity</MenuItem>
            <MenuItem value="comment">Comments only</MenuItem>
            <MenuItem value="system">History only</MenuItem>
          </Select>
          <Select size="small" value={order} onChange={(e) => setOrder(e.target.value as typeof order)} sx={compact} inputProps={{ 'aria-label': 'Sort activity' }}>
            <MenuItem value="asc">Oldest first</MenuItem>
            <MenuItem value="desc">Newest first</MenuItem>
          </Select>
        </Stack>
      </Stack>

      {order === 'desc' && <Box sx={{ mb: 2 }}><CommentEditor taskId={taskId} done={done} canEdit={canEdit} onChanged={onChanged} /></Box>}

      <Stack spacing={0} sx={{ position: 'relative' }}>
        {items.map((c) =>
          c.kind === 'system' ? (
            <Stack key={c.id} direction="row" spacing={1.25} alignItems="flex-start" sx={{ py: 0.9, pl: 0.5 }}>
              <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#b8c1d4', mt: '7px', ml: '10px', flexShrink: 0 }} />
              <Typography variant="body2" color="text.secondary" component="div" sx={{ lineHeight: 1.5 }}>
                <b style={{ color: 'inherit' }}>{c.user_name}</b> <Markdown text={c.body} dense />
              </Typography>
              <Tooltip title={fmtDateTime(c.created_at)}><Typography variant="caption" color="text.disabled" sx={{ whiteSpace: 'nowrap', ml: 'auto !important' }}>{ago(c.created_at)}</Typography></Tooltip>
            </Stack>
          ) : (
            <Paper key={c.id} sx={{ my: 1, overflow: 'hidden', borderColor: c.is_internal ? '#ffd8a8' : undefined, bgcolor: c.is_internal ? '#fff9f0' : undefined }}>
              <Stack direction="row" spacing={1.25} alignItems="center" sx={{ px: 1.75, py: 1, borderBottom: '1px solid', borderColor: c.is_internal ? '#ffe8cc' : 'divider', bgcolor: c.is_internal ? '#fff4e6' : '#f9fafc' }}>
                <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: 'primary.light' }}>{initials(c.user_name)}</Avatar>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>{c.user_name}</Typography>
                <Tooltip title={fmtDateTime(c.created_at)}><Typography variant="caption" color="text.secondary">commented {ago(c.created_at)}</Typography></Tooltip>
                {c.is_internal && (
                  <Tooltip title="Only visible to the author, leads, managers, admins and project owners">
                    <Stack direction="row" spacing={0.5} alignItems="center" sx={{ ml: 'auto !important', px: 1, py: 0.1, borderRadius: 99, bgcolor: '#ffe8cc', color: '#d9480f' }}>
                      <LockIcon sx={{ fontSize: 14 }} />
                      <Typography variant="caption" sx={{ fontWeight: 700 }}>Internal note</Typography>
                    </Stack>
                  </Tooltip>
                )}
              </Stack>
              <Box sx={{ px: 1.75, py: 1 }}><Markdown text={c.body} /></Box>
            </Paper>
          ),
        )}
        {comments.data && items.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>Nothing here yet.</Typography>}
      </Stack>

      {order === 'asc' && <Box sx={{ mt: 2 }}><CommentEditor taskId={taskId} done={done} canEdit={canEdit} onChanged={onChanged} /></Box>}
    </Box>
  )
}

// ----------------------------------------------------------------------------------------------- panel
export function TaskPanel({ id, onClose, onEdit, canLog }: { id: string | null; onClose: () => void; onEdit: (t: Task) => void; canLog: boolean }) {
  const qc = useQueryClient()
  const task = useQuery({ queryKey: ['task', id], queryFn: () => api.get<Task>(`/tasks/${id}`), enabled: !!id })
  const entries = useQuery({ queryKey: ['entries', id], queryFn: () => api.get<Page<TimeEntry>>('/time-entries', { task: id, limit: 50 }), enabled: !!id })
  const running = useRunningTimer().data
  const { start, stop } = useTimerActions()
  const now = useNow()
  const [log, setLog] = useState({ hours: '', note: '' })
  const [removing, setRemoving] = useState(false)
  const [oneAssignee, setOneAssignee] = useState(false)  // a task needs at least one person
  const t = task.data
  // who this person may give the task to: themselves, their team, or (project owner / team lead) the project's members
  const assignable = useQuery({
    queryKey: ['assignable-users', t?.project_id],
    queryFn: () => api.get<{ can_add_tasks: boolean; items: UserLite[] }>(`/projects/${t!.project_id}/assignable-users`),
    enabled: !!t?.can_edit,
  })
  const fields = useQuery({ queryKey: ['task-fields'], queryFn: () => api.get<{ items: TaskField[] }>('/task-fields'), enabled: !!t?.can_edit })
  const runningHere = !!running && running.task_id === id

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['task', id] })
    qc.invalidateQueries({ queryKey: ['tasks'] })
    qc.invalidateQueries({ queryKey: ['entries'] })
    qc.invalidateQueries({ queryKey: ['comments', id] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const patch = useMutation({ mutationFn: (body: Record<string, unknown>) => api.patch(`/tasks/${id}`, { ...body, expected_updated_at: t?.updated_at }), onSuccess: refresh, onError: refresh })
  const reassign = useMutation({ mutationFn: (userIds: string[]) => api.put(`/tasks/${id}/assignees`, { user_ids: userIds, expected_updated_at: t?.updated_at }), onSuccess: refresh, onError: refresh })
  const logTime = useMutation({
    mutationFn: () => api.post('/time-entries', { task_id: id, hours: durationHours(log.hours), entry_date: today(), note: log.note }),
    onSuccess: () => { setLog({ hours: '', note: '' }); refresh() },
  })

  const pct = t?.eta_hours ? Math.min(100, (t.actual_hours / t.eta_hours) * 100) : 0
  const over = !!t?.eta_hours && t.actual_hours > t.eta_hours
  const select = { fontSize: 14, '& .MuiSelect-select': { py: 0.75 } }

  return (
    <Drawer anchor="right" open={!!id} onClose={onClose} PaperProps={{ sx: { width: { xs: '100%', md: 'min(1040px, 94vw)' }, bgcolor: '#fff' } }}>
      {t && (
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {/* header */}
          <Stack direction="row" alignItems="flex-start" spacing={1.5} sx={{ px: 3, py: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}>
                <StatusChip status={t.status} />
                <Typography variant="caption" color="text.secondary">{t.project_name} · {t.activity_type}</Typography>
                {t.overdue && <Typography variant="caption" color="error" sx={{ fontWeight: 800 }}>OVERDUE</Typography>}
              </Stack>
              <Typography variant="h5" sx={{ wordBreak: 'break-word' }}>{t.title}</Typography>
            </Box>
            {t.can_edit && <Button variant="outlined" size="small" onClick={() => onEdit(t)}>Edit</Button>}
            <IconButton onClick={onClose} aria-label="Close"><CloseIcon /></IconButton>
          </Stack>

          <Box sx={{ flex: 1, display: 'flex', minHeight: 0, flexDirection: { xs: 'column', md: 'row' }, overflowY: { xs: 'auto', md: 'hidden' } }}>
            {/* main column */}
            <Box sx={{ flex: 1, minWidth: 0, p: 3, overflowY: { md: 'auto' } }}>
              <Typography variant="overline" color="text.secondary">Description</Typography>
              <Paper sx={{ p: 2, mb: 3, bgcolor: '#fcfcfd' }}>
                {t.description ? <Markdown text={t.description} /> : <Typography variant="body2" color="text.secondary">No description.</Typography>}
              </Paper>
              <Activity taskId={t.id} done={t.status === 'done'} canEdit={!!t.can_edit} onChanged={refresh} />
            </Box>

            {/* sidebar */}
            <Box sx={{ width: { md: 320 }, flexShrink: 0, borderLeft: { md: '1px solid' }, borderTop: { xs: '1px solid', md: 'none' }, borderColor: 'divider', bgcolor: '#fafbfd', p: 2.5, overflowY: { md: 'auto' } }}>
              <Stack spacing={2.5} divider={<Divider flexItem />}>
                <Box>
                  <SideLabel>Status</SideLabel>
                  <Select fullWidth size="small" value={t.status} disabled={!t.can_edit || patch.isPending} onChange={(e) => patch.mutate({ status: e.target.value })} sx={select} inputProps={{ 'aria-label': 'Status' }}
                    renderValue={(v) => <Stack direction="row" spacing={1} alignItems="center"><Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: STATUS_COLORS[v] }} /><span>{STATUS_LABELS[v]}</span></Stack>}>
                    {Object.entries(STATUS_LABELS).map(([k, v]) => (
                      <MenuItem key={k} value={k}><Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: STATUS_COLORS[k], mr: 1.25 }} />{v}</MenuItem>
                    ))}
                  </Select>
                  {patch.error && <Alert severity="error" sx={{ mt: 1 }}>{errorMessage(patch.error)}</Alert>}
                </Box>

                <Box>
                  <SideLabel>Assignees</SideLabel>
                  {t.can_edit && assignable.data ? (
                    <>
                      <Autocomplete
                        multiple size="small" disableClearable options={[...assignable.data.items, ...t.assignees.filter((a) => !assignable.data!.items.some((u) => u.id === a.id)).map((a) => ({ id: a.id, name: a.name, email: '' }))]}
                        value={t.assignees.map((a) => ({ id: a.id, name: a.name, email: '' }))} disabled={reassign.isPending}
                        getOptionLabel={(u) => u.name} isOptionEqualToValue={(a, b) => a.id === b.id}
                        onChange={(_, v) => { if (v.length === 0) { setOneAssignee(true); return } setOneAssignee(false); reassign.mutate(v.map((u) => u.id)) }}
                        renderInput={(p) => <TextField {...p} placeholder="Add people" inputProps={{ ...p.inputProps, 'aria-label': 'Assignees' }} />}
                      />
                      <Typography variant="caption" color={oneAssignee ? 'error' : 'text.secondary'} sx={{ display: 'block', mt: 0.5 }}>
                        {oneAssignee ? 'A task needs at least one person.' : assignable.data.items.length > 1 ? 'You can add or remove people.' : 'You can assign tasks to yourself.'}
                      </Typography>
                      {reassign.error && <Alert severity="error" sx={{ mt: 1 }}>{errorMessage(reassign.error)}</Alert>}
                    </>
                  ) : <Stack spacing={0.75}>{t.assignees.map((a) => <Person key={a.id} name={a.name} />)}</Stack>}
                </Box>

                <Box>
                  <SideLabel>Priority</SideLabel>
                  {t.can_edit ? (
                    <Select fullWidth size="small" value={t.priority} onChange={(e) => patch.mutate({ priority: e.target.value })} sx={{ ...select, '& .MuiSelect-select': { py: 0.75, textTransform: 'capitalize' } }} inputProps={{ 'aria-label': 'Priority' }}>
                      {PRIORITIES.map((p) => <MenuItem key={p} value={p} sx={{ textTransform: 'capitalize' }}>{p}</MenuItem>)}
                    </Select>
                  ) : <PriorityChip priority={t.priority} />}
                </Box>

                <Box>
                  <SideLabel>Activity type</SideLabel>
                  {t.can_edit ? (
                    <Select fullWidth size="small" value={t.activity_type} disabled={patch.isPending} onChange={(e) => patch.mutate({ activity_type: e.target.value })} sx={select} inputProps={{ 'aria-label': 'Activity type' }}>
                      {[...new Set([t.activity_type, ...(fields.data?.items.find((f) => f.key === 'activity_type')?.options ?? [])])].map((a) => <MenuItem key={a} value={a}>{a}</MenuItem>)}
                    </Select>
                  ) : <Typography variant="body2">{t.activity_type}</Typography>}
                </Box>

                <Box>
                  <SideLabel>Start date</SideLabel>
                  {t.can_edit ? (
                    <TextField fullWidth size="small" type="date" value={t.start_date ?? ''} onChange={(e) => patch.mutate({ start_date: e.target.value || null })} inputProps={{ 'aria-label': 'Start date', max: t.due_date ?? undefined }} />
                  ) : <Typography variant="body2">{fmtDate(t.start_date)}</Typography>}
                </Box>

                <Box>
                  <SideLabel>Due date</SideLabel>
                  {t.can_edit ? (
                    <TextField fullWidth size="small" type="date" value={t.due_date ?? ''} onChange={(e) => patch.mutate({ due_date: e.target.value || null })} inputProps={{ 'aria-label': 'Due date' }} />
                  ) : <Typography variant="body2" color={t.overdue ? 'error' : 'text.primary'} sx={{ fontWeight: t.overdue ? 700 : 400 }}>{fmtDate(t.due_date)}</Typography>}
                </Box>

                <Box>
                  <SideLabel>Time tracking</SideLabel>
                  <Typography variant="body2" sx={{ mb: 0.75 }}><b>{hours(t.actual_hours)}</b> spent{t.eta_hours != null ? <> of <b>{hours(t.eta_hours)}</b> estimate</> : ' · no estimate'}</Typography>
                  {t.eta_hours ? <LinearProgress variant="determinate" value={pct} color={over ? 'error' : 'primary'} sx={{ height: 7, borderRadius: 4, mb: 1.5 }} /> : null}
                  {over && <Typography variant="caption" color="error" sx={{ display: 'block', mb: 1 }}>{hours(t.actual_hours - (t.eta_hours ?? 0))} over the estimate</Typography>}

                  {t.status === 'done' && <Alert severity="info" sx={{ mb: 1 }}>This task is done. Reopen it to log time or start a timer.</Alert>}
                  {canLog && t.assignees.length > 0 && t.status !== 'done' && (
                    <>
                      {/* the side panel is narrow: let the text and the button wrap onto their own lines instead of squeezing each other */}
                      <Paper sx={{ p: 1.25, mt: 1, mb: 1.5, display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 1, '& .MuiButton-root': { whiteSpace: 'nowrap', flexShrink: 0 }, bgcolor: runningHere ? '#fff5f5' : '#fff', borderColor: runningHere ? '#ffc9c9' : undefined }}>
                        {runningHere && running?.started_at ? (
                          <>
                            <Box><Typography variant="caption" color="error" sx={{ fontWeight: 700 }}>TIMER RUNNING</Typography><Typography variant="h6" sx={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1.2 }}>{elapsed(running.started_at, now)}</Typography></Box>
                            <Button variant="contained" color="error" size="small" startIcon={<StopIcon />} disabled={stop.isPending} onClick={() => stop.mutate(running.id)}>Stop timer</Button>
                          </>
                        ) : running ? (
                          <>
                            <Typography variant="caption">Timer already running on <b>{running.task_title}</b></Typography>
                            <Button variant="outlined" color="error" size="small" startIcon={<StopIcon />} disabled={stop.isPending} onClick={() => stop.mutate(running.id)}>Stop it</Button>
                          </>
                        ) : (
                          <>
                            <Typography variant="caption" color="text.secondary">Track time as you work</Typography>
                            <Button variant="contained" size="small" startIcon={<PlayArrowIcon />} disabled={start.isPending} onClick={() => start.mutate(id!)}>Start timer</Button>
                          </>
                        )}
                      </Paper>
                      {(start.error || stop.error) && <Alert severity="error" sx={{ mb: 1 }}>{errorMessage(start.error ?? stop.error)}</Alert>}
                      <Typography variant="caption" color="text.secondary">Log time manually</Typography>
                      <Box sx={{ display: 'grid', gridTemplateColumns: '120px minmax(0, 1fr)', gap: 0.75, mt: 0.75 }}>
                        <DurationField value={log.hours} onChange={(v) => setLog({ ...log, hours: v })} />
                        <TextField size="small" label="Note" value={log.note} onChange={(e) => setLog({ ...log, note: e.target.value })} />
                        <Button variant="contained" size="small" sx={{ gridColumn: '1 / -1' }} disabled={durationHours(log.hours) === null || logTime.isPending} onClick={() => logTime.mutate()}>Add time</Button>
                      </Box>
                      {logTime.error && <Alert severity="error" sx={{ mt: 1 }}>{errorMessage(logTime.error)}</Alert>}
                    </>
                  )}
                </Box>

                <Box>
                  <SideLabel>Time entries</SideLabel>
                  {entries.data?.items.length ? entries.data.items.map((e) => (
                    <Stack key={e.id} direction="row" justifyContent="space-between" sx={{ py: 0.5 }}>
                      <Typography variant="caption" sx={{ pr: 1 }}>{e.user_name} · {fmtDate(e.entry_date)}{e.started_at && e.stopped_at ? ` · ${clock(e.started_at)}–${clock(e.stopped_at)}` : ''}{e.note ? ` · ${e.note}` : ''}</Typography>
                      <Typography variant="caption" sx={{ fontWeight: 700 }}>{e.running ? 'running' : hours(e.hours)}</Typography>
                    </Stack>
                  )) : <Typography variant="caption" color="text.secondary">No time logged yet.</Typography>}
                </Box>

                <Box>
                  <SideLabel>Details</SideLabel>
                  <Stack spacing={0.75}>
                    {[['Project', t.project_name], ['Team', t.team_name ?? '—'],
                      ...Object.entries(t.custom_fields).map(([k, v]) => [k.replace(/_/g, ' '), String(v)])].map(([k, v]) => (
                      <Stack key={k} direction="row" justifyContent="space-between"><Typography variant="caption" color="text.secondary" sx={{ textTransform: 'capitalize' }}>{k}</Typography><Typography variant="caption" sx={{ fontWeight: 600 }}>{v}</Typography></Stack>
                    ))}
                  </Stack>
                </Box>

                {t.can_delete && (
                  <Box>
                    <Button color="error" startIcon={<DeleteIcon fontSize="small" />} onClick={() => setRemoving(true)}>Delete task</Button>
                  </Box>
                )}
              </Stack>
            </Box>
          </Box>
        </Box>
      )}
      {removing && t && (
        <DeleteDialog title="Delete this task?" description={`“${t.title}” is removed with its comments and logged time (${hours(t.actual_hours)}). This cannot be undone.`} path={`/tasks/${t.id}`}
          onClose={() => setRemoving(false)} onDeleted={() => { qc.invalidateQueries({ queryKey: ['tasks'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }); qc.invalidateQueries({ queryKey: ['entries'] }); onClose() }} />
      )}
    </Drawer>
  )
}

