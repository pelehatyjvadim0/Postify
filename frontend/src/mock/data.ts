import type {
  MediaAsset,
  Post,
  Project,
  Rubric,
  Rule,
  Slot,
  SlotStatus,
  User,
  ValidationReport,
} from '@/lib/types'

// Демонстрационные данные на октябрь 2026 в таймзоне проекта (+03:00).
export const TZ = '+03:00'

export function iso(day: number, time: string) {
  return `2026-10-${String(day).padStart(2, '0')}T${time}:00${TZ}`
}

/** Сдвиг времени с сохранением смещения проекта: сервер отдаёт его зону. */
export function shiftIso(value: string, minutes: number) {
  const offset = value.slice(19) || TZ
  const sign = offset.startsWith('-') ? -1 : 1
  const offsetMinutes = sign * (Number(offset.slice(1, 3)) * 60 + Number(offset.slice(4, 6)))
  const shifted = new Date(new Date(value).getTime() + (minutes + offsetMinutes) * 60_000)
  return `${shifted.toISOString().slice(0, 19)}${offset}`
}

/** Картинки в моках рисуются на месте: файлового хранилища нет. */
export function placeholder(seed: number, label: string, size: 'thumb' | 'full' = 'full') {
  const hue = (seed * 47) % 360
  const w = size === 'thumb' ? 320 : 1600
  const h = size === 'thumb' ? 180 : 900
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 320 180">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="hsl(${hue} 70% 72%)"/><stop offset="1" stop-color="hsl(${(hue + 40) % 360} 45% 55%)"/>
</linearGradient></defs><rect width="320" height="180" fill="url(#g)"/>
<text x="160" y="96" font-family="Inter,sans-serif" font-size="11" fill="rgba(30,25,20,.72)" text-anchor="middle">${label}</text></svg>`
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

export const user: User = {
  id: 1,
  telegram_user_id: '101',
  telegram_username: 'agro_editor',
  display_name: 'Иван Петров',
  created_at: '2026-08-01T10:00:00+03:00',
  common_prompt:
    'Пишу по-русски, без канцелярита и восклицательных знаков. Без обещаний результата и без превосходных степеней.',
}

export const projects: Project[] = [
  {
    id: 3,
    name: 'Агротех',
    timezone: 'Europe/Moscow',
    language: 'ru',
    audience: 'Руководители хозяйств и агрономы, 30–55 лет',
    tone: 'Деловой, без пафоса, с конкретикой',
    project_prompt:
      'Канал про технику и агрономию. Каждый пост заканчивается вопросом к читателю. Не длиннее 1200 знаков. Без эмодзи в первом абзаце.',
    publication_mode: 'review',
    generation_lead_minutes: 1440,
    media_reuse_days: 30,
    channel: {
      configured: true,
      chat_id: '@agrotech',
      status: 'ok',
      checked_at: '2026-10-08T09:14:00+03:00',
    },
    media: { total: 128, available: 82 },
  },
  {
    id: 8,
    name: 'Склад и логистика',
    timezone: 'Europe/Moscow',
    language: 'ru',
    audience: 'Логисты, руководители складов',
    tone: 'Короткий, прикладной',
    project_prompt: 'Прикладные разборы складских процессов. Без рекламы подрядчиков.',
    publication_mode: 'auto',
    generation_lead_minutes: 720,
    media_reuse_days: 45,
    channel: { configured: false, chat_id: null, status: 'unchecked', checked_at: null },
    media: { total: 12, available: 12 },
  },
]

/** Проект другого пользователя: обращение к нему обязано отвечать 404. */
export const foreignProjectIds = [99]

export const rubrics: Record<number, Rubric[]> = {
  3: [
    { id: 5, name: 'Кейс', instructions: 'История хозяйства: задача, что сделали, что получилось.', enabled: true },
    { id: 7, name: 'Подборка', instructions: 'Список из 3–7 пунктов с коротким выводом.', enabled: true },
    { id: 9, name: 'Новость', instructions: 'Что случилось и что это значит для читателя.', enabled: true },
  ],
  8: [{ id: 21, name: 'Разбор', instructions: 'Процесс по шагам.', enabled: true }],
}

export const rules: Record<number, Rule[]> = {
  3: [
    { id: 12, text: 'Каждый пост заканчивается вопросом', severity: 'block', enabled: true, origin: 'derived', position: 1 },
    { id: 13, text: 'Длина не больше 1200 знаков', severity: 'block', enabled: true, origin: 'derived', position: 2 },
    { id: 14, text: 'Без эмодзи в первом абзаце', severity: 'warn', enabled: true, origin: 'derived', position: 3 },
    { id: 15, text: 'Не обещать конкретный результат читателю', severity: 'warn', enabled: true, origin: 'manual', position: 4 },
  ],
  8: [{ id: 31, text: 'Без упоминания подрядчиков', severity: 'block', enabled: true, origin: 'manual', position: 1 }],
}

const validationNeedsReview: ValidationReport = {
  passed: false,
  iterations: 2,
  layers: [
    {
      layer: 'format',
      passed: true,
      score: '6/6',
      items: [
        { key: 'length', passed: true, detail: '412 из 4096' },
        { key: 'language', passed: true, detail: 'ru' },
        { key: 'markup', passed: true, detail: 'разметка корректна' },
        { key: 'links', passed: true, detail: 'ссылок нет' },
        { key: 'emoji', passed: true, detail: 'в первом абзаце нет' },
        { key: 'media', passed: true, detail: 'изображение выбрано' },
      ],
    },
    {
      layer: 'rules',
      passed: true,
      score: '4/4',
      items: [
        { rule_id: 12, text: 'Вопрос в конце', passed: true, evidence: 'Какую ошибку вы встречали чаще всего?' },
        { rule_id: 13, text: 'Длина не больше 1200 знаков', passed: true, evidence: '412 знаков' },
        { rule_id: 14, text: 'Без эмодзи в первом абзаце', passed: true, evidence: '—' },
        { rule_id: 15, text: 'Не обещать результат', passed: true, evidence: '—' },
      ],
    },
    {
      layer: 'grounding',
      passed: false,
      items: [
        { claim: '−30% потерь', verdict: 'unsupported', span: [120, 131], detail: 'Отсутствует в теме слота' },
        { claim: '14%', verdict: 'supported', detail: 'Есть в теме слота' },
        { claim: '+10 °C', verdict: 'supported', detail: 'Есть в теме слота' },
      ],
    },
    {
      layer: 'image',
      passed: true,
      items: [{ asset_id: 42, verdict: 'match', detail: 'Зернохранилище, силосы · не использовалась 90 дней' }],
    },
  ],
}

const validationClean: ValidationReport = {
  passed: true,
  iterations: 1,
  layers: [
    { layer: 'format', passed: true, score: '6/6', items: [{ key: 'length', passed: true, detail: '508 из 4096' }] },
    {
      layer: 'rules',
      passed: true,
      score: '4/4',
      items: [{ rule_id: 12, text: 'Вопрос в конце', passed: true, evidence: 'А вы уже считали расход по каждой единице?' }],
    },
    { layer: 'grounding', passed: true, items: [{ claim: '18%', verdict: 'supported', detail: 'Есть в теме слота' }] },
    { layer: 'image', passed: true, items: [{ asset_id: 51, verdict: 'match', detail: 'Техника в поле' }] },
  ],
}

const validationFailed: ValidationReport = {
  passed: false,
  iterations: 2,
  layers: [
    { layer: 'format', passed: true, score: '6/6', items: [{ key: 'length', passed: true, detail: '640 из 4096' }] },
    {
      layer: 'rules',
      passed: false,
      score: '3/4',
      items: [{ rule_id: 12, text: 'Вопрос в конце', passed: false, evidence: 'Текст обрывается на перечислении' }],
    },
    {
      layer: 'grounding',
      passed: false,
      items: [{ claim: '2,4 млрд ₽', verdict: 'contradicted', span: [88, 97], detail: 'Противоречит теме слота' }],
    },
    { layer: 'image', passed: false, items: [{ asset_id: 63, verdict: 'mismatch', detail: 'На снимке склад, а не поле' }] },
  ],
}

interface SlotSeed {
  id: number
  day: number
  time: string
  rubric: number | null
  topic: string
  status: SlotStatus
  title?: string
  excerpt?: string
  text?: string
}

const seeds: SlotSeed[] = [
  { id: 1, day: 2, time: '18:00', rubric: 7, topic: 'Сроки сева озимых по регионам. Взять окно с 20 сентября по 10 октября.', status: 'published',
    title: 'Сроки сева озимых', excerpt: 'Озимые в этом году уходят в зиму позже обычного…',
    text: 'Озимые в этом году уходят в зиму позже обычного. Собрали сроки по регионам и то, на что смотреть перед последним окном сева.\n\nОкно сева: с 20 сентября по 10 октября.\n\nКогда вы закрывали сев в этом сезоне?' },
  { id: 2, day: 5, time: '10:00', rubric: 5, topic: 'Кейс: контроль расхода топлива на 40 единицах техники, экономия 18% за сезон.', status: 'published',
    title: 'Экономия топлива на 18%', excerpt: 'Хозяйство поставило контроль расхода на 40 единиц техники…',
    text: 'Хозяйство поставило контроль расхода на 40 единиц техники и за сезон срезало расход на 18%. Разбираем, из чего сложилась экономия.\n\nА вы уже считали расход по каждой единице?' },
  { id: 3, day: 7, time: '10:00', rubric: 9, topic: 'Продление программы льготного лизинга техники. Что изменилось в условиях.', status: 'published',
    title: 'Субсидии на технику', excerpt: 'Программу льготного лизинга продлили…',
    text: 'Программу льготного лизинга продлили. Что изменилось в условиях и кто теперь попадает под неё.\n\nВы пользовались лизингом в этом году?' },
  { id: 4, day: 9, time: '10:00', rubric: 9, topic: 'С октября заявки на господдержку подаются через единое окно. Сроки рассмотрения — 30 дней.', status: 'approved',
    title: 'Господдержка: что изменилось', excerpt: 'С октября заявки подаются через единое окно…',
    text: 'С октября заявки подаются через единое окно. Разобрали новый порядок и сроки рассмотрения — 30 дней.\n\nУспели подать заявку?' },
  { id: 5, day: 9, time: '18:00', rubric: 7, topic: 'Разобрать 5 ошибок при хранении зерна. Обязательно упомянуть влажность 14% и температуру не выше +10 °C.', status: 'needs_review',
    title: '5 ошибок при хранении зерна', excerpt: 'Влажность выше 14% — главная причина порчи зерна…',
    text: 'Влажность выше 14% — главная причина порчи зерна при хранении. Второе по частоте — температура в силосе выше +10 °C. Правильный режим даёт −30% потерь.\n\nЧто проверить перед закладкой:\n• влажность каждой партии отдельно\n• работу вентиляции\n• герметичность люков\n\nКакую ошибку вы встречали чаще всего?' },
  { id: 6, day: 12, time: '10:00', rubric: 5, topic: 'Переход на дифференцированное внесение на 1200 га за два сезона.', status: 'generating' },
  { id: 7, day: 13, time: '19:00', rubric: 9, topic: 'Отраслевые новости недели одной сводкой.', status: 'failed',
    title: 'Вечерний дайджест', excerpt: 'Генерация не прошла проверки за 2 итерации',
    text: 'Коротко о главном за неделю: господдержка, цены на удобрения, лизинг на 2,4 млрд ₽ по отрасли.' },
  { id: 8, day: 14, time: '09:00', rubric: 9, topic: 'Итоги сезона по урожайности. Взять цифры из отчёта, который пришлёт агроном.', status: 'planned' },
  { id: 9, day: 14, time: '13:00', rubric: 5, topic: 'Как хозяйство обновляло парк: что брали в лизинг, что покупали.', status: 'planned' },
  { id: 10, day: 14, time: '19:00', rubric: 7, topic: 'Чек-лист подготовки к зиме: техника, склады, ГСМ.', status: 'planned' },
  { id: 11, day: 14, time: '21:00', rubric: 9, topic: 'Короткая сводка отраслевых новостей за неделю.', status: 'planned' },
  { id: 12, day: 16, time: '18:00', rubric: 7, topic: 'Консервация техники: аккумуляторы, топливо, хранение.', status: 'planned' },
  { id: 13, day: 17, time: '12:00', rubric: 5, topic: 'Субботний разбор — решено не публиковать в этом месяце.', status: 'skipped' },
  { id: 14, day: 19, time: '10:00', rubric: 5, topic: 'Когда ремонт в своей мастерской дешевле сервиса.', status: 'planned' },
  { id: 15, day: 21, time: '10:00', rubric: 9, topic: 'Динамика цен на удобрения к началу закупочного сезона.', status: 'planned' },
  { id: 16, day: 21, time: '17:00', rubric: 7, topic: 'Что проверить в договоре поставки удобрений.', status: 'planned' },
  { id: 17, day: 23, time: '18:00', rubric: 7, topic: 'Хранение зерна зимой: режимы и контроль.', status: 'planned' },
  { id: 18, day: 26, time: '10:00', rubric: 5, topic: '', status: 'no_topic' },
  { id: 19, day: 28, time: '10:00', rubric: 9, topic: '', status: 'no_topic' },
  { id: 20, day: 30, time: '18:00', rubric: 7, topic: '', status: 'no_topic' },
]

const rubricById = (projectId: number, id: number | null) =>
  id === null ? null : (rubrics[projectId] ?? []).find((r) => r.id === id) ?? null

function leadMinutes(projectId: number) {
  return projects.find((x) => x.id === projectId)?.generation_lead_minutes ?? 1440
}

function generateAt(projectId: number, publishAt: string) {
  return shiftIso(publishAt, -leadMinutes(projectId))
}

export function buildSlots(projectId: number): Slot[] {
  if (projectId !== 3) return []
  return seeds.map((seed) => {
    const publishAt = iso(seed.day, seed.time)
    const rubric = rubricById(3, seed.rubric)
    const hasPost = Boolean(seed.title)
    return {
      id: seed.id,
      publish_at: publishAt,
      generate_at: generateAt(3, publishAt),
      rubric: rubric ? { id: rubric.id, name: rubric.name } : null,
      topic: seed.topic,
      status: seed.status,
      post: hasPost
        ? {
            id: 100 + seed.id,
            title: seed.title!,
            excerpt: seed.excerpt!,
            media_thumb_url: placeholder(seed.id, 'изображение из пула', 'thumb'),
            checks_summary:
              seed.status === 'needs_review'
                ? { passed: false, blocking: 0, warnings: 1 }
                : seed.status === 'failed'
                  ? { passed: false, blocking: 2, warnings: 1 }
                  : { passed: true, blocking: 0, warnings: 0 },
          }
        : null,
    }
  })
}

export function buildPosts(): Post[] {
  return seeds
    .filter((seed) => seed.title)
    .map((seed) => ({
      id: 100 + seed.id,
      slot_id: seed.id,
      status: seed.status,
      post_text: seed.text ?? '',
      char_count: (seed.text ?? '').length,
      media: {
        asset_id: 40 + seed.id,
        caption: 'Зернохранилище, металлические силосы, закат',
        url: placeholder(seed.id, 'изображение из пула'),
        rationale: 'Тема о хранении зерна, на снимке силосы',
        last_used_at: null,
      },
      generation: {
        provider: 'codex',
        model: 'gpt-5.6-terra',
        reasoning_effort: 'medium',
        iterations: seed.status === 'needs_review' || seed.status === 'failed' ? 2 : 1,
        generated_at: iso(seed.day - 1, seed.time),
      },
      validation:
        seed.status === 'needs_review'
          ? validationNeedsReview
          : seed.status === 'failed'
            ? validationFailed
            : validationClean,
      published:
        seed.status === 'published'
          ? { published_at: iso(seed.day, seed.time), message_url: 'https://t.me/agrotech/1024' }
          : null,
    }))
}

const captions = [
  'Зернохранилище, металлические силосы, закат',
  'Трактор в поле, вспашка, пасмурно',
  'Комбайн на уборке пшеницы',
  'Склад удобрений, паллеты в ряд',
  'Поле озимых, ранняя весна',
  'Мастерская, ремонт двигателя',
]

export function buildMedia(projectId: number): MediaAsset[] {
  const total = projectId === 3 ? 24 : 6
  return Array.from({ length: total }, (_, index) => {
    const id = 40 + index
    // Три крайних случая в выдаче: подпись считается, подпись не сделалась,
    // актив недоступен по политике повторов.
    const captionStatus = index === 2 ? 'pending' : index === 5 ? 'failed' : 'ready'
    const used = index % 5 === 0 && index > 0
    return {
      id,
      url: placeholder(id, captions[index % captions.length]),
      caption: captionStatus === 'ready' ? captions[index % captions.length] : null,
      caption_status: captionStatus,
      width: 1600,
      height: 900,
      bytes: 380_000 + index * 4_211,
      enabled: index !== 7,
      use_count: used ? 1 : 0,
      last_used_at: used ? iso(1 + index, '12:00') : null,
      available: captionStatus === 'ready' && index !== 7 && !used,
    }
  })
}
