import { Alert, Box, Button, Divider, Link, Paper, Stack, TextField, Typography } from '@mui/material'
import BusinessIcon from '@mui/icons-material/BusinessCenterOutlined'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { PasswordField } from '../components/PasswordField'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined

function Shell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', gridTemplateColumns: { md: '1.05fr 1fr' }, bgcolor: 'background.default' }}>
      <Box sx={{ display: { xs: 'none', md: 'flex' }, flexDirection: 'column', justifyContent: 'center', p: 8, color: '#fff', background: 'linear-gradient(135deg,#2b3f9e 0%,#3b5bdb 55%,#4c6ef5 100%)' }}>
        <BusinessIcon sx={{ fontSize: 44, mb: 2 }} />
        <Typography variant="h3" sx={{ fontWeight: 800, letterSpacing: '-0.03em', mb: 2 }}>
          See the work.
          <br />
          Share the progress.
        </Typography>
        <Typography sx={{ opacity: 0.9, maxWidth: 460, fontSize: 18 }}>
          Tasks, time, daily status and AI-written project reports in one place.
        </Typography>
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', p: 3 }}>
        <Paper sx={{ p: { xs: 3, sm: 4.5 }, width: '100%', maxWidth: 440 }}>
          <Typography variant="h5">{title}</Typography>
          {subtitle && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5, mt: 0.5 }}>
              {subtitle}
            </Typography>
          )}
          {children}
        </Paper>
      </Box>
    </Box>
  )
}

function GoogleButton({ onToken }: { onToken: (credential: string) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !ref.current) return
    const s = document.createElement('script')
    s.src = 'https://accounts.google.com/gsi/client'
    s.async = true
    s.onload = () => {
      const g = (window as any).google
      g?.accounts.id.initialize({ client_id: GOOGLE_CLIENT_ID, callback: (r: { credential: string }) => onToken(r.credential) })
      g?.accounts.id.renderButton(ref.current, { theme: 'outline', size: 'large', width: 340, text: 'continue_with' })
    }
    document.head.appendChild(s)
    return () => {
      s.remove()
    }
  }, [onToken])
  if (!GOOGLE_CLIENT_ID) return null
  return (
    <>
      <Divider sx={{ my: 2.5 }}>or</Divider>
      <Box ref={ref} sx={{ display: 'flex', justifyContent: 'center' }} />
    </>
  )
}

export function Login() {
  const { login, loginWithToken } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      nav('/')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Shell title="Welcome back" subtitle="Sign in to your workspace">
      <form onSubmit={submit}>
        <Stack spacing={2}>
          <TextField label="Work email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required autoFocus />
          <PasswordField label="Password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          {error && <Alert severity="error">{error}</Alert>}
          <Button type="submit" variant="contained" size="large" disabled={busy}>
            Sign in
          </Button>
          <Stack direction="row" justifyContent="space-between">
            <Link component={RouterLink} to="/forgot-password" variant="body2">
              Forgot password?
            </Link>
            <Link component={RouterLink} to="/register" variant="body2">
              Create account
            </Link>
          </Stack>
        </Stack>
      </form>
      <GoogleButton
        onToken={async (credential) => {
          try {
            const r = await api.post<{ access_token: string }>('/auth/google', { credential })
            await loginWithToken(r.access_token)
            nav('/')
          } catch (err) {
            setError(errorMessage(err))
          }
        }}
      />
    </Shell>
  )
}

type DomainStatus = { status: 'join' | 'create' | 'invite_required'; company_name: string | null }

