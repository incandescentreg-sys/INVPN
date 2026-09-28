import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatMoney, formatDate } from '../../lib/format'
import { useAsync } from '../../lib/useAsync'
import { api, ApiError } from '../../lib/api'
import type { AdminStats } from '../../lib/types'
import { Badge, HealthBadge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Card, SectionTitle } from '../../components/Card'
import { CardSkeleton, EmptyState } from '../../components/Feedback'
import { useToast } from '../../store/toast'

type Tab = 'overview' | 'users' | 'plans' | 'payments' | 'servers'

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'overview', label: 'Обзор', icon: '📊' },
  { id: 'users', label: 'Люди', icon: '👥' },
  { id: 'plans', label: 'Тарифы', icon: '🏷' },
  { id: 'payments', label: 'Платежи', icon: '💳' },
  { id: 'servers', label: 'Серверы', icon: '🖧' },
]

export function AdminPage() {
  const [tab, setTab] = useState<Tab>('overview')

  return (
    <>
      <div className="tabs" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            className={['tabs__item', tab === item.id && 'tabs__item--active'].filter(Boolean).join(' ')}
            onClick={() => setTab(item.id)}
          >
            {item.icon} {item.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <AdminOverview />}
      {tab === 'users' && <AdminUsers />}
      {tab === 'plans' && <AdminPlans />}
      {tab === 'payments' && <AdminPayments />}
      {tab === 'servers' && <AdminServers onGoHome={() => undefined} />}
    </>
  )
}

/* ------------------------------------------------------------------ */
/* Overview                                                            */
/* ------------------------------------------------------------------ */
function AdminOverview() {
  const { data, loading, reload } = useAsync<AdminStats>(() => api.get<AdminStats>('/admin/stats'))
  if (loading) return <CardSkeleton rows={4} />
  if (!data) return <EmptyState icon="📊" title="Нет данных" />

  const maxDay = Math.max(1, ...data.payments.by_day.map((day) => day.total_kopeks))

  return (
    <>
      <Card hero>
        <div className="row row--between">
          <div>
            <div className="hero__eyebrow">Выручка за 30 дней</div>
            <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.03em' }}>
              {formatMoney(data.payments.revenue_30d_kopeks)}
            </div>
            <div className="small muted">
              {data.payments.successful_30d} успешных платежей
            </div>
          </div>
          <Button size="sm" variant="secondary" onClick={() => void reload()}>
            ⟳
          </Button>
        </div>
      </Card>

      <div className="stat-grid">
        <div className="stat">
          <div className="stat__value">{data.users.total}</div>
          <div className="stat__label">Пользователей</div>
        </div>
        <div className="stat">
          <div className="stat__value">+{data.users.new_7d}</div>
          <div className="stat__label">За 7 дней</div>
        </div>
        <div className="stat">
          <div className="stat__value">{data.subscriptions.active}</div>
          <div className="stat__label">Активных</div>
        </div>
        <div className="stat">
          <div className="stat__value">{data.subscriptions.expiring_soon}</div>
          <div className="stat__label">Истекают скоро</div>
        </div>
      </div>

      {data.payments.by_day.length > 0 && (
        <Card>
          <SectionTitle title="Продажи по дням" />
          <div className="chart">
            {data.payments.by_day.map((day) => (
              <div
                key={day.date}
                className="chart__bar"
                style={{ height: `${Math.max(4, (day.total_kopeks / maxDay) * 100)}%` }}
                title={`${day.date}: ${formatMoney(day.total_kopeks)}`}
              />
            ))}
          </div>
          <div className="row row--between tiny muted" style={{ marginTop: 6 }}>
            <span>{data.payments.by_day[0]?.date}</span>
            <span>{data.payments.by_day[data.payments.by_day.length - 1]?.date}</span>
          </div>
        </Card>
      )}

      <Card>
        <SectionTitle title="VPN-серверы" />
        <div className="stack stack--sm">
          {data.vpn.servers.length === 0 && (
            <div className="small muted">Серверы не настроены. Добавьте VPS в разделе «Серверы».</div>
          )}
          {data.vpn.servers.map((server) => (
            <div key={server.id} className="device">
              <div className="device__icon">🖧</div>
              <div className="grow">
                <div className="strong small">{server.name}</div>
                <div className="tiny muted">
                  {server.last_checked_at ? formatDate(server.last_checked_at) : 'не проверялся'}
                  {server.last_error ? ` · ${server.last_error.slice(0, 40)}` : ''}
                </div>
              </div>
              <HealthBadge status={server.health} />
            </div>
          ))}
          <div className="row row--between small">
            <span className="muted">Активных клиентов</span>
            <span className="strong">
              {data.vpn.clients_active} / {data.vpn.clients_total}
            </span>
          </div>
        </div>
      </Card>
    </>
  )
}

