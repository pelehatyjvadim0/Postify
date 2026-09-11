import * as React from 'react'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { dayKey, isoWithZone, offsetFor, timeOf } from '@/lib/dates'
import { TOPIC_SPECIFICS_HINT } from '@/lib/status'
import type { Rubric, Slot } from '@/lib/types'

export interface SlotDraft {
  slot: Slot | null
  date: string
}

export function SlotDialog({
  projectId,
  timezone,
  draft,
  rubrics,
  onClose,
  onSaved,
  onDeleteRequest,
}: {
  projectId: number
  /** Таймзона проекта: publish_at обязан нести именно её смещение. */
  timezone: string
  draft: SlotDraft | null
  rubrics: Rubric[]
  onClose: () => void
  onSaved: (slot: Slot) => void
  onDeleteRequest: (slot: Slot) => void
}) {
  const slot = draft?.slot ?? null
  const [date, setDate] = React.useState('')
  const [time, setTime] = React.useState('10:00')
  const [rubricId, setRubricId] = React.useState<string>('none')
  const [topic, setTopic] = React.useState('')
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!draft) return
    setError(null)
    setDate(slot ? dayKey(slot.publish_at) : draft.date)
    setTime(slot ? timeOf(slot.publish_at) : '10:00')
    // Рубрика не назначается молча: пустое значение так и уходит пустым.
    setRubricId(slot?.rubric ? String(slot.rubric.id) : 'none')
    setTopic(slot?.topic ?? '')
  }, [draft, slot, rubrics])

  if (!draft) return null

  // Выключенная рубрика в списке не нужна, но уже назначенную не прячем —
  // иначе сохранение молча сбросило бы её.
  const offered = rubrics.filter(
    (rubric) => rubric.enabled || rubric.id === slot?.rubric?.id,
  )

  const topicLocked = Boolean(slot?.post)

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const publishAt = isoWithZone(date, time, offsetFor(timezone, date, time))
      const rubric = rubricId === 'none' ? null : Number(rubricId)
      const saved = slot
        ? await api.updateSlot(projectId, slot.id, {
            publish_at: publishAt,
            rubric_id: rubric,
            ...(topicLocked ? {} : { topic }),
          })
        : await api.createSlot(projectId, { publish_at: publishAt, rubric_id: rubric, topic })
      onSaved(saved)
      onClose()
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Не удалось сохранить слот',
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{slot ? 'Слот контент-плана' : 'Новый слот'}</DialogTitle>
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-[1fr,120px,1fr] gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="slot-date">Дата публикации</Label>
              <Input
                id="slot-date"
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="slot-time">Время</Label>
              <Input
                id="slot-time"
                type="time"
                value={time}
                onChange={(event) => setTime(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Рубрика</Label>
              <Select value={rubricId} onValueChange={setRubricId}>
                <SelectTrigger>
                  <SelectValue placeholder="Без рубрики" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Без рубрики</SelectItem>
                  {offered.map((rubric) => (
                    <SelectItem key={rubric.id} value={String(rubric.id)}>
                      {rubric.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="slot-topic">Тема от редактора</Label>
            <Textarea
              id="slot-topic"
              rows={5}
              value={topic}
              disabled={topicLocked}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="Что разобрать в посте. Включите сюда все цифры, даты, имена и ссылки."
            />
          </div>

          <Alert tone="warning" title="Конкретика живёт в теме слота">
            {TOPIC_SPECIFICS_HINT}
          </Alert>

          {topicLocked && (
            <Alert tone="info" title="Тема заблокирована">
              По слоту уже сгенерирован пост. Чтобы сменить тему, сначала перепишите пост или
              удалите его.
            </Alert>
          )}

          {error && <Alert tone="error" title="Не сохранено">{error}</Alert>}

          <div className="flex items-center gap-2 pt-1">
            <Button onClick={save} disabled={saving || !date}>
              {saving ? 'Сохраняю…' : 'Сохранить'}
            </Button>
            <Button variant="outline" onClick={onClose}>
              Отмена
            </Button>
            {slot && (
              <Button
                variant="ghost"
                className="ml-auto text-muted-foreground"
                onClick={() => {
                  onClose()
                  onDeleteRequest(slot)
                }}
              >
                Удалить слот
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
