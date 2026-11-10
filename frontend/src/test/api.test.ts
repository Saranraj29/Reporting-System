import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, errorMessage, qs, setToken, tokenExpiry } from '../api'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => {
  vi.restoreAllMocks()
  setToken(null)
})

describe('qs', () => {
  it('skips empty values and encodes the rest', () => {
    expect(qs({ a: 1, b: '', c: undefined, d: 'x y', e: false })).toBe('?a=1&d=x+y&e=false')
    expect(qs({})).toBe('')
  })
})

describe('api client', () => {
  it('sends the bearer token and parses JSON', async () => {
    setToken('abc')
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, { ok: true }))
    expect(await api.get('/me')).toEqual({ ok: true })
    expect((f.mock.calls[0][1]!.headers as Record<string, string>).Authorization).toBe('Bearer abc')
  })

  it('refreshes once on 401 and retries the request', async () => {
    setToken('expired')
    const f = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(401, { code: 'unauthorized', message: 'expired' }))
      .mockResolvedValueOnce(json(200, { access_token: 'fresh' })) // POST /auth/refresh
      .mockResolvedValueOnce(json(200, { name: 'Priya' }))
    expect(await api.get('/me')).toEqual({ name: 'Priya' })
    expect(f).toHaveBeenCalledTimes(3)
    expect(String(f.mock.calls[1][0])).toContain('/auth/refresh')
    expect((f.mock.calls[2][1]!.headers as Record<string, string>).Authorization).toBe('Bearer fresh')
  })

  it('turns the error envelope into ApiError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(409, { code: 'timer_running', message: 'Stop your running timer', details: null }))
    await expect(api.post('/time-entries/start', {})).rejects.toMatchObject({ status: 409, code: 'timer_running' })
  })

  it('handles 204 responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }))
    expect(await api.del('/tasks/1')).toBeUndefined()
  })
})

describe('renewing the access token before it expires', () => {
  const jwt = (expMs: number) => `h.${btoa(JSON.stringify({ exp: Math.floor(expMs / 1000) })).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')}.s`

  it('reads the expiry of a JWT and ignores anything else', () => {
    expect(tokenExpiry(jwt(1_800_000_000_000))).toBe(1_800_000_000_000)
    expect(tokenExpiry('abc')).toBeNull()
    expect(tokenExpiry(null)).toBeNull()
  })

  it('refreshes a minute before expiry, without waiting for a 401, and schedules the next renewal', async () => {
    vi.useFakeTimers()
    try {
      vi.setSystemTime(new Date('2026-11-10T10:00:00Z'))
      const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, { access_token: jwt(Date.now() + 15 * 60_000 + 15 * 60_000) }))
      setToken(jwt(Date.now() + 15 * 60_000))
      await vi.advanceTimersByTimeAsync(13 * 60_000)  // 2 minutes left: nothing yet
      expect(f).not.toHaveBeenCalled()
      await vi.advanceTimersByTimeAsync(61_000)  // inside the last minute
      expect(f).toHaveBeenCalledTimes(1)
      expect(String(f.mock.calls[0][0])).toContain('/auth/refresh')
      await vi.advanceTimersByTimeAsync(15 * 60_000)  // and the fresh token is renewed in turn
      expect(f.mock.calls.length).toBeGreaterThanOrEqual(2)
    } finally {
      setToken(null)
      vi.useRealTimers()
    }
  })

  it('does not schedule anything for a token that is not a JWT, nor after sign-out', async () => {
    vi.useFakeTimers()
    try {
      const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, { access_token: 'x' }))
      setToken('abc')
      setToken(null)
      await vi.advanceTimersByTimeAsync(60 * 60_000)
      expect(f).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('errorMessage', () => {
  it('flattens validation errors', () => {
    const e = new ApiError(422, 'validation_error', 'Invalid request', [{ loc: ['body', 'title'], msg: 'String should have at least 1 character' }])
    expect(errorMessage(e)).toBe('title: String should have at least 1 character')
  })
  it('appends per-field details', () => {
    const e = new ApiError(400, 'invalid_custom_fields', 'Custom field validation failed', { ticket_ref: 'required' })
    expect(errorMessage(e)).toBe('Custom field validation failed: ticket_ref required')
  })
  it('falls back for unknown errors', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom')
    expect(errorMessage('x')).toBe('Something went wrong')
  })
})
