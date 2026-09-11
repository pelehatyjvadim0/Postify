import { AlertTriangle, Info, XCircle } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'

const tones = {
  info: {
    box: 'border-border bg-muted/40 text-foreground',
    icon: 'text-muted-foreground',
    Icon: Info,
  },
  warning: {
    box: 'border-amber-200 bg-amber-50/60 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200',
    icon: 'text-amber-600 dark:text-amber-400',
    Icon: AlertTriangle,
  },
  error: {
    box: 'border-red-200 bg-red-50/60 text-red-900 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200',
    icon: 'text-red-600 dark:text-red-400',
    Icon: XCircle,
  },
} as const

export function Alert({
  tone = 'info',
  title,
  children,
  className,
}: {
  tone?: keyof typeof tones
  title?: string
  children?: React.ReactNode
  className?: string
}) {
  const { box, icon, Icon } = tones[tone]
  return (
    <div className={cn('flex items-start gap-2.5 rounded-md border px-3 py-2.5', box, className)}>
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', icon)} />
      <div className="min-w-0 space-y-0.5">
        {title && <p className="text-[13px] font-medium">{title}</p>}
        {children && <div className="text-[12px] leading-relaxed opacity-90">{children}</div>}
      </div>
    </div>
  )
}
