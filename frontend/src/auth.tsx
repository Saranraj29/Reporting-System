import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, refreshSession, setAuthLostHandler, setToken } from './api'
import type { Me } from './types'

interface AuthState {
  me: Me | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  loginWithToken: (token: string) => Promise<void>
  logout: () => Promise<void>
  reload: () => Promise<void>
  can: (key: string) => boolean
  hasAny: (...bases: string[]) => boolean
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setMe(await api.get<Me>('/me'))
  }, [])

  useEffect(() => {
    setAuthLostHandler(() => setMe(null))
    ;(async () => {
      try {
        if (await refreshSession()) await reload()
      } catch {
        setMe(null)
      } finally {
        setLoading(false)
      }
    })()
  }, [reload])

  const value = useMemo<AuthState>(() => {
    const perms = new Set(me?.permissions ?? [])
    return {
      me,
      loading,
      reload,
      login: async (email, password) => {
        const r = await api.post<{ access_token: string }>('/auth/login', { email, password })
        setToken(r.access_token)
        await reload()
      },
      loginWithToken: async (token) => {
        setToken(token)
        await reload()
      },
      logout: async () => {
        await api.post('/auth/logout').catch(() => undefined)
        setToken(null)
        setMe(null)
      },
      can: (key) => perms.has(key),
      // true if the user holds the base key at any scope (task.view -> task.view.own/.team/.all) or the exact key
      hasAny: (...bases) => bases.some((b) => perms.has(b) || ['own', 'team', 'all'].some((s) => perms.has(`${b}.${s}`))),
    }
  }, [me, loading, reload])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth outside AuthProvider')
  return v
}
