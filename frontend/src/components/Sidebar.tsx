import { Calendar, ChevronsUpDown, Image, List, Plus, Settings, X } from 'lucide-react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as React from 'react'
import { useNav } from '@/lib/nav'
import { navigate, type Screen } from '@/lib/router'
import type { Project, ProjectSummary } from '@/lib/types'
import { cn } from '@/lib/utils'

const NAV: { screen: Screen; label: string; Icon: typeof Calendar }[] = [
  { screen: 'plan', label: 'Контент-план', Icon: Calendar },
  { screen: 'posts', label: 'Посты', Icon: List },
  { screen: 'media', label: 'Изображения', Icon: Image },
  { screen: 'settings', label: 'Настройки', Icon: Settings },
]

export function Sidebar({
  projects,
  project,
  current,
  onSelectProject,
  onCreateProject,
}: {
  projects: ProjectSummary[]
  project: Project | null
  current: Screen
  onSelectProject: (id: number) => void
  onCreateProject: () => void
}) {
  const { open, setOpen } = useNav()
  const wasOpen = React.useRef(false)
  const summary = projects.find((item) => item.id === project?.id)
  const initials = (project?.name ?? '—')
    .split(' ')
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? '')
    .join('')
  React.useEffect(() => {
    if (open) {
      wasOpen.current = true
      return
    }
    if (wasOpen.current) document.querySelector<HTMLElement>('[aria-label="Открыть меню"]')?.focus()
    wasOpen.current = false
  }, [open])

  return (
    <>
      {/* На узком экране панель выезжает поверх содержимого. */}
      {open && (
        <button
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          aria-label="Закрыть меню"
          onClick={() => setOpen(false)}
        />
      )}
      <aside
        className={cn(
          'flex w-60 shrink-0 flex-col border-r border-border bg-background',
          'max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:w-[min(17rem,82vw)] max-md:transition-transform',
          !open && 'max-md:-translate-x-full',
        )}
      >
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <div className="grid h-6 w-6 place-items-center rounded bg-primary text-[11px] font-semibold text-primary-foreground">
          A
        </div>
        <span className="text-sm font-semibold tracking-tight">AutoPostTG</span>
        <button
          className="ml-auto grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground md:hidden"
          title="Закрыть меню"
          aria-label="Закрыть меню"
          onClick={() => setOpen(false)}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="p-3">
        <DropdownMenu.Root>
          <DropdownMenu.Trigger className="flex w-full items-center gap-2 rounded-md border border-border px-3 py-2 text-sm transition-colors hover:bg-accent">
            <span className="grid h-6 w-6 place-items-center rounded bg-muted text-[11px] font-medium">
              {initials}
            </span>
            <span className="flex-1 truncate text-left font-medium">{project?.name ?? 'Проект'}</span>
            <ChevronsUpDown className="h-4 w-4 text-muted-foreground" />
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="start"
              sideOffset={4}
              className="z-50 w-[216px] rounded-md border border-border bg-popover p-1 shadow-lg animate-fade-in"
            >
              {projects.map((item) => (
                <DropdownMenu.Item
                  key={item.id}
                  onSelect={() => {
                    onSelectProject(item.id)
                    setOpen(false)
                  }}
                  className={cn(
                    'flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] outline-none focus:bg-accent',
                    item.id === project?.id && 'bg-accent/60',
                  )}
                >
                  <span className="flex-1 truncate">{item.name}</span>
                  {item.counts.needs_review > 0 && (
                    <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300">
                      {item.counts.needs_review}
                    </span>
                  )}
                </DropdownMenu.Item>
              ))}
              <DropdownMenu.Separator className="my-1 h-px bg-border" />
              <DropdownMenu.Item onSelect={() => { onCreateProject(); setOpen(false) }} className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] outline-none focus:bg-accent">
                <Plus className="h-4 w-4" /> Создать проект
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>

      <nav className="space-y-1 px-3 text-sm">
        {NAV.map(({ screen, label, Icon }) => (
          <button
            key={screen}
            onClick={() => {
              navigate(screen)
              setOpen(false)
            }}
            className={cn(
              'flex w-full items-center gap-2.5 rounded-md px-3 py-2 transition-colors',
              current === screen
                ? 'bg-secondary font-medium'
                : 'text-muted-foreground hover:bg-accent hover:text-foreground',
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
            {screen === 'posts' && summary && summary.counts.needs_review > 0 && (
              <span className="ml-auto rounded bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-secondary-foreground">
                {summary.counts.needs_review}
              </span>
            )}
            {screen === 'plan' && summary && summary.counts.no_topic > 0 && (
              <span className="ml-auto rounded bg-red-500/15 px-1.5 py-0.5 text-[11px] font-medium text-red-700 dark:text-red-300">
                {summary.counts.no_topic}
              </span>
            )}
          </button>
        ))}
      </nav>

      </aside>
    </>
  )
}
