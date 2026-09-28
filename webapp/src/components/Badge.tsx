import type { ReactNode } from 'react'
import { cn } from '../lib/cn'
import type { HealthStatus, SubscriptionStatus } from '../lib/types'

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'accent'

const TONE_CLASS: Record<Tone, string> = {
  neutral: '',
  success: 'badge--success',
  warning: 'badge--warning',
  danger: 'badge--danger',
  accent: 'badge--accent',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={cn('badge', TONE_CLASS[tone])}>{children}</span>
}

const SUBSCRIPTION_LABEL: Record<SubscriptionStatus, { text: string; tone: Tone }> = {
  active: { text: 'Активна', tone: 'success' },
  pending: { text: 'Ожидает оплаты', tone: 'warning' },
  expired: { text: 'Истекла', tone: 'danger' },
  suspended: { text: 'Приостановлена', tone: 'warning' },
  cancelled: { text: 'Отменена', tone: 'neutral' },
}

export function SubscriptionBadge({ status }: { status: SubscriptionStatus }) {
  const item = SUBSCRIPTION_LABEL[status] ?? { text: status, tone: 'neutral' as Tone }
  return <Badge tone={item.tone}>{item.text}</Badge>
}

const HEALTH_TONE: Record<string, { tone: Tone; dot: string; label: string }> = {
  up: { tone: 'success', dot: 'status-dot--up', label: 'Работает' },
  degraded: { tone: 'warning', dot: 'status-dot--warn', label: 'Нестабилен' },
  down: { tone: 'danger', dot: 'status-dot--down', label: 'Недоступен' },
  unknown: { tone: 'neutral', dot: '', label: 'Не проверялся' },
}

export function HealthBadge({ status }: { status: HealthStatus | string }) {
  const item = HEALTH_TONE[status] ?? HEALTH_TONE.unknown
  return (
    <Badge tone={item.tone}>
      <span className={cn('status-dot', item.dot)} style={{ width: 6, height: 6 }} />
      {item.label}
    </Badge>
  )
}

export function StatusDot({ status }: { status: HealthStatus | string }) {
  const item = HEALTH_TONE[status] ?? HEALTH_TONE.unknown
  return <span className={cn('status-dot', item.dot)} />
}
