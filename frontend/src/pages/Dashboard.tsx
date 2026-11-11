import AccessTimeIcon from '@mui/icons-material/AccessTime'
import AssignmentIcon from '@mui/icons-material/AssignmentOutlined'
import BlockIcon from '@mui/icons-material/Block'
import EventBusyIcon from '@mui/icons-material/EventBusyOutlined'
import EditNoteIcon from '@mui/icons-material/EditNoteOutlined'
import WbSunnyIcon from '@mui/icons-material/WbSunnyOutlined'
import { Box, Chip, Grid, List, ListItem, ListItemText, Paper, Skeleton, TextField, Typography } from '@mui/material'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { useAuth } from '../auth'
import LinkedFilters from '../components/LinkedFilters'
import { Empty, ErrorAlert, PageHeader, PriorityChip, StatCard } from '../components/ui'
import { NONE, type Sel } from '../filters'
import { daysAgo, fmtShort, hours, today } from '../format'
import { CHART, STATUS_COLORS, STATUS_LABELS } from '../theme'
import { useTeams } from '../hooks'
import type { Dashboard as DashboardData, Page, Project, UserLite } from '../types'

function Card({ title, children, height }: { title: string; children: React.ReactNode; height?: number }) {
  return (
    <Paper sx={{ p: 2.5, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
      <Box sx={{ height }}>{children}</Box>
    </Paper>
  )
}

export default function Dashboard() {
  const { hasAny, me } = useAuth()
  const [dates, setDates] = useState({ from: daysAgo(29), to: today() })  // the last 30 days until the person picks their own
  const datesBad = !dates.from || !dates.to || dates.from > dates.to
  const { from, to } = dates
  const [sel, setSel] = useState<Sel>(NONE)  // team / project / person narrow each other, see LinkedFilters
  const { team, project, user } = sel
  const teams = useTeams()
  const multiUser = hasAny('dashboard.view') && (me?.permissions ?? []).some((p) => p === 'dashboard.view.team' || p === 'dashboard.view.all')

  const projects = useQuery({ queryKey: ['projects', 'all'], queryFn: () => api.get<Page<Project>>('/projects', { limit: 200 }) })
  const users = useQuery({ queryKey: ['users', 'all'], queryFn: () => api.get<Page<UserLite>>('/users', { limit: 200 }), enabled: multiUser })
  const q = useQuery({
    queryKey: ['dashboard', from, to, project, user, team],
    queryFn: () => api.get<DashboardData>('/dashboard', { from, to, project, user, team }),
    enabled: !datesBad,
    placeholderData: keepPreviousData, // keep the old numbers on screen while a filter change loads: no flicker
  })
  const d = q.data

  const statusData = d ? Object.entries(d.tasks_by_status).map(([k, v]) => ({ name: STATUS_LABELS[k], key: k, value: v })).filter((x) => x.value > 0) : []
  const coverage = d && d.daily_status.expected ? Math.round((d.daily_status.eod_today / d.daily_status.expected) * 100) : 0

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={multiUser ? 'How work is flowing across your projects and people' : 'Your own work at a glance'}
        actions={
          <>
            <TextField size="small" type="date" label="From" InputLabelProps={{ shrink: true }} value={dates.from} onChange={(e) => setDates({ ...dates, from: e.target.value })} inputProps={{ max: dates.to || today() }} error={datesBad} />
            <TextField size="small" type="date" label="To" InputLabelProps={{ shrink: true }} value={dates.to} onChange={(e) => setDates({ ...dates, to: e.target.value })} inputProps={{ min: dates.from, max: today() }} error={datesBad} helperText={datesBad ? 'From must be on or before To.' : undefined} />
            <LinkedFilters value={sel} onChange={setSel} teams={multiUser ? teams : []} projects={projects.data?.items ?? []} users={multiUser ? users.data?.items ?? [] : undefined} />
          </>
        }
      />
      <ErrorAlert error={q.error} />
      <Grid container spacing={2.5}>
        {[
          { label: 'Tasks in play', value: d?.total_tasks, icon: <AssignmentIcon />, color: '#3b5bdb', hint: `${d?.tasks_by_status.done ?? 0} done` },
          { label: 'Hours logged', value: d ? hours(d.total_hours) : undefined, icon: <AccessTimeIcon />, color: '#0ca678', hint: 'in the chosen dates' },
          { label: 'Overdue', value: d?.overdue_count, icon: <EventBusyIcon />, color: '#e8590c', hint: 'past due, not done' },
          { label: 'Blocked', value: d?.blocked_count, icon: <BlockIcon />, color: '#e03131', hint: 'need attention' },
          { label: 'Morning plans', value: d ? `${d.daily_status.morning_today}/${d.daily_status.expected}` : undefined, icon: <WbSunnyIcon />, color: '#f59f00', hint: 'posted today' },
          { label: 'End-of-day updates', value: d ? `${d.daily_status.eod_today}/${d.daily_status.expected}` : undefined, icon: <EditNoteIcon />, color: '#7048e8', hint: multiUser ? `${coverage}% of the team` : d && d.daily_status.eod_today ? 'posted today' : 'not posted yet' },
        ].map((s) => (
          <Grid key={s.label} item xs={6} md={4} lg={2}>
            {q.isLoading ? <Skeleton variant="rounded" height={104} /> : <StatCard label={s.label} value={s.value ?? 0} icon={s.icon} color={s.color} hint={s.hint} />}
          </Grid>
        ))}

        <Grid item xs={12} md={5}>
          <Card title="Tasks by status" height={270}>
            {statusData.length ? (
              <ResponsiveContainer>
                <PieChart>
                  <Pie isAnimationActive={false} data={statusData} dataKey="value" nameKey="name" innerRadius={62} outerRadius={95} paddingAngle={2}>
                    {statusData.map((s) => <Cell key={s.key} fill={STATUS_COLORS[s.key]} />)}
                  </Pie>
                  <Tooltip />
                  <Legend verticalAlign="bottom" iconType="circle" />
                </PieChart>
              </ResponsiveContainer>
            ) : <Empty>No tasks in this range.</Empty>}
          </Card>
        </Grid>
        <Grid item xs={12} md={7}>
          <Card title="Hours per day" height={270}>
            {d?.hours_by_day.length ? (
              <ResponsiveContainer>
                <AreaChart data={d.hours_by_day.map((x) => ({ ...x, label: fmtShort(x.date) }))} margin={{ left: -18, right: 8 }}>
                  <defs>
                    <linearGradient id="hrs" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3b5bdb" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#3b5bdb" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e4e8f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v: number) => [hours(v), 'Time']} />
                  <Area isAnimationActive={false} type="monotone" dataKey="hours" stroke="#3b5bdb" strokeWidth={2.5} fill="url(#hrs)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : <Empty>No time logged in this range.</Empty>}
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card title="Hours by project" height={260}>
            {d?.hours_by_project.length ? (
              <ResponsiveContainer>
                <BarChart data={d.hours_by_project} layout="vertical" margin={{ left: 10, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e4e8f0" />
                  <XAxis type="number" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="project" width={120} tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v: number) => [hours(v), 'Time']} />
                  <Bar isAnimationActive={false} dataKey="hours" radius={[0, 6, 6, 0]}>
                    {d.hours_by_project.map((_, i) => <Cell key={i} fill={CHART[i % CHART.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : <Empty>No hours yet.</Empty>}
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card title="Hours by activity type" height={260}>
            {d?.hours_by_activity.length ? (
              <ResponsiveContainer>
                <BarChart data={d.hours_by_activity} margin={{ left: -18, right: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e4e8f0" />
                  <XAxis dataKey="activity_type" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v: number) => [hours(v), 'Time']} />
                  <Bar isAnimationActive={false} dataKey="hours" radius={[6, 6, 0, 0]}>
                    {d.hours_by_activity.map((_, i) => <Cell key={i} fill={CHART[(i + 2) % CHART.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : <Empty>No hours yet.</Empty>}
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card title={`Overdue tasks${d ? ` (${d.overdue_count})` : ''}`}>
            {d?.overdue_tasks.length ? (
              <List dense disablePadding>
                {d.overdue_tasks.map((t) => (
                  <ListItem key={t.id} divider secondaryAction={<Chip size="small" color="error" variant="outlined" label={`Due ${fmtShort(t.due_date)}`} />}>
                    <ListItemText primary={t.title} secondary={`${t.project}${t.assignees ? ` · ${t.assignees}` : ''}`} primaryTypographyProps={{ fontWeight: 600 }} />
                  </ListItem>
                ))}
              </List>
            ) : <Empty>Nothing is overdue. 🎉</Empty>}
          </Card>
        </Grid>
        {multiUser && d && d.daily_status.expected > 1 && (d.daily_status.missing_morning.length > 0 || d.daily_status.missing_eod.length > 0) && (
          <Grid item xs={12}>
            <Card title="Waiting for today's check-in">
              <Typography variant="caption" color="text.secondary">Morning plan</Typography>
              <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mb: 1.25 }}>{d.daily_status.missing_morning.length ? d.daily_status.missing_morning.map((n) => <Chip key={n} size="small" variant="outlined" color="warning" label={n} />) : <Chip size="small" color="success" label="Everyone has posted" />}</Box>
              <Typography variant="caption" color="text.secondary">End-of-day update</Typography>
              <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>{d.daily_status.missing_eod.length ? d.daily_status.missing_eod.map((n) => <Chip key={n} size="small" variant="outlined" label={n} />) : <Chip size="small" color="success" label="Everyone has posted" />}</Box>
            </Card>
          </Grid>
        )}
        <Grid item xs={12} md={6}>
          <Card title={`Blockers${d ? ` (${d.blocked_count})` : ''}`}>
            {d?.blockers.length || d?.daily_status.blockers.length ? (
              <List dense disablePadding>
                {d?.blockers.map((t) => (
                  <ListItem key={t.id} divider secondaryAction={<PriorityChip priority={t.priority} />}>
                    <ListItemText primary={t.title} secondary={`${t.project}${t.assignees ? ` · ${t.assignees}` : ''}`} primaryTypographyProps={{ fontWeight: 600 }} />
                  </ListItem>
                ))}
                {d?.daily_status.blockers.map((b, i) => (
                  <ListItem key={i} divider>
                    <ListItemText primary={b.text} secondary={`${b.user} · daily status ${fmtShort(b.date)}`} />
                  </ListItem>
                ))}
              </List>
            ) : <Empty>No blockers reported.</Empty>}
          </Card>
        </Grid>
      </Grid>
    </>
  )
}
