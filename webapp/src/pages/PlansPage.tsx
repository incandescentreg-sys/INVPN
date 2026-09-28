import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { formatMoney, plural } from '../lib/format'
import type { Plan } from '../lib/types'
import { useAsync } from '../lib/useAsync'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card, SectionTitle } from '../components/Card'
import { CardSkeleton } from '../components/Feedback'
import { useToast } from '../store/toast'

export function PlansPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const [params] = useSearchParams()
  const [activeId, setActiveId] = useState<string | null>(params.get('focus'))
  const [busyId, setBusyId] = useState<string | null>(null)
  const { data: plans, loading, error, reload } = useAsync<Plan[]>(() => api.get<Plan[]>('/plans'))

  useEffect(() => {
    const focus = params.get('focus')
    if (focus) setActiveId(focus)
  }, [params])

  const buy = async (plan: Plan) => {
    setBusyId(plan.id)
    try {
      // Create the order first so the checkout screen has something to poll.
      const order = await api.post<{ payment: { id: string } }>('/payments', { plan_id: plan.id })
      navigate(`/checkout/${plan.id}?payment=${order.payment.id}`)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Не удалось создать заказ')
    } finally {
      setBusyId(null)
    }
  }

  if (loading) return <CardSkeleton rows={4} />
  if (error) return <Card><div className="small">{error}</div><Button size="sm" variant="secondary" onClick={() => void reload()}>Повторить</Button></Card>
  if (!plans?.length) {
    return (
      <Card>
        <div className="center stack stack--sm">
          <div style={{ fontSize: 32 }}>🗂</div>
          <div className="strong">Тарифы пока не добавлены</div>
          <div className="small muted">Загляните позже или напишите в поддержку.</div>
        </div>
      </Card>
    )
  }

  const selected = plans.find((plan) => plan.id === activeId) ?? plans.find((plan) => plan.is_popular) ?? plans[0]

  return (
    <>
      <SectionTitle
        title="Выберите тариф"
        action={<span className="tiny">цена зафиксирована в тарифе</span>}
      />

      <div className="stack">
        {plans.map((plan) => {
          const perDay = Math.round(plan.price_kopeks / plan.days)
          const isActive = selected.id === plan.id
          return (
            <div
              key={plan.id}
              className={['plan', isActive && 'plan--active', plan.is_popular && 'plan--popular']
                .filter(Boolean)
                .join(' ')}
              onClick={() => setActiveId(plan.id)}
              role="radio"
              aria-checked={isActive}
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  setActiveId(plan.id)
                }
              }}
            >
              {plan.badge && <span className="plan__badge">{plan.badge}</span>}

              <div className="row row--between" style={{ alignItems: 'flex-start' }}>
                <div className="grow">
                  <div className="row row--between">
                    <span className="strong" style={{ fontSize: 16 }}>
                      {plan.title}
                    </span>
                    {isActive && <Badge tone="accent">Выбран</Badge>}
                  </div>
                  {plan.description && <div className="small muted">{plan.description}</div>}
                </div>
                <div className="plan__price">
                  <span className="plan__amount">
                    {formatMoney(plan.price_kopeks, plan.currency)}
                  </span>
                </div>
              </div>

              <div className="small muted">
                {plan.days} {plural(plan.days, ['день', 'дня', 'дней'])} ·{' '}
                {formatMoney(perDay, plan.currency)} в день
              </div>

              {plan.features.length > 0 && (
                <div className="plan__features">
                  {plan.features.map((feature) => (
                    <div key={feature} className="plan__feature">
                      <span className="plan__check">✓</span>
                      <span>{feature}</span>
                    </div>
                  ))}
                </div>
              )}

              <Button
                block
                variant={isActive ? 'primary' : 'secondary'}
                loading={busyId === plan.id}
                onClick={(event) => {
                  event.stopPropagation()
                  void buy(plan)
                }}
              >
                {isActive ? 'Оплатить' : 'Выбрать'}
              </Button>
            </div>
          )
        })}
      </div>

      <Card flat>
        <div className="tiny muted">
          Подписка продлевается на ту же длительность — неиспользованные дни не сгорают при
          продлении. Оплата проводится через защищённый платёжный шлюз.
        </div>
      </Card>
    </>
  )
}
