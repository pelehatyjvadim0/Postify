import * as React from 'react'

/**
 * Боковая панель на узком экране не помещается рядом с содержимым, поэтому
 * выезжает поверх него. Состояние держим здесь: открывает её шапка экрана,
 * а рисует боковая панель.
 */
interface NavValue {
  open: boolean
  setOpen: (value: boolean) => void
}

const NavContext = React.createContext<NavValue>({ open: false, setOpen: () => undefined })

export function NavProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false)
  const value = React.useMemo(() => ({ open, setOpen }), [open])

  React.useEffect(() => {
    if (!open) return

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open])

  return <NavContext.Provider value={value}>{children}</NavContext.Provider>
}

export const useNav = () => React.useContext(NavContext)
