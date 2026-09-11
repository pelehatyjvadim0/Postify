import * as React from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Check, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { dateTimeLabel } from '@/lib/dates'
import { SLOT_STATUS } from '@/lib/status'
import type { Slot } from '@/lib/types'
import { cn } from '@/lib/utils'

const WIDTH = 320
/** Ширина правой панели поста: предпросмотр не должен её перекрывать. */
const PANEL_WIDTH = 400

export interface PeekActions {
  onEditTopic: (slot: Slot) => void
  onGenerate: (slot: Slot) => void
  onApprove: (slot: Slot) => void
  onRegenerate: (slot: Slot) => void
  onOpen: (slot: Slot) => void
  onSkip: (slot: Slot) => void
}

interface PeekState {
  slot: Slot
  left: number
  top: number
}

/** Предпросмотр по наведению: своё содержимое для каждого из восьми статусов. */
export function useSlotPeek() {
  const [state, setState] = React.useState<PeekState | null>(null)
  const showTimer = React.useRef<number>()
  const hideTimer = React.useRef<number>()
  const height = React.useRef(260)

  const hide = React.useCallback(() => {
    window.clearTimeout(showTimer.current)
    hideTimer.current = window.setTimeout(() => setState(null), 120)
  }, [])

  const cancelHide = React.useCallback(() => window.clearTimeout(hideTimer.current), [])

  const show = React.useCallback((element: HTMLElement, slot: Slot) => {
    // На сенсорном экране наведения нет: там касание должно сразу открывать
    // слот, а не вешать поверх карточку предпросмотра.
    if (!matchMedia('(hover: hover) and (pointer: fine)').matches) return
    window.clearTimeout(hideTimer.current)
    window.clearTimeout(showTimer.current)
    showTimer.current = window.setTimeout(() => {
      const rect = element.getBoundingClientRect()
      const gap = 10
      // Справа заканчиваем до панели поста, иначе карточка накрывает её кнопки.
      // Узкий экран панели рядом не показывает — там весь экран наш.
      const limit = (innerWidth >= 768 ? innerWidth - PANEL_WIDTH : innerWidth) - 8
      let left = rect.right + gap
      if (left + WIDTH > limit) left = rect.left - WIDTH - gap
      if (left < 8) left = Math.max(8, Math.min(rect.right + gap, limit - WIDTH))
      let top = rect.top - 8
      if (top + height.current > innerHeight - 8) top = innerHeight - height.current - 8
      if (top < 8) top = 8
      setState({ slot, left, top })
    }, 160)
  }, [])

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setState(null)
    }
    addEventListener('keydown', onKey)
    return () => {
      removeEventListener('keydown', onKey)
      window.clearTimeout(showTimer.current)
      window.clearTimeout(hideTimer.current)
    }
  }, [])

  const bind = React.useCallback(
    (slot: Slot) => ({
      onMouseEnter: (event: React.MouseEvent<HTMLElement>) => show(event.currentTarget, slot),
      onMouseLeave: hide,
    }),
    [show, hide],
  )

  return { state, bind, hide, cancelHide, close: () => setState(null), heightRef: height }
}

export function SlotPeek({
  peek,
  actions,
}: {
  peek: ReturnType<typeof useSlotPeek>
  actions: PeekActions
}) {
  const { state, cancelHide, hide, heightRef } = peek
  const node = React.useRef<HTMLDivElement>(null)

  React.useLayoutEffect(() => {
    if (node.current) heightRef.current = node.current.offsetHeight
  }, [state, heightRef])

  if (!state) return null
  const { slot } = state

  return createPortal(
    <div
      ref={node}
      onMouseEnter={cancelHide}
      onMouseLeave={hide}
      style={{ left: state.left, top: state.top, width: WIDTH }}
      className="fixed z-50 rounded-lg border border-border bg-card shadow-2xl animate-fade-in"
    >
      <PeekHead slot={slot} />
      <PeekBody slot={slot} actions={actions} />
    </div>,
    document.body,
  )
}

function PeekHead({ slot }: { slot: Slot }) {
  const status = SLOT_STATUS[slot.status]
  return (
    <div className="flex items-center gap-2 px-3.5 pb-2.5 pt-3">
      <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', status.dot)} />
      <span className="truncate text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {dateTimeLabel(slot.publish_at)}
      </span>
      <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">{status.label}</span>
    </div>
  )
}

