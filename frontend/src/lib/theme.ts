import { useCallback, useEffect, useState } from 'react'

export type Theme = 'dark' | 'light'

function readTheme(): Theme {
  try {
    return localStorage.getItem('theme') === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readTheme)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      localStorage.setItem('theme', theme)
    } catch {
      /* приватный режим — тема не запоминается */
    }
  }, [theme])

  const toggle = useCallback(() => setTheme((value) => (value === 'dark' ? 'light' : 'dark')), [])
  return { theme, toggle }
}
