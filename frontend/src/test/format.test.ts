import { describe, expect, it } from 'vitest'
import { elapsed, hours, initials, isoDay, titleCase } from '../format'

describe('format helpers', () => {
  it('rounds hours to one decimal', () => {
    expect(hours(2.456)).toBe('2.5h')
    expect(hours(0)).toBe('0h')
  })
  it('builds initials from the first two words', () => {
    expect(initials('Priya Nair Kumar')).toBe('PN')
    expect(initials('madonna')).toBe('M')
  })
  it('title-cases snake_case values', () => {
    expect(titleCase('in_progress')).toBe('In progress')
  })
  it('formats elapsed timer time', () => {
    const start = new Date('2026-01-01T10:00:00Z').toISOString()
    expect(elapsed(start, new Date('2026-01-01T11:02:03Z').getTime())).toBe('01:02:03')
    expect(elapsed(start, new Date('2026-01-01T09:00:00Z').getTime())).toBe('00:00:00') // never negative
  })
  it('formats local calendar days', () => {
    expect(isoDay(new Date(2026, 0, 5, 23, 30))).toBe('2026-01-05')
  })
})
