import { cva, type VariantProps } from 'class-variance-authority'
import type * as React from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ring-1',
  {
    variants: {
      tone: {
        neutral: 'bg-secondary text-secondary-foreground ring-border',
        amber:
          'bg-amber-100 text-amber-900 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-500/30',
        emerald:
          'bg-emerald-100 text-emerald-900 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30',
        red: 'bg-red-100 text-red-900 ring-red-200 dark:bg-red-500/15 dark:text-red-300 dark:ring-red-500/30',
        muted: 'bg-transparent text-muted-foreground ring-border',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}
