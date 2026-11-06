import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'
import type { Page, Team, UserLite } from './types'

export const SEARCH_MIN = 3

/** Search boxes call the API only once 3 or more characters are typed (and again when the box is emptied or cut below 3, to reset the list). */
export function useSearch(delay = 300) {
  const [input, setInput] = useState('')
  const [term, setTerm] = useState('')
  useEffect(() => {
    const next = input.trim().length >= SEARCH_MIN ? input.trim() : ''
    if (next === term) return
    const t = setTimeout(() => setTerm(next), next ? delay : 0)
    return () => clearTimeout(t)
  }, [input]) // eslint-disable-line react-hooks/exhaustive-deps
  return { input, setInput, term }
}

export function useUsers() {
  return useQuery({ queryKey: ['users', 'all'], queryFn: () => api.get<Page<UserLite>>('/users', { limit: 200 }) }).data?.items ?? []
}

export function useTeams() {
  return useQuery({ queryKey: ['teams', ''], queryFn: () => api.get<{ items: Team[] }>('/teams') }).data?.items ?? []
}
