export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

const BASE = '/api/v1'
let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null
let onAuthLost: () => void = () => {}

/** Expiry of a JWT access token in ms since the epoch, or null when the value is not a readable JWT. */
export function tokenExpiry(token: string | null): number | null {
  if (!token) return null
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null
  } catch {
    return null
  }
}

// The access token lives 15 minutes. Renew it a minute BEFORE it runs out, so no request ever goes out with an expired one
// (that would show up as a failed 401 request in the browser console, even though the retry after a refresh works).
const REFRESH_EARLY_MS = 60_000
let refreshTimer: ReturnType<typeof setTimeout> | undefined

function scheduleRefresh() {
  clearTimeout(refreshTimer)
  const exp = tokenExpiry(accessToken)
  if (exp === null) return
  // a failed renewal changes nothing here: the next request meets the 401 and handles it (retry, or sign out when the session is really gone)
  refreshTimer = setTimeout(() => void refreshSession(), Math.max(exp - Date.now() - REFRESH_EARLY_MS, 5_000))
}

export const setToken = (t: string | null) => {
  accessToken = t
  scheduleRefresh()
}
export const getToken = () => accessToken
export const setAuthLostHandler = (fn: () => void) => {
  onAuthLost = fn
}

export async function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
    .then(async (r) => {
      if (!r.ok) return false
      setToken((await r.json()).access_token)
      return true
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

// a sleeping laptop or a long-hidden tab may have missed the timer: renew as soon as the page is shown again
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    const exp = tokenExpiry(accessToken)
    if (document.visibilityState === 'visible' && exp !== null && exp - Date.now() < REFRESH_EARLY_MS) void refreshSession()
  })
}

type Params = Record<string, string | number | boolean | undefined | null>

export function qs(params?: Params): string {
  if (!params) return ''
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

async function request<T>(method: string, path: string, body?: unknown, params?: Params, retried = false): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  const res = await fetch(`${BASE}${path}${qs(params)}`, {
    method,
    headers,
    credentials: 'include',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401 && !retried && !path.startsWith('/auth/')) {
    if (await refreshSession()) return request<T>(method, path, body, params, true)
    onAuthLost()
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    throw new ApiError(res.status, data?.code ?? 'error', data?.message ?? res.statusText, data?.details)
  }
  return data as T
}

export const api = {
  get: <T,>(path: string, params?: Params) => request<T>('GET', path, undefined, params),
  post: <T,>(path: string, body?: unknown, params?: Params) => request<T>('POST', path, body ?? {}, params),
  put: <T,>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  patch: <T,>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  del: <T,>(path: string) => request<T>('DELETE', path),
}

const FIELD_NAMES: Record<string, string> = {
  hours: 'Hours', eta_hours: 'Estimate', email: 'Email', password: 'Password', new_password: 'New password', name: 'Name', title: 'Title', note: 'Note',
  due_date: 'Due date', start_date: 'Start date', entry_date: 'Date', period_start: 'Start of the period', period_end: 'End of the period',
  company_name: 'Company name', message: 'Message', reason: 'Reason', body: 'Text', phone: 'Phone', bio: 'About you',
}

/** One validation failure from the server in plain words ("Hours must be more than 0.") instead of "hours: Input should be greater than 0". */
export function friendlyValidation(d: { loc: string[]; msg: string; type?: string; ctx?: Record<string, number | string> }): string {
  const key = d.loc[d.loc.length - 1] ?? ''
  const label = FIELD_NAMES[key] ?? (key ? key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()) : 'This field')
  const c = d.ctx ?? {}
  switch (d.type) {
    case 'missing': return `${label} is required.`
    case 'greater_than': return `${label} must be more than ${c.gt}.`
    case 'greater_than_equal': return `${label} must be ${c.ge} or more.`
    case 'less_than': return `${label} must be less than ${c.lt}.`
    case 'less_than_equal': return `${label} must be ${c.le} or less.`
    case 'string_too_short': return Number(c.min_length) <= 1 ? `${label} cannot be empty.` : `${label} must have at least ${c.min_length} characters.`
    case 'string_too_long': return `${label} can have at most ${c.max_length} characters.`
    case 'too_short': return `Add at least ${c.min_length} ${Number(c.min_length) === 1 ? 'item' : 'items'} to ${label.toLowerCase()}.`
    case 'string_pattern_mismatch': return `${label} is not in the expected format.`
    case 'date_from_datetime_parsing': case 'date_parsing': case 'date_type': return `${label} is not a valid date.`
    case 'int_parsing': case 'float_parsing': case 'int_type': case 'float_type': return `${label} must be a number.`
    case 'bool_parsing': return `${label} must be yes or no.`
    case 'value_error': return /email/i.test(d.msg) || key === 'email' ? 'Enter a valid email address, like name@company.com.' : `${label} is not valid.`
    default: return key === 'email' ? 'Enter a valid email address, like name@company.com.' : `${label} is not valid.`
  }
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'validation_error' && Array.isArray(e.details)) {
      return [...new Set((e.details as { loc: string[]; msg: string; type?: string; ctx?: Record<string, number | string> }[]).map(friendlyValidation))].join(' ')
    }
    if (e.details && typeof e.details === 'object' && !Array.isArray(e.details)) {
      return `${e.message}: ${Object.entries(e.details as Record<string, string>).map(([k, v]) => `${k} ${v}`).join(', ')}`
    }
    return e.message
  }
  return e instanceof Error ? e.message : 'Something went wrong'
}

/** Downloads an authenticated endpoint (e.g. the Markdown of a draft) as a file in the browser. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { credentials: 'include', headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, data?.code ?? 'error', data?.message ?? res.statusText)
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? fallbackName
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export interface StreamEvent {
  name: string
  data: any
}

/** POSTs to a server-sent-events endpoint and calls `onEvent` for every event as it arrives (fetch + ReadableStream, so the auth header carries over). */
export async function streamPost(path: string, body: unknown, onEvent: (e: StreamEvent) => void, retried = false): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}) },
    body: JSON.stringify(body),
  })
  if (res.status === 401 && !retried && (await refreshSession())) return streamPost(path, body, onEvent, true)
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, data?.code ?? 'error', data?.message ?? res.statusText)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i)
      buf = buf.slice(i + 2)
      const m = /^event: (\w+)\ndata: ([\s\S]*)$/.exec(block)
      if (m) onEvent({ name: m[1], data: JSON.parse(m[2]) })
    }
  }
}
