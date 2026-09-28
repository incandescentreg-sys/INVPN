import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './store/auth'
import { BottomNav } from './components/BottomNav'
import { Button } from './components/Button'
import { Card } from './components/Card'
import { Loading } from './components/Feedback'
import { Header } from './components/Header'
import { HomePage } from './pages/HomePage'
import { PlansPage } from './pages/PlansPage'
import { CheckoutPage } from './pages/CheckoutPage'
import { VpnPage } from './pages/VpnPage'
import { ProfilePage } from './pages/ProfilePage'
import { PaymentsPage } from './pages/PaymentsPage'
import { InstructionsPage } from './pages/InstructionsPage'
import { SupportPage } from './pages/SupportPage'
import { AdminPage } from './pages/admin/AdminPage'

const NAV = [
  { to: '/', label: 'Главная', icon: '🏠', exact: true },
  { to: '/plans', label: 'Тарифы', icon: '🛒' },
  { to: '/vpn', label: 'Мой VPN', icon: '📱' },
  { to: '/payments', label: 'Оплата', icon: '💳' },
  { to: '/profile', label: 'Профиль', icon: '👤' },
]

/** Screen title per route, shown in the header. */
function useTitle(): { title: string; subtitle?: string } {
  const { pathname } = useLocation()
  if (pathname.startsWith('/plans')) return { title: 'Тарифы' }
  if (pathname.startsWith('/checkout')) return { title: 'Оплата' }
  if (pathname.startsWith('/vpn')) return { title: 'Мой VPN' }
  if (pathname.startsWith('/payments')) return { title: 'Оплата' }
  if (pathname.startsWith('/instructions')) return { title: 'Инструкция' }
  if (pathname.startsWith('/support')) return { title: 'Поддержка' }
  if (pathname.startsWith('/admin')) return { title: 'Админ-панель' }
  if (pathname.startsWith('/profile')) return { title: 'Профиль' }
  return { title: 'VPN Service', subtitle: 'Безопасный и быстрый интернет' }
}

export default function App() {
  const { user, loading, error, needsReopen, login, isAdmin } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { title, subtitle } = useTitle()

  // Retry / re-authenticate when Telegram hands us fresh initData.
  if (loading && !user) {
    return (
      <div className="app">
        <main className="app-main">
          <Loading label="Подключаемся…" />
        </main>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="app">
        <main className="app-main">
          <Card hero>
            <div className="stack">
              <div className="hero__eyebrow">VPN Service</div>
              <h1 className="hero__title">Безопасный и быстрый интернет</h1>
              <p className="hero__subtitle">Приложение работает внутри Telegram</p>
            </div>
          </Card>

          <Card>
            <div className="stack">
              <div className="small">
                {error ?? 'Чтобы продолжить, откройте приложение через кнопку в боте.'}
              </div>
              {needsReopen && (
                <div className="tiny muted">
                  Данные Telegram устарели — закройте и заново откройте приложение из бота.
                </div>
              )}
              <Button block onClick={() => void login()}>
                Повторить
              </Button>
            </div>
          </Card>
        </main>
      </div>
    )
  }

  const isAdminRoute = location.pathname.startsWith('/admin')
  if (isAdminRoute && !isAdmin) return <Navigate to="/" replace />

  const showNav = !location.pathname.startsWith('/checkout')

  return (
    <div className="app">
      <Header
        title={title}
        subtitle={subtitle}
        onBack={location.pathname !== '/' ? () => navigate(-1) : undefined}
      />

      <main className="app-main">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/plans" element={<PlansPage />} />
          <Route path="/checkout/:planId" element={<CheckoutPage />} />
          <Route path="/vpn" element={<VpnPage />} />
          <Route path="/payments" element={<PaymentsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/instructions" element={<InstructionsPage />} />
          <Route path="/support" element={<SupportPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      {showNav && (
        <BottomNav
          items={NAV}
          current={location.pathname}
          isAdmin={isAdmin}
          onNavigate={(to) => {
            if (to === '/instructions' || to === '/support') {
              navigate(to)
              return
            }
            navigate(to)
          }}
        />
      )}
    </div>
  )
}
