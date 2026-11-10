import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import BoltIcon from '@mui/icons-material/BoltOutlined'
import FactCheckIcon from '@mui/icons-material/FactCheckOutlined'
import SpeedIcon from '@mui/icons-material/SpeedOutlined'
import TaskAltIcon from '@mui/icons-material/TaskAltOutlined'
import ThumbsUpDownIcon from '@mui/icons-material/ThumbsUpDownOutlined'
import { Alert, Box, Chip, CircularProgress, Grid, LinearProgress, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { ErrorAlert, StatCard } from '../components/ui'
import { fmtShort } from '../format'
import { CHART } from '../theme'
import type { AiUsage } from '../types'

const PERIODS: [string, string][] = [['month', 'This month'], ['7', 'Last 7 days'], ['30', 'Last 30 days'], ['90', 'Last 90 days']]
const FEATURE: Record<string, string> = { assistant: 'AI assistant', 'report.plan': 'AI reports · structure', 'report.write': 'AI reports · writing' }
const ERRORS: Record<string, string> = { provider_error: 'The AI service did not answer', invalid_output: 'The answer could not be used' }
const STATUS: Record<string, string> = {
  off: 'AI is switched off for your company, so no new calls are made.',
  not_configured: 'No AI service is connected. Reports and the assistant use their built-in wording.',
  provider_down: 'The AI service is not answering right now.',
}
const OK = '#0ca678'
const BAD = '#e03131'

const pct = (x: number | null | undefined) => (x === null || x === undefined ? '—' : `${Math.round(x * 100)}%`)
const compact = (n: number) => new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n)
const seconds = (ms: number | null | undefined) => (ms === null || ms === undefined ? '—' : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`)
const feature = (name: string) => FEATURE[name] ?? name

function Panel({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <Paper sx={{ p: 2.5, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{title}</Typography>
      {hint && <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1 }}>{hint}</Typography>}
      <Box sx={{ mt: hint ? 0 : 1.5 }}>{children}</Box>
    </Paper>
  )
}

function Meter({ label, used, limit, note }: { label: string; used: number; limit: number | null; note?: string }) {
  const share = limit ? Math.min(100, (used / limit) * 100) : 0
  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="baseline">
        <Typography variant="body2" sx={{ fontWeight: 600 }}>{label}</Typography>
        <Typography variant="body2" color="text.secondary">{limit ? `${compact(used)} of ${compact(limit)}` : compact(used)}</Typography>
      </Stack>
      {limit ? <LinearProgress variant="determinate" value={share} color={share >= 90 ? 'error' : share >= 70 ? 'warning' : 'primary'} aria-label={label} sx={{ height: 8, borderRadius: 4, mt: 0.5 }} /> : null}
      {note && <Typography variant="caption" color="text.secondary">{note}</Typography>}
    </Box>
  )
}

/** Settings → AI usage: how the AI features are used and how they behave (counts, tokens, timings and ratings only, never any text). */
export default function AiUsagePage() {
  const [period, setPeriod] = useState('month')
  const q = useQuery({ queryKey: ['ai-usage', period], queryFn: () => api.get<AiUsage>('/ai/usage', { period }), placeholderData: keepPreviousData })
  const u = q.data
  if (!u) return q.error ? <ErrorAlert error={q.error} /> : <CircularProgress aria-label="Loading AI usage" />

  const success = u.success_rate
  const successColor = success === null ? undefined : success >= 0.95 ? OK : success >= 0.8 ? '#f59f00' : BAD
  const chartDays = u.daily.map((d) => ({ ...d, ok: d.calls - d.errors, label: fmtShort(d.date) }))
  const tick = { fontSize: 11 }
  const status = u.status === 'ready' ? null : STATUS[u.status]

  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }} justifyContent="space-between">
        <Box>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>AI usage</Typography>
          <Typography variant="body2" color="text.secondary">Since {fmtShort(u.since)}. Counts, tokens, timings and ratings only — no questions or answers are shown here.</Typography>
        </Box>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Chip size="small" variant="outlined" color={u.status === 'ready' ? 'success' : 'warning'} label={u.status === 'ready' ? 'AI ready' : u.enabled ? 'AI unavailable' : 'AI off'} />
          <TextField select size="small" label="Period" value={period} onChange={(e) => setPeriod(e.target.value)} sx={{ minWidth: 150 }}>
            {PERIODS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </TextField>
        </Stack>
      </Stack>
      {status && <Alert severity="warning">{status}</Alert>}

      <Grid container spacing={2}>
        <Grid item xs={6} md={4} lg={2}><StatCard label="AI calls" value={u.calls.toLocaleString()} hint={u.errors ? `${u.errors} failed` : 'none failed'} icon={<AutoAwesomeIcon />} color={CHART[0]} /></Grid>
        <Grid item xs={6} md={4} lg={2}><StatCard label="Success rate" value={pct(success)} hint={u.calls ? 'calls that gave a usable answer' : 'no calls yet'} icon={<TaskAltIcon />} color={successColor ?? CHART[1]} /></Grid>
        <Grid item xs={6} md={4} lg={2}><StatCard label="Tokens" value={compact(u.tokens.input + u.tokens.output)} hint={`${compact(u.tokens.input)} in · ${compact(u.tokens.output)} out`} icon={<BoltIcon />} color={CHART[2]} /></Grid>
        <Grid item xs={6} md={4} lg={2}><StatCard label="Typical speed" value={seconds(u.latency_ms.p50)} hint={`slowest 5%: ${seconds(u.latency_ms.p95)}`} icon={<SpeedIcon />} color={CHART[5]} /></Grid>
        <Grid item xs={6} md={4} lg={2}><StatCard label="Checked against data" value={pct(u.grounding_pass_rate)} hint="of statements verified" icon={<FactCheckIcon />} color={CHART[4]} /></Grid>
        <Grid item xs={6} md={4} lg={2}><StatCard label="Answers rated helpful" value={pct(u.satisfaction)} hint={u.thumbs.up + u.thumbs.down ? `${u.thumbs.up} up · ${u.thumbs.down} down` : 'no ratings yet'} icon={<ThumbsUpDownIcon />} color={CHART[6]} /></Grid>
      </Grid>

      {u.calls === 0 && <Paper sx={{ p: 3, textAlign: 'center' }}><Typography color="text.secondary">No AI calls in this period yet. Charts fill in as people use the assistant and AI reports.</Typography></Paper>}

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Panel title="Calls per day" hint="Answered vs failed">
            <Box sx={{ height: 230 }} role="img" aria-label={`Calls per day, ${u.calls} in total, ${u.errors} failed`}>
              <ResponsiveContainer>
                <BarChart data={chartDays} margin={{ left: -18, right: 8 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" />
                  <XAxis dataKey="label" tick={tick} tickLine={false} interval="preserveStartEnd" minTickGap={24} />
                  <YAxis tick={tick} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip cursor={{ fill: 'rgba(0,0,0,.04)' }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="ok" name="Answered" stackId="c" fill={CHART[0]} radius={[0, 0, 0, 0]} />
                  <Bar dataKey="errors" name="Failed" stackId="c" fill={BAD} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Box>
          </Panel>
        </Grid>
        <Grid item xs={12} md={6}>
          <Panel title="Tokens per day" hint="Input plus output">
            <Box sx={{ height: 230 }} role="img" aria-label={`Tokens per day, ${compact(u.tokens.input + u.tokens.output)} in total`}>
              <ResponsiveContainer>
                <AreaChart data={chartDays} margin={{ left: -10, right: 8 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" />
                  <XAxis dataKey="label" tick={tick} tickLine={false} interval="preserveStartEnd" minTickGap={24} />
                  <YAxis tick={tick} tickLine={false} axisLine={false} tickFormatter={compact} />
                  <Tooltip formatter={(v: number) => [v.toLocaleString(), 'Tokens']} />
                  <Area type="monotone" dataKey="tokens" name="Tokens" stroke={CHART[2]} fill={CHART[2]} fillOpacity={0.2} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </Box>
          </Panel>
        </Grid>

        <Grid item xs={12} md={7}>
          <Panel title="By feature" hint="Where the calls go">
            {u.by_feature.length === 0 ? <Typography variant="body2" color="text.secondary">Nothing yet.</Typography> : (
              <Table size="small">
                <TableHead><TableRow><TableCell>Feature</TableCell><TableCell align="right">Calls</TableCell><TableCell align="right">Failed</TableCell><TableCell align="right">Tokens</TableCell><TableCell align="right">Avg speed</TableCell></TableRow></TableHead>
                <TableBody>
                  {u.by_feature.map((f) => (
                    <TableRow key={f.name}>
                      <TableCell>{feature(f.name)}</TableCell>
                      <TableCell align="right">{f.calls}</TableCell>
                      <TableCell align="right" sx={{ color: f.errors ? BAD : undefined }}>{f.errors}</TableCell>
                      <TableCell align="right">{compact(f.tokens)}</TableCell>
                      <TableCell align="right">{seconds(f.avg_latency_ms)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {u.by_model.length > 0 && <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 1.5 }}>Model: {u.by_model.map((m) => `${m.name} (${m.calls})`).join(', ')}</Typography>}
          </Panel>
        </Grid>
        <Grid item xs={12} md={5}>
          <Panel title="Limits" hint="Counted from midnight, company time">
            <Meter label="Assistant questions today" used={u.today.turns} limit={u.quota.turns_per_day} />
            <Meter label="AI reports today" used={u.today.reports} limit={u.quota.reports_per_day} />
            {u.budget_tokens ? <Meter label="Token budget this month" used={u.month_tokens} limit={u.budget_tokens} note={`${u.budget_used_pct ?? 0}% used`} /> : <Meter label="Tokens this month" used={u.month_tokens} limit={null} note="No monthly budget is set." />}
          </Panel>
        </Grid>

        <Grid item xs={12} md={6}>
          <Panel title="Reliability" hint="How often the safety nets were needed">
            <Stack spacing={0.75}>
              <Row label="Built-in wording used instead of AI" value={pct(u.fallback_rate)} />
              <Row label="Answers that needed a repair" value={pct(u.repair_rate)} />
              <Row label="Statements checked against data" value={pct(u.grounding_pass_rate)} />
            </Stack>
            {u.errors_by_code.length > 0 && (
              <Box sx={{ mt: 1.5 }}>
                <Typography variant="caption" color="text.secondary">Why calls failed</Typography>
                {u.errors_by_code.map((e) => <Row key={e.code} label={ERRORS[e.code] ?? e.code} value={String(e.count)} bad />)}
              </Box>
            )}
          </Panel>
        </Grid>
        <Grid item xs={12} md={6}>
          <Panel title="Feedback" hint="Thumbs on assistant answers and AI reports">
            {u.thumbs.up + u.thumbs.down === 0 ? <Typography variant="body2" color="text.secondary">No ratings in this period.</Typography> : (
              <>
                <Stack direction="row" sx={{ height: 12, borderRadius: 6, overflow: 'hidden', bgcolor: 'action.hover' }} role="img" aria-label={`${u.thumbs.up} helpful, ${u.thumbs.down} not helpful`}>
                  <Box sx={{ width: `${(u.thumbs.up / (u.thumbs.up + u.thumbs.down)) * 100}%`, bgcolor: OK }} />
                  <Box sx={{ flex: 1, bgcolor: BAD }} />
                </Stack>
                <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.5 }}>
                  <Typography variant="caption"><b>{u.thumbs.up}</b> helpful</Typography>
                  <Typography variant="caption"><b>{u.thumbs.down}</b> not helpful</Typography>
                </Stack>
              </>
            )}
            {u.thumbs_down_reasons.length > 0 && (
              <Box sx={{ mt: 1.5 }}>
                <Typography variant="caption" color="text.secondary">What people said was wrong</Typography>
                {u.thumbs_down_reasons.map((r) => <Row key={r.reason} label={r.reason} value={String(r.count)} />)}
              </Box>
            )}
          </Panel>
        </Grid>
      </Grid>
    </Stack>
  )
}

function Row({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <Stack direction="row" justifyContent="space-between" sx={{ py: 0.25 }}>
      <Typography variant="body2">{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 700, color: bad ? BAD : undefined }}>{value}</Typography>
    </Stack>
  )
}
