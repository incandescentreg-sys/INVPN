/** Formatting helpers — all dates are shown in the user's local timezone. */

const MONTHS = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

export function formatMoney(kopeks: number | null | undefined, currency = 'RUB'): string {
  if (kopeks === null || kopeks === undefined) return '—'
  const symbols: Record<string, string> = { RUB: '₽', USD: '$', EUR: '€' }
  const value = kopeks / 100
  const body = value % 1 === 0 ? String(value) : value.toFixed(2)
  return `${body} ${symbols[currency] ?? currency}`.trim()
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()}`
}

export function formatDateLong(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return `${formatDate(iso)}, ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function plural(n: number, forms: [string, string, string]): string {
  const abs = Math.abs(n) % 100
  const last = abs % 10
  if (abs > 10 && abs < 20) return forms[2]
  if (last > 1 && last < 5) return forms[1]
  if (last === 1) return forms[0]
  return forms[2]
}

export function formatDays(days: number): string {
  if (days <= 0) return 'истекла'
  return `${days} ${plural(days, ['день', 'дня', 'дней'])}`
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(diff / 60000)
  if (minutes < 1) return 'только что'
  if (minutes < 60) return `${minutes} ${plural(minutes, ['минуту', 'минуты', 'минут'])} назад`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} ${plural(hours, ['час', 'часа', 'часов'])} назад`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days} ${plural(days, ['день', 'дня', 'дней'])} назад`
  return formatDate(iso)
}

export function daysUntil(iso: string | null | undefined): number {
  if (!iso) return 0
  const diff = new Date(iso).getTime() - Date.now()
  return Math.max(0, Math.ceil(diff / 86_400_000))
}

/** Shortens a long link for display without breaking copy/paste. */
export function truncateMiddle(value: string, head = 24, tail = 12): string {
  if (value.length <= head + tail + 3) return value
  return `${value.slice(0, head)}…${value.slice(-tail)}`
}
