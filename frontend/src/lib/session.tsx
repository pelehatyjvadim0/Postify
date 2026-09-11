import * as React from 'react'
import { api, restoreCsrfToken, setCsrfToken } from './api'
import { ApiError } from './errors'
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
      .then(setUser)
      .catch((error) => {
        // 401 — обычное состояние до входа, а не сбой.
        if (!(error instanceof ApiError && error.isUnauthorized)) console.error(error)
        setUser(null)
      })
      .finally(() => setLoading(false))
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
        await api.logout()
        setCsrfToken(null)
        setUser(null)
      },
    }),
    [user, loading],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export const useSession = () => React.useContext(SessionContext)
