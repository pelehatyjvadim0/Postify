import * as React from 'react'
import { Sidebar } from '@/components/Sidebar'
import { Alert } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Plus } from 'lucide-react'
import { AuthScreen } from '@/screens/AuthScreen'
import { MediaScreen } from '@/screens/MediaScreen'
import { PlanScreen } from '@/screens/PlanScreen'
import { PostsScreen } from '@/screens/PostsScreen'
import { SettingsScreen } from '@/screens/SettingsScreen'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { NavProvider } from '@/lib/nav'
import { useRoute } from '@/lib/router'
import { useSession } from '@/lib/session'
import { useToast } from '@/lib/toast'
import type { Project, ProjectSummary } from '@/lib/types'

export function App() {
  const { user, loading, error, retry } = useSession()
  if (loading) return <BootSkeleton />
  if (error) return (
    <div className="mx-auto max-w-lg space-y-4 p-8">
      <Alert tone="error" title="Сервер временно недоступен">{error}</Alert>
      <Button onClick={retry}>Повторить подключение</Button>
    </div>
  )
  if (!user) return <AuthScreen />
  return <Workspace />
}

function Workspace() {
  const { user } = useSession()
  const projectStorageKey = `autoposttg:last-project:${user!.id}`
  const route = useRoute()
  const screen = route.screen
  const [projects, setProjects] = React.useState<ProjectSummary[]>([])
  const [project, setProject] = React.useState<Project | null>(null)
  const [projectId, setProjectId] = React.useState<number | null>(null)
  const [notFound, setNotFound] = React.useState(false)
  const [loading, setLoading] = React.useState(true)
  const [creating, setCreating] = React.useState(false)
  const [projectName, setProjectName] = React.useState('')
  const [projectTimezone, setProjectTimezone] = React.useState(Intl.DateTimeFormat().resolvedOptions().timeZone)
  const [saving, setSaving] = React.useState(false)
  const [createError, setCreateError] = React.useState<string | null>(null)
  const projectRequest = React.useRef(0)
  const toast = useToast()

  const loadProjects = React.useCallback(async () => {
    const list = await api.projects()
    setProjects(list)
    setProjectId((current) => {
      if (list.some((item) => item.id === current)) return current
      let remembered: number | null = null
      try { remembered = Number(localStorage.getItem(projectStorageKey)) } catch { /* storage unavailable */ }
      return list.find((item) => item.id === remembered)?.id ?? list[0]?.id ?? null
    })
    return list
  }, [projectStorageKey])

  React.useEffect(() => {
    if (projectId === null) return
    try { localStorage.setItem(projectStorageKey, String(projectId)) } catch { /* storage unavailable */ }
  }, [projectId, projectStorageKey])

  React.useEffect(() => {
    loadProjects()
      .catch((error) =>
        toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить проекты'),
      )
      .finally(() => setLoading(false))
  }, [loadProjects, toast])

  const loadProject = React.useCallback(async () => {
    if (projectId === null) return
    const request = ++projectRequest.current
    setNotFound(false)
    try {
      const loaded = await api.project(projectId)
      if (request === projectRequest.current) setProject(loaded)
    } catch (error) {
      if (request !== projectRequest.current) return
      // Чужой проект отвечает 404 — показываем «нет объекта», не «нет прав».
      if (error instanceof ApiError && error.isNotFound) {
        setProject(null)
        setNotFound(true)
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить проект')
      }
    }
  }, [projectId, toast])

  React.useEffect(() => {
    void loadProject()
  }, [loadProject])

  const refresh = React.useCallback(() => {
    void loadProject()
    void loadProjects().catch(() => undefined)
  }, [loadProject, loadProjects])

  async function createProject() {
    setSaving(true)
    setCreateError(null)
    try {
      const created = await api.createProject({ name: projectName.trim(), timezone: projectTimezone.trim() })
      await loadProjects()
      setProjectId(created.id)
      setProject(created)
      setCreating(false)
      setProjectName('')
    } catch (error) {
      setCreateError(error instanceof ApiError ? error.message : 'Не удалось создать проект')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <BootSkeleton />

  return (
    <NavProvider>
      <div className="flex h-screen overflow-hidden">
      <Sidebar
        projects={projects}
        project={project}
        current={screen}
        onSelectProject={(id) => {
          if (id === projectId) return
          projectRequest.current++
          setProject(null)
          setProjectId(id)
        }}
        onCreateProject={() => { setCreateError(null); setCreating(true) }}
      />
      {projects.length === 0 ? (
        <div className="flex min-w-0 flex-1 items-center justify-center p-6">
          <div className="space-y-4 text-center">
            <h1 className="text-xl font-semibold">Первый проект</h1>
            <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />Создать проект</Button>
          </div>
        </div>
      ) : notFound ? (
        <div className="min-w-0 flex-1 p-4 md:p-6">
          <Alert tone="error" title="Проект не найден">
            Объекта нет или он недоступен. Выберите другой проект.
          </Alert>
        </div>
      ) : !project ? (
        <div className="min-w-0 flex-1 space-y-3 p-4 md:p-6">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : screen === 'plan' ? (
        <PlanScreen
          key={project.id}
          project={project}
          onProjectChanged={refresh}
          focus={
            route.params.length === 2
              ? { date: route.params[0], slotId: Number(route.params[1]) }
              : null
          }
        />
      ) : screen === 'posts' ? (
        <PostsScreen key={project.id} project={project} onChanged={refresh} />
      ) : screen === 'media' ? (
        <MediaScreen key={project.id} project={project} onChanged={refresh} />
      ) : (
        <SettingsScreen key={project.id} project={project} onChanged={refresh} />
      )}
      <Dialog open={creating} onOpenChange={(open) => { if (!saving) setCreating(open) }}>
        <DialogContent>
          <DialogTitle>Новый проект</DialogTitle>
          <form className="mt-4 space-y-4" onSubmit={(event) => { event.preventDefault(); void createProject() }}>
            <div className="space-y-1.5">
              <Label htmlFor="project-name">Название</Label>
              <Input id="project-name" value={projectName} maxLength={200} required onChange={(event) => setProjectName(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="project-timezone">Таймзона</Label>
              <Input id="project-timezone" value={projectTimezone} required onChange={(event) => setProjectTimezone(event.target.value)} />
            </div>
            {createError && <Alert tone="error" title="Проект не создан">{createError}</Alert>}
            <Button type="submit" disabled={saving || !projectName.trim() || !projectTimezone.trim()}>{saving ? 'Создаю…' : 'Создать проект'}</Button>
          </form>
        </DialogContent>
      </Dialog>
      </div>
    </NavProvider>
  )
}

function BootSkeleton() {
  return (
    <div className="flex h-screen">
      <div className="hidden w-60 shrink-0 border-r border-border p-3 md:block">
        <Skeleton className="h-9 w-full" />
      </div>
      <div className="flex-1 space-y-3 p-6">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    </div>
  )
}
