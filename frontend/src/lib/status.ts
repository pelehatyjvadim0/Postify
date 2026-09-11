import type { CheckLayer, SlotStatus } from './types'

// Подписи и цвета статусов из утверждённого мокапа ui-mockup/1-react-shadcn.html.
export const SLOT_STATUS: Record<
  SlotStatus,
  { label: string; dot: string; tone: 'neutral' | 'amber' | 'emerald' | 'red' | 'muted' }
> = {
  no_topic: { label: 'Тема не задана', dot: 'bg-red-500', tone: 'red' },
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
  supported: 'есть в теме слота',
  unsupported: 'нет в теме слота',
  contradicted: 'противоречит теме слота',
  match: 'соответствует',
  weak: 'слабое соответствие',
  mismatch: 'не соответствует',
}

/** Предупреждение из раздела 8 трейса: конкретика обязана быть в теме слота. */
export const TOPIC_SPECIFICS_HINT =
  'Вся проверяемая конкретика — цифры, даты, имена, ссылки — должна быть в теме слота. Слой проверок вырежет из поста всё, чего в теме нет.'
