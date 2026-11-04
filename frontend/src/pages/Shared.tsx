import DownloadIcon from '@mui/icons-material/Download'
import { Alert, Box, Button, CircularProgress, Container, Stack, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { ReportFrame } from '../components/ui'
import { fmtDate } from '../format'

interface Shared {
  title: string
  company_name: string
  client_name: string | null
  period_start: string
  period_end: string
  expires_at: string
  html: string
  pdf_url: string | null
  markdown_url: string | null
}

/** Public, read-only client report page (no login). */
export default function SharedReport() {
  const { token } = useParams()
  const q = useQuery({ queryKey: ['shared', token], queryFn: () => api.get<Shared>(`/shared/${token}`), retry: false })
  if (q.isLoading) return <Box sx={{ p: 8, textAlign: 'center' }}><CircularProgress /></Box>
  if (q.error) {
    return (
      <Container maxWidth="sm" sx={{ py: 10 }}>
        <Alert severity="warning">This report link is no longer available. It may have expired or been withdrawn — please ask the sender for a new one.</Alert>
      </Container>
    )
  }
  const d = q.data!
  return (
    <Box sx={{ bgcolor: 'background.default', minHeight: '100vh', py: 4 }}>
      <Container maxWidth="md">
        <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={2} sx={{ mb: 2 }}>
          <Box>
            <Typography variant="overline" color="text.secondary">Shared by {d.company_name}</Typography>
            <Typography variant="h5">{d.title}</Typography>
            <Typography variant="body2" color="text.secondary">{fmtDate(d.period_start)} – {fmtDate(d.period_end)} · link valid until {fmtDate(d.expires_at)}</Typography>
          </Box>
          <Stack direction="row" spacing={1}>
            {d.markdown_url && <Button variant="outlined" startIcon={<DownloadIcon />} href={d.markdown_url}>Download Markdown</Button>}
            {d.pdf_url && <Button variant="contained" startIcon={<DownloadIcon />} href={d.pdf_url}>Download PDF</Button>}
          </Stack>
        </Stack>
        <ReportFrame html={d.html} height={900} />
      </Container>
    </Box>
  )
}
