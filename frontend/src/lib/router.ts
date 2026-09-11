import { useEffect, useState } from 'react'

// Бэкенд монтирует StaticFiles(html=True): произвольный путь отдаёт 404,
// а не index.html. Поэтому маршрутизация хешем — SPA переживает перезагрузку.
export type Screen = 'plan' | 'posts' | 'media' | 'settings'

const SCREENS: Screen[] = ['plan', 'posts', 'media', 'settings']

export interface Route {
  screen: Screen
  /** Хвост маршрута: для плана это дата и идентификатор слота. */
  params: string[]
}

function read(): Route {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  const screen = (SCREENS as string[]).includes(parts[0]) ? (parts[0] as Screen) : 'plan'
  return { screen, params: parts.slice(1) }
}

export function navigate(screen: Screen, ...params: string[]) {
  location.hash = `#/${[screen, ...params].join('/')}`
}

export function useRoute() {
  const [route, setRoute] = useState<Route>(read)
  useEffect(() => {
    const onChange = () => setRoute(read())
    addEventListener('hashchange', onChange)
    return () => removeEventListener('hashchange', onChange)
  }, [])
  return route
}
