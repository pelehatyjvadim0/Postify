import { ApiError } from './errors'
import { supportLog } from './support'
import type {
  LoginRequest,
  LoginStatusResponse,
  MediaAsset,
  MediaPage,
  Operation,
  Post,
  PostSummary,
  Project,
  ProjectChannel,
  ProjectSummary,
  Publication,
  Rubric,
  Rule,
  Slot,
  User,
} from './types'

// Заглушки включаются только явно: npm run dev:mock и build:mock.
export { ApiError }

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

let csrfToken: string | null = null

/**
 * Сессия живёт в httpOnly-куке, а токен защиты от подделки запросов — только
 * в браузере. При загрузке /api/me восстанавливает токен из действующей
 * сессии, даже если localStorage очищен или открыт другой порт приложения.
 */
let onSessionLost: (() => void) | null = null

export function setSessionLostHandler(handler: (() => void) | null) {
  onSessionLost = handler
}

export function hasCsrfToken() {
  return csrfToken !== null
}

export function setCsrfToken(token: string | null) {
  csrfToken = token
  try {
    if (token) localStorage.setItem('csrf', token)
    else localStorage.removeItem('csrf')
  } catch {
    /* приватный режим — работаем без запоминания */
  }
}

export function restoreCsrfToken() {
  try {
    csrfToken = localStorage.getItem('csrf')
  } catch {
    csrfToken = null
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

interface RequestOptions {
  body?: unknown
  /** multipart/form-data для загрузки изображений */
  form?: FormData
  query?: Record<string, string | number | boolean | undefined>
}

function withQuery(path: string, query?: RequestOptions['query']) {
  if (!query) return path
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `${path}?${qs}` : path
}

async function request<T>(method: Method, path: string, options: RequestOptions = {}): Promise<T> {
  const url = withQuery(path, options.query)

  // Условие — литерал сборки, поэтому в прод-бандл мок-модуль не попадает вовсе.
  if (import.meta.env.VITE_USE_MOCKS === 'true') {
    const { mockRequest } = await import('@/mock/server')
    return mockRequest<T>(method, url, options.body, options.form).catch((error: unknown) => {
      if (error instanceof ApiError)
        supportLog('api_error', { method, url, status: error.status, code: error.code })
      throw error
    })
  }

  const headers: Record<string, string> = {}
  if (method !== 'GET' && csrfToken) headers['x-postify-csrf'] = csrfToken
  if (options.body !== undefined) headers['content-type'] = 'application/json'

  const response = await fetch(url, {
    method,
    headers,
    credentials: 'include',
    body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
  })

  if (response.status === 204) return undefined as T

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const error = (payload as { error?: { code: string; message: string; field?: string } } | null)
      ?.error
    supportLog('api_error', {
      method,
      url,
      status: response.status,
      code: error?.code ?? 'unknown_error',
    })
    // Сессия кончилась посреди работы — не сыпать тостами, а вернуть на вход.
    if (response.status === 401) onSessionLost?.()
    throw new ApiError(
      response.status,
      error?.code ?? 'unknown_error',
      error?.message ?? 'Не удалось выполнить запрос',
      error?.field,
    )
  }
  if (path === '/api/me') {
    const restored = response.headers.get('x-postify-csrf')
    if (restored) setCsrfToken(restored)
  }
  return payload as T
}

/**
 * Поллинг длительной операции. Контракт рекомендует интервал 2 секунды.
 * Опрос прекращается по отмене или по истечении предельного времени, иначе
 * зависшая на сервере операция опрашивалась бы бесконечно.
 */
export async function pollOperation(
  projectId: number,
  operationId: number,
  options: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number } = {},
): Promise<Operation> {
  const interval = options.intervalMs ?? 2000
  const deadline = Date.now() + (options.timeoutMs ?? 5 * 60 * 1000)
  for (;;) {
    if (options.signal?.aborted) throw new DOMException('aborted', 'AbortError')
    const operation = await api.operation(projectId, operationId)
    if (operation.status !== 'running') return operation
    if (Date.now() >= deadline)
      throw new ApiError(504, 'operation_timeout', 'Операция не завершилась за отведённое время')
    await new Promise((resolve) => setTimeout(resolve, interval))
  }
}

const p = (projectId: number) => `/api/projects/${projectId}`

