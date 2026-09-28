import { useBackButton, haptic } from '../lib/telegram'

interface TabItem {
  to: string
  label: string
  icon: string
  exact?: boolean
}

/**
 * Bottom tab bar. The last slot becomes "Админ" for users with the admin flag,
 * so operators do not need a separate app.
 */
export function BottomNav({
  items,
  current,
  onNavigate,
  isAdmin,
}: {
  items: TabItem[]
  current: string
  onNavigate: (to: string) => void
  isAdmin: boolean
}) {
  const all = isAdmin ? [...items, { to: '/admin', label: 'Админ', icon: '⚙️' }] : items
  useBackButton(false)

  return (
    <nav className="bottom-nav">
      {all.map((item) => {
        const active = item.exact ? current === item.to : current.startsWith(item.to)
        return (
          <button
            key={item.to}
            className={['bottom-nav__item', active && 'bottom-nav__item--active']
              .filter(Boolean)
              .join(' ')}
            onClick={() => {
              haptic('select')
              onNavigate(item.to)
            }}
            aria-current={active ? 'page' : undefined}
          >
            <span className="bottom-nav__icon" aria-hidden="true">
              {item.icon}
            </span>
            <span>{item.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
