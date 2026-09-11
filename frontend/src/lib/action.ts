import { useCallback } from 'react'
import { ApiError } from './errors'
import { useToast } from './toast'

export interface ActionResult<T> {
  /** Запрос прошёл. Отличается от value: успешный DELETE возвращает 204 без тела. */
  ok: boolean
  value?: T
}

/**
 * Обёртка для действий, меняющих данные: показывает сообщение об успехе и,
 * главное, не даёт сбою запроса остаться незамеченным.
 */
export function useAction() {
  const toast = useToast()
  return useCallback(
    async <T>(
      action: () => Promise<T>,
      options: { ok?: string; fail?: string } = {},
    ): Promise<ActionResult<T>> => {
      try {
        const value = await action()
        if (options.ok) toast.ok(options.ok)
        return { ok: true, value }
      } catch (error) {
        toast.error(
          error instanceof ApiError ? error.message : (options.fail ?? 'Действие не выполнено'),
        )
        return { ok: false }
      }
    },
    [toast],
  )
}
