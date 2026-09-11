const MONTHS = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]
const MONTHS_NOM = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]
export const DOW = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
export const DOW_FULL = [
  'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье',
]

/**
 * Дата слота уже приведена сервером к таймзоне проекта, поэтому части строки
 * берутся как есть, без перевода в локальную зону браузера.
 */
export function parseLocal(value: string) {
  const [date, rest = ''] = value.split('T')
  const [year, month, day] = date.split('-').map(Number)
  const time = /^(\d{2}):(\d{2})/.exec(rest)
  return {
    year,
    month,
    day,
    hour: time ? Number(time[1]) : 0,
    minute: time ? Number(time[2]) : 0,
  }
}

export function dayKey(value: string) {
  return value.slice(0, 10)
}

export function timeOf(value: string) {
  const { hour, minute } = parseLocal(value)
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

export function dayMonth(value: string) {
  const { day, month } = parseLocal(value)
  return `${day} ${MONTHS[month - 1]}`
}

export function dateTimeLabel(value: string) {
  return `${dayMonth(value)}, ${timeOf(value)}`
}

export function monthTitle(year: number, month: number) {
  return `${MONTHS_NOM[month - 1]} ${year}`
}

/** Понедельник = 0. */
export function weekdayIndex(year: number, month: number, day: number) {
  return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7
}

export function daysInMonth(year: number, month: number) {
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

export function ymd(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

export function isoWithZone(date: string, time: string, zoneOffset: string) {
  return `${date}T${time}:00${zoneOffset}`
}

/**
 * Смещение таймзоны проекта на конкретную дату — с учётом перехода на летнее
 * время. Контракт требует отдавать publish_at в зоне проекта.
 */
export function offsetFor(timeZone: string, date: string, time: string) {
  try {
    const instant = new Date(`${date}T${time}:00Z`)
    const name = new Intl.DateTimeFormat('en-US', { timeZone, timeZoneName: 'longOffset' })
      .formatToParts(instant)
      .find((part) => part.type === 'timeZoneName')?.value
    const parsed = /GMT([+-])(\d{1,2})(?::(\d{2}))?/.exec(name ?? '')
    if (!parsed) return '+00:00'
    return `${parsed[1]}${parsed[2].padStart(2, '0')}:${parsed[3] ?? '00'}`
  } catch {
    // Неизвестная зона — не выдумываем смещение.
    return '+00:00'
  }
}

/** Сегодняшняя дата в таймзоне проекта. */
export function todayIn(timeZone: string) {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone }).format(new Date())
  } catch {
    return new Intl.DateTimeFormat('en-CA').format(new Date())
  }
}

export function shiftDays(date: string, delta: number) {
  const at = new Date(`${date}T12:00:00Z`)
  at.setUTCDate(at.getUTCDate() + delta)
  return at.toISOString().slice(0, 10)
}

/** Понедельник недели, в которую попадает дата. */
export function weekStart(date: string) {
  const at = new Date(`${date}T12:00:00Z`)
  const shift = (at.getUTCDay() + 6) % 7
  at.setUTCDate(at.getUTCDate() - shift)
  return at.toISOString().slice(0, 10)
}

export function weekRangeLabel(start: string) {
  const end = shiftDays(start, 6)
  const a = parseLocal(start)
  const b = parseLocal(end)
  if (a.month === b.month) return `${a.day} — ${b.day} ${MONTHS[b.month - 1]}`
  return `${a.day} ${MONTHS[a.month - 1]} — ${b.day} ${MONTHS[b.month - 1]}`
}
