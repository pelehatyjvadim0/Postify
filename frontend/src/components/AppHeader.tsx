import { Menu, Moon, Sun } from 'lucide-react'
import type * as React from 'react'
import { Button } from '@/components/ui/button'
import { useNav } from '@/lib/nav'
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
  const { setOpen } = useNav()
  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-2 md:h-14 md:flex-nowrap md:px-6 md:py-0">
      <Button
        variant="ghost"
        size="icon-sm"
        className="md:hidden"
        title="Меню"
        aria-label="Открыть меню"
        onClick={() => setOpen(true)}
      >
        <Menu className="h-4 w-4" />
      </Button>
      <h1 className="shrink-0 text-sm font-semibold tracking-tight">{title}</h1>
      <div className="ml-auto flex flex-wrap items-center justify-end gap-2 md:order-last md:flex-nowrap">
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
      {children}
    </header>
  )
}
