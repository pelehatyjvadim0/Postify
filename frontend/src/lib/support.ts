/**
 * Технические подробности — коды ошибок, провайдер и модель генерации, номера
 * операций и идентификаторы — в интерфейс не выводятся. Они пишутся сюда,
 * чтобы поддержка могла снять их из консоли браузера.
 */
export function supportLog(event: string, details: Record<string, unknown>) {
  console.info(`[postify] ${event}`, details)
}
