import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import CloseIcon from '@mui/icons-material/Close'
import InfoIcon from '@mui/icons-material/InfoOutlined'
import SendIcon from '@mui/icons-material/Send'
import ThumbDownIcon from '@mui/icons-material/ThumbDownAltOutlined'
import ThumbUpIcon from '@mui/icons-material/ThumbUpAltOutlined'
import { Box, Button, Chip, Collapse, Drawer, IconButton, Paper, Stack, TextField, Typography, useMediaQuery, useTheme } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, errorMessage, streamPost } from '../api'
import type { AssistantMessage, AssistantStatus, SourcesCard } from '../types'

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

function Bubble({ m, onVote }: { m: AssistantMessage; onVote: (id: string, rating: 'up' | 'down') => void }) {
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
      {!mine && m.id && (
        <Stack direction="row" spacing={0.5} sx={{ mt: 0.25 }}>
          <IconButton size="small" aria-label="Helpful answer" onClick={() => onVote(m.id!, 'up')}><ThumbUpIcon fontSize="inherit" /></IconButton>
          <IconButton size="small" aria-label="Not helpful" onClick={() => onVote(m.id!, 'down')}><ThumbDownIcon fontSize="inherit" /></IconButton>
        </Stack>
      )}
    </Box>
  )
}

export function AssistantPanel({ open, onClose, returnFocus }: { open: boolean; onClose: () => void; returnFocus?: () => void }) {
  const theme = useTheme()
  const mobile = useMediaQuery(theme.breakpoints.down('sm'))
  const wide = useMediaQuery(theme.breakpoints.up('md'))
  const { pathname } = useLocation()
  const page = pageKey(pathname)
  const status = useQuery({ queryKey: ['assistant-status', page], queryFn: () => api.get<AssistantStatus>('/assistant/status', { page }), enabled: open, staleTime: 15000 })
  const [thread, setThread] = useState<AssistantMessage[]>([])
  const [conv, setConv] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [live, setLive] = useState('')
  const [input, setInput] = useState('')
  const [err, setErr] = useState('')
  const loaded = useRef(false)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (status.data && !loaded.current) {
      loaded.current = true
      setThread(status.data.messages)
      setConv(status.data.conversation_id)
    }
  }, [status.data])
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }) }, [thread, progress])

  const send = async (body: { message?: string; quick_action?: string }, shown: string) => {
    if (busy) return
    setBusy(true)
    setErr('')
    setInput('')
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
        if (name === 'done') { reply.id = data.message_id; setConv(data.conversation_id); push() }
        if (name === 'error') { reply.error = data.message; setProgress(''); push() }
      })
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
      setProgress('')
    }
  }

  const vote = (id: string, rating: 'up' | 'down') => { api.post(`/assistant/messages/${id}/feedback`, { rating }).catch(() => undefined) }
  const st = status.data
  const chip = busy ? { label: 'Thinking', fg: '#0b5cad' } : st?.status === 'unavailable' ? { label: 'Unavailable', fg: '#8a4b00' } : { label: 'Ready', fg: '#1b6e3a' }  // dark text colours: 4.5:1 on white
  const cards = st?.cards ?? []

  if (!open) return null  // nothing in the page while closed; the conversation lives in this component's state
  return (
    <Drawer anchor="right" variant={wide ? 'persistent' : 'temporary'} open={open} onClose={() => { onClose(); returnFocus?.() }}
      PaperProps={{ component: 'aside', 'aria-label': 'AI assistant', role: 'complementary', sx: { width: mobile ? '100%' : ASSISTANT_WIDTH, borderLeft: '1px solid', borderColor: 'divider', bgcolor: 'background.default' }, onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'Escape') { onClose(); returnFocus?.() } } } as any}>
      <Stack sx={{ height: '100%' }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}>
          <AutoAwesomeIcon color="primary" />
          <Typography variant="subtitle1" sx={{ fontWeight: 700, flex: 1 }}>AI Assistant</Typography>
          <Chip size="small" label={chip.label} variant="outlined" role="status" sx={{ color: chip.fg, borderColor: chip.fg, fontWeight: 600 }} />
          <IconButton size="small" onClick={() => { onClose(); returnFocus?.() }} aria-label="Close assistant"><CloseIcon fontSize="small" /></IconButton>
        </Stack>
        <Stack spacing={1.5} sx={{ flex: 1, overflowY: 'auto', p: 2 }}>
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
          {cards.length > 0 && thread.length > 0 && (
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
              {cards.filter((c) => c.enabled).map((c) => <Chip key={c.id} size="small" label={c.title} onClick={() => send({ quick_action: c.id }, c.title)} disabled={busy} variant="outlined" />)}
            </Stack>
          )}
          <Stack spacing={1.25} aria-label="Conversation">
            {thread.map((m, i) => <Bubble key={m.id ?? i} m={m} onVote={vote} />)}
            {progress && <Typography variant="caption" color="text.secondary" sx={{ pl: 0.5 }}>{progress}</Typography>}
          </Stack>
          <div ref={end} />
        </Stack>
        <Box aria-live="polite" sx={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>{live}</Box>
        <Box sx={{ p: 2, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}>
          {err && <Typography variant="caption" color="error" role="alert" sx={{ display: 'block', mb: 0.5 }}>{err}</Typography>}
          <Stack direction="row" spacing={1} alignItems="flex-end">
            <TextField fullWidth size="small" multiline maxRows={4} value={input} disabled={!st?.input_enabled || busy} onChange={(e) => setInput(e.target.value)}
              placeholder={st?.input_enabled ? 'Ask your assistant anything…' : 'Free questions are unavailable'} inputProps={{ 'aria-label': 'Ask your assistant anything' }}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (input.trim().length > 1) send({ message: input }, input.trim()) } }} />
            <IconButton color="primary" aria-label="Send" disabled={!st?.input_enabled || busy || input.trim().length < 2} onClick={() => send({ message: input }, input.trim())}><SendIcon /></IconButton>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>Answers use only data you can see.</Typography>
        </Box>
      </Stack>
    </Drawer>
  )
}
