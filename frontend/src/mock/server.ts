import type {
  LoginStatus,
  MediaAsset,
  Operation,
  OperationPurpose,
  Post,
  PostSummary,
  Project,
  ProjectSummary,
  Publication,
  Rubric,
  Rule,
  Slot,
  User,
} from '@/lib/types'
import { ApiError } from '@/lib/errors'
import {
  buildMedia,
  buildPosts,
  buildSlots,
  foreignProjectIds,
  placeholder,
  projects as seedProjects,
  shiftIso,
  rubrics as seedRubrics,
  rules as seedRules,
  user as seedUser,
} from './data'

// Заглушки бэкенда. Отвечают в формате контракта, включая 202 + поллинг
// и 404 на чужой project_id.

class MockError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly field?: string,
  ) {
    super(message)
  }
}

const notFound = () => new MockError(404, 'not_found', 'Объект не найден')

interface State {
  user: User
  loggedIn: boolean
  projects: Project[]
  rubrics: Record<number, Rubric[]>
  rules: Record<number, Rule[]>
  slots: Record<number, Slot[]>
  posts: Record<number, Post[]>
  media: Record<number, MediaAsset[]>
  operations: Operation[]
  publications: Publication[]
  nextId: number
}

const media: Record<number, MediaAsset[]> = { 3: buildMedia(3), 8: buildMedia(8) }

const state: State = {
  user: { ...seedUser },
  loggedIn: readSession(),
  // Счётчики проекта считаются по фактическому пулу: интерфейс показывает их
  // человеку, расхождение с содержимым выглядело бы ошибкой.
  projects: seedProjects.map((p) => ({
    ...p,
    media: media[p.id]
      ? { total: media[p.id].length, available: media[p.id].filter((a) => a.available).length }
      : p.media,
  })),
  rubrics: structuredClone(seedRubrics),
  rules: structuredClone(seedRules),
  slots: { 3: buildSlots(3), 8: buildSlots(8) },
  posts: { 3: buildPosts(), 8: [] },
  media,
  operations: [],
  publications: [
    { id: 1, post_id: 101, published_at: '2026-10-02T18:00:00+03:00', message_url: 'https://t.me/agrotech/1021', status: 'delivered' },
    { id: 2, post_id: 102, published_at: '2026-10-05T10:00:00+03:00', message_url: 'https://t.me/agrotech/1022', status: 'delivered' },
    { id: 3, post_id: 103, published_at: '2026-10-07T10:00:00+03:00', message_url: 'https://t.me/agrotech/1023', status: 'delivered' },
  ],
  nextId: 500,
}

function readSession() {
  try {
    return localStorage.getItem('mock-session') === '1'
  } catch {
    return false
  }
}

function writeSession(value: boolean) {
  try {
    if (value) localStorage.setItem('mock-session', '1')
    else localStorage.removeItem('mock-session')
  } catch {
    /* приватный режим */
  }
}

const nextId = () => ++state.nextId

function project(id: number): Project {
  // Чужой проект неотличим от несуществующего: контракт требует 404.
  if (foreignProjectIds.includes(id)) throw notFound()
  const found = state.projects.find((p) => p.id === id)
  if (!found) throw notFound()
  return found
}

function summary(p: Project): ProjectSummary {
  const slots = state.slots[p.id] ?? []
  const count = (status: string) => slots.filter((s) => s.status === status).length
  return {
    id: p.id,
    name: p.name,
    channel_title: p.channel.chat_id,
    publication_mode: p.publication_mode,
    counts: {
      needs_review: count('needs_review'),
      no_topic: count('no_topic'),
      planned: count('planned'),
    },
  }
}

function postSummary(projectId: number, post: Post): PostSummary {
  const slot = (state.slots[projectId] ?? []).find((s) => s.id === post.slot_id)
  return {
    id: post.id,
    slot_id: post.slot_id,
    status: post.status,
    title: slot?.post?.title ?? 'Без заголовка',
    excerpt: slot?.post?.excerpt ?? post.post_text.slice(0, 120),
    publish_at: slot?.publish_at ?? '',
    rubric: slot?.rubric ?? null,
    checks_summary: slot?.post?.checks_summary ?? { passed: true, blocking: 0, warnings: 0 },
  }
}

