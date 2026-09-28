import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { formatDate, formatDays, truncateMiddle } from '../lib/format'
import { openLink } from '../lib/telegram'
import type { ClientLinks, VpnClient, VpnState } from '../lib/types'
import { useAsync } from '../lib/useAsync'
import { Badge, HealthBadge, SubscriptionBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card, SectionTitle } from '../components/Card'
import { CardSkeleton, EmptyState } from '../components/Feedback'
import { ProgressRing } from '../components/ProgressRing'
import { QrCode } from '../components/QrCode'
import { ConfirmSheet, CopyButton, Sheet } from '../components/Sheet'
import { useToast } from '../store/toast'

const DEVICE_ICONS: Record<string, string> = {
  android: '🤖',
  ios: '🍎',
  windows: '🖥️',
  macos: '💻',
  linux: '🐧',
  desktop: '🖥️',
  other: '📱',
}

export function VpnPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const { data, loading, reload } = useAsync<VpnState>(() => api.get<VpnState>('/vpn/state'))
  const [links, setLinks] = useState<ClientLinks | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<{ client: VpnClient; action: 'remove' | 'rotate' } | null>(null)
  const [adding, setAdding] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const openConfig = useCallback(
    async (client: VpnClient) => {
      setBusyId(client.id)
      try {
        setLinks(await api.get<ClientLinks>(`/vpn/clients/${client.id}/link`))
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : 'Не удалось получить конфигурацию')
      } finally {
        setBusyId(null)
      }
    },
    [toast],
  )

  const addDevice = useCallback(async () => {
    setAdding(true)
    try {
      const created = await api.post<{ links: ClientLinks | null }>('/vpn/clients', {
        label: `Устройство ${(data?.clients.length ?? 0) + 1}`,
      })
      await reload()
      if (created.links) setLinks(created.links)
      toast.success('Устройство добавлено')
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Не удалось добавить устройство')
    } finally {
      setAdding(false)
    }
  }, [data?.clients.length, reload, toast])

  const runAction = useCallback(
    async (client: VpnClient, action: 'remove' | 'rotate') => {
      setBusyId(client.id)
      try {
        if (action === 'remove') {
          await api.delete(`/vpn/clients/${client.id}`)
          toast.success('Устройство отключено')
          setConfirm(null)
        } else {
          const fresh = await api.post<ClientLinks>(`/vpn/clients/${client.id}/rotate`)
          setLinks(fresh)
          toast.success('Конфигурация обновлена')
          setConfirm(null)
        }
        await reload()
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : 'Ошибка')
      } finally {
        setBusyId(null)
      }
    },
    [reload, toast],
  )

  const resync = async () => {
    setSyncing(true)
    try {
      await api.post('/vpn/sync')
      toast.success('Подключение обновлено')
      await reload()
    } catch {
      toast.error('Сервер VPN временно недоступен')
    } finally {
      setSyncing(false)
    }
  }

  if (loading) return <CardSkeleton rows={5} />
  if (!data) return <EmptyState icon="📡" title="Нет данных" />

  const subscription = data.subscription
  const primary = data.primary_client
  const enabled = data.clients.filter((client) => client.status !== 'disabled')

  if (!data.has_access || !subscription) {
    return (
      <>
        <EmptyState
          icon="🔒"
          title="Нет активной подписки"
          description="Купите тариф, и конфигурация появится здесь автоматически после оплаты."
          action={
            <Button onClick={() => navigate('/plans')} style={{ marginTop: 8 }}>
              🛒 Выбрать тариф
            </Button>
          }
        />
        <Button block variant="secondary" onClick={() => void reload()}>
          Обновить
        </Button>
      </>
    )
  }

  return (
    <>
      {/* Status ---------------------------------------------------------- */}
      <Card hero>
        <div className="row row--between">
          <div className="stack stack--sm grow">
            <div className="hero__eyebrow">Статус VPN</div>
            <div className="row row--between">
              <span className="strong" style={{ fontSize: 17 }}>
                {subscription.is_expired ? 'Отключён' : 'Подключён'}
              </span>
              <HealthBadge status={data.server?.healthy ? 'up' : 'degraded'} />
            </div>
            <div className="small muted">
              {subscription.plan_title} · до {formatDate(subscription.expires_at)}
            </div>
            {data.sync_pending && (
              <Badge tone="accent">Обновляем конфигурацию на сервере…</Badge>
            )}
          </div>
          <ProgressRing
            value={subscription.progress_percent}
            number={String(subscription.days_left)}
            caption="дней"
          />
        </div>
      </Card>

      {/* Primary config --------------------------------------------------- */}
      {primary && (
        <Card>
          <SectionTitle
            title="Подключение"
            action={<SubscriptionBadge status={subscription.status} />}
          />
          <div className="device device--primary">
            <div className="device__icon">🔑</div>
            <div className="grow">
              <div className="strong small ellipsis">{primary.label ?? 'Основной конфиг'}</div>
              <div className="tiny muted mono">{truncateMiddle(primary.uuid, 14, 8)}</div>
            </div>
            <Button size="sm" onClick={() => void openConfig(primary)} loading={busyId === primary.id}>
              Открыть
            </Button>
          </div>

          <div className="row" style={{ marginTop: 12, gap: 8 }}>
            <Button size="sm" variant="secondary" block loading={syncing} onClick={() => void resync()}>
              Обновить
            </Button>
            <Button size="sm" variant="secondary" block onClick={() => navigate('/instructions')}>
              Инструкция
            </Button>
          </div>
        </Card>
      )}

      {/* Devices ---------------------------------------------------------- */}
      <Card>
        <SectionTitle
          title="Устройства"
          action={
            <span className="tiny">
              {enabled.length}
              {data.device_limit.limit > 0 ? ` / ${data.device_limit.limit}` : ''}
            </span>
          }
        />

        <div className="stack stack--sm">
          {enabled.map((client) => (
            <div key={client.id} className={['device', client.is_primary && 'device--primary'].filter(Boolean).join(' ')}>
              <div className="device__icon">{DEVICE_ICONS[client.server_name ?? 'other'] ?? '📱'}</div>
              <div className="grow">
                <div className="strong small ellipsis">{client.label ?? 'Устройство'}</div>
                <div className="tiny muted">
                  {client.is_primary ? 'Основной · ' : ''}
                  {client.status === 'active' ? 'в сети' : client.status === 'pending' ? 'настраивается' : client.status}
                </div>
              </div>
              <div className="row" style={{ gap: 4 }}>
                <Button size="sm" variant="ghost" onClick={() => void openConfig(client)}>
                  Конфиг
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirm({ client, action: 'rotate' })}
                >
                  ⟳
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirm({ client, action: 'remove' })}
                >
                  ✕
                </Button>
              </div>
            </div>
          ))}
        </div>

        <div className="divider" />
        <Button
          block
          variant="secondary"
          loading={adding}
          disabled={data.device_limit.remaining === 0}
          onClick={() => void addDevice()}
        >
          {data.device_limit.remaining === 0 ? 'Достигнут лимит устройств' : '+ Добавить устройство'}
        </Button>
        {data.device_limit.remaining !== null && data.device_limit.remaining > 0 && (
          <div className="tiny muted center" style={{ marginTop: 6 }}>
            Осталось {data.device_limit.remaining} из {data.device_limit.limit}
          </div>
        )}
      </Card>

      {/* Subscription ----------------------------------------------------- */}
      <Card>
        <SectionTitle title="Подписка" />
        <div className="stack stack--sm">
          <div className="row row--between">
            <span className="small muted">Тариф</span>
            <span className="small strong">{subscription.plan_title}</span>
          </div>
          <div className="row row--between">
            <span className="small muted">Осталось</span>
            <span className="small strong">{formatDays(subscription.days_left)}</span>
          </div>
          <div className="row row--between">
            <span className="small muted">Действует до</span>
            <span className="small strong">{formatDate(subscription.expires_at)}</span>
          </div>
          {data.server && (
            <div className="row row--between">
              <span className="small muted">Сервер</span>
              <span className="small strong">
                {data.server.host}:{data.server.port}
              </span>
            </div>
          )}
        </div>
        <div className="divider" />
        <Button block onClick={() => navigate('/plans')}>
          🔄 Продлить подписку
        </Button>
      </Card>

      {/* Config sheet ------------------------------------------------------ */}
      <Sheet
        open={Boolean(links)}
        title="Конфигурация"
        onClose={() => setLinks(null)}
        footer={
          links && (
            <>
              <CopyButton value={links.link} className="btn btn--primary btn--block" label="Скопировать ссылку" />
              {Object.entries(links.deep_links).map(([name, url]) => (
                <Button
                  key={name}
                  block
                  variant="secondary"
                  onClick={() => openLink(url)}
                >
                  Открыть в {name}
                </Button>
              ))}
            </>
          )
        }
      >
        {links && (
          <>
            <div className="qr-wrap">
              <QrCode value={links.qr_payload} />
              <div className="tiny muted center">Наведите камеру телефона, чтобы добавить конфиг</div>
            </div>

            <div className="stack stack--sm">
              <div className="row row--between">
                <span className="small muted">Протокол</span>
                <span className="small strong">{links.protocol}</span>
              </div>
              <div className="row row--between">
                <span className="small muted">Сервер</span>
                <span className="small strong mono">
                  {links.host}:{links.port}
                </span>
              </div>
              <div className="row row--between">
                <span className="small muted">SNI</span>
                <span className="small strong mono">{links.server_name}</span>
              </div>
            </div>

            <div className="divider" />
            <div className="tiny muted">Ссылка (никогда не публикуйте её)</div>
            <div className="code-block">{links.link}</div>
            <div className="tiny muted">
              Если конфиг перестал работать — нажмите «Обновить подключение» на главной: сервер
              перезапустится, а конфиг останется прежним.
            </div>
          </>
        )}
      </Sheet>

      {/* Confirm sheet ----------------------------------------------------- */}
      <ConfirmSheet
        open={Boolean(confirm)}
        danger={confirm?.action === 'remove'}
        title={confirm?.action === 'remove' ? 'Отключить устройство?' : 'Обновить конфигурацию?'}
        confirmLabel={confirm?.action === 'remove' ? 'Отключить' : 'Обновить'}
        loading={busyId === confirm?.client.id}
        message={
          confirm?.action === 'remove' ? (
            <>
              Устройство «{confirm.client.label ?? 'без имени'}» перестанет подключаться. Конфигурацию можно
              будет восстановить только выпуском новой.
            </>
          ) : (
            <>Будет выпущен новый ключ, старый перестанет работать. Обновите конфиг в приложении.</>
          )
        }
        onCancel={() => setConfirm(null)}
        onConfirm={() => confirm && void runAction(confirm.client, confirm.action)}
      />
    </>
  )
}
