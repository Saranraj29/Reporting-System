import { TextField } from '@mui/material'
import { hours, parseDuration } from '../format'

export const MIN_HOURS = 1 / 60  // one minute
export const MAX_HOURS = 24

/** hours for what is typed, or null when empty / not a time / outside one minute to 24 hours. */
export function durationHours(text: string): number | null {
  const h = parseDuration(text)
  return h !== null && h >= MIN_HOURS - 1e-9 && h <= MAX_HOURS ? h : null
}

/** A "Time" box: type 45m, 1h 30m, 1:30 or 1.5. It says how it understood you, or what is wrong, while you type. */
export default function DurationField({ value, onChange, label = 'Time', fullWidth = true, autoFocus }: { value: string; onChange: (v: string) => void; label?: string; fullWidth?: boolean; autoFocus?: boolean }) {
  const parsed = parseDuration(value)
  const ok = durationHours(value) !== null
  const bad = value.trim() !== '' && !ok
  return (
    <TextField
      size="small" label={label} value={value} onChange={(e) => onChange(e.target.value)} fullWidth={fullWidth} autoFocus={autoFocus} placeholder="1h 30m"
      error={bad} inputProps={{ 'aria-label': label }}
      helperText={bad ? (parsed === null ? 'Try 45m, 1h 30m or 1.5' : 'From 1 minute to 24 hours') : ok ? `= ${hours(parseDuration(value)!)}` : 'e.g. 45m, 1h 30m, 1.5'}
    />
  )
}