export function Register() {
  const [params] = useSearchParams()
  const invite = params.get('invite') ?? undefined
  const [form, setForm] = useState({ name: '', email: '', password: '', company_name: '' })
  const [domain, setDomain] = useState<DomainStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ token?: string; verify: boolean } | null>(null)

  useEffect(() => {
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email) || invite) return setDomain(null)
    const t = setTimeout(() => api.get<DomainStatus>('/auth/domain-check', { email: form.email }).then(setDomain).catch(() => setDomain(null)), 350)
    return () => clearTimeout(t)
  }, [form.email, invite])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      const r = await api.post<{ verification_required: boolean; dev_verification_token?: string }>('/auth/register', {
        ...form,
        company_name: domain?.status === 'create' ? form.company_name : undefined,
        invite_token: invite,
      })
      setDone({ token: r.dev_verification_token, verify: r.verification_required })
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  if (done) {
    return (
      <Shell title={done.verify ? 'Check your inbox' : 'Account created'} subtitle={done.verify ? 'We sent a verification link. Data stays hidden until your email is verified.' : 'You can sign in now.'}>
        {done.token && (
          <Alert severity="info" sx={{ mb: 2 }}>
            Development mode: <Link component={RouterLink} to={`/verify-email?token=${done.token}`}>verify now</Link>
          </Alert>
        )}
        <Button component={RouterLink} to="/login" variant="contained" fullWidth>
          Go to sign in
        </Button>
      </Shell>
    )
  }
  return (
    <Shell title="Create your account" subtitle={invite ? "You've been invited to join a workspace." : 'Your email domain decides which company you join.'}>
      <form onSubmit={submit}>
        <Stack spacing={2}>
          <TextField label="Full name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          <TextField label="Work email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
          {domain?.status === 'join' && <Alert severity="success">You'll join <b>{domain.company_name}</b> as a Team Member after verifying your email.</Alert>}
          {domain?.status === 'create' && (
            <>
              <Alert severity="info">No company uses this domain yet. You'll create one and become its admin.</Alert>
              <TextField label="Company name" value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} required />
            </>
          )}
          {domain?.status === 'invite_required' && <Alert severity="warning">Personal email domains need an invite link from a company admin.</Alert>}
          <PasswordField label="Password" helperText="At least 8 characters" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} inputProps={{ minLength: 8 }} required />
          {error && <Alert severity="error">{error}</Alert>}
          <Button type="submit" variant="contained" size="large">
            Create account
          </Button>
          <Typography variant="body2" align="center">
            Already registered?{' '}
            <Link component={RouterLink} to="/login">
              Sign in
            </Link>
          </Typography>
        </Stack>
      </form>
    </Shell>
  )
}

export function VerifyEmail() {
  const [params] = useSearchParams()
  const [state, setState] = useState<'working' | 'ok' | string>('working')
  useEffect(() => {
    const token = params.get('token')
    if (!token) return setState('Missing token')
    api.post('/auth/verify-email', { token }).then(() => setState('ok')).catch((e) => setState(errorMessage(e)))
  }, [params])
  return (
    <Shell title="Email verification">
      {state === 'working' && <Typography>Verifying…</Typography>}
      {state === 'ok' && <Alert severity="success" sx={{ mb: 2 }}>Your email is verified.</Alert>}
      {state !== 'working' && state !== 'ok' && <Alert severity="error" sx={{ mb: 2 }}>{state}</Alert>}
      <Button component={RouterLink} to="/login" variant="contained" fullWidth>
        Continue to sign in
      </Button>
    </Shell>
  )
}

export function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<{ token?: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  return (
    <Shell title="Reset your password" subtitle="We'll email you a one-time link, valid for one hour.">
      {sent ? (
        <Alert severity="success">
          If the address is registered, a reset link is on its way.
          {sent.token && (
            <>
              {' '}Development mode: <Link component={RouterLink} to={`/reset-password?token=${sent.token}`}>open link</Link>
            </>
          )}
        </Alert>
      ) : (
        <form
          onSubmit={async (e) => {
            e.preventDefault()
            try {
              const r = await api.post<{ dev_reset_token?: string }>('/auth/forgot-password', { email })
              setSent({ token: r.dev_reset_token })
            } catch (err) {
              setError(errorMessage(err))
            }
          }}
        >
          <Stack spacing={2}>
            <TextField label="Work email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            {error && <Alert severity="error">{error}</Alert>}
            <Button type="submit" variant="contained">Send reset link</Button>
          </Stack>
        </form>
      )}
      <Box sx={{ mt: 2 }}>
        <Link component={RouterLink} to="/login" variant="body2">Back to sign in</Link>
      </Box>
    </Shell>
  )
}

export function ResetPassword() {
  const [params] = useSearchParams()
  const [password, setPassword] = useState('')
  const [state, setState] = useState<'form' | 'ok'>('form')
  const [error, setError] = useState<string | null>(null)
  return (
    <Shell title="Choose a new password">
      {state === 'ok' ? (
        <>
          <Alert severity="success" sx={{ mb: 2 }}>Password updated.</Alert>
          <Button component={RouterLink} to="/login" variant="contained" fullWidth>Sign in</Button>
        </>
      ) : (
        <form
          onSubmit={async (e) => {
            e.preventDefault()
            try {
              await api.post('/auth/reset-password', { token: params.get('token'), password })
              setState('ok')
            } catch (err) {
              setError(errorMessage(err))
            }
          }}
        >
          <Stack spacing={2}>
            <PasswordField label="New password" value={password} onChange={(e) => setPassword(e.target.value)} inputProps={{ minLength: 8 }} required />
            {error && <Alert severity="error">{error}</Alert>}
            <Button type="submit" variant="contained">Update password</Button>
          </Stack>
        </form>
      )}
    </Shell>
  )
}
