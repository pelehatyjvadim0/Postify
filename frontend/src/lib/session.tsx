import * as React from 'react'
import { api, restoreCsrfToken, setCsrfToken, setSessionLostHandler } from './api'
import { ApiError } from './errors'
import type { User } from './types'

interface SessionValue {
  user: User | null
  loading: boolean
  error: string | null
  retry: () => void
  /** Вызывается, когда статус входа пришёл со значением approved. */
  signedIn: (user: User, csrf: string) => void
  logout: () => Promise<void>
  setUser: (user: User) => void
}

const SessionContext = React.createContext<SessionValue>(null as unknown as SessionValue)

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<User | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [attempt, setAttempt] = React.useState(0)

  React.useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    restoreCsrfToken()
    api
      .me()
      .then((loaded) => {
        if (active) setUser(loaded)
      })
      .catch((caught) => {
        if (!active) return
        if (caught instanceof ApiError && caught.isUnauthorized) {
          setUser(null)
          setCsrfToken(null)
        } else {
          setError('Не удалось подключиться к серверу. Повторите подключение.')
        }
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [attempt])

  React.useEffect(() => {
    setSessionLostHandler(() => {
      setCsrfToken(null)
      setUser(null)
    })
    return () => setSessionLostHandler(null)
  }, [])

  const value = React.useMemo<SessionValue>(
    () => ({
      user,
      loading,
      error,
      retry: () => setAttempt((value) => value + 1),
      setUser,
      signedIn: (signedUser, csrf) => {
        setCsrfToken(csrf)
        setUser(signedUser)
      },
      logout: async () => {
        // Даже если запрос не прошёл, из интерфейса выходим: держать человека
        // в сессии, из которой он просил выйти, нельзя.
        try {
          await api.logout()
        } finally {
          setCsrfToken(null)
          setUser(null)
        }
      },
    }),
    [user, loading, error],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export const useSession = () => React.useContext(SessionContext)
