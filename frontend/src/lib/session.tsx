import * as React from 'react'
import { api, hasCsrfToken, restoreCsrfToken, setCsrfToken, setSessionLostHandler } from './api'
import { ApiError } from './errors'
import { supportLog } from './support'
import type { User } from './types'

interface SessionValue {
  user: User | null
  loading: boolean
  /** Вызывается, когда статус входа пришёл со значением approved. */
  signedIn: (user: User, csrf: string) => void
  logout: () => Promise<void>
  setUser: (user: User) => void
}

const SessionContext = React.createContext<SessionValue>(null as unknown as SessionValue)

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<User | null>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    restoreCsrfToken()
    api
      .me()
      .then((loaded) => {
        if (hasCsrfToken()) {
          setUser(loaded)
          return
        }
        // Кука жива, а токен защиты потерян (очищено хранилище, приватный
        // режим). Без него не пройдёт ни одно изменение, включая выход, —
        // поэтому сразу отправляем на вход, а не в неработающий интерфейс.
        supportLog('session_without_csrf', { user_id: loaded.id })
        setUser(null)
      })
      .catch((error) => {
        // 401 — обычное состояние до входа, а не сбой.
        if (!(error instanceof ApiError && error.isUnauthorized)) console.error(error)
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, [])

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
    [user, loading],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export const useSession = () => React.useContext(SessionContext)
