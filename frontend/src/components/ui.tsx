import CloseIcon from '@mui/icons-material/Close'
import SearchIcon from '@mui/icons-material/Search'
import { Alert, Avatar, AvatarGroup, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, InputAdornment, Paper, Stack, TextField, Tooltip, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import { errorMessage } from '../api'
import { initials, titleCase } from '../format'
import { PRIORITY_COLORS, STATUS_COLORS, STATUS_LABELS } from '../theme'
import type { Assignee } from '../types'

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={2} sx={{ mb: 3 }}>
      <Box>
        <Typography variant="h5">{title}</Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary">
            {subtitle}
          </Typography>
        )}
      </Box>
      {actions && <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>{actions}</Stack>}
    </Stack>
  )
}

export function StatCard({ label, value, hint, color, icon }: { label: string; value: ReactNode; hint?: string; color?: string; icon?: ReactNode }) {
  return (
    <Paper sx={{ p: 2.25, height: '100%' }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
        <Box>
          <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
            {label}
          </Typography>
          <Typography variant="h4" sx={{ mt: 0.5, color: color ?? 'text.primary' }}>
            {value}
          </Typography>
          {hint && (
            <Typography variant="caption" color="text.secondary">
              {hint}
            </Typography>
          )}
        </Box>
        {icon && (
          <Avatar variant="rounded" sx={{ bgcolor: `${color ?? '#3b5bdb'}18`, color: color ?? 'primary.main', width: 40, height: 40 }}>
            {icon}
          </Avatar>
        )}
      </Stack>
    </Paper>
  )
}

export function StatusChip({ status, size = 'small' }: { status: string; size?: 'small' | 'medium' }) {
  const c = STATUS_COLORS[status] ?? '#8a94a6'
  return <Chip size={size} label={STATUS_LABELS[status] ?? titleCase(status)} sx={{ bgcolor: `${c}1f`, color: c }} />
}

export function PriorityChip({ priority }: { priority: string }) {
  return <Chip size="small" variant="outlined" color={PRIORITY_COLORS[priority] ?? 'default'} label={titleCase(priority)} />
}

const RUN_COLORS: Record<string, string> = { queued: '#8a94a6', drafted: '#f59f00', approved: '#3b5bdb', sent: '#2f9e44', ready: '#2f9e44', failed: '#e03131' }
export function RunStatusChip({ status }: { status: string }) {
  const c = RUN_COLORS[status] ?? '#8a94a6'
  return <Chip size="small" label={titleCase(status)} sx={{ bgcolor: `${c}1f`, color: c }} />
}

export function AssigneeAvatars({ people, max = 3 }: { people: Assignee[]; max?: number }) {
  return (
    <AvatarGroup max={max} sx={{ justifyContent: 'flex-end', '& .MuiAvatar-root': { width: 28, height: 28, fontSize: 12, bgcolor: 'primary.light' } }}>
      {people.map((p) => (
        <Tooltip key={p.id} title={p.name}>
          <Avatar>{initials(p.name)}</Avatar>
        </Tooltip>
      ))}
    </AvatarGroup>
  )
}

export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <Alert severity="error" sx={{ my: 1 }}>
      {errorMessage(error)}
    </Alert>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ py: 5, textAlign: 'center', color: 'text.secondary' }}>
      <Typography variant="body2">{children}</Typography>
    </Box>
  )
}

export function ConfirmDialog({ open, title, body, confirmLabel = 'Confirm', onClose, onConfirm, danger, busy }: { open: boolean; title: string; body: ReactNode; confirmLabel?: string; onClose: () => void; onConfirm: () => void; danger?: boolean; busy?: boolean }) {
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>{body}</DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" color={danger ? 'error' : 'primary'} onClick={onConfirm} disabled={busy}>
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

/** Renders server-generated report HTML. Sandboxed: no scripts, same-origin access or navigation. */
export function ReportFrame({ html, height = 760 }: { html: string; height?: number }) {
  return <Box component="iframe" title="Report preview" sandbox="" srcDoc={html} sx={{ width: '100%', height, border: '1px solid', borderColor: 'divider', borderRadius: 2, bgcolor: '#fff' }} />
}

/** The search box used on every list: shows a hint until 3 characters are typed (that is when the search request is sent). */
/** Props that make a clickable table row / card work from the keyboard too: it can be reached with Tab and opened with Enter or Space. */
export function clickable(activate: () => void) {
  return {
    onClick: activate,
    tabIndex: 0,
    onKeyDown: (e: React.KeyboardEvent) => {
      if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) { e.preventDefault(); activate() }
    },
  }
}

/** Shown in place of a page the person is not allowed to open (instead of silently sending them somewhere else). */
export function NoAccess({ onHome }: { onHome: () => void }) {
  return (
    <Paper sx={{ p: 4, maxWidth: 520, mx: 'auto', mt: 4, textAlign: 'center' }} role="alert">
      <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }}>You do not have access to this page</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>Your role does not include it. If you think it should, ask an administrator.</Typography>
      <Button variant="contained" onClick={onHome}>Go to the dashboard</Button>
    </Paper>
  )
}

export function SearchBox({ value, onChange, placeholder = 'Search', width }: { value: string; onChange: (v: string) => void; placeholder?: string; width?: number | string }) {
  const short = value.trim().length > 0 && value.trim().length < 3
  return (
    <TextField size="small" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} sx={{ width: width ?? { xs: '100%', sm: 320 } }}
      inputProps={{ 'aria-label': placeholder }} helperText={short ? 'Type at least 3 characters to search' : undefined}
      InputProps={{
        startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
        endAdornment: value ? <InputAdornment position="end"><IconButton size="small" aria-label="Clear search" onClick={() => onChange('')}><CloseIcon fontSize="small" /></IconButton></InputAdornment> : undefined,
      }} />
  )
}
