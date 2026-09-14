import * as React from 'react'
import { ExternalLink, ImagePlus, Loader2, Pencil, Trash2 } from 'lucide-react'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { dateTimeLabel } from '@/lib/dates'
import { SLOT_STATUS } from '@/lib/status'
import type { MediaAsset, Post, Slot } from '@/lib/types'
import { supportLog } from '@/lib/support'
import { useToast } from '@/lib/toast'
import { useOperation } from '@/lib/operation'

interface Props {
  projectId: number
  slot: Slot | null
  onEditTopic: (slot: Slot) => void
  onGenerate: (slot: Slot) => void
  onRegenerate: (slot: Slot) => void
  onSkip: (slot: Slot) => void
  onDelete: (slot: Slot) => void
  onChanged: () => void
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
  const [choosingMedia, setChoosingMedia] = React.useState(false)
  const [assets, setAssets] = React.useState<MediaAsset[]>([])
  const [mediaCursor, setMediaCursor] = React.useState<string | null>(null)
  const [loadingMedia, setLoadingMedia] = React.useState(false)
  const toast = useToast()
  const recovery = useOperation(projectId)
  const currentPostId = React.useRef(slot?.post?.id ?? null)

  const postId = slot?.post?.id ?? null
  currentPostId.current = postId
  const loadedKey = React.useRef<string | null>(null)

