import * as React from 'react'
import { AppHeader } from '@/components/AppHeader'
import { FieldHelp } from '@/components/FieldHelp'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { useAction } from '@/lib/action'
import { useSession } from '@/lib/session'
import { supportLog } from '@/lib/support'
import { useToast } from '@/lib/toast'
import type { Project } from '@/lib/types'
import { cn } from '@/lib/utils'

type Tab = 'project' | 'account'

const TABS: { value: Tab; label: string }[] = [
  { value: 'project', label: 'Проект' },
  { value: 'account', label: 'Аккаунт' },
]

export function SettingsScreen({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [tab, setTab] = React.useState<Tab>('project')
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <AppHeader title="Настройки">
        <div className="ml-2 inline-flex h-8 items-center rounded-lg bg-muted p-0.5 text-muted-foreground">
          {TABS.map((item) => (
            <button
              key={item.value}
              onClick={() => setTab(item.value)}
              className={cn(
                'h-7 rounded-md px-3 text-[13px] font-medium transition-colors',
                tab === item.value ? 'bg-background text-foreground shadow-sm' : 'hover:text-foreground',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </AppHeader>
      <div className="flex-1 overflow-auto">
        <div className="mx-auto max-w-2xl space-y-6 p-4 md:p-6">
          {tab === 'project' && <ProjectForm project={project} onChanged={onChanged} />}
          {tab === 'account' && <AccountForm />}
        </div>
      </div>
    </div>
  )
}

function Section({
  title,
  hint,
  help,
  children,
}: {
  title: string
  hint?: string
  help?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="space-y-3">
      <div>
        <div className="flex items-center gap-1.5">
          <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
          {help}
        </div>
        {hint && <p className="mt-0.5 text-[12px] text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </section>
  )
}

function ProjectForm({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [draft, setDraft] = React.useState(project)
  const [savingPrompt, setSavingPrompt] = React.useState(false)
  const [savingSettings, setSavingSettings] = React.useState(false)
  const [chatId, setChatId] = React.useState(project.channel.chat_id ?? '')
  const [botToken, setBotToken] = React.useState('')
  // Числовые поля держим строкой: иначе очистка поля молча сохраняла бы 0.
  const [lead, setLead] = React.useState(String(project.generation_lead_minutes))
  const [reuse, setReuse] = React.useState(String(project.media_reuse_days))
  const toast = useToast()
  const act = useAction()

  React.useEffect(() => {
    setDraft(project)
    setChatId(project.channel.chat_id ?? '')
    setLead(String(project.generation_lead_minutes))
    setReuse(String(project.media_reuse_days))
  }, [project])

  const set = <K extends keyof Project>(key: K, value: Project[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))

  async function savePrompt() {
    setSavingPrompt(true)
    const { ok } = await act(
      () => api.updateProject(project.id, { project_prompt: draft.project_prompt }),
      { ok: 'Промпт агента сохранён' },
    )
    setSavingPrompt(false)
    if (ok) onChanged()
  }

  async function saveSettings() {
    const leadMinutes = Number(lead)
    const reuseDays = Number(reuse)
    if (!Number.isInteger(leadMinutes) || leadMinutes < 1 || leadMinutes > 43200) {
      toast.error('Запас на генерацию должен быть от 1 до 43200 минут')
      return
    }
    if (!Number.isInteger(reuseDays) || reuseDays < 1 || reuseDays > 3650) {
      toast.error('Повтор изображений должен быть от 1 до 3650 дней')
      return
    }
    setSavingSettings(true)
    const { ok } = await act(
      () =>
        api.updateProject(project.id, {
          name: draft.name,
          timezone: draft.timezone,
          publication_mode: draft.publication_mode,
          generation_lead_minutes: leadMinutes,
          media_reuse_days: reuseDays,
          media_reuse_blocked: draft.media_reuse_blocked ?? true,
        }),
      { ok: 'Настройки проекта сохранены' },
    )
    setSavingSettings(false)
    if (ok) onChanged()
  }

  return (
    <>
      <Section
        title="Промпт агента"
        hint="Опишите одним текстом, что и как должен писать агент для этого проекта."
        help={
          <FieldHelp title="Промпт агента">
            Укажите аудиторию, стиль, форматы, ограничения и требования к результату.
          </FieldHelp>
        }
      >
        <Textarea
          rows={14}
          value={draft.project_prompt}
          onChange={(event) => set('project_prompt', event.target.value)}
          placeholder="Пиши для владельцев агробизнеса. Коротко и по делу, без рекламных обещаний. Используй конкретные цифры из задания, объясняй термины простым языком и заканчивай пост вопросом. Не используй больше двух эмодзи."
          aria-label="Промпт агента"
        />
        <Button onClick={savePrompt} disabled={savingPrompt}>
          {savingPrompt ? 'Сохраняю…' : 'Сохранить промпт'}
        </Button>
      </Section>

      <Section title="Проект">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Название"
            help={
              <FieldHelp title="Название">
                Как проект подписан у вас в списке слева. На текст постов не влияет.
              </FieldHelp>
            }
          >
            <Input value={draft.name} onChange={(event) => set('name', event.target.value)} />
          </Field>
          <Field
            label="Таймзона"
            help={
              <FieldHelp title="Таймзона">
                В этой зоне показываются даты плана и назначается время публикации.
              </FieldHelp>
            }
          >
            <Input value={draft.timezone} onChange={(event) => set('timezone', event.target.value)} />
          </Field>
        </div>
      </Section>

      <Section title="Публикация">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field
            label="Режим"
            help={
              <FieldHelp title="Режим публикации">
                Ревью — каждый пост ждёт вашего одобрения. Автопубликация — готовый пост уходит
                сам, а спорный остаётся на ревью.
              </FieldHelp>
            }
          >
            <Select
              value={draft.publication_mode}
              onValueChange={(value) => set('publication_mode', value as Project['publication_mode'])}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="review">ревью</SelectItem>
                <SelectItem value="auto">автопубликация</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field
            label="Запас на генерацию, мин"
            help={
              <FieldHelp title="Запас на генерацию">
                За сколько минут до публикации агент начинает писать пост. 1440 минут — сутки.
                Запас даёт время прочитать текст и поправить его до выхода.
              </FieldHelp>
            }
          >
            <Input
              type="number"
              min={1}
              max={43200}
              value={lead}
              onChange={(event) => setLead(event.target.value)}
            />
          </Field>
          <Field
            label="Повтор изображений, дней"
            help={
              <FieldHelp title="Повтор изображений">
                После одобрения поста изображение блокируется на указанный срок. Если выключить, изображения можно использовать без ограничений по повторам.
              </FieldHelp>
            }
          >
            <div className="relative">
            <Input
              className="pr-16 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              disabled={draft.media_reuse_blocked === false}
              type="number"
              min={1}
              max={3650}
              value={reuse}
              onChange={(event) => setReuse(event.target.value)}
            />
            <Switch className="absolute right-3 top-1/2 -translate-y-1/2" aria-label="Блокировать повторное использование изображений" checked={draft.media_reuse_blocked ?? true} onCheckedChange={(value) => set('media_reuse_blocked', value)} />
            </div>
          </Field>
        </div>
        {draft.publication_mode === 'auto' && (
          <Alert tone="warning" title="Автопубликация">
            Готовый пост уйдёт сам. Если агенту потребуется решение редактора, пост останется на
            ревью.
          </Alert>
        )}
      </Section>

      <Section
        title="Канал"
        hint="Токен бота принимается, но никогда не возвращается обратно."
        help={
          <FieldHelp title="Канал">
            Куда уходят одобренные посты. Без настроенного канала план работает, но публикации
            не будет.
          </FieldHelp>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Идентификатор канала"
            help={
              <FieldHelp title="Идентификатор канала">
                Имя канала вида @channel или его числовой id. Бот должен быть админом канала.
              </FieldHelp>
            }
          >
            <Input value={chatId} onChange={(event) => setChatId(event.target.value)} placeholder="@channel" />
          </Field>
          <Field
            label="Токен бота"
            help={
              <FieldHelp title="Токен бота">
                Токен бота, от имени которого выходят посты. Хранится зашифрованным и обратно не
              отдаётся — при замене введите новый.
              </FieldHelp>
            }
          >
            <Input
              type="password"
              value={botToken}
              onChange={(event) => setBotToken(event.target.value)}
              placeholder={project.channel.configured ? 'сохранён' : 'не задан'}
            />
          </Field>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!chatId || (!project.channel.configured && !botToken)}
            onClick={async () => {
              // Пустой токен не отправляем: сервер не отличит «не менять» от «стереть».
              const { ok } = await act(
                () =>
                  api.saveChannel(project.id, {
                    chat_id: chatId,
                    ...(botToken ? { bot_token: botToken } : {}),
                  }),
                { ok: 'Канал сохранён' },
              )
              if (!ok) return
              setBotToken('')
              onChanged()
            }}
          >
            Сохранить канал
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!project.channel.configured}
            onClick={async () => {
              const { value: channel } = await act(() => api.checkChannel(project.id))
              if (!channel) return
              supportLog('channel_checked', { project_id: project.id, status: channel.status })
              if (channel.status === 'ok') toast.ok('Канал отвечает')
              else toast.error('Канал не отвечает')
              onChanged()
            }}
          >
            Проверить
          </Button>
          <Badge tone={project.channel.status === 'ok' ? 'emerald' : 'muted'} className="ml-1">
            {!project.channel.configured
              ? 'не настроен'
              : project.channel.status === 'ok'
                ? 'подключён'
                : project.channel.status === 'error'
                  ? 'не отвечает'
                  : 'не проверен'}
          </Badge>
        </div>
      </Section>

      <Button onClick={saveSettings} disabled={savingSettings}>
        {savingSettings ? 'Сохраняю…' : 'Сохранить настройки'}
      </Button>
    </>
  )
}

function AccountForm() {
  const { user, logout } = useSession()
  const act = useAction()

  if (!user) return null

  return (
    <>
      <Section
        title="Аккаунт"
        hint="Вход выполняется через Telegram-бота, паролей нет."
        help={
          <FieldHelp title="Аккаунт">
            Ваш Telegram-аккаунт. Проекты принадлежат только вам: совместной работы, ролей и
            приглашений нет.
          </FieldHelp>
        }
      >
        <div className="rounded-lg border border-border p-3 text-[13px]">
          <p className="font-medium">{user.display_name}</p>
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            {user.telegram_username ? `@${user.telegram_username}` : 'Telegram-аккаунт привязан'}
          </p>
        </div>
      </Section>

      <Section
        title="Сессия"
        help={
          <FieldHelp title="Сессия">
            Выход завершает сессию в этом браузере. Вернуться можно повторным входом через бота.
          </FieldHelp>
        }
      >
        <Button
          size="sm"
          variant="outline"
          onClick={() => void act(() => logout(), { fail: 'Не удалось выйти' })}
        >
          Выйти
        </Button>
      </Section>
    </>
  )
}

function Field({
  label,
  hint,
  help,
  children,
}: {
  label: string
  hint?: string
  help?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex min-h-[16px] items-center gap-1.5">
        <Label className="truncate whitespace-nowrap">{label}</Label>
        {help && <span className="ml-auto shrink-0">{help}</span>}
      </div>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  )
}
