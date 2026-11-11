export const fmtDate = (d?: string | null) =>
  d ? new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
export const fmtShort = (d?: string | null) =>
  d ? new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '—'
export const fmtDateTime = (d?: string | null) =>
  d ? new Date(d).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'
/** A length of time from hours, the way people say it: "45m", "2h", "1h 30m". Under a minute: "<1m". */
export const hours = (n: number) => {
  if (!(n > 0)) return '0m'
  const minutes = Math.round(n * 60)
  if (minutes < 1) return '<1m'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h === 0 ? `${m}m` : m === 0 ? `${h}h` : `${h}h ${m}m`
}

/** What a person types into a Time box -> hours, or null when it is not a duration. Understands 1.5, 1:30, 90m, 45 min, 1h, 1h 30m, 2 hrs. */
export function parseDuration(text: string): number | null {
  const t = text.trim().toLowerCase()
  if (!t) return null
  let m = /^(\d+(?:\.\d+)?)$/.exec(t)  // a bare number is hours
  if (m) return Number(m[1])
  m = /^(\d+):([0-5]?\d)$/.exec(t)  // 1:30
  if (m) return Number(m[1]) + Number(m[2]) / 60
  m = /^(?:(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours))?\s*(?:(\d+(?:\.\d+)?)\s*(?:m|min|mins|minute|minutes))?$/.exec(t)  // 1h 30m, 90m, 2 hrs
  if (m && (m[1] || m[2])) return Number(m[1] ?? 0) + Number(m[2] ?? 0) / 60
  return null
}

/** The same duration written the way it can be typed back into a Time box. */
export const durationText = (n: number) => hours(n)
export const isoDay = (d: Date) => {
  const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
  return z.toISOString().slice(0, 10)
}
export const daysAgo = (n: number) => isoDay(new Date(Date.now() - n * 86400000))
export const today = () => isoDay(new Date())
export const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
export const titleCase = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
export const elapsed = (startIso: string, now: number) => {
  const s = Math.max(0, Math.floor((now - new Date(startIso).getTime()) / 1000))
  const h = String(Math.floor(s / 3600)).padStart(2, '0')
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0')
  const sec = String(s % 60).padStart(2, '0')
  return `${h}:${m}:${sec}`
}
/** The UI never names the LLM vendor: a draft is either AI-written or built from the figures only. */
export const providerLabel = (p?: string | null) => (p === 'figures_only' ? 'Figures only' : p ? 'AI draft' : '—')
export const isAi = (p?: string | null) => !!p && p !== 'figures_only'
export const clock = (d?: string | null) => (d ? new Date(d).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '')
export const ago = (d: string) => {
  const s = Math.max(0, Math.floor((Date.now() - new Date(d).getTime()) / 1000))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return fmtDateTime(d)
}
