import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import NightsStayIcon from '@mui/icons-material/NightsStayOutlined'
import WbSunnyIcon from '@mui/icons-material/WbSunnyOutlined'
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, Paper, Stack, TextField, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { ModalTitle, keepOpen } from './ui'
import { useAuth } from '../auth'
import { clock, today } from '../format'
import type { DailyStatus, Page } from '../types'

type Which = 'morning' | 'eod'

/** Two check-ins a day: the morning plan and the end-of-day update. Each one is timestamped the first time it is posted
 *  and stays editable until midnight (company timezone). */
export function DailyStatusForm({ onSaved }: { onSaved?: () => void }) {
  const qc = useQueryClient()
  const { me } = useAuth()
  const d = today()
  const existing = useQuery({
    queryKey: ['daily-status', 'today'],
    queryFn: () => api.get<Page<DailyStatus>>('/daily-status', { from: d, to: d, user: me?.id, limit: 200 }),
  })
  const row = existing.data?.items.find((s) => s.user_id === me?.id)
  const [form, setForm] = useState({ plan_today: '', did_today: '', next_up: '', blockers: '' })
  const [saved, setSaved] = useState<Which | null>(null)
  useEffect(() => {
    if (row) setForm({ plan_today: row.plan_today, did_today: row.did_today, next_up: row.next_up, blockers: row.blockers })
  }, [row?.id, row?.updated_at]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (_which: Which) => api.put<DailyStatus>(`/daily-status/${d}`, form),
    onSuccess: (_r, which) => {
      setSaved(which)
      qc.invalidateQueries({ queryKey: ['daily-status'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      onSaved?.()
    },
  })
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => { setForm({ ...form, [k]: e.target.value }); setSaved(null) }
  const posted = (at?: string | null) => at ? <Chip size="small" color="success" icon={<CheckCircleIcon />} label={`Posted ${clock(at)}`} /> : <Chip size="small" variant="outlined" label="Not posted yet" />

  return (
    <Stack spacing={2}>
      <Paper sx={{ p: 2, borderColor: row?.morning_at ? '#b2f2bb' : undefined }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.25 }}>
          <Stack direction="row" spacing={1} alignItems="center"><WbSunnyIcon color="warning" fontSize="small" /><Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Morning check-in</Typography></Stack>
          {posted(row?.morning_at)}
        </Stack>
        <TextField label="What will you work on today?" multiline minRows={2} value={form.plan_today} onChange={set('plan_today')} fullWidth />
        <Button sx={{ mt: 1.25 }} variant={row?.morning_at ? 'outlined' : 'contained'} size="small" disabled={save.isPending || !form.plan_today.trim()} onClick={() => save.mutate('morning')}>
          {row?.morning_at ? 'Update morning plan' : 'Save morning plan'}
        </Button>
        {saved === 'morning' && <Alert severity="success" sx={{ mt: 1.25 }}>Saved. You can keep editing until midnight.</Alert>}
      </Paper>

      <Paper sx={{ p: 2, borderColor: row?.eod_at ? '#b2f2bb' : undefined }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.25 }}>
          <Stack direction="row" spacing={1} alignItems="center"><NightsStayIcon color="primary" fontSize="small" /><Typography variant="subtitle2" sx={{ fontWeight: 700 }}>End-of-day update</Typography></Stack>
          {posted(row?.eod_at)}
        </Stack>
        <Stack spacing={1.5}>
          <TextField label="What did you do today?" multiline minRows={2} value={form.did_today} onChange={set('did_today')} fullWidth />
          <TextField label="What's next up?" multiline minRows={2} value={form.next_up} onChange={set('next_up')} fullWidth />
        </Stack>
        <Button sx={{ mt: 1.25 }} variant={row?.eod_at ? 'outlined' : 'contained'} size="small" disabled={save.isPending || !form.did_today.trim()} onClick={() => save.mutate('eod')}>
          {row?.eod_at ? 'Update end-of-day' : 'Save end-of-day update'}
        </Button>
        {saved === 'eod' && <Alert severity="success" sx={{ mt: 1.25 }}>Saved. You can keep editing until midnight.</Alert>}
      </Paper>

      <Box>
        <TextField label="Any blockers?" helperText="Shared by both check-ins — shown to your lead and on the dashboard" multiline minRows={2} value={form.blockers} onChange={set('blockers')} fullWidth />
        <Button sx={{ mt: 1 }} size="small" variant="text" disabled={save.isPending || (!row && !form.plan_today.trim() && !form.did_today.trim())} onClick={() => save.mutate(row?.eod_at ? 'eod' : 'morning')}>Save blockers</Button>
      </Box>
      {save.error && <Alert severity="error">{errorMessage(save.error)}</Alert>}
    </Stack>
  )
}

export function DailyStatusDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={keepOpen(onClose)} fullWidth maxWidth="sm">
      <ModalTitle onClose={onClose}>Daily check-in</ModalTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          One entry per day with two check-ins — morning plan and end-of-day update — editable until midnight in your company's timezone.
        </Typography>
        <DailyStatusForm />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}
