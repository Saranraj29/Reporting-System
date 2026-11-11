import { ThemeProvider } from '@mui/material'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setToken } from '../api'
import DeleteDialog from '../components/DeleteDialog'
import { theme } from '../theme'

const json = (status: number, body: unknown) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { vi.restoreAllMocks(); setToken(null) })

const show = () => {
  const onDeleted = vi.fn()
  const onClose = vi.fn()
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
        <DeleteDialog title="Delete Apollo?" description="The project is removed." path="/projects/p1" onClose={onClose} onDeleted={onDeleted} />
      </QueryClientProvider>
    </ThemeProvider>,
  )
  return { onDeleted, onClose }
}

describe('delete confirmation', () => {
  it('deletes straight away when nothing else would go', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(204, null))
    const { onDeleted, onClose } = show()
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
    expect(onClose).toHaveBeenCalled()
    expect(String(f.mock.calls[0][0])).toMatch(/\/projects\/p1$/)
    expect(f.mock.calls[0][1]?.method).toBe('DELETE')
  })

  it('says what would go along and asks once more, then deletes with force', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(409, { code: 'in_use', message: 'Apollo has 12 tasks and 40 h logged.' }))
      .mockResolvedValueOnce(json(204, null))
    const { onDeleted } = show()
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText('Apollo has 12 tasks and 40 h logged.')).toBeInTheDocument()
    expect(onDeleted).not.toHaveBeenCalled()  // nothing was deleted yet
    await userEvent.click(screen.getByRole('button', { name: 'Delete anyway' }))
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
    expect(String(f.mock.calls[1][0])).toMatch(/\/projects\/p1\?force=true$/)
  })

  it('explains why something cannot be deleted and offers no way around it', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(409, { code: 'has_history', message: 'Mia has work history. Deactivate the account instead.' }))
    const { onDeleted } = show()
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText(/Deactivate the account instead/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Delete/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
    expect(onDeleted).not.toHaveBeenCalled()
  })

  it('shows any other error and keeps the dialog open', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(403, { code: 'forbidden', message: 'You do not have permission' }))
    const { onDeleted, onClose } = show()
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText('You do not have permission')).toBeInTheDocument()
    expect(onDeleted).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })
})
