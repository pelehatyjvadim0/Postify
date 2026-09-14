import { Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

export interface WebImage {
  id: number
  title: string
  thumbnail_url: string
  source_url: string
  author?: string
  license?: string
}

export function WebImagePicker({ images, loading, selecting, hasMore, onNext, onSelect }: {
  images: WebImage[]
  loading: boolean
  selecting: boolean
  hasMore: boolean
  onNext: () => void
  onSelect: (image: WebImage) => void
}) {
  return (
    <div className="space-y-3 rounded-lg border border-border p-3" aria-busy={loading || selecting}>
      <p className="text-xs text-muted-foreground">Выберите изображение для поста</p>
      {loading ? (
        <div role="status" className="flex min-h-28 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> Ищем изображения
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {images.map((image) => (
            <div key={image.id} className="overflow-hidden rounded-md border border-border">
              <button type="button" disabled={selecting} onClick={() => onSelect(image)} className="block w-full text-left disabled:opacity-50" aria-label={`Выбрать: ${image.title}`}>
                <img src={image.thumbnail_url} alt={image.title} referrerPolicy="no-referrer" className="aspect-[16/10] w-full object-cover" />
                <span className="line-clamp-2 block p-2 text-xs">{image.title}</span>
              </button>
              <a href={image.source_url} target="_blank" rel="noreferrer" className="block px-2 pb-2 text-[11px] text-muted-foreground underline">Источник{image.license ? ` · ${image.license}` : ""}</a>
              {image.author && <p className="px-2 pb-2 text-[11px] text-muted-foreground">{image.author}</p>}
            </div>
          ))}
        </div>
      )}
      {!loading && images.length === 0 && <p className="text-xs text-muted-foreground">Изображения не найдены.</p>}
      {selecting && <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> Добавляем изображение</p>}
      <Button size="sm" variant="outline" disabled={loading || selecting || !hasMore} onClick={onNext}>
        <RefreshCw className="h-4 w-4" /> Найти другие
      </Button>
      {!hasMore && !loading && images.length > 0 && <p className="text-xs text-muted-foreground">Других изображений по этому запросу нет.</p>}
    </div>
  )
}
