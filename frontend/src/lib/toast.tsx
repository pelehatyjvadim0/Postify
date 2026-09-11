import * as React from 'react'
import { CheckCircle2, X, XCircle } from 'lucide-react'
import { cn } from './utils'

interface Toast {
  id: number
  tone: 'ok' | 'error'
  text: string
}

const ToastContext = React.createContext<{
  ok: (text: string) => void
  error: (text: string) => void
}>({ ok: () => {}, error: () => {} })

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<Toast[]>([])

  const push = React.useCallback((tone: Toast['tone'], text: string) => {
    const id = Date.now() + Math.random()
    setItems((list) => [...list, { id, tone, text }])
    setTimeout(() => setItems((list) => list.filter((item) => item.id !== id)), 6000)
  }, [])

  const value = React.useMemo(
    () => ({ ok: (text: string) => push('ok', text), error: (text: string) => push('error', text) }),
    [push],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[360px] flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            className={cn(
              'pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-card px-3 py-2.5 shadow-2xl animate-zoom-in',
              item.tone === 'error'
                ? 'border-red-200 dark:border-red-500/30'
                : 'border-border',
            )}
          >
            {item.tone === 'error' ? (
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
            ) : (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            )}
            <p className="min-w-0 flex-1 text-[13px] leading-relaxed">{item.text}</p>
            <button
              onClick={() => setItems((list) => list.filter((x) => x.id !== item.id))}
              className="grid h-5 w-5 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => React.useContext(ToastContext)