/** Длительная операция: сначала running, затем эффект и succeeded. */
const pending = new Map<number, { finishAt: number; apply: () => void; fail?: { code: string; message: string } }>()

function startOperation(
  purpose: OperationPurpose,
  apply: (operation: Operation) => void,
  options: { seconds?: number; fail?: { code: string; message: string } } = {},
) {
  const id = nextId()
  const operation: Operation = {
    operation_id: id,
    status: 'running',
    purpose,
    actor: 'user',
    error: null,
    started_at: new Date().toISOString(),
    finished_at: null,
  }
  state.operations.unshift(operation)
  pending.set(id, {
    finishAt: Date.now() + (options.seconds ?? 5) * 1000,
    apply: () => apply(operation),
    fail: options.fail,
  })
  return { operation_id: id, status: 'running' as const }
}

function settle(operation: Operation) {
  const task = pending.get(operation.operation_id)
  if (!task || Date.now() < task.finishAt) return operation
  pending.delete(operation.operation_id)
  if (task.fail) {
    operation.status = 'failed'
    operation.error = task.fail
  } else {
    task.apply()
    operation.status = 'succeeded'
  }
  operation.finished_at = new Date().toISOString()
  return operation
}

function slotOf(projectId: number, slotId: number) {
  const slot = (state.slots[projectId] ?? []).find((s) => s.id === slotId)
  if (!slot) throw notFound()
  return slot
}

function postOf(projectId: number, postId: number) {
  const post = (state.posts[projectId] ?? []).find((x) => x.id === postId)
  if (!post) throw notFound()
  return post
}

function generatedPost(projectId: number, slot: Slot): Post {
  const id = nextId()
  const text = `${slot.topic}\n\nЧерновик сгенерирован агентом по теме слота. Проверяемая конкретика взята только из темы.\n\nЧто думаете?`
  const post: Post = {
    id,
    slot_id: slot.id,
    status: 'needs_review',
    post_text: text,
    char_count: text.length,
    media: {
      asset_id: 41,
      caption: 'Подобранное изображение из пула проекта',
      url: placeholder(id, 'подобранное изображение'),
      rationale: 'Ближайший по смыслу актив из пула',
      last_used_at: null,
    },
    generation: {
      provider: 'codex',
      model: 'gpt-5.6-terra',
      reasoning_effort: 'medium',
      iterations: 1,
      generated_at: new Date().toISOString(),
    },
    validation: {
      passed: true,
      iterations: 1,
      layers: [
        { layer: 'format', passed: true, score: '6/6', items: [{ key: 'length', passed: true, detail: `${text.length} из 4096` }] },
        { layer: 'rules', passed: true, score: '4/4', items: [{ rule_id: 12, text: 'Вопрос в конце', passed: true, evidence: 'Что думаете?' }] },
        { layer: 'grounding', passed: true, items: [{ claim: '—', verdict: 'supported', detail: 'Конкретики сверх темы нет' }] },
        { layer: 'image', passed: true, items: [{ asset_id: 41, verdict: 'match', detail: 'Соответствует теме' }] },
      ],
    },
    published: null,
  }
  state.posts[projectId] = [post, ...(state.posts[projectId] ?? [])]
  slot.status = 'needs_review'
  slot.post = {
    id: post.id,
    title: slot.topic.slice(0, 60),
    excerpt: text.slice(0, 100),
    media_thumb_url: placeholder(id, 'подобранное изображение', 'thumb'),
    checks_summary: { passed: true, blocking: 0, warnings: 0 },
  }
  return post
}

/**
 * Вход по контракту: POST /auth/login выдаёт browser_token и диплинк, дальше
 * фронтенд опрашивает статус. Мок проходит pending → confirmation → исход.
 * Исход выбирается ключом mock-login-outcome, чтобы оператор мог посмотреть
 * все четыре ветки без бэкенда.
 */
interface LoginRequestState {
  token: string
  startedAt: number
  outcome: 'approved' | 'denied' | 'expired'
}

let loginRequest: LoginRequestState | null = null

