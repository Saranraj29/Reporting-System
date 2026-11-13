import AddCommentIcon from '@mui/icons-material/AddCommentOutlined'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/DeleteOutline'
import EditIcon from '@mui/icons-material/EditOutlined'
import HistoryIcon from '@mui/icons-material/History'
import InfoIcon from '@mui/icons-material/InfoOutlined'
import SendIcon from '@mui/icons-material/Send'
import ThumbDownFilledIcon from '@mui/icons-material/ThumbDownAlt'
import ThumbDownIcon from '@mui/icons-material/ThumbDownAltOutlined'
import ThumbUpFilledIcon from '@mui/icons-material/ThumbUpAlt'
import ThumbUpIcon from '@mui/icons-material/ThumbUpAltOutlined'
import { Box, Button, Chip, Collapse, Dialog, DialogActions, DialogContent, DialogContentText, Drawer, IconButton, Paper, Stack, TextField, Tooltip, Typography, useMediaQuery, useTheme } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api, errorMessage, streamPost } from '../api'
import { ModalTitle, keepOpen } from './ui'
import { groupConversations, makeTitle } from '../assistantHistory'
import type { AssistantConversation, AssistantMessage, AssistantStatus, SourcesCard } from '../types'

export const ASSISTANT_WIDTH = 380
const PAGES: Record<string, string> = { '/': 'dashboard', '/tasks': 'tasks', '/my-day': 'my-day', '/check-ins': 'check-ins' }
const UNAVAILABLE: Record<string, string> = {
  off: 'The assistant is switched off for your company. The app works as normal.',
  not_configured: 'Free questions need the AI service, which is not connected. The quick actions still work.',
  provider_down: 'The AI service is not answering right now. The quick actions still work.',
}

export function pageKey(path: string): string {
  return PAGES[path] ?? (path.startsWith('/ai-reports') ? 'ai-reports' : 'other')
}

function Sources({ card }: { card: SourcesCard }) {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  return (
    <Paper variant="outlined" sx={{ mt: 1, p: 1.25, bgcolor: 'action.hover' }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography variant="caption" sx={{ fontWeight: 700 }}>Where this comes from</Typography>
        <Button size="small" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? 'Hide' : 'Show'}</Button>
      </Stack>
      <Collapse in={open}>
        {card.sources.map((s) => (
          <Box key={s.label} sx={{ mt: 0.5 }}>
            <Typography variant="caption" color="text.secondary">
              {s.label} · {s.returned === s.total ? `${s.total} rows` : `${s.returned} of ${s.total} rows`}{s.as_of ? ` · as of ${new Date(s.as_of).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}` : ''}
            </Typography>
            <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
              {s.items.map((i, k) => <li key={`${i.id}${k}`}><Typography variant="caption">{i.title}</Typography></li>)}
            </Box>
          </Box>
        ))}
      </Collapse>
      {card.handoff && (
        <Button size="small" variant="outlined" sx={{ mt: 1 }} onClick={() => nav(`${card.handoff!.path}?days=${card.handoff!.days ?? 7}&projects=${card.handoff!.project_ids.join(',')}`)}>{card.handoff.label}</Button>
      )}
    </Paper>
  )
}

export type Vote = (id: string, rating: 'up' | 'down', reason?: string) => Promise<void>
const REASONS = ['Wrong or missing numbers', 'Not what I asked', 'Hard to understand', 'Something else']

