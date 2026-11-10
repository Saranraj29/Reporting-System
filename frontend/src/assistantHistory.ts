import type { AssistantConversation } from './types'

/** Same rule as the server (service.make_title): the first question on one line, shortened. Used until the server's title is known. */
export const TITLE_LENGTH = 60
export function makeTitle(text: string): string {
  const one = text.split(/\s+/).filter(Boolean).join(' ')
  return one.length <= TITLE_LENGTH ? one : `${one.slice(0, TITLE_LENGTH - 1).trimEnd()}…`
}

export interface Group {
  label: string
  items: AssistantConversation[]
}

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()

/** The history list the way chat apps show it: Today, Yesterday, Previous 7 days, Older. Order inside a group is kept (newest first). */
export function groupConversations(items: AssistantConversation[], now = new Date()): Group[] {
  const today = startOfDay(now)
  const day = 86_400_000
  const buckets: Group[] = [
    { label: 'Today', items: [] },
    { label: 'Yesterday', items: [] },
    { label: 'Previous 7 days', items: [] },
    { label: 'Older', items: [] },
  ]
  for (const c of items) {
    const t = startOfDay(new Date(c.updated_at))
    const i = t >= today ? 0 : t >= today - day ? 1 : t >= today - 7 * day ? 2 : 3
    buckets[i].items.push(c)
  }
  return buckets.filter((b) => b.items.length > 0)
}