  React.useEffect(() => {
    let active = true
    setEditing(false)
    setChoosingMedia(false)
    setMissing(false)
    const key = `${projectId}:${postId}`
    const samePost = loadedKey.current === key
    loadedKey.current = key
    if (!samePost) setPost(null)
    if (postId === null) {
      setLoading(false)
      return
    }
    if (!samePost) setLoading(true)
    api
      .post(projectId, postId)
      .then((loaded) => {
        if (!active) return
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
        if (!active) return
        // 404 — объекта нет: он удалён либо принадлежит другому пользователю.
        if (error instanceof ApiError && error.isNotFound) setMissing(true)
        else toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить пост')
        setPost(null)
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [projectId, postId, slot?.status, toast, operationRunning])

  const generating = slot?.status === 'generating' || post?.status === 'generating'
  const changed = React.useRef(onChanged)
  changed.current = onChanged

  // Продолжаем наблюдать и за генерацией, начатой до открытия панели.
  React.useEffect(() => {
    if (!generating || postId === null) return
    let active = true
    let timer: number
    async function refresh() {
      try {
        const loaded = await api.post(projectId, postId!)
        if (!active) return
        setPost(loaded)
        setDraft(loaded.post_text)
        if (loaded.status !== 'generating') {
          changed.current()
          return
        }
      } catch {
        // Временная ошибка сети не прекращает наблюдение за постом.
      }
      if (active) timer = window.setTimeout(refresh, 1000)
    }
    timer = window.setTimeout(refresh, 1000)
    return () => { active = false; window.clearTimeout(timer) }
  }, [projectId, postId, generating])

  if (!slot) return null

  const status = SLOT_STATUS[slot.status]
  const assembling = recovery.running || (post ? post.status === 'generating' : slot.status === 'generating')
  const missingMedia = !assembling && post?.generation?.error_code === 'media_pool_empty'
  const editable = !assembling && (post?.status === 'needs_review' || post?.status === 'approved')
  const canSkip = ['planned', 'no_topic', 'failed'].includes(slot.status)
  const canDelete = !slot.post && slot.status !== 'generating'

  async function recover(body: { without_image?: boolean; media_asset_id?: number }) {
    if (!post) return
    const recoveringPostId = post.id
    await recovery.run(() => api.regeneratePost(projectId, recoveringPostId, body), {
      onStarted: onChanged,
      successText: 'Пост подготовлен',
    })
    if (currentPostId.current !== recoveringPostId) return
    try {
      const updated = await api.post(projectId, recoveringPostId)
      if (currentPostId.current !== recoveringPostId) return
      setPost(updated)
      setDraft(updated.post_text)
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить пост')
    }
    onChanged()
  }

  async function loadMedia(cursor?: string) {
    setChoosingMedia(true)
    setLoadingMedia(true)
    try {
      const page = await api.media(projectId, { available: true, limit: 60, cursor })
      setAssets((current) => cursor ? [...current, ...page.items] : page.items)
      setMediaCursor(page.next_cursor)
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить изображения')
    } finally {
      setLoadingMedia(false)
    }
  }

  async function selectMedia(asset: MediaAsset) {
    if (!post) return
    setBusy(true)
    try {
      const updated = await api.updatePost(projectId, post.id, { media_asset_id: asset.id })
      setPost(updated)
      setChoosingMedia(false)
      toast.ok('Изображение сохранено')
      onChanged()
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Не удалось сохранить изображение')
    } finally {
      setBusy(false)
    }
  }

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
            : 'Текст сохранён',
      )
      onChanged()
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Действие не выполнено')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto p-0">
        <div className="space-y-5 p-5">
          <div>
            <div className="mb-1 flex items-center justify-between gap-2 pr-8">
              <span className="truncate text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {dateTimeLabel(slot.publish_at)}
              </span>
              <Badge tone={status.tone}>{status.label}</Badge>
            </div>
            <DialogTitle className="sr-only">Пост контент-плана</DialogTitle>
          </div>

          <div className="rounded-lg border border-border">
            <details key={slot.id} className="group">
              <summary className="cursor-pointer px-3 py-2 text-[11px] font-medium text-muted-foreground">
                <span className="uppercase tracking-wide">Промпт поста</span>
                <span className="mt-1 block truncate text-xs font-normal group-open:hidden">
                  {slot.topic || 'Промпт не заполнен'}
                </span>
              </summary>
              <p className="whitespace-pre-wrap border-t border-border px-3 py-2 text-xs leading-relaxed text-muted-foreground">
                {slot.topic || 'Промпт не заполнен — агент не возьмёт слот в работу.'}
              </p>
            </details>
            <div className="flex flex-wrap gap-2 border-t border-border px-3 py-2">
              <Button size="xs" variant="outline" onClick={() => onEditTopic(slot)}>
                <Pencil className="h-3 w-3" />
                {slot.post ? 'Изменить время' : slot.topic ? 'Изменить промпт' : 'Заполнить промпт'}
              </Button>
              {(slot.status === 'planned' || slot.status === 'no_topic' || slot.status === 'failed') && (
                <Button
                  size="xs"
                  variant="outline"
                  disabled={!slot.topic || operationRunning || recovery.running}
                  onClick={() => onGenerate(slot)}
                >
                  {operationRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                  Сгенерировать сейчас
                </Button>
              )}
              <div className="ml-auto flex items-center gap-1">
                {canSkip && (
                  <Button
                    size="xs"
                    variant="ghost"
                    className="text-muted-foreground"
                    onClick={() => onSkip(slot)}
                  >
                    Пропустить
                  </Button>
                )}
                {canDelete && <Button
                  size="icon-sm"
                  variant="ghost"
                  className="text-muted-foreground"
                  title="Удалить слот из плана"
                  aria-label="Удалить слот из плана"
                  onClick={() => onDelete(slot)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>}
              </div>
            </div>
          </div>

          {missing && (
            <Alert tone="error" title="Пост не найден">
              Объект удалён или недоступен.
            </Alert>
          )}

          {loading && !assembling && <Skeleton className="h-48 w-full" />}
          {assembling && (!post || loading) && (
            <div className="relative overflow-hidden rounded-lg border border-border" aria-busy="true">
              <div className="h-80 bg-muted/40 blur-sm" />
              <AssemblyOverlay />
            </div>
          )}

          {post && !loading && (
            <>
              {missingMedia && (
                <div className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
                  <p className="text-sm font-medium">Упс, не нашли доступное изображение</p>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" disabled={busy || operationRunning} onClick={() => void recover({ without_image: true })}>Опубликовать без изображения</Button>
                  </div>
                  <p className="text-xs text-muted-foreground">Подготовим черновик без изображения. Перед публикацией его можно будет проверить и одобрить.</p>
                </div>
              )}
              {post.generation?.repair_error && (
                <Alert tone="warning" title="Не удалось исправить черновик">
                  Сервис генерации прервал исправление текста. Черновик сохранён с результатами
                  проверки. Можно отредактировать его или повторить генерацию.
                </Alert>
              )}
              <div className="relative overflow-hidden rounded-lg border border-border bg-card" aria-busy={assembling}>
                <div className={assembling ? 'pointer-events-none select-none blur-sm' : undefined} aria-hidden={assembling || undefined}>
                {post.media ? (
                  <img
                    src={post.media.url}
                    alt={post.media.caption}
                    className="block aspect-[16/9] w-full object-cover"
                  />
                ) : !missingMedia && !post.post_text ? (
                  <div className="grid aspect-[16/9] place-items-center bg-muted/40 px-6 text-center">
                    <p className="text-[12px] text-muted-foreground">
                      Упс, не нашли доступное изображение
                    </p>
                  </div>
                ) : null}
                <div className="space-y-2 p-3">
                  {editing ? (
                    <>
                      <Textarea
                        rows={10}
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        className="text-[13px]"
                      />
                      <div className="flex gap-2">
                        <Button size="sm" disabled={busy || !draft.trim() || draft.length > (post.media ? 1024 : 4096)} onClick={() => act('save')}>
                          Сохранить
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
                      {editable && <button
                        className="ml-auto inline-flex items-center gap-1 transition-colors hover:text-foreground"
                        onClick={() => setEditing(true)}
                        disabled={busy || operationRunning}
                      >
                        <Pencil className="h-3 w-3" />
                        Править текст
                      </button>}
                    </div>
                  )}
                </div>
                </div>
                {assembling && <AssemblyOverlay />}
              </div>

              {editable && !editing && (
                <div className="space-y-3">
                  <Button variant="outline" size="sm" disabled={busy || operationRunning} onClick={() => choosingMedia ? setChoosingMedia(false) : void loadMedia()}>
                    <ImagePlus className="h-4 w-4" />
                    {choosingMedia ? 'Закрыть выбор изображения' : 'Выбрать изображение'}
                  </Button>
                  {choosingMedia && (
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {assets.map((asset) => (
                          <button key={asset.id} disabled={busy || loadingMedia} onClick={() => void selectMedia(asset)} className="overflow-hidden rounded-md border border-border text-left disabled:opacity-50" title={asset.caption ?? 'Выбрать изображение'}>
                            <img src={asset.url} alt={asset.caption ?? ''} className="aspect-[16/10] w-full object-cover" />
                            <span className="block line-clamp-2 p-2 text-xs">{asset.caption}</span>
                          </button>
                        ))}
                      </div>
                      {loadingMedia && <Loader2 className="h-4 w-4 animate-spin" />}
                      {!loadingMedia && assets.length === 0 && <p className="text-xs text-muted-foreground">Нет доступных изображений.</p>}
                      {mediaCursor && <Button size="sm" variant="outline" disabled={loadingMedia} onClick={() => void loadMedia(mediaCursor)}>Показать ещё</Button>}
                    </div>
                  )}
                </div>
              )}

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

              {!post.published && !assembling && (
                <div className="flex items-center gap-2 pt-1">
                  {post.status === 'approved' ? (
                    <Button className="flex-1" variant="outline" disabled={busy || editing || operationRunning} onClick={() => act('reject')}>
                      Вернуть на доработку
                    </Button>
                  ) : post.status === 'needs_review' ? (
                    <Button className="flex-1" disabled={busy || editing || operationRunning} onClick={() => act('approve')}>
                      Одобрить
                    </Button>
                  ) : null}
                  <Button
                    variant="outline"
                    disabled={busy || editing || operationRunning}
                    onClick={() => onRegenerate(slot)}
                  >
                    {operationRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Переписать
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function AssemblyOverlay() {
  return (
    <div className="absolute inset-0 grid place-items-center bg-background/60">
      <div role="status" className="flex flex-col items-center gap-3 p-6 text-center">
        <Loader2 aria-hidden="true" className="h-7 w-7 animate-spin text-muted-foreground" />
        <p className="text-sm font-medium">Собираем пост</p>
      </div>
    </div>
  )
}
