import * as React from 'react'
import { Loader2, RefreshCw, Search, Trash2, Upload } from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { FieldHelp } from '@/components/FieldHelp'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { useAction } from '@/lib/action'
import { useOperation } from '@/lib/operation'
import { supportLog } from '@/lib/support'
import { useToast } from '@/lib/toast'
import type { MediaAsset, Project } from '@/lib/types'
import { cn } from '@/lib/utils'

const CAPTION_LABEL: Record<MediaAsset['caption_status'], { text: string; tone: 'neutral' | 'amber' | 'red' | 'emerald' }> = {
  pending: { text: 'описание готовится', tone: 'amber' },
  ready: { text: 'описано', tone: 'emerald' },
  failed: { text: 'описать не удалось', tone: 'red' },
}

export function MediaScreen({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [items, setItems] = React.useState<MediaAsset[]>([])
  const [cursor, setCursor] = React.useState<string | null>(null)
  const [loadingMore, setLoadingMore] = React.useState(false)
  const [removing, setRemoving] = React.useState<MediaAsset | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [query, setQuery] = React.useState('')
  // Запрос уходит не на каждый символ, и поздний ответ не перетирает свежий.
  const [search, setSearch] = React.useState('')
  const requestId = React.useRef(0)
  const [availableOnly, setAvailableOnly] = React.useState(false)
  const [uploadError, setUploadError] = React.useState<string | null>(null)
  const fileInput = React.useRef<HTMLInputElement>(null)
  const toast = useToast()
  const act = useAction()
  const operation = useOperation(project.id)

  React.useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query), 300)
    return () => window.clearTimeout(timer)
  }, [query])

  const load = React.useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    try {
      const page = await api.media(project.id, {
        available: availableOnly || undefined,
        q: search || undefined,
        limit: 60,
      })
      if (id !== requestId.current) return
      setItems(page.items)
      setCursor(page.next_cursor)
    } catch (error) {
      if (id === requestId.current)
        toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить пул')
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [project.id, availableOnly, search, toast])

  React.useEffect(() => {
    void load()
  }, [load])

  /** Пул больше страницы: остальное догружается по кнопке, а не теряется. */
  async function loadMore() {
    if (!cursor) return
    const id = requestId.current
    setLoadingMore(true)
    try {
      const page = await api.media(project.id, {
        available: availableOnly || undefined,
        q: search || undefined,
        limit: 60,
        cursor,
      })
      if (id !== requestId.current) return
      setItems((current) => [...current, ...page.items])
      setCursor(page.next_cursor)
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить ещё')
    } finally {
      if (id === requestId.current) setLoadingMore(false)
    }
  }

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return
    const form = new FormData()
    for (const file of Array.from(files).slice(0, 20)) form.append('files', file)
    setUploadError(null)
    const result = await operation.run(() => api.uploadMedia(project.id, form), {
      successText: 'Изображения загружены и описаны',
    })
    if (result?.status === 'failed') {
      // Техническую причину видит только поддержка, пользователю — что делать.
      supportLog('media_upload_failed', { code: result.error?.code ?? null, message: result.error?.message ?? null })
      setUploadError('Описания к загруженным изображениям составить не удалось.')
    }
    await load()
    onChanged()
  }

  const noCaption = items.filter((item) => item.caption_status === 'failed').length

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <AppHeader
        title="Изображения"
        actions={
          <Button disabled={operation.running} onClick={() => fileInput.current?.click()}>
            {operation.running ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            Загрузить
          </Button>
        }
      >
        <FieldHelp title="Пул изображений">
          Агент не ищет картинки в интернете: он берёт их отсюда. К каждой загруженной картинке
          система составляет описание того, что на ней, и по нему подбирает подходящую к теме
          поста. Без описания картинка в подбор не попадает. Переключателем на карточке её можно
          временно вывести из подбора, а «Описать заново» просит систему пересмотреть картинку и
          написать описание заново.
        </FieldHelp>
        <div className="relative ml-2 w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Поиск по описанию"
            className="h-8 pl-8 text-[13px]"
          />
        </div>
        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Switch
            checked={availableOnly}
            aria-label="Показывать только доступные изображения"
            onCheckedChange={setAvailableOnly}
          />
          только доступные
        </label>
      </AppHeader>

      <input
        ref={fileInput}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        hidden
        onChange={(event) => {
          void upload(event.target.files)
          event.target.value = ''
        }}
      />

      <div className="flex-1 overflow-auto">
        <div className="space-y-4 p-4 md:p-6">
          {operation.running && (
            <Alert tone="info" title="Идёт обработка">
              Файлы загружены. Система рассматривает их и составляет описание — обычно это
              занимает несколько секунд. Пока описания нет, картинка в подбор не попадает.
            </Alert>
          )}

          {uploadError && (
            <Alert tone="error" title="Подбор изображения недоступен">
              {uploadError} Файлы остались в пуле, но выбрать их агент не сможет: попробуйте
              «Описать заново» на карточке позже.
            </Alert>
          )}

          {!operation.running && !uploadError && noCaption > 0 && (
            <Alert tone="error" title="Подбор изображения недоступен">
              Среди показанных изображений у {noCaption} не получилось составить описание. Такие
              картинки агент выбрать не может — попробуйте «Описать заново» на карточке.
            </Alert>
          )}

          {!loading && project.media.available === 0 && project.media.total > 0 && (
            <Alert tone="warning" title="Нет доступных изображений">
              Все картинки либо выключены, либо уже выходили за последние{' '}
              {project.media_reuse_days} дней. Агенту нечего выбрать — загрузите новые.
            </Alert>
          )}

          {loading ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
              {Array.from({ length: 8 }, (_, index) => (
                <Skeleton key={index} className="aspect-[16/10] w-full" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <Alert tone="info" title="Пул пуст">
              Загрузите изображения: агент берёт картинку к посту только отсюда.
            </Alert>
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
              {items.map((asset) => (
                <AssetCard
                  key={asset.id}
                  asset={asset}
                  projectId={project.id}
                  onChanged={load}
                  operation={operation}
                  onRemoveRequest={setRemoving}
                />
              ))}
            </div>
          )}

          {!loading && cursor && (
            <div className="flex justify-center">
              <Button variant="outline" size="sm" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadingMore && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Показать ещё
              </Button>
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={removing !== null}
        title="Удалить изображение?"
        description="Картинка исчезнет из пула безвозвратно. Если нужно просто убрать её из подбора, воспользуйтесь переключателем на карточке."
        onConfirm={async () => {
          const asset = removing
          if (!asset) return
          const { ok } = await act(() => api.deleteAsset(project.id, asset.id), {
            ok: 'Изображение удалено',
          })
          if (ok) {
            await load()
            onChanged()
          }
        }}
        onClose={() => setRemoving(null)}
      />
    </div>
  )
}

function AssetCard({
  asset,
  projectId,
  onChanged,
  operation,
  onRemoveRequest,
}: {
  asset: MediaAsset
  projectId: number
  onChanged: () => Promise<void>
  operation: ReturnType<typeof useOperation>
  onRemoveRequest: (asset: MediaAsset) => void
}) {
  const caption = CAPTION_LABEL[asset.caption_status]
  const act = useAction()

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border border-border bg-card',
        !asset.available && 'opacity-80',
      )}
    >
      <img src={asset.url} alt={asset.caption ?? ''} className="block aspect-[16/10] w-full object-cover" />
      <div className="space-y-2 p-2.5">
        <p className="line-clamp-2 min-h-[2.4em] text-[12px] leading-snug">
          {asset.caption ?? <span className="italic text-muted-foreground">описания нет</span>}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={caption.tone}>{caption.text}</Badge>
          {asset.available ? (
            <Badge tone="neutral">доступно</Badge>
          ) : (
            <Badge tone="muted">
              {asset.use_count > 0
                ? 'недавно выходила'
                : !asset.enabled
                  ? 'выключено'
                  : 'нет описания'}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 pt-0.5">
          <Switch
            checked={asset.enabled}
            aria-label={asset.enabled ? 'Вывести картинку из подбора' : 'Вернуть картинку в подбор'}
            onCheckedChange={async (enabled) => {
              const { ok } = await act(() => api.updateAsset(projectId, asset.id, { enabled }))
              if (ok) await onChanged()
            }}
          />
          <span className="text-[11px] leading-tight text-muted-foreground">
            {asset.enabled ? 'участвует в подборе' : 'не участвует'}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            size="xs"
            variant="ghost"
            className="px-1.5 text-muted-foreground"
            disabled={operation.running}
            onClick={async () => {
              await operation.run(() => api.recaptionAsset(projectId, asset.id), {
                successText: 'Описание обновлено',
              })
              await onChanged()
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Описать заново
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            className="ml-auto"
            title="Удалить из пула"
            aria-label="Удалить изображение из пула"
            onClick={() => onRemoveRequest(asset)}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}
