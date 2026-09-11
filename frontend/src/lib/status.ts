import type { CheckLayer, SlotStatus } from './types'

// Подписи и цвета статусов из утверждённого мокапа ui-mockup/1-react-shadcn.html.
export const SLOT_STATUS: Record<
  SlotStatus,
  { label: string; dot: string; tone: 'neutral' | 'amber' | 'emerald' | 'red' | 'muted' }
> = {
  no_topic: { label: 'Промпт не задан', dot: 'bg-red-500', tone: 'red' },
  planned: { label: 'В плане', dot: 'bg-muted-foreground/25', tone: 'muted' },
  generating: { label: 'Генерируется', dot: 'bg-sky-500 animate-pulse', tone: 'neutral' },
  needs_review: { label: 'На ревью', dot: 'bg-amber-500', tone: 'amber' },
  approved: { label: 'Готов', dot: 'bg-emerald-500', tone: 'emerald' },
  published: { label: 'Опубликован', dot: 'bg-muted-foreground/40', tone: 'muted' },
  failed: { label: 'Ошибка', dot: 'bg-red-500', tone: 'red' },
  skipped: { label: 'Пропущен', dot: 'bg-muted-foreground/20', tone: 'muted' },
}

export const SLOT_STATUS_ORDER: SlotStatus[] = [
  'no_topic',
  'planned',
  'generating',
  'needs_review',
  'approved',
  'published',
  'failed',
  'skipped',
]

export const LAYER_TITLE: Record<CheckLayer, string> = {
  format: 'Формальные правила',
  rules: 'Следование инструкциям',
  grounding: 'Конкретика сверх плана',
  image: 'Картинка соответствует тексту',
}

export const VERDICT_LABEL: Record<string, string> = {
  supported: 'есть в промпте поста',
  unsupported: 'нет в промпте поста',
  contradicted: 'противоречит промпту поста',
  match: 'соответствует',
  weak: 'слабое соответствие',
  mismatch: 'не соответствует',
}

export const TOPIC_SPECIFICS_HINT =
  'Добавьте в промпт всю важную конкретику: цифры, даты, имена и ссылки. Агент не будет придумывать недостающие факты.'
