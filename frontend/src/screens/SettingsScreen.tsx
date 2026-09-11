import * as React from 'react'
import { Loader2, Plus, Trash2, Wand2 } from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { FieldHelp } from '@/components/FieldHelp'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { useOperation } from '@/lib/operation'
import { useSession } from '@/lib/session'
import { supportLog } from '@/lib/support'
import { useToast } from '@/lib/toast'
import type { Project, Rubric, Rule } from '@/lib/types'
import { cn } from '@/lib/utils'

type Tab = 'project' | 'rubrics' | 'rules' | 'account'

const TABS: { value: Tab; label: string }[] = [
  { value: 'project', label: 'Проект' },
  { value: 'rubrics', label: 'Рубрики' },
  { value: 'rules', label: 'Правила' },
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
        <div className="mx-auto max-w-2xl space-y-6 p-6">
          {tab === 'project' && <ProjectForm project={project} onChanged={onChanged} />}
          {tab === 'rubrics' && <RubricsForm project={project} />}
          {tab === 'rules' && <RulesForm project={project} />}
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
  const [saving, setSaving] = React.useState(false)
  const [chatId, setChatId] = React.useState(project.channel.chat_id ?? '')
  const [botToken, setBotToken] = React.useState('')
  const toast = useToast()

  React.useEffect(() => {
    setDraft(project)
    setChatId(project.channel.chat_id ?? '')
  }, [project])

  const set = <K extends keyof Project>(key: K, value: Project[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))

  async function save() {
    setSaving(true)
    try {
      await api.updateProject(project.id, {
        name: draft.name,
        timezone: draft.timezone,
        language: draft.language,
        audience: draft.audience,
        tone: draft.tone,
        project_prompt: draft.project_prompt,
        publication_mode: draft.publication_mode,
        generation_lead_minutes: draft.generation_lead_minutes,
        media_reuse_days: draft.media_reuse_days,
      })
      toast.ok('Настройки проекта сохранены')
      onChanged()
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Section
        title="Проект"
        help={
          <FieldHelp title="Проект">
            Проект — это один Telegram-канал: свой контент-план, свои рубрики, правила и пул
              изображений. Настройки ниже агент учитывает при написании каждого поста.
          </FieldHelp>
        }
      >
        <div className="grid grid-cols-2 gap-3">
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
          <Field
            label="Аудитория"
            help={
              <FieldHelp title="Аудитория">
                Для кого канал. Агент подбирает под это глубину объяснений и примеры.
              </FieldHelp>
            }
          >
            <Input value={draft.audience} onChange={(event) => set('audience', event.target.value)} />
          </Field>
          <Field
            label="Тон"
            help={
              <FieldHelp title="Тон">
                Манера речи: сухо и по делу, дружелюбно, с примерами. Проверяется слоем правил.
              </FieldHelp>
            }
          >
            <Input value={draft.tone} onChange={(event) => set('tone', event.target.value)} />
          </Field>
        </div>
        <Field
          label="Промпт проекта"
          hint="Специфика этого канала. Общий промпт задаётся в аккаунте."
          help={
            <FieldHelp title="Промпт проекта">
              Указания именно для этого канала: что писать, чего избегать, как оформлять. Идут в
            каждую генерацию вместе с общим промптом и темой слота.
            </FieldHelp>
          }
        >
          <Textarea
            rows={5}
            value={draft.project_prompt}
            onChange={(event) => set('project_prompt', event.target.value)}
          />
        </Field>
      </Section>

      <Section title="Публикация">
        <div className="grid grid-cols-3 gap-3">
          <Field
            label="Режим"
            help={
              <FieldHelp title="Режим публикации">
                Ревью — каждый пост ждёт вашего одобрения. Автопубликация — пост уходит сам, если
                все проверки зелёные; любое нарушение отправляет его на ревью.
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
              value={draft.generation_lead_minutes}
              onChange={(event) => set('generation_lead_minutes', Number(event.target.value))}
            />
          </Field>
          <Field
            label="Повтор изображений, дней"
            help={
              <FieldHelp title="Повтор изображений">
                Сколько дней изображение не возвращается в подбор после использования. Не даёт
                одной и той же картинке выходить в канал слишком часто.
              </FieldHelp>
            }
          >
            <Input
              type="number"
              value={draft.media_reuse_days}
              onChange={(event) => set('media_reuse_days', Number(event.target.value))}
            />
          </Field>
        </div>
        {draft.publication_mode === 'auto' && (
          <Alert tone="warning" title="Автопубликация">
            Пост уходит сам только при полностью зелёных проверках. Любое нарушение отправляет его
            на ревью.
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
        <div className="grid grid-cols-2 gap-3">
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
            onClick={async () => {
              await api.saveChannel(project.id, { bot_token: botToken, chat_id: chatId })
              setBotToken('')
              toast.ok('Канал сохранён')
              onChanged()
            }}
          >
            Сохранить канал
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              const channel = await api.checkChannel(project.id)
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

      <Button onClick={save} disabled={saving}>
        {saving ? 'Сохраняю…' : 'Сохранить настройки'}
      </Button>
    </>
  )
}

function RubricsForm({ project }: { project: Project }) {
  const [rubrics, setRubrics] = React.useState<Rubric[]>([])
  const [name, setName] = React.useState('')
  const [instructions, setInstructions] = React.useState('')
  const toast = useToast()

  const load = React.useCallback(async () => {
    setRubrics(await api.rubrics(project.id))
  }, [project.id])

  React.useEffect(() => {
    void load()
  }, [load])

  return (
    <>
      <Section
        title="Рубрики"
        hint="Инструкции формата, которые агент применяет к слоту."
        help={
          <FieldHelp title="Рубрики">
            Рубрика — формат поста: кейс, новость, подборка. У слота плана выбирается рубрика, и
            агент пишет по её инструкции. Выключенная рубрика не предлагается в новых слотах,
            а занятую слотами удалить нельзя.
          </FieldHelp>
        }
      >
        <div className="space-y-2">
          {rubrics.map((rubric) => (
            <div key={rubric.id} className="rounded-lg border border-border p-3">
              <div className="flex items-center gap-2">
                <Input
                  value={rubric.name}
                  className="h-8 max-w-[220px] text-[13px]"
                  onChange={(event) =>
                    setRubrics((list) =>
                      list.map((item) =>
                        item.id === rubric.id ? { ...item, name: event.target.value } : item,
                      ),
                    )
                  }
                />
                <Switch
                  checked={rubric.enabled}
                  onCheckedChange={async (enabled) => {
                    await api.updateRubric(project.id, rubric.id, { enabled })
                    await load()
                  }}
                />
                <span className="text-[11px] text-muted-foreground">
                  {rubric.enabled ? 'включена' : 'выключена'}
                </span>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  className="ml-auto"
                  onClick={async () => {
                    try {
                      await api.deleteRubric(project.id, rubric.id)
                      await load()
                    } catch (error) {
                      // 409 rubric_in_use: рубрику держат слоты плана.
                      toast.error(
                        error instanceof ApiError ? error.message : 'Не удалось удалить рубрику',
                      )
                    }
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
              <Textarea
                rows={2}
                className="mt-2 text-[13px]"
                value={rubric.instructions}
                onChange={(event) =>
                  setRubrics((list) =>
                    list.map((item) =>
                      item.id === rubric.id ? { ...item, instructions: event.target.value } : item,
                    ),
                  )
                }
                onBlur={() => api.updateRubric(project.id, rubric.id, rubric)}
              />
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="Новая рубрика"
        help={
          <FieldHelp title="Новая рубрика">
            Название видно при выборе рубрики в слоте, инструкция целиком уходит агенту.
            Пишите её как указание: «История хозяйства: задача, что сделали, что получилось».
          </FieldHelp>
        }
      >
        <div className="space-y-2">
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Название" />
          <Textarea
            rows={2}
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            placeholder="Инструкция формата"
          />
          <Button
            size="sm"
            disabled={!name}
            onClick={async () => {
              await api.createRubric(project.id, { name, instructions })
              setName('')
              setInstructions('')
              await load()
            }}
          >
            <Plus className="h-3.5 w-3.5" />
            Добавить
          </Button>
        </div>
      </Section>
    </>
  )
}

function RulesForm({ project }: { project: Project }) {
  const [rules, setRules] = React.useState<Rule[]>([])
  const [proposal, setProposal] = React.useState<Rule[] | null>(null)
  const operation = useOperation(project.id)
  const toast = useToast()

  const load = React.useCallback(async () => {
    setRules(await api.rules(project.id))
  }, [project.id])

  React.useEffect(() => {
    void load()
  }, [load])

  const update = (id: number, patch: Partial<Rule>) =>
    setRules((list) => list.map((rule) => (rule.id === id ? { ...rule, ...patch } : rule)))

  return (
    <>
      <Section
        title="Правила проверки"
        hint="Пост сверяется с этим чеклистом: «блокирует» отправляет на доработку, «предупреждает» только помечает для редактора."
        help={
          <FieldHelp title="Правила проверки">
            Готовый пост сверяется с этим списком построчно. Нарушение правила «блокирует»
            отправляет пост на доработку, «предупреждает» — только помечается для вас. Правила
            можно написать руками или попросить агента разобрать промпт проекта на пункты.
          </FieldHelp>
        }
      >
        <div className="space-y-2">
          {rules.map((rule) => (
            <div key={rule.id} className="flex items-center gap-2 rounded-lg border border-border p-2.5">
              <Input
                value={rule.text}
                className="h-8 flex-1 text-[13px]"
                onChange={(event) => update(rule.id, { text: event.target.value })}
              />
              <Select
                value={rule.severity}
                onValueChange={(value) => update(rule.id, { severity: value as Rule['severity'] })}
              >
                <SelectTrigger className="h-8 w-[110px] text-[13px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="block">блокирует</SelectItem>
                  <SelectItem value="warn">предупреждает</SelectItem>
                </SelectContent>
              </Select>
              <Badge tone="muted">{rule.origin === 'derived' ? 'из промпта' : 'вручную'}</Badge>
              <Switch
                checked={rule.enabled}
                onCheckedChange={(enabled) => update(rule.id, { enabled })}
              />
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={() => setRules((list) => list.filter((item) => item.id !== rule.id))}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={async () => {
              await api.saveRules(project.id, rules)
              toast.ok('Правила сохранены')
              await load()
            }}
          >
            Сохранить правила
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              setRules((list) => [
                ...list,
                {
                  id: -Date.now(),
                  text: '',
                  severity: 'warn',
                  enabled: true,
                  origin: 'manual',
                  position: list.length + 1,
                },
              ])
            }
          >
            <Plus className="h-3.5 w-3.5" />
            Добавить правило
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={operation.running}
            className="ml-auto"
            onClick={async () => {
              const result = await operation.run(() => api.deriveRules(project.id), {
                successText: 'Агент разобрал промпт проекта',
              })
              const derived = (result?.result as { rules?: Rule[] } | undefined)?.rules
              if (derived) setProposal(derived)
            }}
          >
            {operation.running ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Wand2 className="h-3.5 w-3.5" />
            )}
            Разобрать промпт
          </Button>
        </div>
      </Section>

      {proposal && (
        <Section title="Предложение агента" hint="Ничего не записано: примите список целиком или закройте.">
          <div className="space-y-1.5">
            {proposal.map((rule) => (
              <div key={rule.id} className="flex items-center gap-2 rounded-md border border-border px-3 py-2">
                <span className="flex-1 text-[13px]">{rule.text}</span>
                <Badge tone="muted">
                  {rule.severity === 'block' ? 'блокирует' : 'предупреждает'}
                </Badge>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => {
                setRules(proposal)
                setProposal(null)
              }}
            >
              Перенести в правила
            </Button>
            <Button size="sm" variant="outline" onClick={() => setProposal(null)}>
              Закрыть
            </Button>
          </div>
        </Section>
      )}
    </>
  )
}

function AccountForm() {
  const { user, setUser, logout } = useSession()
  const [prompt, setPrompt] = React.useState(user?.common_prompt ?? '')
  const toast = useToast()

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
        title="Общий промпт"
        hint="Один на все проекты. Системный промпт сервера не редактируется."
        help={
          <FieldHelp title="Общий промпт">
            Указания, общие для всех ваших проектов: язык, запреты, манера. Чтобы не повторять
            одно и то же в промпте каждого канала.
          </FieldHelp>
        }
      >
        <Textarea rows={5} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        <Button
          size="sm"
          onClick={async () => {
            const saved = await api.saveCommonPrompt(prompt)
            setUser({ ...user, common_prompt: saved.common_prompt })
            toast.ok('Общий промпт сохранён')
          }}
        >
          Сохранить
        </Button>
      </Section>

      <Section
        title="Сессия"
        help={
          <FieldHelp title="Сессия">
            Выход завершает сессию в этом браузере. Вернуться можно повторным входом через бота.
          </FieldHelp>
        }
      >
        <Button size="sm" variant="outline" onClick={() => void logout()}>
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
