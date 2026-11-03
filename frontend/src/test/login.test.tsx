import { ThemeProvider } from '@mui/material'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setToken } from '../api'
import { AuthProvider, useAuth } from '../auth'
import { Login } from '../pages/Auth'
import { theme } from '../theme'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => {
  vi.restoreAllMocks()
  setToken(null)
})

function Probe() {
  const { hasAny, can } = useAuth()
  return <div>{`reports:${hasAny('report.weekly.view')} approve:${can('report.approve')}`}</div>
}

const wrap = (ui: React.ReactNode) =>
  render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </ThemeProvider>,
  )

describe('Login', () => {
  it('shows the server error for bad credentials', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/auth/refresh')) return json(401, { code: 'unauthorized', message: 'No refresh token' })
      return json(401, { code: 'invalid_credentials', message: 'Incorrect email or password' })
    })
    wrap(<Login />)
    await userEvent.type(await screen.findByLabelText(/Work email/), 'a@acme.com')
    await userEvent.type(screen.getByLabelText(/Password/), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Incorrect email or password')).toBeInTheDocument()
  })
})

describe('permission helpers', () => {
  it('hasAny matches any scope of a base key; can needs the exact key', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/auth/refresh')) return json(200, { access_token: 't' })
      return json(200, { id: '1', email: 'l@acme.com', name: 'Lead', company: { id: 'c', name: 'Acme', timezone: 'UTC' }, roles: [], permissions: ['report.weekly.view.team'] })
    })
    wrap(<Probe />)
    await waitFor(() => expect(screen.getByText('reports:true approve:false')).toBeInTheDocument())
  })
})
