import StopIcon from '@mui/icons-material/Stop'
import TimerIcon from '@mui/icons-material/Timer'
import { Box, Button, Tooltip, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from './api'
import { useAuth } from './auth'
import { elapsed } from './format'
import type { TimeEntry } from './types'

/** The one source of truth for "is my timer running?" — shared by the header, My day and the task drawer. */
export function useRunningTimer() {
  const { me } = useAuth()
  return useQuery({
    queryKey: ['running-timer'],
    queryFn: () => api.get<TimeEntry | null>('/time-entries/running'),
    enabled: !!me,
    staleTime: 30_000,  // every header, panel and page asks the same question: once every 30 s at most, not on every mount
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}

export function useTimerActions() {
  const qc = useQueryClient()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['running-timer'] })
    qc.invalidateQueries({ queryKey: ['entries'] })
    qc.invalidateQueries({ queryKey: ['tasks'] })
    qc.invalidateQueries({ queryKey: ['task'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const start = useMutation({
    mutationFn: (taskId: string) => api.post<TimeEntry>('/time-entries/start', { task_id: taskId }),
    onSuccess: refresh,
    onError: (e) => {
      if (e instanceof ApiError && e.code === 'timer_running') refresh() // the UI was stale: show the running timer now
    },
  })
  const stop = useMutation({ mutationFn: (id: string) => api.post<TimeEntry>(`/time-entries/${id}/stop`), onSuccess: refresh, onError: refresh })
  return { start, stop }
}

export function useNow() {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  return now
}

/** Live timer + Stop button shown in the top bar on every page while a timer is running. */
export function HeaderTimer() {
  const running = useRunningTimer().data
  const { stop } = useTimerActions()
  const now = useNow()
  const nav = useNavigate()
  if (!running?.started_at) return null
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mr: 2, pl: 1.5, pr: 0.5, py: 0.5, borderRadius: 99, bgcolor: '#e03131', color: '#fff' }}>
      <Tooltip title={`Timer running on “${running.task_title}” — open My day`}>
        <Box onClick={() => nav('/my-day')} sx={{ display: 'flex', alignItems: 'center', gap: 0.75, cursor: 'pointer', minWidth: 0 }}>
          <TimerIcon fontSize="small" />
          <Typography variant="body2" sx={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{elapsed(running.started_at, now)}</Typography>
          <Typography variant="caption" noWrap sx={{ maxWidth: 160, display: { xs: 'none', md: 'block' }, opacity: 0.9 }}>{running.task_title}</Typography>
        </Box>
      </Tooltip>
      <Button size="small" variant="contained" startIcon={<StopIcon />} disabled={stop.isPending} onClick={() => stop.mutate(running.id)}
        sx={{ bgcolor: '#fff', color: '#e03131', '&:hover': { bgcolor: '#ffe3e3' }, borderRadius: 99, py: 0.25 }}>
        Stop
      </Button>
    </Box>
  )
}
