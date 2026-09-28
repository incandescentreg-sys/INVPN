import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

export function Skeleton({ className, height = 16 }: { className?: string; height?: number }) {
  return <div className={cn('skeleton', className)} style={{ height }} />
}

export function CardSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="card stack">
      <Skeleton height={20} className="grow" />
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} height={13} />
      ))}
    </div>
  )
}

export function EmptyState({
  icon = '📭',
  title,
  description,
  action,
}: {
  icon?: string
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <div className="empty__icon" aria-hidden="true">
        {icon}
      </div>
      <div className="strong">{title}</div>
      {description && (
        <div className="small muted" style={{ maxWidth: 320 }}>
          {description}
        </div>
      )}
      {action}
    </div>
  )
}

export function Loading({ label }: { label?: string }) {
  return (
    <div className="empty">
      <span className="spinner" style={{ width: 26, height: 26 }} />
      {label && <span className="small muted">{label}</span>}
    </div>
  )
}
