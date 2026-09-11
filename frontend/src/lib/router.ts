import { useEffect, useState } from 'react'

// Бэкенд монтирует StaticFiles(html=True): произвольный путь отдаёт 404,
// а не index.html. Поэтому маршрутизация хешем — SPA переживает перезагрузку.
export type Screen = 'plan' | 'posts' | 'media' | 'settings'

const SCREENS: Screen[] = ['plan', 'posts', 'media', 'settings']

function read(): Screen {
  const value = location.hash.replace(/^#\/?/, '').split('/')[0]
  return (SCREENS as string[]).includes(value) ? (value as Screen) : 'plan'
}

export function navigate(screen: Screen) {
  location.hash = `#/${screen}`
}

export function useRoute() {
  const [screen, setScreen] = useState<Screen>(read)
  useEffect(() => {
    const onChange = () => setScreen(read())
    addEventListener('hashchange', onChange)
    return () => removeEventListener('hashchange', onChange)
  }, [])
  return screen
}
