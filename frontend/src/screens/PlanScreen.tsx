import * as React from 'react'
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { PostPanel } from '@/components/plan/PostPanel'
import { SlotDialog, type SlotDraft } from '@/components/plan/SlotDialog'
import { SlotPeek, useSlotPeek } from '@/components/plan/SlotPeek'
import { ListView, MonthView, WeekView } from '@/components/plan/views'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import {
  daysInMonth,
  monthTitle,
  shiftDays,
  todayIn,
  weekRangeLabel,
  weekStart,
  ymd,
} from '@/lib/dates'
import { useAction } from '@/lib/action'
import { useOperation } from '@/lib/operation'
import { useToast } from '@/lib/toast'
import type { Project, Rubric, Slot } from '@/lib/types'
import { cn } from '@/lib/utils'

type View = 'list' | 'week' | 'month'

export function PlanScreen({
  project,
  onProjectChanged,
  focus,
}: {
  project: Project
  onProjectChanged: () => void
  /** Слот, на который нужно открыть план — например, при переходе из «Постов». */
  focus?: { date: string; slotId: number } | null
}) {
  // «Сегодня» считается в таймзоне проекта, а не браузера.
  const today = React.useMemo(() => todayIn(project.timezone), [project.timezone])
  const [view, setView] = React.useState<View>('list')
  const [anchor, setAnchor] = React.useState(today)
  const [slots, setSlots] = React.useState<Slot[]>([])
  const [rubrics, setRubrics] = React.useState<Rubric[]>([])
  const [loading, setLoading] = React.useState(true)
  const [notFound, setNotFound] = React.useState(false)
  const [selectedId, setSelectedId] = React.useState<number | null>(null)
  const [wideWeekend, setWideWeekend] = React.useState(false)
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set())
  const [draft, setDraft] = React.useState<SlotDraft | null>(null)
  const [pendingDelete, setPendingDelete] = React.useState<Slot | null>(null)
  const peek = useSlotPeek()
  const act = useAction()
  const toast = useToast()
  const operation = useOperation(project.id)

  // Переход извне: встаём на нужный месяц и выделяем слот.
  const focusKey = focus ? `${focus.date}:${focus.slotId}` : null
  const appliedFocus = React.useRef<string | null>(null)
  React.useEffect(() => {
    if (!focusKey || !focus || appliedFocus.current === focusKey) return
    appliedFocus.current = focusKey
    setView('list')
    setAnchor(focus.date)
    setSelectedId(focus.slotId)
  }, [focusKey, focus])

  const appliedProject = React.useRef(project.id)
  React.useEffect(() => {
    if (appliedProject.current === project.id) return
    appliedProject.current = project.id
    setAnchor(today)
    setSelectedId(null)
  }, [project.id, today])

  const [year, month] = [Number(anchor.slice(0, 4)), Number(anchor.slice(5, 7))]
  const range = React.useMemo(() => {
    if (view === 'week') {
      const start = weekStart(anchor)
      return { from: start, to: shiftDays(start, 6) }
    }
    return { from: ymd(year, month, 1), to: ymd(year, month, daysInMonth(year, month)) }
  }, [view, anchor, year, month])

  const load = React.useCallback(async () => {
    setLoading(true)
    setNotFound(false)
    try {
      const [plan, rubricList] = await Promise.all([
        api.plan(project.id, range.from, range.to),
        api.rubrics(project.id),
      ])
      setSlots(plan)
      setRubrics(rubricList)
    } catch (error) {
      // Контракт: чужой project_id отвечает 404 — для UI это «нет объекта».
      if (error instanceof ApiError && error.isNotFound) setNotFound(true)
      else toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить план')
    } finally {
      setLoading(false)
    }
  }, [project.id, range.from, range.to, toast])

  React.useEffect(() => {
    void load()
  }, [load])

  const selected = slots.find((slot) => slot.id === selectedId) ?? null

  function shiftPeriod(delta: number) {
    peek.close()
    if (view === 'week') {
      setAnchor(shiftDays(weekStart(anchor), delta * 7))
      return
    }
    const next = new Date(Date.UTC(year, month - 1 + delta, 1))
    setAnchor(ymd(next.getUTCFullYear(), next.getUTCMonth() + 1, 1))
  }

  async function generate(slot: Slot) {
    peek.close()
    await operation.run(() => api.generateSlot(project.id, slot.id), {
      // Слот сразу переходит в generating, чтобы состояние было видно во время поллинга.
      onStarted: load,
      successText: 'Пост сгенерирован',
    })
    await load()
  }

  async function regenerate(slot: Slot) {
    peek.close()
    if (!slot.post) return
    await operation.run(() => api.regeneratePost(project.id, slot.post!.id), {
      onStarted: load,
      successText: 'Пост переписан',
    })
    await load()
  }

  async function approve(slot: Slot) {
    peek.close()
    if (!slot.post) return
    const { ok } = await act(() => api.approvePost(project.id, slot.post!.id), { ok: 'Пост одобрен' })
    if (!ok) return
    await load()
    onProjectChanged()
  }

  async function skip(slot: Slot) {
    peek.close()
    const { ok } = await act(() => api.skipSlot(project.id, slot.id), { ok: 'Слот пропущен' })
    if (!ok) return
    await load()
    onProjectChanged()
  }

  async function removeSlot(slot: Slot) {
    const { ok } = await act(() => api.deleteSlot(project.id, slot.id), { ok: 'Слот удалён' })
    if (!ok) return
    setSelectedId(null)
    await load()
    onProjectChanged()
  }

  const viewProps = {
    slots,
    selectedId,
    today,
    onSelect: (slot: Slot) => {
      // Предпросмотр висит справа и перекрывал бы панель поста.
      peek.close()
      setSelectedId(slot.id)
    },
    onAdd: (date: string) => setDraft({ slot: null, date }),
    bindPeek: peek.bind,
  }

  const periodLabel =
    view === 'week' ? weekRangeLabel(weekStart(anchor)) : monthTitle(year, month)

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <AppHeader
        title="Контент-план"
        actions={
          <>
            <div className="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-xs">
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  project.publication_mode === 'auto' ? 'bg-sky-500' : 'bg-emerald-500',
                )}
              />
              <span className="text-muted-foreground">Режим</span>
              <span className="font-medium">
                {project.publication_mode === 'auto' ? 'автопубликация' : 'ревью'}
              </span>
            </div>
            <Button onClick={() => setDraft({ slot: null, date: anchor })}>
              <Plus className="h-4 w-4" />
              Добавить слот
            </Button>
          </>
        }
      >
        <div className="ml-2 inline-flex h-8 items-center rounded-lg bg-muted p-0.5 text-muted-foreground">
          {(['list', 'week', 'month'] as View[]).map((value) => (
            <button
              key={value}
              onClick={() => {
                peek.close()
                setView(value)
              }}
              className={cn(
                'h-7 rounded-md px-3 text-[13px] font-medium transition-colors',
                view === value ? 'bg-background text-foreground shadow-sm' : 'hover:text-foreground',
              )}
            >
              {value === 'list' ? 'Список' : value === 'week' ? 'Неделя' : 'Месяц'}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            title="Предыдущий период"
            aria-label="Предыдущий период"
            onClick={() => shiftPeriod(-1)}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="px-1 text-sm font-medium tabular-nums">{periodLabel}</span>
          <Button
            variant="ghost"
            size="icon-sm"
            title="Следующий период"
            aria-label="Следующий период"
            onClick={() => shiftPeriod(1)}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </AppHeader>

      <div className="flex min-h-0 flex-1">
        <section className="min-w-0 flex-1 overflow-auto" onScroll={peek.close}>
          {notFound ? (
            <div className="p-6">
              <Alert tone="error" title="Проект не найден">
                Объекта нет или он недоступен. Выберите другой проект в боковой панели.
              </Alert>
            </div>
          ) : loading ? (
            <div className="mx-auto max-w-3xl space-y-3 p-6">
              <Skeleton className="h-11 w-full" />
              <Skeleton className="h-11 w-full" />
              <Skeleton className="h-11 w-full" />
            </div>
          ) : view === 'list' ? (
            <ListView {...viewProps} />
          ) : view === 'week' ? (
            <WeekView {...viewProps} weekStartDate={weekStart(anchor)} />
          ) : (
            <MonthView
              {...viewProps}
              year={year}
              month={month}
              wideWeekend={wideWeekend}
              onToggleWeekend={() => setWideWeekend((value) => !value)}
              expanded={expanded}
              onToggleDay={(date) =>
                setExpanded((current) => {
                  const next = new Set(current)
                  if (next.has(date)) next.delete(date)
                  else next.add(date)
                  return next
                })
              }
            />
          )}
        </section>

        <PostPanel
          projectId={project.id}
          slot={selected}
          operationRunning={operation.running}
          onEditTopic={(slot) => setDraft({ slot, date: slot.publish_at.slice(0, 10) })}
          onGenerate={generate}
          onRegenerate={regenerate}
          onSkip={skip}
          onDelete={(slot) => setPendingDelete(slot)}
          onChanged={() => {
            void load()
            onProjectChanged()
          }}
        />
      </div>

      <SlotPeek
        peek={peek}
        actions={{
          onEditTopic: (slot) => {
            peek.close()
            setSelectedId(slot.id)
            setDraft({ slot, date: slot.publish_at.slice(0, 10) })
          },
          onGenerate: generate,
          onApprove: approve,
          onRegenerate: regenerate,
          onSkip: skip,
          onOpen: (slot) => {
            peek.close()
            setSelectedId(slot.id)
          },
        }}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Удалить слот из плана?"
        description="Слот и связанный с ним пост исчезнут из плана. Действие необратимо."
        onConfirm={() => pendingDelete && void removeSlot(pendingDelete)}
        onClose={() => setPendingDelete(null)}
      />

      <SlotDialog
        projectId={project.id}
        timezone={project.timezone}
        draft={draft}
        rubrics={rubrics}
        onClose={() => setDraft(null)}
        onSaved={(slot) => {
          setSelectedId(slot.id)
          void load()
          onProjectChanged()
        }}
        onDeleteRequest={(slot) => setPendingDelete(slot)}
      />
    </div>
  )
}
