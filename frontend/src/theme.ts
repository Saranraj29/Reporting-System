import { createTheme } from '@mui/material/styles'

export const STATUS_COLORS: Record<string, string> = {
  todo: '#8a94a6',
  in_progress: '#3b5bdb',
  blocked: '#e03131',
  in_review: '#f59f00',
  done: '#2f9e44',
}
export const STATUS_LABELS: Record<string, string> = {
  todo: 'To do',
  in_progress: 'In progress',
  blocked: 'Blocked',
  in_review: 'In review',
  done: 'Done',
}
export const PRIORITY_COLORS: Record<string, 'default' | 'info' | 'warning' | 'error'> = {
  low: 'default',
  medium: 'info',
  high: 'warning',
  urgent: 'error',
}
export const CHART = ['#3b5bdb', '#0ca678', '#f59f00', '#e8590c', '#7048e8', '#1098ad', '#d6336c', '#868e96']

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#3b5bdb' },
    secondary: { main: '#0ca678' },
    error: { main: '#e03131' },
    warning: { main: '#f59f00' },
    success: { main: '#2f9e44' },
    background: { default: '#f5f7fb', paper: '#ffffff' },
    text: { primary: '#1c2434', secondary: '#5d6879' },
    divider: '#e4e8f0',
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Inter", -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    h4: { fontWeight: 700, letterSpacing: '-0.02em' },
    h5: { fontWeight: 700, letterSpacing: '-0.01em' },
    h6: { fontWeight: 650 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { border: '1px solid #e4e8f0' } } },
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiTableCell: { styleOverrides: { head: { fontWeight: 600, color: '#5d6879', background: '#f9fafc' } } },
    MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
  },
})
