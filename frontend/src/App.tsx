import * as React from 'react'
import { Sidebar } from '@/components/Sidebar'
import { Alert } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
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
  const { user, loading } = useSession()
  if (loading) return <BootSkeleton />
  if (!user) return <AuthScreen />
  return <Workspace />
}

function Workspace() {
  const route = useRoute()
  const screen = route.screen
  const [projects, setProjects] = React.useState<ProjectSummary[]>([])
  const [project, setProject] = React.useState<Project | null>(null)
  const [projectId, setProjectId] = React.useState<number | null>(null)
  const [notFound, setNotFound] = React.useState(false)
  const [loading, setLoading] = React.useState(true)
  const toast = useToast()

  const loadProjects = React.useCallback(async () => {
    const list = await api.projects()
    setProjects(list)
    setProjectId((current) => current ?? list[0]?.id ?? null)
    return list
  }, [])

  React.useEffect(() => {
    loadProjects()
      .catch((error) =>
        toast.error(error instanceof ApiError ? error.message : 'Не удалось загрузить проекты'),
      )
      .finally(() => setLoading(false))
  }, [loadProjects, toast])

  const loadProject = React.useCallback(async () => {
    if (projectId === null) return
    setNotFound(false)
    try {
      setProject(await api.project(projectId))
    } catch (error) {
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

  if (loading) return <BootSkeleton />

  return (
    <NavProvider>
      <div className="flex h-screen overflow-hidden">
      <Sidebar
        projects={projects}
        project={project}
        current={screen}
        onSelectProject={setProjectId}
      />
      {notFound ? (
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
          project={project}
          onProjectChanged={refresh}
          focus={
            route.params.length === 2
              ? { date: route.params[0], slotId: Number(route.params[1]) }
              : null
          }
        />
      ) : screen === 'posts' ? (
        <PostsScreen project={project} onChanged={refresh} />
      ) : screen === 'media' ? (
        <MediaScreen project={project} onChanged={refresh} />
      ) : (
        <SettingsScreen project={project} onChanged={refresh} />
      )}
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
