import { HelpCircle } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

/** Кругляш с вопросом рядом с подписью поля: короткое объяснение настройки. */
export function FieldHelp({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Popover>
      <PopoverTrigger className="grid h-4 w-4 shrink-0 place-items-center rounded-full border border-border text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
        <HelpCircle className="h-4 w-4" strokeWidth={1.75} />
        <span className="sr-only">Что это за настройка</span>
      </PopoverTrigger>
      <PopoverContent>
        <p className="text-[13px] font-medium">{title}</p>
        <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{children}</p>
      </PopoverContent>
    </Popover>
  )
}
