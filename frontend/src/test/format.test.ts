import { describe, expect, it } from 'vitest'
import { elapsed, hours, initials, isoDay, parseDuration, titleCase } from '../format'

describe('format helpers', () => {
  it('shows time in hours and minutes, so one minute is not "0h"', () => {
    expect(hours(1 / 60)).toBe('1m')
    expect(hours(0.0167)).toBe('1m')
    expect(hours(0.25)).toBe('15m')
    expect(hours(1)).toBe('1h')
    expect(hours(1.5)).toBe('1h 30m')
    expect(hours(2.456)).toBe('2h 27m')
    expect(hours(10.7)).toBe('10h 42m')
    expect(hours(0.001)).toBe('<1m')
    expect(hours(0)).toBe('0m')
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

describe('typing a duration', () => {
  it('understands the usual ways to write it', () => {
    expect(parseDuration('1.5')).toBe(1.5)
    expect(parseDuration('1:30')).toBe(1.5)
    expect(parseDuration('90m')).toBe(1.5)
    expect(parseDuration('45 min')).toBeCloseTo(0.75)
    expect(parseDuration('1h')).toBe(1)
    expect(parseDuration('1h 30m')).toBe(1.5)
    expect(parseDuration('2 hrs 15 mins')).toBeCloseTo(2.25)
    expect(parseDuration('1m')).toBeCloseTo(1 / 60)
  })
  it('refuses what is not a time', () => {
    for (const bad of ['', 'abc', '-5', '1h30x', 'h', '1:75']) expect(parseDuration(bad), bad).toBeNull()
  })
})