/** Thumbs under an answer. The chosen thumb lights up, a short thank-you confirms it, and a thumbs-down asks (optionally) what was wrong. */
export function Feedback({ m, onVote }: { m: AssistantMessage; onVote: Vote }) {
  const [rating, setRating] = useState<'up' | 'down' | null>(m.rating ?? null)
  const [asking, setAsking] = useState(false)  // the "what was wrong?" choices after a thumbs-down
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const send = async (r: 'up' | 'down', why?: string) => {
    setBusy(true); setFailed(false)
    try {
      await onVote(m.id!, r, why)
      setRating(r)
      setNote(r === 'up' ? 'Thanks for the feedback.' : why ? 'Thanks, this helps us improve.' : '')
      setAsking(r === 'down' && !why)
    } catch {
      setFailed(true); setNote('Could not save your feedback. Try again.')
    } finally {
      setBusy(false)
    }
  }
  const choose = (r: 'up' | 'down') => {
    if (r === rating) { if (r === 'down') setAsking(true); return }  // already chosen: nothing to send (a second thumbs-down must not wipe the reason)
    void send(r)
  }
  return (
    <Box sx={{ mt: 0.25 }}>
      <Stack direction="row" spacing={0.5} alignItems="center">
        <IconButton size="small" aria-label="Helpful answer" aria-pressed={rating === 'up'} disabled={busy} color={rating === 'up' ? 'primary' : 'default'} onClick={() => choose('up')}>
          {rating === 'up' ? <ThumbUpFilledIcon fontSize="inherit" /> : <ThumbUpIcon fontSize="inherit" />}
        </IconButton>
        <IconButton size="small" aria-label="Not helpful" aria-pressed={rating === 'down'} disabled={busy} color={rating === 'down' ? 'error' : 'default'} onClick={() => choose('down')}>
          {rating === 'down' ? <ThumbDownFilledIcon fontSize="inherit" /> : <ThumbDownIcon fontSize="inherit" />}
        </IconButton>
        <Typography variant="caption" role="status" color={failed ? 'error' : 'text.secondary'}>{note}</Typography>
      </Stack>
      {asking && (
        <Box sx={{ mt: 0.5 }}>
          <Typography variant="caption" color="text.secondary">What was wrong? (optional)</Typography>
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
            {REASONS.map((r) => <Chip key={r} size="small" variant="outlined" label={r} disabled={busy} onClick={() => void send('down', r)} />)}
          </Stack>
        </Box>
      )}
    </Box>
  )
}

function Bubble({ m, onVote }: { m: AssistantMessage; onVote: Vote }) {
  const mine = m.role === 'user'
  const lines = m.sentences ?? (m.text ? m.text.split('\n') : [])
  return (
    <Box sx={{ alignSelf: mine ? 'flex-end' : 'flex-start', maxWidth: '92%' }}>
      <Paper elevation={0} sx={{ p: 1.5, bgcolor: mine ? 'primary.main' : 'background.paper', color: mine ? 'primary.contrastText' : 'text.primary', border: mine ? 0 : '1px solid', borderColor: 'divider', borderRadius: 2 }}>
        {mine ? <Typography variant="body2">{m.text}</Typography> : lines.map((l, i) => {
          const s = typeof l === 'string' ? { text: l, grounded: true } : l
          return (
            <Typography key={i} variant="body2" sx={{ mb: i < lines.length - 1 ? 0.75 : 0, display: 'flex', gap: 0.5, alignItems: 'flex-start', color: s.grounded ? 'inherit' : 'warning.dark' }}>
              {!s.grounded && <InfoIcon fontSize="inherit" sx={{ mt: '3px' }} aria-label="Not confirmed" />}
              <span>{s.text}</span>
            </Typography>
          )
        })}
        {m.error && <Typography variant="body2" color="error">{m.error}</Typography>}
      </Paper>
      {!mine && m.card && <Sources card={m.card} />}
      {!mine && m.id && <Feedback m={m} onVote={onVote} />}
    </Box>
  )
}

