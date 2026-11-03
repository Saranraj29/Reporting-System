import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { today } from '../format'
import type { DailyStatus, Page } from '../types'

export function DailyStatusForm({ onSaved }: { onSaved?: () => void }) {
  const qc = useQueryClient()
  const { me } = useAuth()
  const d = today()
  const existing = useQuery({
    queryKey: ['daily-status', 'today'],
    queryFn: () => api.get<Page<DailyStatus>>('/daily-status', { from: d, to: d, user: me?.id, limit: 200 }),
  })
  const [form, setForm] = useState({ did_today: '', next_up: '', blockers: '' })
  useEffect(() => {
    const row = existing.data?.items.find((s) => s.user_id === me?.id)
    if (row) setForm({ did_today: row.did_today, next_up: row.next_up, blockers: row.blockers })
  }, [existing.data, me?.id])
  const save = useMutation({
    mutationFn: () => api.put<DailyStatus>(`/daily-status/${d}`, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['daily-status'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      onSaved?.()
    },
  })
  return (
    <Stack spacing={2}>
      <TextField label="What did you do today?" multiline minRows={3} value={form.did_today} onChange={(e) => setForm({ ...form, did_today: e.target.value })} fullWidth />
      <TextField label="What's next up?" multiline minRows={2} value={form.next_up} onChange={(e) => setForm({ ...form, next_up: e.target.value })} fullWidth />
      <TextField label="Any blockers?" multiline minRows={2} value={form.blockers} onChange={(e) => setForm({ ...form, blockers: e.target.value })} fullWidth />
      {save.error && <Alert severity="error">{errorMessage(save.error)}</Alert>}
      {save.isSuccess && <Alert severity="success">Saved. You can keep editing until midnight.</Alert>}
      <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>
        Save status
      </Button>
    </Stack>
  )
}

export function DailyStatusDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Daily status</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          One entry per day, editable until midnight in your company's timezone.
        </Typography>
        <DailyStatusForm onSaved={onClose} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}
