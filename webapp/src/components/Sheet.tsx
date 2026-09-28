import { useEffect, useState, type ReactNode } from 'react'
import { cn } from '../lib/cn'
import { haptic } from '../lib/telegram'

/** Bottom sheet used for confirmations and the config viewer. */
export function Sheet({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}) {
  // Lock background scrolling while the sheet is open.
  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previous
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      <div className="sheet-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title}>
        <div className="sheet__handle" aria-hidden="true" />
        <div className="sheet__header">
          <div className="sheet__title">{title}</div>
          <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Закрыть">
            Закрыть
          </button>
        </div>
        <div className="sheet__body">{children}</div>
        {footer && <div className="sheet__footer">{footer}</div>}
      </div>
    </>
  )
}

export function ConfirmSheet({
  open,
  title,
  message,
  confirmLabel = 'Подтвердить',
  danger,
  loading,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  message: ReactNode
  confirmLabel?: string
  danger?: boolean
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Sheet open={open} title={title} onClose={onCancel} footer={
      <>
        <button
          className={cn('btn', 'btn--block', danger ? 'btn--danger' : 'btn--primary')}
          onClick={() => {
            haptic('warning')
            onConfirm()
          }}
          disabled={loading}
        >
          {loading && <span className="spinner" />}
          {confirmLabel}
        </button>
        <button className="btn btn--block btn--secondary" onClick={onCancel} disabled={loading}>
          Отмена
        </button>
      </>
    }>
      <div className="small">{message}</div>
    </Sheet>
  )
}

/** Copy-to-clipboard button with inline confirmation. */
export function CopyButton({
  value,
  label = 'Скопировать',
  copiedLabel = 'Скопировано',
  className,
}: {
  value: string
  label?: string
  copiedLabel?: string
  className?: string
}) {
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!done) return
    const timer = window.setTimeout(() => setDone(false), 1800)
    return () => window.clearTimeout(timer)
  }, [done])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
    } catch {
      // Fallback for older WebViews that lack the async clipboard API.
      const area = document.createElement('textarea')
      area.value = value
      area.style.position = 'fixed'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      try {
        document.execCommand('copy')
      } finally {
        document.body.removeChild(area)
      }
    }
    haptic('success')
    setDone(true)
  }

  return (
    <button className={cn('btn', 'btn--secondary', className)} onClick={copy}>
      {done ? `✓ ${copiedLabel}` : label}
    </button>
  )
}
