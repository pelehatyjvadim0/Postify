import { Moon, Sun } from 'lucide-react'
import type * as React from 'react'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/lib/theme'

export function AppHeader({
  title,
  children,
  actions,
}: {
  title: string
  children?: React.ReactNode
  actions?: React.ReactNode
}) {
  const { theme, toggle } = useTheme()
  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border px-6">
      <h1 className="shrink-0 text-sm font-semibold tracking-tight">{title}</h1>
      {children}
      <div className="ml-auto flex items-center gap-2">
        {actions}
        <Button
          variant="outline"
          size="icon"
          title="Сменить тему"
          aria-label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
          onClick={toggle}
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </header>
  )
}