function readOutcome(): LoginRequestState['outcome'] {
  try {
    const value = localStorage.getItem('mock-login-outcome')
    if (value === 'denied' || value === 'expired') return value
  } catch {
    /* приватный режим */
  }
  return 'approved'
}

function startLogin() {
  const token = `mock-${Math.random().toString(36).slice(2, 10)}`
  loginRequest = { token, startedAt: Date.now(), outcome: readOutcome() }
  return {
    browser_token: token,
    telegram_url: `https://t.me/autopost_auth_bot?start=login_${token}`,
    expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
  }
}

function loginStatus(token: string): { status: LoginStatus; user?: typeof state.user; csrf?: string } {
  if (!loginRequest || loginRequest.token !== token)
    throw new MockError(404, 'login_request_expired', 'Запрос на вход истёк')
  const elapsed = Date.now() - loginRequest.startedAt
  if (elapsed < 3000) return { status: 'pending' }
  if (elapsed < 7000) return { status: 'confirmation' }
  if (loginRequest.outcome === 'expired')
    throw new MockError(404, 'login_request_expired', 'Запрос на вход истёк')
  if (loginRequest.outcome === 'denied') return { status: 'denied' }
  state.loggedIn = true
  writeSession(true)
  return { status: 'approved', user: state.user, csrf: 'mock-csrf-token' }
}

function match(path: string, pattern: RegExp) {
  const found = pattern.exec(path)
  return found ? found.slice(1).map(Number) : null
}

export async function mockRequest<T>(
  method: string,
  url: string,
  body?: unknown,
  form?: FormData,
): Promise<T> {
  // Небольшая задержка, чтобы состояния загрузки были видны.
  await new Promise((resolve) => setTimeout(resolve, 120))
  const [path, search = ''] = url.split('?')
  const query = new URLSearchParams(search)
  const payload = (body ?? {}) as Record<string, never>

  try {
    return handle(method, path, query, payload, form) as T
  } catch (error) {
    if (error instanceof MockError) {
      throw new ApiError(error.status, error.code, error.message, error.field)
    }
    throw error
  }
}

