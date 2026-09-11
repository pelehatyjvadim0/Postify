import * as React from 'react'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { dayKey, isoWithZone, offsetFor, timeOf } from '@/lib/dates'
import { TOPIC_SPECIFICS_HINT } from '@/lib/status'
import type { Slot } from '@/lib/types'

export interface SlotDraft {
  slot: Slot | null
  date: string
}

export function SlotDialog({
  projectId,
  timezone,
  draft,
  onClose,
  onSaved,
  onDeleteRequest,
}: {
  projectId: number
  /** Таймзона проекта: publish_at обязан нести именно её смещение. */
  timezone: string
  draft: SlotDraft | null
  onClose: () => void
  onSaved: (slot: Slot) => void
  onDeleteRequest: (slot: Slot) => void
}) {
  const slot = draft?.slot ?? null
  const [date, setDate] = React.useState('')
  const [time, setTime] = React.useState('10:00')
  const [topic, setTopic] = React.useState('')
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!draft) return
    setError(null)
    setDate(slot ? dayKey(slot.publish_at) : draft.date)
    setTime(slot ? timeOf(slot.publish_at) : '10:00')
    setTopic(slot?.topic ?? '')
  }, [draft, slot])

  if (!draft) return null

  const topicLocked = Boolean(slot?.post)

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const publishAt = isoWithZone(date, time, offsetFor(timezone, date, time))
      const saved = slot
        ? await api.updateSlot(projectId, slot.id, {
            publish_at: publishAt,
            ...(topicLocked ? {} : { topic }),
          })
        : await api.createSlot(projectId, { publish_at: publishAt, rubric_id: null, topic })
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
          <div className="grid grid-cols-[1fr,120px] gap-3">
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
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="slot-topic">Промпт поста</Label>
            <Textarea
              id="slot-topic"
              rows={5}
              value={topic}
              disabled={topicLocked}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="Опишите, какой пост нужно написать. Добавьте тему, факты, цифры, даты, имена и ссылки."
            />
          </div>

          <Alert tone="warning" title="Конкретика живёт в промпте поста">
            {TOPIC_SPECIFICS_HINT}
          </Alert>

          {topicLocked && (
            <Alert tone="info" title="Промпт заблокирован">
              По слоту уже сгенерирован пост. Чтобы изменить промпт, сначала перепишите пост или
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
