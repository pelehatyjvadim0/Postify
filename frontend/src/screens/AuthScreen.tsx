import * as React from 'react'
import { Loader2, Moon, Send, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, USE_MOCKS } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { useSession } from '@/lib/session'
import { supportLog } from '@/lib/support'
import { useTheme } from '@/lib/theme'
import type { LoginRequest, LoginStatus } from '@/lib/types'

// Вид и тексты взяты со страницы входа FakeTG (loginPage в
// mockups/telegram-web/storychat-telegram-auth.mjs).
const POLL_MS = 1500

export function AuthScreen() {
  const { signedIn } = useSession()
  const { theme, toggle } = useTheme()
  const [request, setRequest] = React.useState<LoginRequest | null>(null)
  const [status, setStatus] = React.useState<LoginStatus | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [starting, setStarting] = React.useState(false)

  const waiting = Boolean(request) && (status === 'pending' || status === 'confirmation')

  React.useEffect(() => {
    if (!request || !waiting) return
    let active = true
    let inFlight = false
    const timer = window.setInterval(async () => {
      if (!active || inFlight) return
      if (Date.now() >= Date.parse(request.expires_at)) {
        setStatus('expired')
        setError('Запрос на вход истёк')
        return
      }
      inFlight = true
      try {
        const result = await api.loginStatus(request.browser_token)
        if (!active) return
        supportLog('login_status', { status: result.status })
        setStatus(result.status)
        if (result.status === 'approved' && result.user && result.csrf) {
          active = false
          signedIn(result.user, result.csrf)
        }
        if (result.status === 'denied') {
          active = false
          setError('Авторизация не удалась')
        }
        if (result.status === 'expired') {
          active = false
          setError('Запрос на вход истёк')
        }
      } catch (caught) {
        if (!active) return
        // Истёкший или неизвестный запрос приходит как 404.
        if (caught instanceof ApiError && caught.isNotFound) {
          active = false
          setStatus('expired')
          setError('Запрос на вход истёк')
        } else if (caught instanceof ApiError && (caught.status === 403 || caught.status === 503)) {
          active = false
          setStatus('denied')
          setError(caught.message)
        }
      } finally {
        inFlight = false
      }
    }, POLL_MS)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [request, waiting, signedIn])

  async function start() {
    // Открываем вкладку прямо в обработчике клика: после await браузер
    // может заблокировать её как незапрошенное всплывающее окно.
    const telegram = window.open('about:blank', '_blank')
    if (telegram) telegram.opener = null
    setStarting(true)
    setError(null)
    setStatus(null)
    try {
      const created = await api.startLogin()
      supportLog('login_started', {
        expires_at: created.expires_at,
        // Исход входа на моках переключается ключом mock-login-outcome:
        // approved (по умолчанию), denied, expired.
        mock: USE_MOCKS,
      })
      setRequest(created)
      setStatus('pending')
      if (telegram && !telegram.closed) telegram.location.replace(created.telegram_url)
    } catch (caught) {
      telegram?.close()
      setError(
        caught instanceof ApiError ? caught.message : 'Не удалось начать вход',
      )
    } finally {
      setStarting(false)
    }
  }

  const failed = Boolean(error)

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <Button
        variant="outline"
        size="icon"
        onClick={toggle}
        title="Сменить тему"
        aria-label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
        className="absolute right-4 top-4"
      >
        {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </Button>

      <main className="w-full max-w-[420px] rounded-lg border border-border bg-card p-8 text-center">
        <p className="mb-4 text-[12px] font-bold text-muted-foreground">AutoPostTG</p>
        <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-md bg-secondary text-lg font-bold">
          A
        </div>
        <h1 className="text-[22px] font-semibold leading-tight tracking-tight">Вход в AutoPostTG</h1>

        {request && !failed ? (
          <>
            <p className="mx-auto mb-6 mt-2.5 max-w-[330px] text-[13px] leading-relaxed text-muted-foreground">
              Откройте бота и подтвердите, что вход выполняете вы.
            </p>
            <Button asChild className="w-full">
              <a href={request.telegram_url} target="_blank" rel="noreferrer">
                <Send className="h-4 w-4" />
                Открыть Telegram
              </a>
            </Button>
            <div className="mt-4 flex min-h-[42px] items-center justify-center gap-2.5 rounded-md border border-border bg-muted/40 px-3 py-2.5 text-[13px] text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>
                {status === 'confirmation'
                  ? 'Подтвердите вход в Telegram'
                  : 'Ожидаем подтверждение'}
              </span>
            </div>
          </>
        ) : failed ? (
          <>
            <p className="mx-auto mb-6 mt-2.5 max-w-[330px] text-[13px] leading-relaxed text-muted-foreground">
              Начните вход заново — ссылка действует 10 минут.
            </p>
            <div className="flex min-h-[42px] items-center justify-center rounded-md border border-red-200 bg-red-50/60 px-3 py-2.5 text-[13px] text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              {error}
            </div>
            <Button variant="ghost" className="mt-2.5 w-full" onClick={start} disabled={starting}>
              Попробовать снова
            </Button>
          </>
        ) : (
          <>
            <p className="mx-auto mb-6 mt-2.5 max-w-[330px] text-[13px] leading-relaxed text-muted-foreground">
              Бот отправит запрос на подтверждение входа в ваш аккаунт.
            </p>
            <Button className="w-full" onClick={start} disabled={starting}>
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              Войти через Telegram
            </Button>
          </>
        )}

      </main>
    </div>
  )
}
