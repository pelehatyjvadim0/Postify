import { ChevronRight, Columns3, Plus } from 'lucide-react'
import type * as React from 'react'
import { Button } from '@/components/ui/button'
import {
  DOW,
  DOW_FULL,
  dayKey,
  daysInMonth,
  timeOf,
  weekdayIndex,
  shiftDays,
  ymd,
} from '@/lib/dates'
import { SLOT_STATUS } from '@/lib/status'
import type { Slot } from '@/lib/types'
import { cn } from '@/lib/utils'

export interface ViewProps {
  slots: Slot[]
  selectedId: number | null
  today: string
  onSelect: (slot: Slot) => void
  onAdd: (date: string) => void
  bindPeek: (slot: Slot) => {
    onMouseEnter: (event: React.MouseEvent<HTMLElement>) => void
    onMouseLeave: () => void
  }
}

const byTime = (a: Slot, b: Slot) => a.publish_at.localeCompare(b.publish_at)

function groupByDay(slots: Slot[]) {
  const map = new Map<string, Slot[]>()
  for (const slot of slots) {
    const key = dayKey(slot.publish_at)
    map.set(key, [...(map.get(key) ?? []), slot])
  }
  for (const list of map.values()) list.sort(byTime)
  return map
}

function dayTitle(date: string, today: string) {
  const [year, month, day] = date.split('-').map(Number)
  if (date === today) return 'Сегодня'
  return DOW_FULL[weekdayIndex(year, month, day)]
}

const MONTH_OF = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

export function ListView({ slots, selectedId, today, onSelect, onAdd, bindPeek }: ViewProps) {
  const groups = [...groupByDay(slots).entries()].sort((a, b) => a[0].localeCompare(b[0]))

  if (groups.length === 0)
    return (
      <div className="mx-auto max-w-3xl p-4 md:p-6">
        <EmptyPlan onAdd={() => onAdd(today)} />
      </div>
    )

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4 md:p-6">
      {groups.map(([date, items]) => {
        const [, month, day] = date.split('-').map(Number)
        return (
          <div key={date}>
            <div className="mb-1.5 flex items-baseline gap-2 px-3">
              <span className="text-[13px] font-semibold">{dayTitle(date, today)}</span>
              <span className="text-[13px] text-muted-foreground">
                {day} {MONTH_OF[month - 1]}
              </span>
              {items.length > 1 && (
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {items.length} поста
                </span>
              )}
            </div>
            <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
              {items.map((slot) => (
                <ListRow
                  key={slot.id}
                  slot={slot}
                  selected={slot.id === selectedId}
                  onSelect={onSelect}
                  bindPeek={bindPeek}
                />
              ))}
              <button
                onClick={() => onAdd(date)}
                className="flex h-9 w-full items-center gap-2 px-3 text-[13px] text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Добавить пост</span>
              </button>
            </div>
          </div>
        )
      })}
      <button
        onClick={() => onAdd(today)}
        className="flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border text-[13px] text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
      >
        <Plus className="h-3.5 w-3.5" />
        <span>Добавить пост на другую дату</span>
      </button>
    </div>
  )
}