/** The person's earlier chats: grouped by day, reopen one, rename it, delete it (one or all). Chats are private to the person and kept for 30 days. */
function HistoryView({ current, onOpen, onNew, onDeleted }: { current: string | null; onOpen: (id: string) => void; onNew: () => void; onDeleted: (id: string | null) => void }) {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['assistant-conversations'], queryFn: () => api.get<{ items: AssistantConversation[] }>('/assistant/conversations'), staleTime: 0 })
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null)
  const [confirm, setConfirm] = useState<{ id: string | null; title: string } | null>(null)  // id null = every chat
  const refresh = () => qc.invalidateQueries({ queryKey: ['assistant-conversations'] })
  const rename = useMutation({
    mutationFn: (v: { id: string; title: string }) => api.patch(`/assistant/conversations/${v.id}`, { title: v.title }),
    onSuccess: () => { setRenaming(null); refresh() },
  })
  const remove = useMutation({
    mutationFn: (id: string | null) => (id ? api.del(`/assistant/conversations/${id}`) : api.del('/assistant/conversations')),
    onSuccess: (_, id) => { onDeleted(id); setConfirm(null); refresh() },
  })
  const items = list.data?.items ?? []
  const groups = groupConversations(items)
  const when = (iso: string) => {
    const d = new Date(iso)
    return d.toDateString() === new Date().toDateString() ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString([], { day: 'numeric', month: 'short' })
  }
  return (
    <Stack spacing={1.5}>
      <Button variant="outlined" startIcon={<AddCommentIcon />} onClick={onNew}>New chat</Button>
      {list.isLoading && <Typography variant="body2" color="text.secondary">Loading…</Typography>}
      {!list.isLoading && items.length === 0 && <Typography variant="body2" color="text.secondary">No chats yet. Ask something and it will show up here.</Typography>}
      {groups.map((g) => (
        <Box key={g.label} component="section" aria-label={g.label}>
          <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.06em' }}>{g.label}</Typography>
          <Stack component="ul" sx={{ listStyle: 'none', m: 0, p: 0, mt: 0.5 }} spacing={0.5}>
            {g.items.map((c) => (
              <Paper key={c.id} component="li" variant="outlined" sx={{ display: 'flex', alignItems: 'center', gap: 0.5, pr: 0.5, bgcolor: c.id === current ? 'action.selected' : 'background.paper' }}>
                {renaming?.id === c.id ? (
                  <Stack direction="row" spacing={0.5} sx={{ p: 0.75, flex: 1 }}>
                    <TextField autoFocus size="small" fullWidth value={renaming.title} inputProps={{ maxLength: 80, 'aria-label': 'Chat name' }} onChange={(e) => setRenaming({ id: c.id, title: e.target.value })}
                      onKeyDown={(e) => { if (e.key === 'Enter' && renaming.title.trim()) rename.mutate({ id: c.id, title: renaming.title }); if (e.key === 'Escape') { e.stopPropagation(); setRenaming(null) } }} />
                    <IconButton size="small" color="primary" aria-label="Save name" disabled={!renaming.title.trim() || rename.isPending} onClick={() => rename.mutate({ id: c.id, title: renaming.title })}><CheckIcon fontSize="small" /></IconButton>
                    <IconButton size="small" aria-label="Cancel rename" onClick={() => setRenaming(null)}><CloseIcon fontSize="small" /></IconButton>
                  </Stack>
                ) : (
                  <>
                    <Box component="button" type="button" onClick={() => onOpen(c.id)} aria-current={c.id === current ? 'true' : undefined}
                      sx={{ flex: 1, minWidth: 0, textAlign: 'left', p: 1.25, border: 0, bgcolor: 'transparent', font: 'inherit', color: 'inherit', cursor: 'pointer' }}>
                      <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{c.title}</Typography>
                      <Typography variant="caption" color="text.secondary">{when(c.updated_at)} · {Math.ceil(c.message_count / 2)} {Math.ceil(c.message_count / 2) === 1 ? 'question' : 'questions'}</Typography>
                    </Box>
                    <Tooltip title="Rename"><IconButton size="small" aria-label={`Rename ${c.title}`} onClick={() => setRenaming({ id: c.id, title: c.title })}><EditIcon fontSize="small" /></IconButton></Tooltip>
                    <Tooltip title="Delete"><IconButton size="small" aria-label={`Delete ${c.title}`} onClick={() => setConfirm({ id: c.id, title: c.title })}><DeleteIcon fontSize="small" /></IconButton></Tooltip>
                  </>
                )}
              </Paper>
            ))}
          </Stack>
        </Box>
      ))}
      <ErrorAlertLine error={rename.error ?? remove.error} />
      {items.length > 0 && <Button color="error" size="small" sx={{ alignSelf: 'flex-start' }} onClick={() => setConfirm({ id: null, title: '' })}>Delete all chats</Button>}
      <Typography variant="caption" color="text.secondary">Chats are visible only to you and are kept for 30 days.</Typography>
      <Dialog open={!!confirm} onClose={keepOpen(() => setConfirm(null))}>
        <ModalTitle onClose={() => setConfirm(null)}>{confirm?.id ? 'Delete this chat?' : 'Delete all chats?'}</ModalTitle>
        <DialogContent><DialogContentText>{confirm?.id ? `“${confirm.title}” and its answers will be removed. This cannot be undone.` : 'Every chat in your history will be removed. This cannot be undone.'}</DialogContentText></DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirm(null)}>Cancel</Button>
          <Button color="error" variant="contained" disabled={remove.isPending} onClick={() => confirm && remove.mutate(confirm.id)}>Delete</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}

