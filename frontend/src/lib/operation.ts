import { useCallback, useEffect, useRef, useState } from 'react'
import { pollOperation } from './api'
import { ApiError } from './errors'
import type { Operation } from './types'
import { supportLog } from './support'
import { useToast } from './toast'

/**
 * Сценарий «202 + поллинг»: запрос возвращает operation_id, дальше
 * GET /operations/{id} раз в 2 секунды до succeeded или failed.
 */
export function useOperation(projectId: number | null) {
  const [running, setRunning] = useState(false)
  const [lastError, setLastError] = useState<string | null>(null)
  const aborted = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const toast = useToast()

  useEffect(() => {
    // Флаг сбрасывается при каждом монтировании: в StrictMode эффект
    // выполняется дважды, иначе после первой размонтировки он залипал.
    aborted.current = false
    return () => {
      aborted.current = true
      controller.current?.abort()
    }
  }, [])

  const run = useCallback(
    async (
      start: () => Promise<{ operation_id: number }>,
      options: {
        /** Вызывается сразу после ответа 202, до начала поллинга. */
        onStarted?: () => void | Promise<void>
        onDone?: (operation: Operation) => void
        successText?: string
      } = {},
    ) => {
      if (projectId === null) return null
      setRunning(true)
      setLastError(null)
      try {
        const { operation_id } = await start()
        supportLog('operation_started', { project_id: projectId, operation_id })
        await options.onStarted?.()
        controller.current = new AbortController()
        const operation = await pollOperation(projectId, operation_id, {
          signal: controller.current.signal,
        })
        if (aborted.current) return operation
        supportLog('operation_finished', {
          operation_id,
          status: operation.status,
          purpose: operation.purpose,
          code: operation.error?.code ?? null,
        })
        if (operation.status === 'failed') {
          const message = operation.error?.message ?? 'Операция не выполнена'
          setLastError(message)
          toast.error(message)
        } else {
          if (options.successText) toast.ok(options.successText)
          options.onDone?.(operation)
        }
        return operation
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return null
        const message =
          error instanceof ApiError ? error.message : 'Не удалось выполнить операцию'
        if (!aborted.current) {
          setLastError(message)
          toast.error(message)
        }
        return null
      } finally {
        if (!aborted.current) setRunning(false)
      }
    },
    [projectId, toast],
  )

  return { run, running, lastError }
}
