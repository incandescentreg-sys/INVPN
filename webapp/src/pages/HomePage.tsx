import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { formatDate, formatDays, formatMoney } from '../lib/format'
import type { Plan, VpnState } from '../lib/types'
import { useAuth } from '../store/auth'
import { useToast } from '../store/toast'
import { Badge, HealthBadge, SubscriptionBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card, SectionTitle } from '../components/Card'
import { CardSkeleton, EmptyState } from '../components/Feedback'
import { ProgressRing } from '../components/ProgressRing'
import { openLink } from '../lib/telegram'

export function HomePage() {
  const navigate = useNavigate()
  const toast = useToast()
  const { user } = useAuth()
  const [state, setState] = useState<VpnState | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    try {
      const [vpn, catalogue] = await Promise.all([
        api.get<VpnState>('/vpn/state'),
        api.get<Plan[]>('/plans'),
      ])
      setState(vpn)
      setPlans(catalogue)
    } catch {
      /* the error surfaces through the empty state below */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    // Refresh on focus: the user often returns from the payment gateway here.
    const onFocus = () => void load()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [load])

  const reconnect = async () => {
    setRefreshing(true)
    try {
      await api.post('/vpn/sync')
      toast.success('Соединение обновлено')
      await load()
    } catch {
      toast.error('Не удалось обновить соединение')
    } finally {
      setRefreshing(false)
    }
  }

  if (loading) {
    return (
      <>
        <CardSkeleton />
        <CardSkeleton rows={2} />
      </>
    )
  }

  const subscription = state?.subscription ?? null
  const hasAccess = Boolean(state?.has_access)
  const isExpiringSoon = Boolean(subscription && subscription.days_left <= 3 && !subscription.is_expired)
  const cheapest = plans.length ? plans.reduce((a, b) => (a.price_kopeks <= b.price_kopeks ? a : b)) : null

  return (
    <>
      {/* ---------------------------------------------------------------- */}
      <Card hero className="hero">
        <div className="stack">
          <div className="hero__eyebrow">VPN Service</div>
          <h1 className="hero__title">Безопасный и быстрый интернет</h1>
          <p className="hero__subtitle">
            VLESS + REALITY — трафик невозможно заблокировать по DPI
          </p>

          <div className="row" style={{ marginTop: 4 }}>
            {hasAccess ? (
              <HealthBadge status={state?.server?.healthy ? 'up' : 'degraded'} />
            ) : (
              <Badge tone="warning">Нет активной подписки</Badge>
            )}
            {state?.sync_pending && <Badge tone="accent">Обновляется</Badge>}
          </div>
        </div>
      </Card>

      {/* ---------------------------------------------------------------- */}
      {hasAccess && subscription ? (
        <Card>
          <div className="row row--between">
            <div className="stack stack--sm grow">
              <div className="row row--between">
                <span className="small muted">Тариф</span>
                <SubscriptionBadge status={subscription.status} />
              </div>
              <div className="strong" style={{ fontSize: 17 }}>
                {subscription.plan_title}
              </div>
              <div className="small muted">
                Действует до {formatDate(subscription.expires_at)}
              </div>
            </div>
            <ProgressRing
              value={subscription.progress_percent}
              number={String(subscription.days_left)}
              caption={subscription.days_left === 1 ? 'день' : 'дней'}
            />
          </div>

          {isExpiringSoon && (
            <div
              className="card card--flat"
              style={{ marginTop: 12, borderLeft: '3px solid var(--warning)' }}
            >
              <div className="small">
                Подписка заканчивается {formatDays(subscription.days_left)}. Продлите, чтобы не потерять
                доступ.
              </div>
            </div>
          )}

          <div className="stack stack--sm" style={{ marginTop: 14 }}>
            <Button block onClick={() => navigate('/vpn')}>
              📱 Мой VPN и конфигурация
            </Button>
            <Button
              block
              variant="secondary"
              loading={refreshing}
              onClick={() => void reconnect()}
            >
              Обновить подключение
            </Button>
          </div>
        </Card>
      ) : (
        <Card>
          <div className="stack">
            <div className="row" style={{ gap: 10 }}>
              <span style={{ fontSize: 26 }}>🔒</span>
              <div className="grow">
                <div className="strong">Подписка не активна</div>
                <div className="small muted">
                  {subscription?.is_expired
                    ? `Срок действия истёк ${formatDate(subscription.expires_at)}`
                    : 'Выберите тариф и оплатите — конфигурация выдается автоматически'}
                </div>
              </div>
            </div>
            <Button block onClick={() => navigate('/plans')}>
              🛒 {cheapest ? `Купить за ${formatMoney(cheapest.price_kopeks)}` : 'Купить VPN'}
            </Button>
          </div>
        </Card>
      )}

      {/* ---------------------------------------------------------------- */}
      {plans.length > 0 && (
        <>
          <SectionTitle
            title="Тарифы"
            action={
              <button className="btn btn--ghost btn--sm" onClick={() => navigate('/plans')}>
                Все →
              </button>
            }
          />
          <div className="stack">
            {plans.slice(0, 2).map((plan) => (
              <div
                key={plan.id}
                className={['plan', plan.is_popular && 'plan--popular'].filter(Boolean).join(' ')}
                onClick={() => navigate(`/plans?focus=${plan.id}`)}
                role="button"
                tabIndex={0}
                onKeyDown={(event) => event.key === 'Enter' && navigate(`/plans?focus=${plan.id}`)}
              >
                {plan.badge && <span className="plan__badge">{plan.badge}</span>}
                <div className="row row--between">
                  <div>
                    <div className="strong">{plan.title}</div>
                    <div className="small muted">{plan.description}</div>
                  </div>
                  <div className="plan__price">
                    <span className="plan__amount">{formatMoney(plan.price_kopeks, plan.currency)}</span>
                  </div>
                </div>
                <Button size="sm" variant="secondary" block>
                  Выбрать
                </Button>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ---------------------------------------------------------------- */}
      <Card>
        <SectionTitle title="Как это работает" />
        <div className="stack stack--sm">
          {[
            ['1️⃣', 'Оплатите тариф', 'Безопасная оплата, доступ сразу после подтверждения'],
            ['2️⃣', 'Получите конфиг', 'Ссылка vless:// и QR-код в разделе «Мой VPN»'],
            ['3️⃣', 'Подключитесь', 'Установите приложение и включите VPN'],
          ].map(([emoji, title, text]) => (
            <div key={title} className="row" style={{ alignItems: 'flex-start' }}>
              <span style={{ fontSize: 18 }}>{emoji}</span>
              <div className="grow">
                <div className="strong small">{title}</div>
                <div className="tiny muted">{text}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="divider" />
        <div className="row row--between">
          <span className="small muted">Нужна помощь?</span>
          <Button size="sm" variant="ghost" onClick={() => navigate('/support')}>
            Написать в поддержку
          </Button>
        </div>
      </Card>

      {user?.is_banned && (
        <EmptyState
          icon="🚫"
          title="Доступ ограничен"
          description="Обратитесь в поддержку, чтобы решить вопрос."
          action={
            <Button size="sm" variant="secondary" onClick={() => openLink('https://t.me/')}>
              Поддержка
            </Button>
          }
        />
      )}
    </>
  )
}
