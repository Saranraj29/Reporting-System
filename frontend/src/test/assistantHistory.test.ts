import { describe, expect, it } from 'vitest'
import { groupConversations, makeTitle, TITLE_LENGTH } from '../assistantHistory'
import type { AssistantConversation } from '../types'

const conv = (id: string, updated: string): AssistantConversation => ({ id, title: id, updated_at: updated, message_count: 2 })
const now = new Date(2026, 10, 10, 15, 0, 0)  // 10 Nov 2026, 15:00 local

describe('assistant history grouping', () => {
  it('groups by day like a chat app and drops empty groups', () => {
    const groups = groupConversations([
      conv('a', new Date(2026, 10, 10, 9, 0).toISOString()),
      conv('b', new Date(2026, 10, 9, 23, 30).toISOString()),
      conv('c', new Date(2026, 10, 5, 8, 0).toISOString()),
      conv('d', new Date(2026, 9, 1, 8, 0).toISOString()),
    ], now)
    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ['Today', ['a']], ['Yesterday', ['b']], ['Previous 7 days', ['c']], ['Older', ['d']],
    ])
    expect(groupConversations([conv('x', new Date(2026, 10, 10, 1, 0).toISOString())], now).map((g) => g.label)).toEqual(['Today'])
    expect(groupConversations([], now)).toEqual([])
  })

  it('keeps the incoming (newest first) order inside a group', () => {
    const g = groupConversations([conv('late', new Date(2026, 10, 10, 14, 0).toISOString()), conv('early', new Date(2026, 10, 10, 8, 0).toISOString())], now)
    expect(g[0].items.map((i) => i.id)).toEqual(['late', 'early'])
  })
})

describe('conversation titles', () => {
  it('puts the first question on one line and shortens a long one', () => {
    expect(makeTitle('  Why is   Apollo\n late? ')).toBe('Why is Apollo late?')
    const long = makeTitle('word '.repeat(40))
    expect(long.length).toBeLessThanOrEqual(TITLE_LENGTH)
    expect(long.endsWith('…')).toBe(true)
  })
})
