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
export function useOperation(projectId: number | null, concurrent = false) {
  const [running, setRunning] = useState(false)
  const [lastError, setLastError] = useState<string | null>(null)
  const aborted = useRef(false)
  const controllers = useRef(new Set<AbortController>())
  const toast = useToast()

  useEffect(() => {
    // Флаг сбрасывается при каждом монтировании: в StrictMode эффект
    // выполняется дважды, иначе после первой размонтировки он залипал.
    aborted.current = false
    return () => {
      aborted.current = true
      controllers.current.forEach((controller) => controller.abort())
      controllers.current.clear()
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
      if (!concurrent && controllers.current.size > 0) return null
      const activeController = new AbortController()
      controllers.current.add(activeController)
      setRunning(true)
      setLastError(null)
      try {
        const { operation_id } = await start()
        if (activeController.signal.aborted) return null
        supportLog('operation_started', { project_id: projectId, operation_id })
        await options.onStarted?.()
        if (activeController.signal.aborted) return null
        const operation = await pollOperation(projectId, operation_id, {
          signal: activeController.signal,
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
        controllers.current.delete(activeController)
        if (!aborted.current) setRunning(controllers.current.size > 0)
      }
    },
    [projectId, toast, concurrent],
  )

  return { run, running, lastError }
}