/* ------------------------------------------------------------------ */
/* Users                                                               */
/* ------------------------------------------------------------------ */
function AdminUsers() {
  const toast = useToast()
  const [search, setSearch] = useState('')
  const [bannedOnly, setBannedOnly] = useState(false)
  const { data, loading, reload } = useAsync<{ items: any[]; total: number }>(
    () =>
      api.get(`/admin/users?limit=50&search=${encodeURIComponent(search)}&is_banned=${bannedOnly}`),
    [search, bannedOnly],
  )

  const act = async (userId: string, action: 'ban' | 'unban' | 'admin') => {
    try {
      await api.post(`/admin/users/${userId}/${action}`)
      toast.success('Готово')
      await reload()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Ошибка')
    }
  }

  if (loading) return <CardSkeleton rows={5} />

  return (
    <Card>
      <SectionTitle
        title="Пользователи"
        action={<span className="tiny">{data?.total ?? 0}</span>}
      />

      <div className="stack stack--sm" style={{ marginBottom: 12 }}>
        <input
          className="input"
          placeholder="Поиск по имени, @username или Telegram ID"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className="tabs">
          <button
            className={['tabs__item', !bannedOnly && 'tabs__item--active'].filter(Boolean).join(' ')}
            onClick={() => setBannedOnly(false)}
          >
            Все
          </button>
          <button
            className={['tabs__item', bannedOnly && 'tabs__item--active'].filter(Boolean).join(' ')}
            onClick={() => setBannedOnly(true)}
          >
            Заблокированные
          </button>
        </div>
      </div>

      <div className="table">
        <div className="table__row table__row--head">
          <span className="grow">Пользователь</span>
          <span>Действия</span>
        </div>
        {data?.items.length === 0 && (
          <div className="table__row">
            <span className="muted small">Ничего не найдено</span>
          </div>
        )}
        {data?.items.map((user) => (
          <div key={user.id} className="table__row">
            <div className="grow">
              <div className="row" style={{ gap: 6 }}>
                <span className="strong ellipsis">{user.display_name}</span>
                {user.is_admin && <Badge tone="accent">админ</Badge>}
                {user.is_banned && <Badge tone="danger">бан</Badge>}
              </div>
              <div className="tiny muted">
                {user.username ? `@${user.username}` : user.telegram_id} · {formatDate(user.created_at)}
              </div>
            </div>
            <div className="row" style={{ gap: 4 }}>
              <Button size="sm" variant="ghost" onClick={() => void act(user.id, user.is_banned ? 'unban' : 'ban')}>
                {user.is_banned ? 'Разбан' : 'Бан'}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => void act(user.id, 'admin')}>
                {user.is_admin ? '−ADM' : '+ADM'}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Plans                                                               */
/* ------------------------------------------------------------------ */
function AdminPlans() {
  const toast = useToast()
  const { data, loading, reload } = useAsync<any[]>(() => api.get('/admin/plans'))
  const [editing, setEditing] = useState<any | null>(null)
  const [creating, setCreating] = useState(false)

  if (loading) return <CardSkeleton rows={4} />

  const save = async (plan: any) => {
    try {
      if (plan.id) await api.patch(`/admin/plans/${plan.id}`, plan)
      else await api.post('/admin/plans', plan)
      toast.success('Сохранено')
      setEditing(null)
      setCreating(false)
      await reload()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Ошибка')
    }
  }

  return (
    <>
      <Card>
        <SectionTitle
          title="Тарифы"
          action={
            <Button size="sm" variant="ghost" onClick={() => setCreating(true)}>
              + Добавить
            </Button>
          }
        />
        <div className="table">
          {data?.map((plan) => (
            <div key={plan.id} className="table__row">
              <div className="grow">
                <div className="row" style={{ gap: 6 }}>
                  <span className="strong ellipsis">{plan.title}</span>
                  {plan.is_popular && <Badge tone="accent">топ</Badge>}
                  {!plan.is_active && <Badge tone="danger">выкл</Badge>}
                </div>
                <div className="tiny muted">
                  {plan.days} дн · {formatMoney(plan.price_kopeks, plan.currency)} · {plan.code}
                </div>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setEditing(plan)}>
                Изм.
              </Button>
            </div>
          ))}
        </div>
      </Card>

      {(editing || creating) && (
        <Card hero>
          <SectionTitle title={creating ? 'Новый тариф' : 'Редактирование'} />
          <div className="stack">
            <div className="field">
              <span className="field__label">Название</span>
              <input
                className="input"
                value={editing?.title ?? ''}
                onChange={(event) => setEditing({ ...(editing ?? {}), title: event.target.value })}
              />
            </div>
            <div className="input-row">
              <div className="field">
                <span className="field__label">Дней</span>
                <input
                  className="input"
                  type="number"
                  value={editing?.days ?? 30}
                  onChange={(event) =>
                    setEditing({ ...(editing ?? {}), days: Number(event.target.value) })
                  }
                />
              </div>
              <div className="field">
                <span className="field__label">Цена, копейки</span>
                <input
                  className="input"
                  type="number"
                  value={editing?.price_kopeks ?? 29900}
                  onChange={(event) =>
                    setEditing({ ...(editing ?? {}), price_kopeks: Number(event.target.value) })
                  }
                />
              </div>
            </div>
            {!creating && (
              <div className="field">
                <span className="field__label">Код (не меняется)</span>
                <input className="input" value={editing?.code ?? ''} disabled />
              </div>
            )}
            <Button block onClick={() => void save(editing ?? { code: `plan_${Date.now()}`, days: 30, price_kopeks: 0 })}>
              Сохранить
            </Button>
            <Button
              block
              variant="secondary"
              onClick={() => {
                setEditing(null)
                setCreating(false)
              }}
            >
              Отмена
            </Button>
            <div className="tiny muted">
              29900 копеек = 299 ₽. Цена берётся из базы, а не из кода.
            </div>
          </div>
        </Card>
      )}
    </>
  )
}

/* ------------------------------------------------------------------ */
/* Payments                                                            */
/* ------------------------------------------------------------------ */
function AdminPayments() {
  const { data, loading } = useAsync<{ items: any[] }>(() => api.get('/admin/payments?limit=50'))

  if (loading) return <CardSkeleton rows={5} />

  const tone: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
    succeeded: 'success',
    pending: 'warning',
    failed: 'danger',
  }

  return (
    <Card>
      <SectionTitle title="Платежи" action={<span className="tiny">последние 50</span>} />
      <div className="table">
        <div className="table__row table__row--head">
          <span className="grow">Пользователь</span>
          <span>Сумма</span>
          <span>Статус</span>
        </div>
        {data?.items.length === 0 && (
          <div className="table__row">
            <span className="muted small">Платежей пока нет</span>
          </div>
        )}
        {data?.items.map((payment) => (
          <div key={payment.id} className="table__row">
            <div className="grow">
              <div className="small ellipsis">{payment.username ?? payment.user_id.slice(0, 8)}</div>
              <div className="tiny muted">
                {payment.description} · {formatDate(payment.created_at)}
              </div>
            </div>
            <span className="small strong">{formatMoney(payment.amount_kopeks, payment.currency)}</span>
            <Badge tone={tone[payment.status] ?? 'neutral'}>{payment.status}</Badge>
          </div>
        ))}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Servers                                                             */
/* ------------------------------------------------------------------ */
function AdminServers({ onGoHome }: { onGoHome: () => void }) {
  const toast = useToast()
  const navigate = useNavigate()
  const { data, loading, reload } = useAsync<any[]>(() => api.get('/admin/servers'))
  const [syncing, setSyncing] = useState(false)

  if (loading) return <CardSkeleton rows={3} />

  const syncAll = async () => {
    setSyncing(true)
    try {
      const result = await api.post<{ ok: boolean; results: any[] }>('/admin/servers/sync')
      toast.success(result.ok ? 'Все серверы синхронизированы' : 'Синхронизация с ошибками')
      await reload()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Ошибка синхронизации')
    } finally {
      setSyncing(false)
    }
  }

  const health = async (serverId: string) => {
    try {
      const report = await api.get<{ status: string }>(`/admin/servers/${serverId}/health`)
      toast.show(`Сервер: ${report.status}`)
      await reload()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Сервер недоступен')
    }
  }

  return (
    <>
      <Card>
        <SectionTitle
          title="VPN-серверы"
          action={
            <Button size="sm" variant="secondary" loading={syncing} onClick={() => void syncAll()}>
              Синхронизировать
            </Button>
          }
        />
        <div className="stack stack--sm">
          {data?.length === 0 && (
            <EmptyState
              icon="🖧"
              title="Серверы не добавлены"
              description="Добавьте VPS вручную или задайте SERVER_* в переменных окружения."
            />
          )}
          {data?.map((server) => (
            <div key={server.id} className="card card--flat">
              <div className="row row--between">
                <div className="grow">
                  <div className="row" style={{ gap: 6 }}>
                    <span className="strong">{server.name}</span>
                    <HealthBadge status={server.last_check_status} />
                    {!server.is_active && <Badge tone="neutral">выкл</Badge>}
                  </div>
                  <div className="tiny muted mono">
                    {server.public_host}:{server.public_port} · {server.host}:{server.ssh_port}
                  </div>
                </div>
                <Button size="sm" variant="ghost" onClick={() => void health(server.id)}>
                  Проверить
                </Button>
              </div>
              <div className="divider" />
              <div className="row row--between tiny">
                <span className="muted">Клиентов</span>
                <span className="strong">
                  {server.clients_active} / {server.clients_total}
                  {server.max_clients > 0 ? ` (макс ${server.max_clients})` : ''}
                </span>
              </div>
              {server.last_error && (
                <div className="tiny" style={{ color: 'var(--tg-destructive)', marginTop: 4 }}>
                  {server.last_error}
                </div>
              )}
              <div className="tiny muted" style={{ marginTop: 4 }}>
                pbk: <span className="mono">{server.reality_public_key?.slice(0, 16)}…</span> · sid:{' '}
                <span className="mono">{server.reality_short_id}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card flat>
        <div className="stack stack--sm">
          <div className="tiny muted">
            Ключи REALITY и SSH-ключи хранятся в базе в зашифрованном виде и никогда не выводятся в API.
          </div>
          <Button size="sm" variant="ghost" block onClick={onGoHome ?? (() => navigate('/'))}>
            ← Вернуться в приложение
          </Button>
        </div>
      </Card>
    </>
  )
}
