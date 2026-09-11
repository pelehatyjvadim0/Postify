import * as React from 'react'
import { ArrowLeft, ExternalLink, Loader2, Pencil, Trash2 } from 'lucide-react'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { dateTimeLabel } from '@/lib/dates'
import { SLOT_STATUS, TOPIC_SPECIFICS_HINT } from '@/lib/status'
import type { Post, Slot } from '@/lib/types'
import { cn } from '@/lib/utils'
import { supportLog } from '@/lib/support'
import { useToast } from '@/lib/toast'
import { ChecksReport } from './ChecksReport'

interface Props {
  projectId: number
  slot: Slot | null
  onEditTopic: (slot: Slot) => void
  onGenerate: (slot: Slot) => void
  onRegenerate: (slot: Slot) => void
  onSkip: (slot: Slot) => void
  onDelete: (slot: Slot) => void
  onChanged: () => void
  /** Закрыть панель — нужно на узком экране, где она занимает весь экран. */
  onClose: () => void
  operationRunning: boolean
}

export function PostPanel({
  projectId,
  slot,
  onEditTopic,
  onGenerate,
  onRegenerate,
  onSkip,
  onDelete,
  onChanged,
  onClose,
  operationRunning,
}: Props) {
  const [post, setPost] = React.useState<Post | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [missing, setMissing] = React.useState(false)
  const [editing, setEditing] = React.useState(false)
  const [draft, setDraft] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const toast = useToast()

  const postId = slot?.post?.id ?? null

  React.useEffect(() => {
    setEditing(false)
    setMissing(false)
    if (postId === null) {
      setPost(null)
      return
    }
    setLoading(true)
    api
      .post(projectId, postId)
      .then((loaded) => {
        setPost(loaded)
        setDraft(loaded.post_text)
        supportLog('post_loaded', {
          post_id: loaded.id,
          slot_id: loaded.slot_id,
          provider: loaded.generation?.provider ?? null,
          model: loaded.generation?.model ?? null,
          reasoning_effort: loaded.generation?.reasoning_effort ?? null,
          iterations: loaded.generation?.iterations ?? null,
          media_asset_id: loaded.media?.asset_id ?? null,
        })
      })
      .catch((error) => {
        // 404 — объекта нет: он удалён либо принадлежит другому пользователю.
        if (error instanceof ApiError && error.isNotFound) setMissing(true)
        else toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить пост')
        setPost(null)
      })
      .finally(() => setLoading(false))
  }, [projectId, postId, toast, operationRunning])

  if (!slot)
    return (
      <PanelShell empty onClose={onClose}>
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Выберите слот в плане, чтобы увидеть тему, пост и отчёт проверок.
        </p>
      </PanelShell>
    )

  const status = SLOT_STATUS[slot.status]

  async function act(action: 'approve' | 'reject' | 'save') {
    if (!post) return
    setBusy(true)
    try {
      const updated =
        action === 'approve'
          ? await api.approvePost(projectId, post.id)
          : action === 'reject'
            ? await api.rejectPost(projectId, post.id)
            : await api.updatePost(projectId, post.id, { post_text: draft })
      setPost(updated)
      setDraft(updated.post_text)
      setEditing(false)
      toast.ok(
        action === 'approve'
          ? 'Пост одобрен'
          : action === 'reject'
            ? 'Пост отправлен на доработку'
            : 'Текст сохранён, проверки пересчитаны',
      )
      onChanged()
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Действие не выполнено')
    } finally {
      setBusy(false)
    }
  }

  return (
    <PanelShell onClose={onClose}>
      <div>
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="truncate text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {dateTimeLabel(slot.publish_at)}
            {slot.rubric ? ` · ${slot.rubric.name}` : ''}
          </span>
          <Badge tone={status.tone}>{status.label}</Badge>
        </div>
        <h2 className="text-base font-semibold tracking-tight">
          {slot.post?.title || slot.topic || 'Тема не задана'}
        </h2>
      </div>

      <div className="rounded-lg border border-border">
        <div className="border-b border-border px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Тема от редактора
        </div>
        <p className="px-3 py-2.5 text-[13px] leading-relaxed text-muted-foreground">
          {slot.topic || 'Тема не заполнена — агент не возьмёт слот в работу.'}
        </p>
        <div className="flex gap-2 border-t border-border px-3 py-2">
          <Button size="xs" variant="outline" onClick={() => onEditTopic(slot)}>
            <Pencil className="h-3 w-3" />
            {slot.topic ? 'Изменить тему' : 'Заполнить тему'}
          </Button>
          {(slot.status === 'planned' || slot.status === 'no_topic' || slot.status === 'failed') && (
            <Button
              size="xs"
              variant="outline"
              disabled={!slot.topic || operationRunning}
              onClick={() => onGenerate(slot)}
            >
              {operationRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              Сгенерировать сейчас
            </Button>
          )}
          <div className="ml-auto flex items-center gap-1">
            {slot.status !== 'skipped' && slot.status !== 'published' && (
              <Button
                size="xs"
                variant="ghost"
                className="text-muted-foreground"
                onClick={() => onSkip(slot)}
              >
                Пропустить
              </Button>
            )}
            <Button
              size="icon-sm"
              variant="ghost"
              className="text-muted-foreground"
              title="Удалить слот из плана"
              aria-label="Удалить слот из плана"
              onClick={() => onDelete(slot)}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>

      {slot.status === 'generating' && (
        <Alert tone="info" title="Агент пишет пост">
          Идёт генерация и слои проверок. Статус обновится сам.
        </Alert>
      )}

      {missing && (
        <Alert tone="error" title="Пост не найден">
          Объект удалён или недоступен.
        </Alert>
      )}

      {loading && <Skeleton className="h-48 w-full" />}

      {post && !loading && (
        <>
          <div className="overflow-hidden rounded-lg border border-border bg-card">
            {post.media ? (
              <img src={post.media.url} alt={post.media.caption} className="block aspect-[16/9] w-full object-cover" />
            ) : (
              <div className="grid aspect-[16/9] place-items-center bg-muted/40 px-6 text-center">
                <p className="text-[12px] text-muted-foreground">
                  Изображение не подобрано: в пуле нет доступных активов с подписью.
                </p>
              </div>
            )}
            <div className="space-y-2 p-3">
              {editing ? (
                <>
                  <Textarea
                    rows={10}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    className="text-[13px]"
                  />
                  <Alert tone="warning">{TOPIC_SPECIFICS_HINT}</Alert>
                  <div className="flex gap-2">
                    <Button size="sm" disabled={busy} onClick={() => act('save')}>
                      Сохранить и перепроверить
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setDraft(post.post_text)
                        setEditing(false)
                      }}
                    >
                      Отмена
                    </Button>
                  </div>
                </>
              ) : (
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{post.post_text}</p>
              )}
              {!editing && (
                <div className="flex flex-wrap items-center gap-3 pt-1 text-[11px] tabular-nums text-muted-foreground">
                  <span>{post.char_count} знаков</span>
                  <button
                    className="ml-auto inline-flex items-center gap-1 transition-colors hover:text-foreground"
                    onClick={() => setEditing(true)}
                  >
                    <Pencil className="h-3 w-3" />
                    Править текст
                  </button>
                </div>
              )}
            </div>
          </div>

          {post.media && (
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              Изображение: {post.media.caption}. {post.media.rationale}.
            </p>
          )}

          <ChecksReport report={post.validation} />

          {post.published && (
            <Alert tone="info" title="Опубликован">
              {dateTimeLabel(post.published.published_at)} ·{' '}
              <a
                href={post.published.message_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 underline underline-offset-2"
              >
                открыть в Telegram
                <ExternalLink className="h-3 w-3" />
              </a>
            </Alert>
          )}

          {!post.published && (
            <div className="flex items-center gap-2 pt-1">
              {post.status === 'approved' ? (
                <Button className="flex-1" variant="outline" disabled={busy} onClick={() => act('reject')}>
                  Вернуть на доработку
                </Button>
              ) : (
                <Button className="flex-1" disabled={busy} onClick={() => act('approve')}>
                  Одобрить
                </Button>
              )}
              <Button
                variant="outline"
                disabled={operationRunning}
                onClick={() => onRegenerate(slot)}
              >
                {operationRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Переписать
              </Button>
            </div>
          )}
        </>
      )}
    </PanelShell>
  )
}

function PanelShell({
  children,
  empty,
  onClose,
}: {
  children: React.ReactNode
  empty?: boolean
  onClose: () => void
}) {
  return (
    <aside
      className={cn(
        'shrink-0 overflow-auto border-l border-border bg-background md:w-[400px]',
        // На узком экране панель занимает весь экран: рядом с планом
        // 400 пикселей не помещаются.
        'max-md:fixed max-md:inset-0 max-md:z-40 max-md:border-l-0',
        // Подсказка «выберите слот» нужна только там, где панель видна всегда.
        empty && 'max-md:hidden',
      )}
    >
      <div className="space-y-5 p-5">
        <Button variant="outline" size="sm" className="md:hidden" onClick={onClose}>
          <ArrowLeft className="h-3.5 w-3.5" />
          К плану
        </Button>
        {children}
      </div>
    </aside>
  )
}
