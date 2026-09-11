import { Calendar, ChevronsUpDown, Image, List, Settings } from 'lucide-react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
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
}: {
  projects: ProjectSummary[]
  project: Project | null
  current: Screen
  onSelectProject: (id: number) => void
}) {
  const summary = projects.find((item) => item.id === project?.id)
  const initials = (project?.name ?? '—')
    .split(' ')
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? '')
    .join('')
  const media = project?.media
  const share = media && media.total > 0 ? Math.round((media.available / media.total) * 100) : 0

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border">
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <div className="grid h-6 w-6 place-items-center rounded bg-primary text-[11px] font-semibold text-primary-foreground">
          A
        </div>
        <span className="text-sm font-semibold tracking-tight">AutoPostTG</span>
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
                  onSelect={() => onSelectProject(item.id)}
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
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>

      <nav className="space-y-1 px-3 text-sm">
        {NAV.map(({ screen, label, Icon }) => (
          <button
            key={screen}
            onClick={() => navigate(screen)}
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

      {media && (
        <div className="mt-auto p-3">
          <div className="rounded-lg border border-border p-3">
            <div className="mb-2 flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Пул изображений</span>
              <span className="font-medium tabular-nums">{media.total}</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
              <div className="h-full rounded-full bg-primary" style={{ width: `${share}%` }} />
            </div>
            <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
              {media.available} доступны, {media.total - media.available} недавно выходили или
              без описания
            </p>
          </div>
        </div>
      )}
    </aside>
  )
}
