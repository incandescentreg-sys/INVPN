import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { formatMoney } from '../lib/format'
import type { CreatePaymentResponse, PaymentStatusResponse, Plan } from '../lib/types'
import { openLink } from '../lib/telegram'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card, SectionTitle } from '../components/Card'
import { Loading } from '../components/Feedback'
import { useToast } from '../store/toast'

/**
 * Checkout screen.
 *
 * The flow: create the order -> open the gateway -> poll `GET /payments/{id}`
 * until it reports `succeeded` (the webhook is the primary signal, polling is
 * the fallback in case the webhook is slow or blocked).
 */
export function CheckoutPage() {
  const { planId = '' } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const toast = useToast()

  const paymentId = params.get('payment')
  const [plan, setPlan] = useState<Plan | null>(null)
  const [order, setOrder] = useState<CreatePaymentResponse | null>(null)
  const [status, setStatus] = useState<PaymentStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const pollRef = useRef<number | null>(null)
  const attempts = useRef(0)

  // Load the plan we are buying.
  useEffect(() => {
    api
      .get<Plan[]>('/plans')
      .then((plans) => {
        const found = plans.find((item) => item.id === planId) ?? null
        setPlan(found)
        if (!found) setError('Тариф не найден или больше не доступен')
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Не удалось загрузить тариф'))
  }, [planId])

  // Create the order when we arrive without one.
  useEffect(() => {
    if (paymentId || !planId) return
    api
      .post<CreatePaymentResponse>('/payments', { plan_id: planId })
      .then((created) => {
        setOrder(created)
        if (created.payment.status === 'succeeded') {
          toast.success('Оплата уже получена')
          navigate('/vpn', { replace: true })
        }
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Не удалось создать заказ'))
  }, [paymentId, planId, navigate, toast])

  const check = useCallback(async () => {
    if (!paymentId && !order?.payment.id) return
    const id = paymentId ?? order?.payment.id
    if (!id) return
    try {
      const response = await api.get<PaymentStatusResponse>(`/payments/${id}`)
      setStatus(response)
      attempts.current += 1
      if (response.payment.status === 'succeeded') {
        toast.success('Оплата получена — VPN активен')
        navigate('/vpn', { replace: true })
        return
      }
      if (['failed', 'cancelled'].includes(response.payment.status)) {
        setError(response.message ?? 'Платёж не завершён')
        return
      }
    } catch (err) {
      if (attempts.current > 3) {
        setError(err instanceof ApiError ? err.message : 'Не удалось проверить платёж')
      }
    }
    // Keep polling for a couple of minutes; the webhook usually wins the race.
    if (attempts.current < 60) {
      pollRef.current = window.setTimeout(() => void check(), 2000)
    }
  }, [paymentId, order?.payment.id, navigate, toast])

  useEffect(() => {
    void check()
    return () => {
      if (pollRef.current) window.clearTimeout(pollRef.current)
    }
  }, [check])

  const pay = async () => {
    if (!order?.redirect_url) return
    setBusy(true)
    openLink(order.redirect_url)
    // Give the user a moment, then start looking for the payment.
    window.setTimeout(() => {
      attempts.current = 0
      void check()
    }, 1200)
    setBusy(false)
  }

  if (error) {
    return (
      <Card>
        <div className="stack">
          <div className="row">
            <span style={{ fontSize: 26 }}>⚠️</span>
            <div className="strong grow">{error}</div>
          </div>
          <Button block variant="secondary" onClick={() => navigate('/plans')}>
            К списку тарифов
          </Button>
        </div>
      </Card>
    )
  }

  if (!plan) return <Loading label="Готовим заказ…" />

  const payment = status?.payment ?? order?.payment

  return (
    <>
      <Card hero>
        <div className="stack stack--sm">
          <div className="hero__eyebrow">Оплата подписки</div>
          <div className="row row--between">
            <div>
              <div className="strong" style={{ fontSize: 17 }}>
                {plan.title}
              </div>
              <div className="small muted">{plan.days} дней доступа</div>
            </div>
            <div className="plan__amount">{formatMoney(plan.price_kopeks, plan.currency)}</div>
          </div>
        </div>
      </Card>

      <Card>
        <SectionTitle title="Способы оплаты" />
        <div className="stack stack--sm">
          <div className="row row--between">
            <span className="small grow">Банковская карта (МИР, Visa, Mastercard)</span>
            <Badge tone="success">Доступен</Badge>
          </div>
          <div className="divider" style={{ margin: '4px 0' }} />
          <div className="row row--between">
            <span className="small muted grow">Платёж проводится на защищённой странице шлюза</span>
          </div>
        </div>
      </Card>

      <Card>
        <div className="stack stack--sm">
          <div className="row row--between">
            <span className="small muted">К оплате</span>
            <span className="strong">{formatMoney(payment?.amount_kopeks ?? plan.price_kopeks, plan.currency)}</span>
          </div>
          {payment?.status === 'pending' && (
            <div className="row small muted" style={{ gap: 8 }}>
              <span className="spinner" style={{ width: 13, height: 13 }} />
              Ожидаем подтверждение оплаты…
            </div>
          )}

          <Button block loading={busy} onClick={() => void pay()} disabled={!order?.redirect_url}>
            {order?.redirect_url ? 'Перейти к оплате' : 'Готовим ссылку…'}
          </Button>

          <Button block variant="ghost" onClick={() => void check()}>
            Я оплатил — проверить
          </Button>

          <div className="tiny muted center">
            Не закрывайте приложение: статус обновится автоматически. Конфигурация выдаётся сразу после
            оплаты.
          </div>
        </div>
      </Card>
    </>
  )
}