function PeekBody({ slot, actions }: { slot: Slot; actions: PeekActions }) {
  if (slot.status === 'no_topic')
    return (
      <div className="px-3.5 pb-3.5">
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Слот стоит в плане, но промпт не заполнен. Агент не возьмёт его в работу, пока не появится
          задание.
        </p>
        <div className="mt-3 flex gap-2">
          <Button size="sm" className="flex-1" onClick={() => actions.onEditTopic(slot)}>
            Заполнить промпт
          </Button>
          <Button size="sm" variant="outline" onClick={() => actions.onSkip(slot)}>
            Пропустить
          </Button>
        </div>
      </div>
    )

  if (slot.status === 'planned')
    return (
      <div className="px-3.5 pb-3.5">
        <TopicBox topic={slot.topic} />
        <p className="text-[12px] text-muted-foreground">
          Текст будет сгенерирован {dateTimeLabel(slot.generate_at)} — заранее, до публикации.
        </p>
        <div className="mt-3 flex gap-2">
          <Button size="sm" className="flex-1" onClick={() => actions.onEditTopic(slot)}>
            Изменить промпт
          </Button>
          <Button size="sm" variant="outline" onClick={() => actions.onGenerate(slot)}>
            Сгенерировать сейчас
          </Button>
        </div>
      </div>
    )

  if (slot.status === 'generating')
    return (
      <div className="px-3.5 pb-3.5">
        <TopicBox topic={slot.topic} />
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Агент пишет пост и проходит слои проверок.
        </div>
      </div>
    )

  if (slot.status === 'skipped')
    return (
      <div className="px-3.5 pb-3.5">
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Слот пропущен вручную. Агент его не возьмёт, публикации не будет.
        </p>
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="outline" className="flex-1" onClick={() => actions.onOpen(slot)}>
            Открыть слот
          </Button>
        </div>
      </div>
    )

  const post = slot.post
  const checks = post?.checks_summary
  return (
    <div className="px-3.5 pb-3.5">
      {post?.media_thumb_url && (
        <div className="mb-2.5 overflow-hidden rounded-md border border-border">
          <img src={post.media_thumb_url} alt="" className="block aspect-[16/9] w-full object-cover" />
        </div>
      )}
      <p className="mb-2.5 line-clamp-5 text-[12.5px] leading-relaxed">
        {post?.excerpt ?? slot.topic}
      </p>
      {checks &&
        (checks.passed ? (
          <div className="flex items-center gap-1.5 text-[12px] text-emerald-600 dark:text-emerald-400">
            <Check className="h-3.5 w-3.5 shrink-0" strokeWidth={2.5} />
            <span>Все проверки пройдены</span>
          </div>
        ) : (
          <div className="flex items-start gap-1.5 text-[12px] text-amber-600 dark:text-amber-400">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.5} />
            <span>
              {checks.blocking > 0
                ? `${checks.blocking} блокирующих нарушения`
                : `${checks.warnings} замечание в проверках`}
            </span>
          </div>
        ))}
      <div className="mt-3 flex gap-2">
        {slot.status === 'published' ? (
          <Button size="sm" className="flex-1" onClick={() => actions.onOpen(slot)}>
            Открыть пост
          </Button>
        ) : slot.status === 'needs_review' ? (
          <>
            <Button size="sm" className="flex-1" onClick={() => actions.onApprove(slot)}>
              Одобрить
            </Button>
            <Button size="sm" variant="outline" onClick={() => actions.onRegenerate(slot)}>
              Переписать
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" className="flex-1" onClick={() => actions.onOpen(slot)}>
              Открыть
            </Button>
            <Button size="sm" variant="outline" onClick={() => actions.onRegenerate(slot)}>
              Переписать
            </Button>
          </>
        )}
      </div>
    </div>
  )
}

function TopicBox({ topic }: { topic: string }) {
  return (
    <div className="mb-2.5 rounded-md border border-border px-2.5 py-2">
      <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        Промпт поста
      </div>
      <p className="text-[12.5px] leading-relaxed">{topic || '—'}</p>
    </div>
  )
}
