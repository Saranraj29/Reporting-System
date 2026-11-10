import { ThemeProvider } from '@mui/material'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Feedback } from '../components/AssistantPanel'
import { theme } from '../theme'

const show = (onVote = vi.fn().mockResolvedValue(undefined), rating: 'up' | 'down' | null = null) => {
  render(<ThemeProvider theme={theme}><Feedback m={{ id: 'm1', role: 'assistant', text: 'Hello', rating }} onVote={onVote} /></ThemeProvider>)
  return onVote
}

describe('thumbs under an assistant answer', () => {
  it('lights the thumb, confirms it and sends the vote', async () => {
    const vote = show()
    const up = screen.getByRole('button', { name: 'Helpful answer' })
    expect(up).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(up)
    await waitFor(() => expect(up).toHaveAttribute('aria-pressed', 'true'))
    expect(vote).toHaveBeenCalledWith('m1', 'up', undefined)
    expect(screen.getByRole('status')).toHaveTextContent('Thanks for the feedback.')
    expect(screen.getByRole('button', { name: 'Not helpful' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('asks what was wrong after a thumbs-down and sends the chosen reason', async () => {
    const vote = show()
    await userEvent.click(screen.getByRole('button', { name: 'Not helpful' }))
    await userEvent.click(await screen.findByText('Wrong or missing numbers'))
    await waitFor(() => expect(vote).toHaveBeenLastCalledWith('m1', 'down', 'Wrong or missing numbers'))
    expect(screen.getByRole('status')).toHaveTextContent('Thanks, this helps us improve.')
    expect(screen.queryByText('What was wrong? (optional)')).not.toBeInTheDocument()
  })

  it('says so when the vote could not be saved, and does not light the thumb', async () => {
    show(vi.fn().mockRejectedValue(new Error('offline')))
    const up = screen.getByRole('button', { name: 'Helpful answer' })
    await userEvent.click(up)
    expect(await screen.findByText('Could not save your feedback. Try again.')).toBeInTheDocument()
    expect(up).toHaveAttribute('aria-pressed', 'false')
  })

  it('shows an earlier vote as already chosen, and does not resend it', async () => {
    const vote = show(undefined, 'up')
    const up = screen.getByRole('button', { name: 'Helpful answer' })
    expect(up).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(up)
    expect(vote).not.toHaveBeenCalled()
  })
})
