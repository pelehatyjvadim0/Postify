import * as React from 'react'
import { AlertTriangle, Check, Loader2 } from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { dateTimeLabel, dayKey } from '@/lib/dates'
import { ApiError } from '@/lib/errors'
import { navigate } from '@/lib/router'
import { SLOT_STATUS } from '@/lib/status'
import { useOperation } from '@/lib/operation'
import { useToast } from '@/lib/toast'
import type { PostSummary, Project, SlotStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

const FILTERS: { value: SlotStatus | 'all'; label: string }[] = [
  { value: 'needs_review', label: 'На ревью' },
  { value: 'approved', label: 'Готовы' },
  { value: 'published', label: 'Опубликованы' },
  { value: 'failed', label: 'С ошибкой' },
  { value: 'all', label: 'Все' },
]

export function PostsScreen({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [filter, setFilter] = React.useState<SlotStatus | 'all'>('needs_review')
  const [posts, setPosts] = React.useState<PostSummary[]>([])
  const [loading, setLoading] = React.useState(true)
  const [busyId, setBusyId] = React.useState<number | null>(null)
  const toast = useToast()
  const operation = useOperation(project.id)

  // Смена проекта или фильтра: поздний ответ прежнего запроса игнорируется.
  const requestId = React.useRef(0)

  const load = React.useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    try {
      const page = await api.posts(project.id, filter === 'all' ? undefined : filter)
      if (id !== requestId.current) return
      setPosts(page)
    } catch (error) {
      if (id === requestId.current)
        toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить посты')
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [project.id, filter, toast])

  React.useEffect(() => {
    void load()
  }, [load])

  /** Открывает пост в плане: там полный текст, отчёт проверок и решения. */
  function open(post: PostSummary) {
    navigate('plan', dayKey(post.publish_at), String(post.slot_id))
  }

  async function approve(post: PostSummary) {
    setBusyId(post.id)
    try {
      await api.approvePost(project.id, post.id)
      toast.ok('Пост одобрен')
      await load()
      onChanged()
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Не удалось одобрить пост')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <AppHeader title="Посты">
        <div className="ml-2 inline-flex h-8 items-center rounded-lg bg-muted p-0.5 text-muted-foreground">
          {FILTERS.map((item) => (
            <button
              key={item.value}
              onClick={() => setFilter(item.value)}
              className={cn(
                'h-7 rounded-md px-3 text-[13px] font-medium transition-colors',
                filter === item.value
                  ? 'bg-background text-foreground shadow-sm'
                  : 'hover:text-foreground',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </AppHeader>

      <div className="flex-1 overflow-auto">
        <div className="mx-auto max-w-3xl space-y-2 p-4 md:p-6">
          {loading ? (
            <>
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
            </>
          ) : posts.length === 0 ? (
            <Alert tone="info" title="Постов в этом состоянии нет">
              Посты появляются, когда агент отработает слот контент-плана.
            </Alert>
          ) : (
            posts.map((post) => {
              const status = SLOT_STATUS[post.status]
              return (
                <div
                  key={post.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => open(post)}
                  onKeyDown={(event) => event.key === 'Enter' && open(post)}
                  className="cursor-pointer rounded-lg border border-border p-3 transition-colors hover:border-foreground/25 hover:bg-accent/40"
                >
                  <div className="mb-1 flex items-center gap-2">
                    <span className={cn('h-1.5 w-1.5 rounded-full', status.dot)} />
                    <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {post.publish_at ? dateTimeLabel(post.publish_at) : '—'}
                    </span>
                    <Badge tone={status.tone} className="ml-auto">
                      {status.label}
                    </Badge>
                  </div>
                  <p className="text-[13px] font-medium">{post.title}</p>
                  <p className="mt-0.5 line-clamp-2 text-[12.5px] leading-relaxed text-muted-foreground">
                    {post.excerpt}
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    {post.checks_summary.passed ? (
                      <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-600 dark:text-emerald-400">
                        <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
                        Проверки пройдены
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-[12px] text-amber-600 dark:text-amber-400">
                        <AlertTriangle className="h-3.5 w-3.5" strokeWidth={2.5} />
                        {post.checks_summary.blocking > 0
                          ? `${post.checks_summary.blocking} блокирующих`
                          : `${post.checks_summary.warnings} замечание`}
                      </span>
                    )}
                    <div className="ml-auto flex gap-2">
                      <Button size="xs" onClick={(event) => { event.stopPropagation(); open(post) }}>
                        Открыть
                      </Button>
                      {post.status === 'needs_review' && (
                        <Button
                          size="xs"
                          variant="outline"
                          disabled={busyId === post.id}
                          onClick={(event) => {
                            event.stopPropagation()
                            void approve(post)
                          }}
                        >
                          Одобрить
                        </Button>
                      )}
                      {post.status !== 'published' && (
                        <Button
                          size="xs"
                          variant="outline"
                          disabled={operation.running}
                          onClick={async (event) => {
                            event.stopPropagation()
                            await operation.run(() => api.regeneratePost(project.id, post.id), {
                              successText: 'Пост переписан',
                            })
                            await load()
                          }}
                        >
                          {operation.running ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                          Переписать
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
