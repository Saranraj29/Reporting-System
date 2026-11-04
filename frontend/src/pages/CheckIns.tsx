import NightsStayIcon from '@mui/icons-material/NightsStayOutlined'
import WbSunnyIcon from '@mui/icons-material/WbSunnyOutlined'
import { Alert, Box, Chip, Grid, LinearProgress, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { Empty, ErrorAlert, PageHeader, StatCard } from '../components/ui'
import { clock, daysAgo, fmtDate, today } from '../format'
import type { CheckInSummary, DailyStatus, Page, UserLite } from '../types'

/** Team view of the two daily check-ins: who posted what, and who has not yet. Scoped by status.view.team / .all. */
export default function CheckIns() {
  const [day, setDay] = useState(today())
  const [range, setRange] = useState({ from: daysAgo(6), to: today() })
  const [person, setPerson] = useState('')
  const users = useQuery({ queryKey: ['users', 'all'], queryFn: () => api.get<Page<UserLite>>('/users', { limit: 200 }) })
  const summary = useQuery({ queryKey: ['checkin-summary', day], queryFn: () => api.get<CheckInSummary>('/daily-status/summary', { date: day }), placeholderData: keepPreviousData })
  const log = useQuery({
    queryKey: ['daily-status', 'log', range, person],
    queryFn: () => api.get<Page<DailyStatus>>('/daily-status', { from: range.from, to: range.to, user: person, limit: 200 }),
    placeholderData: keepPreviousData,
  })
  const s = summary.data
  const pct = (n: number) => (s && s.expected ? Math.round((n / s.expected) * 100) : 0)

  return (
    <>
      <PageHeader title="Check-ins" subtitle="Morning plans and end-of-day updates across your team"
        actions={<TextField size="small" type="date" label="Day" value={day} onChange={(e) => setDay(e.target.value || today())} inputProps={{ max: today() }} />} />
      <ErrorAlert error={summary.error ?? log.error} />
      <Grid container spacing={2.5} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} lg={3}><StatCard label="Morning plans" value={s ? `${s.morning_done}/${s.expected}` : '–'} hint={`${pct(s?.morning_done ?? 0)}% posted`} color="#f59f00" icon={<WbSunnyIcon />} /></Grid>
        <Grid item xs={12} sm={6} lg={3}><StatCard label="End-of-day updates" value={s ? `${s.eod_done}/${s.expected}` : '–'} hint={`${pct(s?.eod_done ?? 0)}% posted`} color="#3b5bdb" icon={<NightsStayIcon />} /></Grid>
        <Grid item xs={12} lg={6}>
          <Paper sx={{ p: 2.25, height: '100%' }}>
            <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600, mb: 1 }}>Waiting for · {fmtDate(day)}</Typography>
            <Typography variant="caption" color="text.secondary">Morning plan</Typography>
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
              {s?.missing_morning.length ? s.missing_morning.map((n) => <Chip key={n} size="small" label={n} color="warning" variant="outlined" />) : <Chip size="small" color="success" label="Everyone has posted" />}
            </Stack>
            <Typography variant="caption" color="text.secondary">End-of-day update</Typography>
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
              {s?.missing_eod.length ? s.missing_eod.map((n) => <Chip key={n} size="small" label={n} variant="outlined" />) : <Chip size="small" color="success" label="Everyone has posted" />}
            </Stack>
          </Paper>
        </Grid>
      </Grid>
      {s?.blockers.length ? (
        <Alert severity="warning" sx={{ mb: 3 }}>
          <b>Blockers reported on {fmtDate(day)}</b>
          <ul style={{ margin: '4px 0 0 18px', padding: 0 }}>{s.blockers.map((b) => <li key={b.user}><b>{b.user}:</b> {b.text}</li>)}</ul>
        </Alert>
      ) : null}

      <Paper sx={{ overflow: 'hidden' }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ md: 'center' }} justifyContent="space-between" sx={{ p: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Check-in log</Typography>
          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
            <TextField size="small" type="date" label="From" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} />
            <TextField size="small" type="date" label="To" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} />
            <TextField select size="small" label="Person" value={person} onChange={(e) => setPerson(e.target.value)} sx={{ minWidth: 180 }}>
              <MenuItem value="">Everyone in scope</MenuItem>
              {users.data?.items.map((u) => <MenuItem key={u.id} value={u.id}>{u.name}</MenuItem>)}
            </TextField>
          </Stack>
        </Stack>
        {log.isFetching && <LinearProgress />}
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="small" sx={{ minWidth: 860 }}>
            <TableHead><TableRow><TableCell>Date</TableCell><TableCell>Person</TableCell><TableCell>Morning plan</TableCell><TableCell>End of day</TableCell><TableCell>Blockers</TableCell></TableRow></TableHead>
            <TableBody>
              {log.data?.items.map((r) => (
                <TableRow key={r.id} hover sx={{ verticalAlign: 'top' }}>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(r.status_date)}</TableCell>
                  <TableCell sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{r.user_name}</TableCell>
                  <TableCell sx={{ maxWidth: 280 }}>
                    {r.plan_today ? <>{r.plan_today}<Typography variant="caption" color="text.secondary" display="block">posted {clock(r.morning_at)}</Typography></> : <Chip size="small" variant="outlined" label="missing" />}
                  </TableCell>
                  <TableCell sx={{ maxWidth: 320 }}>
                    {r.did_today ? <>{r.did_today}{r.next_up && <Typography variant="caption" color="text.secondary" display="block">Next: {r.next_up}</Typography>}<Typography variant="caption" color="text.secondary" display="block">posted {clock(r.eod_at)}</Typography></> : <Chip size="small" variant="outlined" label="missing" />}
                  </TableCell>
                  <TableCell sx={{ maxWidth: 220, color: r.blockers ? 'warning.dark' : 'text.disabled' }}>{r.blockers || '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
        {log.data?.items.length === 0 && <Empty>No check-ins in this range.</Empty>}
      </Paper>
    </>
  )
}