function ListRow({
  slot,
  selected,
  onSelect,
  bindPeek,
}: {
  slot: Slot
  selected: boolean
  onSelect: (slot: Slot) => void
  bindPeek: ViewProps['bindPeek']
}) {
  const status = SLOT_STATUS[slot.status]
  const title = slot.post?.title || slot.topic
  return (
    <div
      {...bindPeek(slot)}
      onClick={() => onSelect(slot)}
      className={cn(
        // На узком экране строка переносится: промпт в первой строке, статус во второй.
        'group flex cursor-pointer items-center gap-3 px-3 transition-colors',
        'h-11 max-md:h-auto max-md:flex-wrap max-md:gap-x-3 max-md:gap-y-0.5 max-md:py-2',
        selected ? 'bg-accent' : 'hover:bg-accent/60',
        slot.status === 'skipped' && 'opacity-55',
      )}
    >
      <span className="w-11 shrink-0 text-[13px] font-medium tabular-nums text-muted-foreground">
        {timeOf(slot.publish_at)}
      </span>
      <span className={cn('flex-1 truncate text-[13px]', !title && 'italic text-muted-foreground')}>
        {title || 'промпт не задан'}
      </span>
      <span className="flex shrink-0 items-center gap-1.5 max-md:w-full max-md:pl-[56px]">
        <span className={cn('h-1.5 w-1.5 rounded-full', status.dot)} />
        <span className="w-[92px] text-[12px] text-muted-foreground max-md:w-auto">
          {status.label}
        </span>
      </span>
      <ChevronRight className="h-4 w-4 shrink-0 text-transparent transition-colors group-hover:text-muted-foreground/70 max-md:hidden" />
    </div>
  )
}