function ErrorAlertLine({ error }: { error: unknown }) {
  return error ? <Typography variant="caption" color="error" role="alert">{errorMessage(error)}</Typography> : null
}

export function AssistantPanel({ open, onClose, returnFocus }: { open: boolean; onClose: () => void; returnFocus?: () => void }) {
  const theme = useTheme()
  const qc = useQueryClient()
  const mobile = useMediaQuery(theme.breakpoints.down('sm'))
  const wide = useMediaQuery(theme.breakpoints.up('md'))
  const { pathname } = useLocation()
  const page = pageKey(pathname)
  const status = useQuery({ queryKey: ['assistant-status', page], queryFn: () => api.get<AssistantStatus>('/assistant/status', { page }), enabled: open, staleTime: 15000 })
  const [thread, setThread] = useState<AssistantMessage[]>([])
  const [conv, setConv] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [full, setFull] = useState(false)  // the conversation reached its length cap: only a new chat can go on
  const [view, setView] = useState<'chat' | 'history'>('chat')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [live, setLive] = useState('')
  const [input, setInput] = useState('')
  const [err, setErr] = useState('')
  const loaded = useRef(false)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (status.data && !loaded.current) {
      loaded.current = true  // the server resumes the last chat only if it is recent; otherwise this starts empty
      setThread(status.data.messages)
      setConv(status.data.conversation_id)
      setTitle(status.data.conversation_title ?? '')
    }
  }, [status.data])
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }) }, [thread, progress])

  /** A fresh chat: nothing of the old one (messages, context) goes along. The old one stays in the history. */
  const newChat = () => {
    if (busy) return
    loaded.current = true
    setThread([]); setConv(null); setTitle(''); setFull(false); setErr(''); setInput(''); setProgress(''); setView('chat')
  }
  const openChat = async (id: string) => {
    if (busy) return
    try {
      const d = await api.get<{ id: string; title: string; messages: AssistantMessage[]; full: boolean }>(`/assistant/conversations/${id}`)
      loaded.current = true
      setThread(d.messages); setConv(d.id); setTitle(d.title); setFull(d.full); setErr(''); setProgress('')
    } catch (e) {
      setErr(errorMessage(e))
    }
    setView('chat')
  }

  const send = async (body: { message?: string; quick_action?: string }, shown: string) => {
    if (busy || full) return
    setBusy(true)
    setErr('')
    setInput('')
    const isNew = !conv
    setThread((t) => [...t, { role: 'user', text: shown }])
    const reply: AssistantMessage = { role: 'assistant', text: '', sentences: [] }
    let added = false
    const push = () => setThread((t) => (added ? [...t.slice(0, -1), { ...reply, sentences: [...(reply.sentences ?? [])] }] : (added = true, [...t, { ...reply, sentences: [...(reply.sentences ?? [])] }])))
    try {
      await streamPost('/assistant/chat', { ...body, conversation_id: conv, context: { page } }, ({ name, data }) => {
        if (name === 'status') setProgress(data.text)
        if (name === 'sentence') { reply.sentences!.push(data); setProgress(''); setLive(data.text); push() }
        if (name === 'clarify') { reply.sentences!.push({ text: data.text, grounded: true }); setProgress(''); setLive(data.text); push() }
        if (name === 'card') { reply.card = data; push() }
        if (name === 'done') {
          reply.id = data.message_id; setConv(data.conversation_id); push()
          if (isNew) setTitle(makeTitle(shown))
          qc.invalidateQueries({ queryKey: ['assistant-conversations'] })
        }
        if (name === 'error') { reply.error = data.message; setProgress(''); push() }
      })
    } catch (e) {
      if (e instanceof ApiError && e.code === 'conversation_full') {
        setFull(true)
        setThread((t) => t.slice(0, -1))  // the question was not taken
      }
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
      setProgress('')
    }
  }

  const vote: Vote = async (id, rating, reason) => { await api.post(`/assistant/messages/${id}/feedback`, { rating, reason: reason ?? '' }) }
  const st = status.data
  const chip = busy ? { label: 'Thinking', fg: '#0b5cad' } : st?.status === 'unavailable' ? { label: 'Unavailable', fg: '#8a4b00' } : { label: 'Ready', fg: '#1b6e3a' }  // dark text colours: 4.5:1 on white
  const cards = st?.cards ?? []
  const inHistory = view === 'history'

  if (!open) return null  // nothing in the page while closed; the conversation lives in this component's state
  return (
    <Drawer anchor="right" variant={wide ? 'persistent' : 'temporary'} open={open} onClose={() => { onClose(); returnFocus?.() }}
      PaperProps={{ component: 'aside', 'aria-label': 'AI assistant', role: 'complementary', sx: { width: mobile ? '100%' : ASSISTANT_WIDTH, borderLeft: '1px solid', borderColor: 'divider', bgcolor: 'background.default' }, onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'Escape') { onClose(); returnFocus?.() } } } as any}>
      <Stack sx={{ height: '100%' }}>
        <Stack direction="row" alignItems="center" spacing={0.5} sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}>
          {inHistory
            ? <IconButton size="small" onClick={() => setView('chat')} aria-label="Back to the chat"><ArrowBackIcon fontSize="small" /></IconButton>
            : <AutoAwesomeIcon color="primary" sx={{ mr: 0.5 }} />}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" noWrap sx={{ fontWeight: 700, lineHeight: 1.25 }}>{inHistory ? 'Chat history' : 'AI Assistant'}</Typography>
            {!inHistory && title && <Typography variant="caption" color="text.secondary" noWrap component="div">{title}</Typography>}
          </Box>
          <Chip size="small" label={chip.label} variant="outlined" role="status" sx={{ color: chip.fg, borderColor: chip.fg, fontWeight: 600 }} />
          {!inHistory && (
            <Tooltip title="New chat">
              <span><IconButton size="small" onClick={newChat} disabled={busy || (!conv && thread.length === 0)} aria-label="New chat"><AddCommentIcon fontSize="small" /></IconButton></span>
            </Tooltip>
          )}
          <Tooltip title="Chat history">
            <span><IconButton size="small" onClick={() => setView(inHistory ? 'chat' : 'history')} disabled={busy} aria-label="Chat history" aria-pressed={inHistory}><HistoryIcon fontSize="small" /></IconButton></span>
          </Tooltip>
          <IconButton size="small" onClick={() => { onClose(); returnFocus?.() }} aria-label="Close assistant"><CloseIcon fontSize="small" /></IconButton>
        </Stack>
        <Stack spacing={1.5} sx={{ flex: 1, overflowY: 'auto', p: 2 }}>
          {inHistory ? (
            <HistoryView current={conv} onOpen={openChat} onNew={newChat}
              onDeleted={(id) => { if (id === null || id === conv) newChat() }} />
          ) : (
            <>
              {st?.status === 'unavailable' && st.reason && <Paper variant="outlined" sx={{ p: 1.25 }}><Typography variant="body2" color="text.secondary">{UNAVAILABLE[st.reason]}</Typography></Paper>}
              {cards.length > 0 && !thread.length && (
                <Box>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Want help with this {page === 'check-ins' ? 'day' : 'week'}?</Typography>
                  <Stack spacing={1}>
                    {cards.map((c) => (
                      <Paper key={c.id} variant="outlined" component="button" type="button" disabled={!c.enabled || busy} onClick={() => send({ quick_action: c.id }, c.title)}
                        sx={{ p: 1.25, textAlign: 'left', cursor: c.enabled ? 'pointer' : 'default', opacity: c.enabled ? 1 : 0.55, font: 'inherit', color: 'inherit', bgcolor: 'background.paper', '&:hover': c.enabled ? { borderColor: 'primary.main' } : undefined }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>{c.title}</Typography>
                        <Typography variant="caption" color="text.secondary">{c.enabled ? c.subtitle : 'Coming soon'}</Typography>
                      </Paper>
                    ))}
                  </Stack>
                </Box>
              )}
              {cards.length > 0 && thread.length > 0 && !full && (
                <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                  {cards.filter((c) => c.enabled).map((c) => <Chip key={c.id} size="small" label={c.title} onClick={() => send({ quick_action: c.id }, c.title)} disabled={busy} variant="outlined" />)}
                </Stack>
              )}
              <Stack spacing={1.25} aria-label="Conversation">
                {thread.map((m, i) => <Bubble key={m.id ?? i} m={m} onVote={vote} />)}
                {progress && <Typography variant="caption" color="text.secondary" sx={{ pl: 0.5 }}>{progress}</Typography>}
              </Stack>
              <div ref={end} />
            </>
          )}
        </Stack>
        <Box aria-live="polite" sx={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>{live}</Box>
        {!inHistory && (
          <Box sx={{ p: 2, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}>
            {full && (
              <Paper variant="outlined" sx={{ p: 1.25, mb: 1 }}>
                <Typography variant="body2" sx={{ mb: 0.75 }}>This chat has got long. Start a new chat to keep the answers focused; this one stays in your history.</Typography>
                <Button size="small" variant="contained" startIcon={<AddCommentIcon />} onClick={newChat}>New chat</Button>
              </Paper>
            )}
            {err && !full && <Typography variant="caption" color="error" role="alert" sx={{ display: 'block', mb: 0.5 }}>{err}</Typography>}
            <Stack direction="row" spacing={1} alignItems="flex-end">
              <TextField fullWidth size="small" multiline maxRows={4} value={input} disabled={!st?.input_enabled || busy || full} onChange={(e) => setInput(e.target.value)}
                placeholder={st?.input_enabled ? (conv ? 'Ask a follow-up…' : 'Ask your assistant anything…') : 'Free questions are unavailable'} inputProps={{ 'aria-label': 'Ask your assistant anything' }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (input.trim().length > 1) send({ message: input }, input.trim()) } }} />
              <IconButton color="primary" aria-label="Send" disabled={!st?.input_enabled || busy || full || input.trim().length < 2} onClick={() => send({ message: input }, input.trim())}><SendIcon /></IconButton>
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>Answers use only data you can see.</Typography>
          </Box>
        )}
      </Stack>
    </Drawer>
  )
}
