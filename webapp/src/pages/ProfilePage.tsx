import { useNavigate } from 'react-router-dom'
import { formatDate, formatDateTime, relativeTime } from '../lib/format'
import type { Notification, ProfileResponse } from '../lib/types'
import { useAsync } from '../lib/useAsync'
import { api } from '../lib/api'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card, SectionTitle } from '../components/Card'
import { CardSkeleton, EmptyState } from '../components/Feedback'
import { useAuth } from '../store/auth'
import { openTelegramLink } from '../lib/telegram'

export function ProfilePage() {
  const navigate = useNavigate()
  const { user, isAdmin } = useAuth()
  const { data, loading } = useAsync<ProfileResponse>(() => api.get<ProfileResponse>('/profile'))
  const { data: notifications } = useAsync<Notification[]>(() => api.get<Notification[]>('/notifications'))

  if (loading) return <CardSkeleton rows={3} />

  const unread = notifications?.filter((item) => !item.is_read).length ?? 0

  return (
    <>
      <Card hero>
        <div className="row">
          <div
            className="device__icon"
            style={{ width: 52, height: 52, fontSize: 24, borderRadius: 16 }}
            aria-hidden="true"
          >
            {user?.first_name?.[0] ?? user?.username?.[0] ?? '👤'}
          </div>
          <div className="grow">
            <div className="strong" style={{ fontSize: 17 }}>
              {data?.user.display_name ?? user?.display_name}
            </div>
            <div className="small muted">
              {data?.user.username ? `@${data.user.username}` : `ID ${data?.user.telegram_id ?? ''}`}
            </div>
          </div>
          {isAdmin && <Badge tone="accent">Админ</Badge>}
        </div>

        <div className="divider" />

        <div className="stack stack--sm">
          <div className="row row--between">
            <span className="small muted">Регистрация</span>
            <span className="small">{formatDate(data?.user.created_at)}</span>
          </div>
          <div className="row row--between">
            <span className="small muted">Telegram ID</span>
            <span className="small mono">{data?.user.telegram_id}</span>
          </div>
          {data?.subscription && (
            <div className="row row--between">
              <span className="small muted">Подписка до</span>
              <span className="small strong">{formatDate(data.subscription.expires_at)}</span>
            </div>
          )}
        </div>
      </Card>

      <Card>
        <SectionTitle
          title="Уведомления"
          action={unread > 0 ? <Badge tone="accent">{unread} новых</Badge> : undefined}
        />
        {notifications && notifications.length > 0 ? (
          <div className="stack stack--sm">
            {notifications.slice(0, 8).map((item) => (
              <div key={item.id} className="device">
                <div className="device__icon">
                  {item.kind.includes('expir') ? '⏳' : item.kind.includes('payment') ? '💳' : '🔔'}
                </div>
                <div className="grow">
                  <div className="strong small">{item.title}</div>
                  <div className="tiny muted">{item.body}</div>
                  <div className="tiny muted">{relativeTime(item.created_at)}</div>
                </div>
                {!item.is_read && <span className="status-dot status-dot--up" />}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState icon="🔔" title="Пока пусто" description="Здесь появятся уведомления о подписке" />
        )}
        {notifications && notifications.length > 0 && (
          <Button
            block
            variant="ghost"
            size="sm"
            onClick={async () => {
              await api.post('/notifications/read-all')
              navigate(0)
            }}
          >
            Отметить всё прочитанным
          </Button>
        )}
      </Card>

      <Card>
        <SectionTitle title="Разделы" />
        <div className="stack stack--sm">
          {[
            ['🛒', 'Тарифы и оплата', () => navigate('/plans')],
            ['💳', 'История платежей', () => navigate('/payments')],
            ['📖', 'Инструкция', () => navigate('/instructions')],
            ['🆘', 'Поддержка', () => navigate('/support')],
            ...(isAdmin ? [['⚙️', 'Админ-панель', () => navigate('/admin')] as const] : []),
          ].map(([icon, title, action]) => (
            <button
              key={title as string}
              className="device"
              onClick={action as () => void}
              style={{ textAlign: 'left', width: '100%' }}
            >
              <div className="device__icon">{icon as string}</div>
              <div className="grow strong small">{title as string}</div>
              <span className="muted">›</span>
            </button>
          ))}
        </div>
      </Card>

      <Card flat>
        <div className="stack stack--sm">
          <div className="row row--between">
            <span className="small muted">Версия приложения</span>
            <span className="tiny mono">1.0.0</span>
          </div>
          {data?.support_username && (
            <Button
              block
              size="sm"
              variant="ghost"
              onClick={() =>
                openTelegramLink(
                  `https://t.me/${(data.support_username ?? '').replace('@', '')}`,
                )
              }
            >
              Написать @{data.support_username.replace('@', '')}
            </Button>
          )}
          <div className="tiny muted center">Обновлено {formatDateTime(new Date().toISOString())}</div>
        </div>
      </Card>
    </>
  )
}
