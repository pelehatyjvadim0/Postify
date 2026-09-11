import * as React from 'react'
import { Loader2, RefreshCw, Search, Trash2, Upload } from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { useOperation } from '@/lib/operation'
import { useToast } from '@/lib/toast'
import type { MediaAsset, Project } from '@/lib/types'
import { cn } from '@/lib/utils'

const CAPTION_LABEL: Record<MediaAsset['caption_status'], { text: string; tone: 'neutral' | 'amber' | 'red' | 'emerald' }> = {
  pending: { text: 'подпись считается', tone: 'amber' },
  ready: { text: 'готово', tone: 'emerald' },
  failed: { text: 'подпись не построена', tone: 'red' },
}

export function MediaScreen({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [items, setItems] = React.useState<MediaAsset[]>([])
  const [loading, setLoading] = React.useState(true)
  const [query, setQuery] = React.useState('')
  const [availableOnly, setAvailableOnly] = React.useState(false)
  const [uploadError, setUploadError] = React.useState<string | null>(null)
  const fileInput = React.useRef<HTMLInputElement>(null)
  const toast = useToast()
  const operation = useOperation(project.id)

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const page = await api.media(project.id, {
        available: availableOnly || undefined,
        q: query || undefined,
        limit: 60,
      })
      setItems(page.items)
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить пул')
    } finally {
      setLoading(false)
    }
  }, [project.id, availableOnly, query, toast])

  React.useEffect(() => {
    void load()
  }, [load])

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return
    const form = new FormData()
    for (const file of Array.from(files).slice(0, 20)) form.append('files', file)
    setUploadError(null)
    const result = await operation.run(() => api.uploadMedia(project.id, form), {
      successText: 'Изображения загружены, подписи построены',
    })
    if (result?.status === 'failed')
      setUploadError(result.error?.message ?? 'Подписи не построены')
    await load()
    onChanged()
  }

  const noCaption = items.filter((item) => item.caption_status === 'failed').length
  const available = items.filter((item) => item.available).length

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
        <div className="relative ml-2 w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Поиск по подписи"
            className="h-8 pl-8 text-[13px]"
          />
        </div>
        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Switch checked={availableOnly} onCheckedChange={setAvailableOnly} />
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
        <div className="space-y-4 p-6">
          {operation.running && (
            <Alert tone="info" title="Идёт обработка">
              Файлы загружены. Подпись и эмбеддинг считаются асинхронно — до их появления
              изображение не участвует в подборе.
            </Alert>
          )}

          {uploadError && (
            <Alert tone="error" title="Подбор изображения недоступен">
              {uploadError} Загруженные файлы остались в пуле, но агент не сможет их выбрать, пока
              подписи не построены.
            </Alert>
          )}

          {!operation.running && !uploadError && noCaption > 0 && (
            <Alert tone="error" title="Подбор изображения недоступен">
              У {noCaption} изображений подпись не построена: провайдер vision не отвечает или ключ
              не задан. Такие активы в подбор не попадают.
            </Alert>
          )}

          {!loading && available === 0 && items.length > 0 && (
            <Alert tone="warning" title="Нет доступных изображений">
              Все активы либо выключены, либо использованы за последние {project.media_reuse_days}{' '}
              дней. Агент не сможет подобрать картинку.
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
              Загрузите изображения — агент выбирает картинку только из пула проекта.
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
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function AssetCard({
  asset,
  projectId,
  onChanged,
  operation,
}: {
  asset: MediaAsset
  projectId: number
  onChanged: () => Promise<void>
  operation: ReturnType<typeof useOperation>
}) {
  const caption = CAPTION_LABEL[asset.caption_status]
  const toast = useToast()

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
          {asset.caption ?? <span className="italic text-muted-foreground">подписи нет</span>}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={caption.tone}>{caption.text}</Badge>
          {asset.available ? (
            <Badge tone="neutral">доступно</Badge>
          ) : (
            <Badge tone="muted">
              {asset.use_count > 0 ? 'в политике повторов' : !asset.enabled ? 'выключено' : 'не в подборе'}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1.5 pt-0.5">
          <Switch
            checked={asset.enabled}
            onCheckedChange={async (enabled) => {
              await api.updateAsset(projectId, asset.id, { enabled })
              await onChanged()
            }}
          />
          <span className="text-[11px] text-muted-foreground">
            {asset.enabled ? 'включено' : 'выключено'}
          </span>
          <Button
            size="icon-sm"
            variant="ghost"
            title="Пересчитать подпись"
            disabled={operation.running}
            onClick={async () => {
              await operation.run(() => api.recaptionAsset(projectId, asset.id), {
                successText: 'Подпись пересчитана',
              })
              await onChanged()
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            title="Удалить"
            onClick={async () => {
              try {
                await api.deleteAsset(projectId, asset.id)
                await onChanged()
              } catch (error) {
                toast.error(error instanceof ApiError ? error.message : 'Не удалось удалить')
              }
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}
