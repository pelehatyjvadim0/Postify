import { Check } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

export function PublishedBadge() {
  return (
    <Badge tone="emerald" className="shrink-0 gap-1 rounded-full">
      <Check className="h-3 w-3" aria-hidden="true" />
      Опубликовано
    </Badge>
  )
}