export const api = {
  // Аутентификация: вход через Telegram-бота, паролей нет.
  startLogin: () => request<LoginRequest>('POST', '/api/auth/login'),
  loginStatus: (browserToken: string) =>
    request<LoginStatusResponse>('GET', '/api/auth/login/status', {
      query: { request: browserToken },
    }),
  logout: () => request<void>('POST', '/api/auth/logout'),
  me: () => request<User>('GET', '/api/me'),
  saveCommonPrompt: (prompt: string) =>
    request<{ common_prompt: string }>('PUT', '/api/me/prompt', { body: { prompt } }),

  // Проекты
  projects: () => request<ProjectSummary[]>('GET', '/api/projects'),
  createProject: (body: { name: string; timezone: string }) =>
    request<Project>('POST', '/api/projects', { body }),
  project: (id: number) => request<Project>('GET', p(id)),
  updateProject: (id: number, body: Partial<Project>) =>
    request<Project>('PUT', p(id), { body }),
  deleteProject: (id: number) => request<void>('DELETE', p(id)),
  // bot_token не передаётся, когда его не меняют: пустая строка стёрла бы токен.
  saveChannel: (id: number, body: { bot_token?: string; chat_id: string }) =>
    request<ProjectChannel>('PUT', `${p(id)}/channel`, { body }),
  checkChannel: (id: number) => request<ProjectChannel>('POST', `${p(id)}/channel/check`),
  deleteChannel: (id: number) => request<void>('DELETE', `${p(id)}/channel`),

  // Рубрики
  rubrics: (id: number) => request<Rubric[]>('GET', `${p(id)}/rubrics`),
  createRubric: (id: number, body: { name: string; instructions: string }) =>
    request<Rubric>('POST', `${p(id)}/rubrics`, { body }),
  updateRubric: (id: number, rubricId: number, body: Partial<Rubric>) =>
    request<Rubric>('PUT', `${p(id)}/rubrics/${rubricId}`, { body }),
  deleteRubric: (id: number, rubricId: number) =>
    request<void>('DELETE', `${p(id)}/rubrics/${rubricId}`),

  // Правила
  rules: (id: number) => request<Rule[]>('GET', `${p(id)}/rules`),
  saveRules: (id: number, rules: Rule[]) =>
    // У ещё не сохранённого правила идентификатора нет: отрицательный номер
    // нужен только как ключ списка в браузере, наружу он не уходит.
    request<Rule[]>('PUT', `${p(id)}/rules`, {
      body: {
        rules: rules.map(({ id: ruleId, ...rest }) => (ruleId > 0 ? { id: ruleId, ...rest } : rest)),
      },
    }),
  deriveRules: (id: number) =>
    request<{ operation_id: number; status: 'running' }>('POST', `${p(id)}/rules/derive`),

  // Контент-план
  plan: (id: number, from: string, to: string) =>
    request<Slot[]>('GET', `${p(id)}/plan`, { query: { from, to } }),
  createSlot: (id: number, body: { publish_at: string; rubric_id: number | null; topic: string }) =>
    request<Slot>('POST', `${p(id)}/plan`, { body }),
  updateSlot: (
    id: number,
    slotId: number,
    body: { publish_at?: string; rubric_id?: number | null; topic?: string },
  ) => request<Slot>('PATCH', `${p(id)}/plan/${slotId}`, { body }),
  deleteSlot: (id: number, slotId: number) => request<void>('DELETE', `${p(id)}/plan/${slotId}`),
  generateSlot: (id: number, slotId: number) =>
    request<{ operation_id: number; status: 'running' }>('POST', `${p(id)}/plan/${slotId}/generate`),
  skipSlot: (id: number, slotId: number) => request<Slot>('POST', `${p(id)}/plan/${slotId}/skip`),

  // Посты
  posts: (id: number, status?: string) =>
    request<PostSummary[]>('GET', `${p(id)}/posts`, { query: { status } }),
  post: (id: number, postId: number) => request<Post>('GET', `${p(id)}/posts/${postId}`),
  updatePost: (id: number, postId: number, body: { post_text?: string; media_asset_id?: number }) =>
    request<Post>('PATCH', `${p(id)}/posts/${postId}`, { body }),
  approvePost: (id: number, postId: number) =>
    request<Post>('POST', `${p(id)}/posts/${postId}/approve`),
  rejectPost: (id: number, postId: number) =>
    request<Post>('POST', `${p(id)}/posts/${postId}/reject`),
  regeneratePost: (id: number, postId: number) =>
    request<{ operation_id: number; status: 'running' }>(
      'POST',
      `${p(id)}/posts/${postId}/regenerate`,
    ),

  // Пул изображений
  media: (id: number, query: { available?: boolean; q?: string; limit?: number; cursor?: string }) =>
    request<MediaPage>('GET', `${p(id)}/media`, { query }),
  uploadMedia: (id: number, form: FormData) =>
    request<{ operation_id: number; status: 'running' }>('POST', `${p(id)}/media`, { form }),
  updateAsset: (id: number, assetId: number, body: { caption?: string; enabled?: boolean }) =>
    request<MediaAsset>('PATCH', `${p(id)}/media/${assetId}`, { body }),
  deleteAsset: (id: number, assetId: number) =>
    request<void>('DELETE', `${p(id)}/media/${assetId}`),
  recaptionAsset: (id: number, assetId: number) =>
    request<{ operation_id: number; status: 'running' }>(
      'POST',
      `${p(id)}/media/${assetId}/recaption`,
    ),

  // История и операции
  operations: (id: number, limit = 50) =>
    request<Operation[]>('GET', `${p(id)}/operations`, { query: { limit } }),
  operation: (id: number, operationId: number) =>
    request<Operation>('GET', `${p(id)}/operations/${operationId}`),
  publications: (id: number, limit = 50) =>
    request<Publication[]>('GET', `${p(id)}/publications`, { query: { limit } }),
}