function handle(
  method: string,
  path: string,
  query: URLSearchParams,
  body: Record<string, never>,
  form?: FormData,
): unknown {
  const get = <V>(key: string): V => body[key] as unknown as V

  // ——— вход через Telegram-бота ———
  if (path === '/api/auth/login' && method === 'POST') return startLogin()

  if (path === '/api/auth/login/status' && method === 'GET')
    return loginStatus(query.get('request') ?? '')

  if (path === '/api/auth/logout' && method === 'POST') {
    state.loggedIn = false
    writeSession(false)
    return undefined
  }

  if (!state.loggedIn) throw new MockError(401, 'unauthorized', 'Нужен вход')

  if (path === '/api/me' && method === 'GET') return state.user
  if (path === '/api/me/prompt' && method === 'PUT') {
    state.user.common_prompt = String(get<string>('prompt') ?? '')
    return { common_prompt: state.user.common_prompt }
  }

  // ——— проекты ———
  if (path === '/api/projects' && method === 'GET') return state.projects.map(summary)
  if (path === '/api/projects' && method === 'POST') {
    const created: Project = {
      ...state.projects[0],
      id: nextId(),
      name: String(get<string>('name') ?? 'Новый проект'),
      timezone: String(get<string>('timezone') ?? 'Europe/Moscow'),
      project_prompt: '',
      audience: '',
      tone: '',
      channel: { configured: false, chat_id: null, status: 'unchecked', checked_at: null },
      media: { total: 0, available: 0 },
    }
    state.projects.push(created)
    state.slots[created.id] = []
    state.posts[created.id] = []
    state.rubrics[created.id] = []
    state.rules[created.id] = []
    state.media[created.id] = []
    return created
  }

  const projectId = Number(/^\/api\/projects\/(\d+)/.exec(path)?.[1] ?? NaN)
  if (Number.isNaN(projectId)) throw notFound()
  const current = project(projectId)
  const rest = path.replace(`/api/projects/${projectId}`, '')

  if (rest === '' && method === 'GET') return current
  if (rest === '' && method === 'PUT') {
    Object.assign(current, body)
    return current
  }
  if (rest === '' && method === 'DELETE') {
    state.projects = state.projects.filter((p) => p.id !== projectId)
    return undefined
  }

  // ——— канал ———
  if (rest === '/channel' && method === 'PUT') {
    current.channel = {
      configured: true,
      chat_id: String(get<string>('chat_id') ?? ''),
      status: 'ok',
      checked_at: new Date().toISOString(),
    }
    return current.channel
  }
  if (rest === '/channel/check' && method === 'POST') {
    current.channel = { ...current.channel, status: current.channel.configured ? 'ok' : 'error', checked_at: new Date().toISOString() }
    return current.channel
  }
  if (rest === '/channel' && method === 'DELETE') {
    current.channel = { configured: false, chat_id: null, status: 'unchecked', checked_at: null }
    return undefined
  }

  // ——— рубрики ———
  const rubrics = (state.rubrics[projectId] ??= [])
  if (rest === '/rubrics' && method === 'GET') return rubrics
  if (rest === '/rubrics' && method === 'POST') {
    const created: Rubric = {
      id: nextId(),
      name: String(get<string>('name') ?? ''),
      instructions: String(get<string>('instructions') ?? ''),
      enabled: true,
    }
    rubrics.push(created)
    return created
  }
  const rubricIds = match(rest, /^\/rubrics\/(\d+)$/)
  if (rubricIds) {
    const rubric = rubrics.find((r) => r.id === rubricIds[0])
    if (!rubric) throw notFound()
    if (method === 'PUT') {
      Object.assign(rubric, body)
      return rubric
    }
    if (method === 'DELETE') {
      const used = (state.slots[projectId] ?? []).some((s) => s.rubric?.id === rubric.id)
      if (used) throw new MockError(409, 'rubric_in_use', 'Рубрика используется слотами плана')
      state.rubrics[projectId] = rubrics.filter((r) => r.id !== rubric.id)
      return undefined
    }
  }

  // ——— правила ———
  if (rest === '/rules' && method === 'GET') return state.rules[projectId] ?? []
  if (rest === '/rules' && method === 'PUT') {
    state.rules[projectId] = (get<Rule[]>('rules') ?? []).map((rule, index) => ({
      ...rule,
      id: rule.id || nextId(),
      position: index + 1,
    }))
    return state.rules[projectId]
  }
  if (rest === '/rules/derive' && method === 'POST') {
    return startOperation('derive_rules', (operation) => {
      const derived: Rule[] = [
        { id: nextId(), text: 'Каждый пост заканчивается вопросом', severity: 'block', enabled: true, origin: 'derived', position: 1 },
        { id: nextId(), text: 'Длина не больше 1200 знаков', severity: 'block', enabled: true, origin: 'derived', position: 2 },
        { id: nextId(), text: 'Без эмодзи в первом абзаце', severity: 'warn', enabled: true, origin: 'derived', position: 3 },
        { id: nextId(), text: 'Тон деловой, без превосходных степеней', severity: 'warn', enabled: true, origin: 'derived', position: 4 },
      ]
      operation.result = { rules: derived }
    })
  }

  // ——— контент-план ———
  const slots = (state.slots[projectId] ??= [])
  if (rest === '/plan' && method === 'GET') {
    const from = query.get('from') ?? ''
    const to = query.get('to') ?? ''
    return slots.filter((slot) => {
      const day = slot.publish_at.slice(0, 10)
      return (!from || day >= from) && (!to || day <= to)
    })
  }
  if (rest === '/plan' && method === 'POST') {
    const topic = String(get<string>('topic') ?? '')
    const rubricId = get<number | null>('rubric_id')
    const rubric = rubrics.find((r) => r.id === rubricId)
    const publishAt = String(get<string>('publish_at') ?? '')
    const created: Slot = {
      id: nextId(),
      publish_at: publishAt,
      generate_at: shiftIso(publishAt, -current.generation_lead_minutes),
      rubric: rubric ? { id: rubric.id, name: rubric.name } : null,
      topic,
      status: topic ? 'planned' : 'no_topic',
      post: null,
    }
    slots.push(created)
    return created
  }
  const slotIds = match(rest, /^\/plan\/(\d+)$/)
  if (slotIds) {
    const slot = slotOf(projectId, slotIds[0])
    if (method === 'PATCH') {
      if ('topic' in body && slot.post)
        throw new MockError(409, 'post_already_generated', 'Пост уже сгенерирован — сначала перепишите его или удалите')
      if ('publish_at' in body) {
        slot.publish_at = String(get<string>('publish_at'))
        slot.generate_at = shiftIso(slot.publish_at, -current.generation_lead_minutes)
      }
      if ('topic' in body) {
        slot.topic = String(get<string>('topic'))
        if (slot.status === 'no_topic' && slot.topic) slot.status = 'planned'
        if (!slot.topic) slot.status = 'no_topic'
      }
      if ('rubric_id' in body) {
        const rubric = rubrics.find((r) => r.id === get<number>('rubric_id'))
        slot.rubric = rubric ? { id: rubric.id, name: rubric.name } : null
      }
      return slot
    }
    if (method === 'DELETE') {
      state.slots[projectId] = slots.filter((s) => s.id !== slot.id)
      return undefined
    }
  }
  const generateIds = match(rest, /^\/plan\/(\d+)\/generate$/)
  if (generateIds && method === 'POST') {
    const slot = slotOf(projectId, generateIds[0])
    if (!slot.topic) throw new MockError(400, 'slot_topic_required', 'Промпт поста не заполнен', 'topic')
    slot.status = 'generating'
    return startOperation('generate', (operation) => {
      const post = generatedPost(projectId, slot)
      operation.result = { post_id: post.id }
    })
  }
  const skipIds = match(rest, /^\/plan\/(\d+)\/skip$/)
  if (skipIds && method === 'POST') {
    const slot = slotOf(projectId, skipIds[0])
    slot.status = 'skipped'
    return slot
  }

  // ——— посты ———
  const posts = (state.posts[projectId] ??= [])
  if (rest === '/posts' && method === 'GET') {
    const status = query.get('status')
    return posts.filter((post) => !status || post.status === status).map((post) => postSummary(projectId, post))
  }
  const postIds = match(rest, /^\/posts\/(\d+)$/)
  if (postIds) {
    const post = postOf(projectId, postIds[0])
    if (method === 'GET') return post
    if (method === 'PATCH') {
      if ('post_text' in body) {
        post.post_text = String(get<string>('post_text'))
        post.char_count = post.post_text.length
        const formatLayer = post.validation.layers.find((l) => l.layer === 'format')
        if (formatLayer) formatLayer.items = [{ key: 'length', passed: true, detail: `${post.char_count} из 4096` }]
      }
      // Правка одобренного поста требует повторного одобрения.
      if (post.status === 'approved') post.status = 'needs_review'
      syncSlot(projectId, post)
      return post
    }
  }
  const approveIds = match(rest, /^\/posts\/(\d+)\/approve$/)
  if (approveIds && method === 'POST') {
    const post = postOf(projectId, approveIds[0])
    post.status = 'approved'
    syncSlot(projectId, post)
    return post
  }
  const rejectIds = match(rest, /^\/posts\/(\d+)\/reject$/)
  if (rejectIds && method === 'POST') {
    const post = postOf(projectId, rejectIds[0])
    post.status = 'needs_review'
    syncSlot(projectId, post)
    return post
  }
  const regenerateIds = match(rest, /^\/posts\/(\d+)\/regenerate$/)
  if (regenerateIds && method === 'POST') {
    const post = postOf(projectId, regenerateIds[0])
    const slot = slotOf(projectId, post.slot_id)
    slot.status = 'generating'
    return startOperation('generate', (operation) => {
      post.post_text = `${slot.topic}\n\nПереписано агентом. Конкретика взята только из темы слота.\n\nЧто думаете?`
      post.char_count = post.post_text.length
      post.status = 'needs_review'
      post.generation = { ...post.generation!, iterations: (post.generation?.iterations ?? 1) + 1, generated_at: new Date().toISOString() }
      syncSlot(projectId, post)
      operation.result = { post_id: post.id }
    })
  }

  // ——— пул изображений ———
  const media = (state.media[projectId] ??= [])
  if (rest === '/media' && method === 'GET') {
    const q = (query.get('q') ?? '').toLowerCase()
    const availableOnly = query.get('available') === 'true'
    const items = media.filter((asset) => {
      if (availableOnly && !asset.available) return false
      if (q && !(asset.caption ?? '').toLowerCase().includes(q)) return false
      return true
    })
    // Постраничная выдача — чтобы догрузка проверялась и на заглушках.
    const limit = Number(query.get('limit') ?? 60) || 60
    const offset = Number(query.get('cursor') ?? 0) || 0
    const page = items.slice(offset, offset + limit)
    const next = offset + limit
    return { items: page, next_cursor: next < items.length ? String(next) : null }
  }
  if (rest === '/media' && method === 'POST') {
    const files = form ? form.getAll('files') : []
    if (files.length === 0) throw new MockError(400, 'no_files', 'Файлы не выбраны')
    const uploaded: MediaAsset[] = files.slice(0, 20).map((file) => {
      const id = nextId()
      return {
        id,
        url: placeholder(id, file instanceof File ? file.name : 'загруженное изображение'),
        caption: null,
        caption_status: 'pending',
        width: 1600,
        height: 900,
        bytes: file instanceof File ? file.size : 0,
        enabled: true,
        use_count: 0,
        last_used_at: null,
        available: false,
      }
    })
    media.unshift(...uploaded)
    current.media = { total: media.length, available: media.filter((a) => a.available).length }
    // Ключа Gemini нет: подпись и эмбеддинг не считаются, актив остаётся
    // недоступным для подбора, а операция падает с явной ошибкой.
    return startOperation(
      'caption',
      () => undefined,
      {
        seconds: 6,
        fail: {
          code: 'vision_provider_unavailable',
          message: 'Ключ провайдера vision не задан: подписи не построены, подбор изображения недоступен',
        },
      },
    )
  }
  const assetIds = match(rest, /^\/media\/(\d+)$/)
  if (assetIds) {
    const asset = media.find((a) => a.id === assetIds[0])
    if (!asset) throw notFound()
    if (method === 'PATCH') {
      Object.assign(asset, body)
      asset.available = asset.enabled && asset.caption_status === 'ready' && asset.use_count === 0
      return asset
    }
    if (method === 'DELETE') {
      state.media[projectId] = media.filter((a) => a.id !== asset.id)
      current.media = { total: state.media[projectId].length, available: state.media[projectId].filter((a) => a.available).length }
      return undefined
    }
  }
  const recaptionIds = match(rest, /^\/media\/(\d+)\/recaption$/)
  if (recaptionIds && method === 'POST') {
    const asset = media.find((a) => a.id === recaptionIds[0])
    if (!asset) throw notFound()
    asset.caption_status = 'pending'
    return startOperation('caption', () => undefined, {
      seconds: 5,
      fail: {
        code: 'vision_provider_unavailable',
        message: 'Ключ провайдера vision не задан: подпись не построена',
      },
    })
  }

  // ——— операции и публикации ———
  if (rest === '/operations' && method === 'GET') return state.operations.map(settle).slice(0, 50)
  const operationIds = match(rest, /^\/operations\/(\d+)$/)
  if (operationIds && method === 'GET') {
    const operation = state.operations.find((o) => o.operation_id === operationIds[0])
    if (!operation) throw notFound()
    const settled = settle(operation)
    if (settled.status === 'failed') revertGenerating(projectId)
    return settled
  }
  if (rest === '/publications' && method === 'GET') return state.publications

  throw notFound()
}

function syncSlot(projectId: number, post: Post) {
  const slot = (state.slots[projectId] ?? []).find((s) => s.id === post.slot_id)
  if (!slot) return
  slot.status = post.status
  if (slot.post) {
    slot.post.excerpt = post.post_text.slice(0, 100)
    slot.post.checks_summary = {
      passed: post.validation.passed,
      blocking: post.validation.layers.filter((l) => !l.passed).length,
      warnings: post.validation.passed ? 0 : 1,
    }
  }
}

/** Упавшая операция не должна оставлять слот в состоянии «генерируется». */
function revertGenerating(projectId: number) {
  for (const slot of state.slots[projectId] ?? []) {
    if (slot.status === 'generating') slot.status = slot.post ? 'needs_review' : 'failed'
  }
}
