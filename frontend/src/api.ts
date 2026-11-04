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

export const setToken = (t: string | null) => {
  accessToken = t
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

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'validation_error' && Array.isArray(e.details)) {
      return (e.details as { loc: string[]; msg: string }[]).map((d) => `${d.loc.slice(1).join('.')}: ${d.msg}`).join('; ')
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
