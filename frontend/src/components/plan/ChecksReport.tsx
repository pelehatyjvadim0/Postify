import { AlertTriangle, Check, X } from 'lucide-react'
import { LAYER_TITLE, VERDICT_LABEL } from '@/lib/status'
import type { ValidationLayer, ValidationReport } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Одна структура отчёта для правой панели и карточки предпросмотра. */
export function ChecksReport({ report }: { report: ValidationReport }) {
  const failed = report.layers.filter((layer) => !layer.passed).length
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Проверки
        </span>
        <span
          className={cn(
            'text-[11px] font-medium',
            report.passed
              ? 'text-emerald-700 dark:text-emerald-400'
              : 'text-amber-700 dark:text-amber-400',
          )}
        >
          {report.passed ? 'Пройдены' : `Замечания в ${failed} из ${report.layers.length}`}
        </span>
      </div>
      <div className="space-y-1.5">
        {report.layers.map((layer) => (
          <LayerRow key={layer.layer} layer={layer} />
        ))}
      </div>
    </div>
  )
}

function LayerRow({ layer }: { layer: ValidationLayer }) {
  const detail = summarize(layer)
  const issues = layer.items.filter((item) => item.passed === false || (item.verdict && item.verdict !== 'supported' && item.verdict !== 'match'))
  const hasIssues = !layer.passed || issues.length > 0
  return (
    <div
      className={cn(
        'flex items-start gap-2.5 rounded-md border px-3 py-2',
        hasIssues
          ? 'border-amber-200 bg-amber-50/60 dark:border-amber-500/30 dark:bg-amber-500/10'
          : 'border-border',
      )}
    >
      {!hasIssues ? (
        <Check
          className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400"
          strokeWidth={2.5}
        />
      ) : (
        <AlertTriangle
          className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400"
          strokeWidth={2.5}
        />
      )}
      <div className="min-w-0">
        <p className="text-[13px] font-medium">{LAYER_TITLE[layer.layer]}</p>
        <p className="text-[11px] leading-relaxed text-muted-foreground">{detail}</p>
        {issues.length > 0 && (
          <ul className="mt-1.5 space-y-1">
            {issues
              .map((item, index) => (
                <li key={index} className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
                  {item.severity === 'warn' ? <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-600" /> : <X className="mt-0.5 h-3 w-3 shrink-0 text-red-600 dark:text-red-400" />}
                  <span>
                    {item.claim ? `«${item.claim}» — ` : item.text ? `${item.text} — ` : ''}
                    {item.verdict ? (VERDICT_LABEL[item.verdict] ?? 'не подтверждено') : item.detail}
                    {item.verdict && item.detail ? `, ${item.detail.toLowerCase()}` : ''}
                  </span>
                </li>
              ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function summarize(layer: ValidationLayer) {
  // Служебные ключи проверок (length, markup и подобные) в интерфейс не идут.
  if (layer.layer === 'format') return layer.score ? `${layer.score} проверок пройдено` : '—'
  if (layer.layer === 'rules')
    return [layer.score, layer.items.map((item) => item.text).filter(Boolean).slice(0, 3).join(', ')]
      .filter(Boolean)
      .join(' · ')
  if (layer.layer === 'grounding') {
    const total = layer.items.length
    const bad = layer.items.filter((item) => item.verdict && item.verdict !== 'supported').length
    return bad === 0
      ? `${total} утверждений опираются на тему слота`
      : `${bad} из ${total} утверждений без опоры в теме слота`
  }
  return layer.items.map((item) => item.detail).filter(Boolean).join(' · ') || '—'
}
