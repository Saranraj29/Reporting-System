import { ThemeProvider } from '@mui/material'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { setToken } from '../api'
import AiUsagePage from '../pages/AiUsage'
import { theme } from '../theme'
import type { AiUsage } from '../types'

beforeAll(() => {
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver  // the charts measure their box
})
afterEach(() => { vi.restoreAllMocks(); setToken(null) })

const base: AiUsage = {
  period: 'month', since: '2026-11-01', status: 'ready', enabled: true, calls: 18, errors: 6, success_rate: 0.667,
  tokens: { input: 12000, output: 3313, cached: 0 }, budget_used_pct: null, budget_tokens: null, month_tokens: 15313,
  grounding_pass_rate: 1, fallback_rate: 0, repair_rate: 0.1, p95_latency_ms: 31300, latency_ms: { avg: 9000, p50: 8000, p95: 31300 },
  daily: [{ date: '2026-11-09', calls: 10, errors: 2, tokens: 8000 }, { date: '2026-11-10', calls: 8, errors: 4, tokens: 7313 }],
  by_feature: [{ name: 'assistant', calls: 12, errors: 5, tokens: 9000, avg_latency_ms: 7000 }, { name: 'report.write', calls: 6, errors: 1, tokens: 6313, avg_latency_ms: 12000 }],
  by_model: [{ name: 'anthropic · claude', calls: 18, errors: 6, tokens: 15313, avg_latency_ms: 9000 }],
  errors_by_code: [{ code: 'provider_error', count: 6 }],
  thumbs: { up: 0, down: 1 }, satisfaction: 0, thumbs_down_reasons: [{ reason: 'Not what I asked', count: 1 }],
  today: { turns: 3, reports: 1 }, quota: { reports_per_day: 50, turns_per_day: 500 },
}

const show = (data: AiUsage) => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AiUsagePage /></QueryClientProvider>
    </ThemeProvider>,
  )
}

describe('AI usage dashboard', () => {
  it('shows the headline numbers, the breakdown by feature and why calls failed', async () => {
    show(base)
    expect(await screen.findByText('AI calls')).toBeInTheDocument()
    expect(screen.getByText('6 failed')).toBeInTheDocument()
    expect(screen.getByText('67%')).toBeInTheDocument()  // success rate
    expect(screen.getAllByText('15.3K').length).toBeGreaterThan(0)  // tokens, compact (the tile and the monthly meter)
    expect(screen.getByText('8.0 s')).toBeInTheDocument()  // typical speed
    expect(screen.getByText('AI assistant')).toBeInTheDocument()  // friendly feature names
    expect(screen.getByText('AI reports · writing')).toBeInTheDocument()
    expect(screen.getByText('The AI service did not answer')).toBeInTheDocument()
    expect(screen.getByText('Not what I asked')).toBeInTheDocument()
    expect(screen.getByText('3 of 500')).toBeInTheDocument()  // assistant questions today against the limit
    expect(screen.getByRole('img', { name: /Calls per day, 18 in total, 6 failed/ })).toBeInTheDocument()
  })

  it('says so plainly when there has been no AI use yet', async () => {
    show({ ...base, calls: 0, errors: 0, success_rate: null, satisfaction: null, grounding_pass_rate: null, thumbs: { up: 0, down: 0 }, thumbs_down_reasons: [], errors_by_code: [], by_feature: [], by_model: [], daily: [], tokens: { input: 0, output: 0, cached: 0 }, latency_ms: { avg: null, p50: null, p95: null } })
    expect(await screen.findByText(/No AI calls in this period yet/)).toBeInTheDocument()
    expect(screen.getByText('No ratings in this period.')).toBeInTheDocument()
  })

  it('explains when AI is switched off', async () => {
    show({ ...base, status: 'off', enabled: false })
    expect(await screen.findByText(/AI is switched off for your company/)).toBeInTheDocument()
  })
})
