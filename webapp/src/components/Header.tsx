import type { ReactNode } from 'react'

export function Header({
  title,
  subtitle,
  right,
  onBack,
}: {
  title: string
  subtitle?: string
  right?: ReactNode
  onBack?: () => void
}) {
  return (
    <header className="app-header">
      {onBack && (
        <button className="btn btn--ghost btn--sm" onClick={onBack} aria-label="Назад">
          ←
        </button>
      )}
      <div className="app-header__title">
        <div>{title}</div>
        {subtitle && <div className="app-header__sub ellipsis">{subtitle}</div>}
      </div>
      {right}
    </header>
  )
}
