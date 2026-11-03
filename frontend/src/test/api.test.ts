import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, errorMessage, qs, setToken } from '../api'

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
