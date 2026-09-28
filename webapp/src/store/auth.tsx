import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { api, ApiError, setAccessToken, setUnauthorizedHandler } from '../lib/api'
import { getInitData, isTelegram } from '../lib/telegram'
import type { AuthResponse, User } from '../lib/types'

interface AuthState {
  user: User | null
  isAdmin: boolean
  loading: boolean
  error: string | null
  /** true when we are inside Telegram but initData is empty (stale Web App). */
  needsReopen: boolean
  login: () => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
  patchUser: (patch: Partial<User>) => void
}

const AuthContext = createContext<AuthState | null>(null)

const TOKEN_KEY = 'vpn.token'
const USER_KEY = 'vpn.user'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => readJson<User>(USER_KEY))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [needsReopen, setNeedsReopen] = useState(false)
  const booted = useRef(false)

  const login = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const initData = getInitData()
      if (!initData) {
        // Outside Telegram (or a stale Web App) we cannot authenticate at all.
        setNeedsReopen(true)
        setError(
          isTelegram
            ? 'Данные авторизации устарели. Перезапустите приложение.'
            : 'Приложение работает только внутри Telegram.',
        )
        return
      }
      const response = await api.post<AuthResponse>('/auth/telegram', { init_data: initData }, { anonymous: true })
      setAccessToken(response.token.access_token)
      localStorage.setItem(TOKEN_KEY, response.token.access_token)
      localStorage.setItem(USER_KEY, JSON.stringify(response.user))
      setUser(response.user)
      setNeedsReopen(false)
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Не удалось войти'
      setError(message)
      setAccessToken(null)
      localStorage.removeItem(TOKEN_KEY)
    } finally {
      setLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    setAccessToken(null)
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setUser(null)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<User>('/auth/me')
      setUser(me)
      localStorage.setItem(USER_KEY, JSON.stringify(me))
    } catch {
      /* keep the cached profile */
    }
  }, [])

  const patchUser = useCallback((patch: Partial<User>) => {
    setUser((current) => (current ? { ...current, ...patch } : current))
  }, [])

  // Restore a token from a previous session so a warm start skips /auth/telegram.
  useEffect(() => {
    if (booted.current) return
    booted.current = true
    setAccessToken(localStorage.getItem(TOKEN_KEY))
    void login()
  }, [login])

  // A 401 anywhere means the token is no longer valid — start over.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAccessToken(null)
      localStorage.removeItem(TOKEN_KEY)
      void login()
    })
  }, [login])

  const value = useMemo<AuthState>(
    () => ({
      user,
      isAdmin: Boolean(user?.is_admin),
      loading,
      error,
      needsReopen,
      login,
      logout,
      refresh,
      patchUser,
    }),
    [user, loading, error, needsReopen, login, logout, refresh, patchUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}

function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}
