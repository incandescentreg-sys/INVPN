import { useState } from 'react'
import { api } from '../lib/api'
import { openLink } from '../lib/telegram'
import type { Instructions } from '../lib/types'
import { useAsync } from '../lib/useAsync'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card, SectionTitle } from '../components/Card'
import { CardSkeleton, EmptyState } from '../components/Feedback'
import { Sheet } from '../components/Sheet'
import { useToast } from '../store/toast'

const PLATFORM_LABEL: Record<string, string> = {
  android: 'Android',
  ios: 'iOS',
  windows: 'Windows',
  macos: 'macOS',
  linux: 'Linux',
}

export function InstructionsPage() {
  const toast = useToast()
  const { data, loading } = useAsync<Instructions>(() => api.get<Instructions>('/instructions'))
  const [openHowTo, setOpenHowTo] = useState<Instructions['apps'][number] | null>(null)

  if (loading) return <CardSkeleton rows={3} />
  if (!data) return <EmptyState icon="📖" title="Инструкция недоступна" />

  return (
    <>
      <Card hero>
        <div className="stack stack--sm">
          <div className="hero__eyebrow">Инструкция</div>
          <h1 className="hero__title">Как подключиться</h1>
          <p className="hero__subtitle">
            Выберите приложение для вашего устройства и следуйте шагам
          </p>
        </div>
      </Card>

      <div className="stack">
        {data.apps.map((app) => (
          <Card key={app.id} flat>
            <div className="row row--between">
              <div className="grow">
                <div className="strong">{app.name}</div>
                <div className="row" style={{ gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                  {app.platforms.map((platform) => (
                    <Badge key={platform}>{PLATFORM_LABEL[platform] ?? platform}</Badge>
                  ))}
                </div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                <Button size="sm" variant="ghost" onClick={() => setOpenHowTo(app)}>
                  Как
                </Button>
                {app.store_url && (
                  <Button size="sm" onClick={() => openLink(app.store_url!)}>
                    Скачать
                  </Button>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card>
        <SectionTitle title="Проверка подключения" />
        <ol className="stack stack--sm" style={{ paddingLeft: 18, listStyle: 'decimal' }}>
          <li className="small">Включите VPN в приложении</li>
          <li className="small">Откройте <span className="mono">ipinfo.io</span> или <span className="mono">2ip.ru</span></li>
          <li className="small">Убедитесь, что IP принадлежит VPN-серверу</li>
        </ol>
        <Button
          block
          size="sm"
          variant="secondary"
          onClick={() => {
            openLink('https://ipinfo.io')
            toast.show('Открыли проверку IP')
          }}
        >
          Проверить свой IP
        </Button>
      </Card>

      {data.faq.length > 0 && (
        <Card>
          <SectionTitle title="Частые вопросы" />
          <div className="stack stack--sm">
            {data.faq.map((item) => (
              <details key={item.q} className="device">
                <summary className="small strong" style={{ cursor: 'pointer', listStyle: 'none' }}>
                  {item.q}
                </summary>
                <div className="tiny muted" style={{ marginTop: 6 }}>
                  {item.a}
                </div>
              </details>
            ))}
          </div>
        </Card>
      )}

      <Card flat>
        <SectionTitle title="Важно" />
        <div className="stack stack--sm">
          {data.notes.map((note) => (
            <div key={note} className="row" style={{ alignItems: 'flex-start' }}>
              <span style={{ color: 'var(--warning)' }}>⚠️</span>
              <span className="small">{note}</span>
            </div>
          ))}
        </div>
      </Card>

      <Sheet open={Boolean(openHowTo)} title={openHowTo?.name ?? ''} onClose={() => setOpenHowTo(null)}>
        {openHowTo && (
          <>
            <ol className="stack stack--sm" style={{ paddingLeft: 18, listStyle: 'decimal' }}>
              {openHowTo.howto.map((step) => (
                <li key={step} className="small">
                  {step}
                </li>
              ))}
            </ol>
            {openHowTo.store_url && (
              <Button block onClick={() => openLink(openHowTo.store_url!)}>
                Открыть страницу приложения
              </Button>
            )}
          </>
        )}
      </Sheet>
    </>
  )
}
