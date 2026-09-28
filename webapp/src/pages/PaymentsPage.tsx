import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { formatDateTime, formatMoney } from '../lib/format'
import type { Payment } from '../lib/types'
import { useAsync } from '../lib/useAsync'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card, SectionTitle } from '../components/Card'
import { CardSkeleton, EmptyState } from '../components/Feedback'

const STATUS: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }> = {
  succeeded: { label: 'Оплачен', tone: 'success' },
  pending: { label: 'Ожидает', tone: 'warning' },
  failed: { label: 'Ошибка', tone: 'danger' },
  cancelled: { label: 'Отменён', tone: 'neutral' },
  refunded: { label: 'Возврат', tone: 'neutral' },
  partially_refunded: { label: 'Частичный возврат', tone: 'neutral' },
}

export function PaymentsPage() {
  const navigate = useNavigate()
  const { data, loading, reload } = useAsync<Payment[]>(() => api.get<Payment[]>('/payments'))

  if (loading) return <CardSkeleton rows={4} />

  const total = (data ?? [])
    .filter((payment) => payment.status === 'succeeded')
    .reduce((sum, payment) => sum + payment.amount_kopeks - payment.refunded_kopeks, 0)

  return (
    <>
      <Card hero>
        <div className="stack stack--sm">
          <div className="hero__eyebrow">Оплата</div>
          <div className="row row--between">
            <div>
              <div className="small muted">Всего оплачено</div>
              <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.03em' }}>
                {formatMoney(total)}
              </div>
            </div>
            <div className="device__icon" style={{ fontSize: 24 }} aria-hidden="true">
              💳
            </div>
          </div>
          <Button size="sm" variant="secondary" block onClick={() => navigate('/plans')}>
            🛒 Купить подписку
          </Button>
        </div>
      </Card>

      <Card>
        <SectionTitle
          title="История платежей"
          action={
            <button className="btn btn--ghost btn--sm" onClick={() => void reload()}>
              ⟳
            </button>
          }
        />

        {!data || data.length === 0 ? (
          <EmptyState
            icon="🧾"
            title="Платежей пока нет"
            description="После первой оплаты здесь появится история."
            action={
              <Button size="sm" onClick={() => navigate('/plans')}>
                Выбрать тариф
              </Button>
            }
          />
        ) : (
          <div className="stack stack--sm">
            {data.map((payment) => {
              const status = STATUS[payment.status] ?? { label: payment.status, tone: 'neutral' as const }
              return (
                <div key={payment.id} className="device">
                  <div className="grow">
                    <div className="row row--between">
                      <span className="strong small">{payment.description ?? 'Подписка VPN'}</span>
                      <span className="small strong">
                        {formatMoney(payment.amount_kopeks, payment.currency)}
                      </span>
                    </div>
                    <div className="row row--between" style={{ marginTop: 2 }}>
                      <span className="tiny muted">{formatDateTime(payment.created_at)}</span>
                      <Badge tone={status.tone}>{status.label}</Badge>
                    </div>
                    {payment.refunded_kopeks > 0 && (
                      <div className="tiny" style={{ color: 'var(--tg-hint)' }}>
                        Возвращено {formatMoney(payment.refunded_kopeks, payment.currency)}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Card>

      <Card flat>
        <div className="tiny muted">
          Возврат средств — через поддержку. Обычно обрабатываем за 1–3 рабочих дня.
        </div>
      </Card>
    </>
  )
}