export function WeekView({
  slots,
  selectedId,
  today,
  onSelect,
  onAdd,
  bindPeek,
  weekStartDate,
}: ViewProps & { weekStartDate: string }) {
  const days = Array.from({ length: 7 }, (_, index) => shiftDays(weekStartDate, index))
  const groups = groupByDay(slots)

  return (
    <div className="overflow-x-auto p-4 md:p-6">
      <div className="grid grid-cols-7 gap-3 max-md:w-[860px]">
        {days.map((date, index) => {
          const items = groups.get(date) ?? []
          const day = Number(date.slice(8))
          return (
            <div key={date} className="min-w-0">
              <div className="mb-2 flex items-baseline gap-1.5 px-1">
                <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {DOW[index]}
                </span>
                <span
                  className={cn(
                    'text-[13px] font-semibold tabular-nums',
                    date === today && 'text-foreground',
                  )}
                >
                  {day}
                </span>
              </div>
              <div className="space-y-1.5">
                {items.map((slot) => {
                  const status = SLOT_STATUS[slot.status]
                  const title = slot.post?.title || slot.topic
                  return (
                    <div
                      key={slot.id}
                      {...bindPeek(slot)}
                      onClick={() => onSelect(slot)}
                      className={cn(
                        'cursor-pointer rounded-md border border-border p-2 transition-colors hover:border-foreground/25',
                        slot.id === selectedId && 'bg-accent',
                        slot.status === 'skipped' && 'opacity-55',
                      )}
                    >
                      <div className="mb-1 flex items-center gap-1.5">
                        <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', status.dot)} />
                        <span className="text-[11px] font-medium tabular-nums text-muted-foreground">
                          {timeOf(slot.publish_at)}
                        </span>
                      </div>
                      <p
                        className={cn(
                          'line-clamp-2 text-[12px] leading-snug',
                          !title && 'italic text-muted-foreground',
                        )}
                      >
                        {title || 'промпт не задан'}
                      </p>
                    </div>
                  )
                })}
                <button
                  onClick={() => onAdd(date)}
                  title="Добавить пост на этот день"
                  aria-label="Добавить пост на этот день"
                  className="flex h-7 w-full items-center justify-center rounded-md border border-dashed border-border text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function MonthView({
  slots,
  selectedId,
  today,
  onSelect,
  onAdd,
  bindPeek,
  year,
  month,
  wideWeekend,
  onToggleWeekend,
  expanded,
  onToggleDay,
}: ViewProps & {
  year: number
  month: number
  wideWeekend: boolean
  onToggleWeekend: () => void
  expanded: Set<string>
  onToggleDay: (date: string) => void
}) {
  const groups = groupByDay(slots)
  // Узкие колонки выходных: будни делят место поровну, суббота и воскресенье ужимаются.
  const columns = wideWeekend
    ? 'repeat(7,minmax(0,1fr))'
    : 'repeat(5,minmax(0,1fr)) repeat(2,minmax(0,0.52fr))'
  const lead = weekdayIndex(year, month, 1)
  const total = daysInMonth(year, month)
  const cells = Math.ceil((lead + total) / 7) * 7

  return (
    <div className="overflow-x-auto p-4 md:p-6">
      <div className="mb-3 flex items-center justify-end max-md:justify-start">
        <Button variant="outline" size="sm" onClick={onToggleWeekend} className="text-muted-foreground">
          <Columns3 className="h-3.5 w-3.5" />
          Выходные: {wideWeekend ? 'обычные' : 'узкие'}
        </Button>
      </div>
      <div
        className="grid gap-px overflow-hidden rounded-lg border border-border bg-border max-md:w-[860px]"
        style={{ gridTemplateColumns: columns }}
      >
        {DOW.map((name, index) => (
          <div
            key={name}
            className={cn(
              'bg-muted/40 px-3 py-2 text-[11px] font-medium uppercase tracking-wide',
              index > 4 ? 'text-muted-foreground/60' : 'text-muted-foreground',
            )}
          >
            {name}
          </div>
        ))}
        {Array.from({ length: cells }, (_, index) => {
          const dayNumber = index - lead + 1
          const inMonth = dayNumber >= 1 && dayNumber <= total
          const date = inMonth ? ymd(year, month, dayNumber) : `out-${index}`
          const items = inMonth ? (groups.get(date) ?? []) : []
          const open = expanded.has(date)
          const shown = open ? items : items.slice(0, 3)
          return (
            <div
              key={date}
              className={cn('group relative min-h-[104px] bg-background p-1.5', !inMonth && 'opacity-40')}
            >
              <div className="mb-1 flex items-center justify-between px-1">
                <span
                  className={cn(
                    'text-xs tabular-nums',
                    date === today
                      ? 'inline-grid h-5 w-5 place-items-center rounded-full bg-primary font-semibold text-primary-foreground'
                      : 'text-muted-foreground',
                  )}
                >
                  {inMonth ? dayNumber : ''}
                </span>
                {inMonth && (
                  <button
                    onClick={() => onAdd(date)}
                    title="Добавить пост на этот день"
                    aria-label="Добавить пост на этот день"
                    className="grid h-5 w-5 place-items-center rounded text-muted-foreground opacity-0 transition-opacity hover:bg-accent hover:text-foreground group-hover:opacity-100"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              {shown.map((slot) => {
                const status = SLOT_STATUS[slot.status]
                const title = slot.post?.title || slot.topic
                return (
                  <div
                    key={slot.id}
                    {...bindPeek(slot)}
                    onClick={() => onSelect(slot)}
                    className={cn(
                      'flex h-6 cursor-pointer items-center gap-1.5 rounded px-1',
                      slot.id === selectedId ? 'bg-accent' : 'hover:bg-accent/60',
                      slot.status === 'skipped' && 'opacity-55',
                    )}
                  >
                    <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', status.dot)} />
                    <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                      {timeOf(slot.publish_at)}
                    </span>
                    <span
                      className={cn('truncate text-[11px]', !title && 'italic text-muted-foreground')}
                    >
                      {title || 'нет темы'}
                    </span>
                  </div>
                )
              })}
              {items.length > 3 && (
                <button
                  onClick={() => onToggleDay(date)}
                  className="h-5 px-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
                >
                  {open ? 'свернуть' : `+${items.length - 3} ещё`}
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function EmptyPlan({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="grid place-items-center rounded-lg border border-dashed border-border py-16 text-center">
      <div className="space-y-3">
        <p className="text-sm font-medium">В плане пока нет слотов</p>
        <p className="max-w-sm text-[13px] text-muted-foreground">
          Агент не придумывает темы сам: слоты и темы заполняет редактор.
        </p>
        <Button size="sm" onClick={onAdd}>
          <Plus className="h-3.5 w-3.5" />
          Добавить первый слот
        </Button>
      </div>
    </div>
  )
}
