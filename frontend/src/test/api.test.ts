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
  it('says validation errors in plain words', () => {
    const v = (loc: string, type: string, msg: string, ctx: Record<string, number | string> = {}) => new ApiError(422, 'validation_error', 'Invalid request', [{ loc: ['body', loc], msg, type, ctx }])
    expect(errorMessage(v('title', 'string_too_short', 'String should have at least 1 character', { min_length: 1 }))).toBe('Title cannot be empty.')
    expect(errorMessage(v('hours', 'greater_than', 'Input should be greater than 0', { gt: 0 }))).toBe('Hours must be more than 0.')
    expect(errorMessage(v('eta_hours', 'greater_than_equal', 'Input should be greater than or equal to 0', { ge: 0 }))).toBe('Estimate must be 0 or more.')
    expect(errorMessage(v('hours', 'less_than_equal', 'Input should be less than or equal to 24', { le: 24 }))).toBe('Hours must be 24 or less.')
    expect(errorMessage(v('password', 'string_too_short', 'String should have at least 8 characters', { min_length: 8 }))).toBe('Password must have at least 8 characters.')
    expect(errorMessage(v('name', 'missing', 'Field required'))).toBe('Name is required.')
    expect(errorMessage(v('email', 'value_error', 'value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email.'))).toBe('Enter a valid email address, like name@company.com.')
    expect(errorMessage(v('due_date', 'date_from_datetime_parsing', 'Input should be a valid date'))).toBe('Due date is not a valid date.')
  })
  it('joins several problems and never repeats one', () => {
    const e = new ApiError(422, 'validation_error', 'Invalid request', [
      { loc: ['body', 'hours'], msg: 'x', type: 'greater_than', ctx: { gt: 0 } }, { loc: ['body', 'title'], msg: 'y', type: 'missing' }, { loc: ['body', 'hours'], msg: 'x', type: 'greater_than', ctx: { gt: 0 } },
    ])
    expect(errorMessage(e)).toBe('Hours must be more than 0. Title is required.')
  })
  it('still copes with an older server that sends no rule type', () => {
    const e = new ApiError(422, 'validation_error', 'Invalid request', [{ loc: ['body', 'ticket_ref'], msg: 'whatever' }])
    expect(errorMessage(e)).toBe('Ticket ref is not valid.')
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
