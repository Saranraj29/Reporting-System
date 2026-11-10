import { Button, Paper, Stack, TextField, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { fmtDate, isoDay } from '../format'
import type { TimeOff } from '../types'
import { ErrorAlert } from './ui'

/** A list of date ranges with an "add" form. Used for a person's own leave (/leave) and for company holidays (/holidays, admins only). */
export default function TimeOffCard({ title, help, path, noun, canEdit = true }: { title: string; help: string; path: '/leave' | '/holidays'; noun: string; canEdit?: boolean }) {
  const qc = useQueryClient()
  const today = isoDay(new Date())
  const [f, setF] = useState({ start_date: today, end_date: today, note: '' })
  const list = useQuery({ queryKey: ['time-off', path], queryFn: () => api.get<{ items: TimeOff[] }>(path) })
  const refresh = () => qc.invalidateQueries({ queryKey: ['time-off', path] })
  const add = useMutation({ mutationFn: () => api.post(path, f), onSuccess: () => { setF({ start_date: today, end_date: today, note: '' }); refresh() } })
  const del = useMutation({ mutationFn: (id: string) => api.del(`${path}/${id}`), onSuccess: refresh })
  const items = list.data?.items ?? []
  return (
    <Paper sx={{ p: 3, maxWidth: 720, mt: 2.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{title}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{help}</Typography>
      {items.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>No {noun} added yet.</Typography>}
      {items.map((t) => (
        <Stack key={t.id} direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 0.75, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography variant="body2">
            {t.start_date === t.end_date ? fmtDate(t.start_date) : `${fmtDate(t.start_date)} – ${fmtDate(t.end_date)}`}
            {t.note ? ` · ${t.note}` : ''}
          </Typography>
          {canEdit && <Button size="small" color="error" onClick={() => del.mutate(t.id)} disabled={del.isPending}>Remove</Button>}
        </Stack>
      ))}
      <ErrorAlert error={del.error} />
      {canEdit && (
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mt: 2 }} alignItems={{ sm: 'center' }}>
          <TextField size="small" type="date" label="From" InputLabelProps={{ shrink: true }} value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value, end_date: f.end_date < e.target.value ? e.target.value : f.end_date })} />
          <TextField size="small" type="date" label="To" InputLabelProps={{ shrink: true }} value={f.end_date} inputProps={{ min: f.start_date }} onChange={(e) => setF({ ...f, end_date: e.target.value })} />
          <TextField size="small" label="Note (optional)" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} inputProps={{ maxLength: 200 }} sx={{ flex: 1 }} />
          <Button variant="outlined" disabled={!f.start_date || !f.end_date || add.isPending} onClick={() => add.mutate()}>Add</Button>
        </Stack>
      )}
      <ErrorAlert error={add.error} />
    </Paper>
  )
}
