import { useState } from 'react'
import { api, ApiError } from '../lib/api'
import { openTelegramLink } from '../lib/telegram'
import type { SupportInfo } from '../lib/types'
import { useAsync } from '../lib/useAsync'
import { Button } from '../components/Button'
import { Card, SectionTitle } from '../components/Card'
import { useToast } from '../store/toast'

const TOPICS = [
  { id: 'connect', label: 'Не подключается', icon: '🔌' },
  { id: 'slow', label: 'Медленная скорость', icon: '🐌' },
  { id: 'pay', label: 'Вопрос по оплате', icon: '💳' },
  { id: 'other', label: 'Другое', icon: '💬' },
]

export function SupportPage() {
  const toast = useToast()
  const { data: info } = useAsync<SupportInfo>(() => api.get<SupportInfo>('/support'))
  const [topic, setTopic] = useState(TOPICS[0].id)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)

  const send = async () => {
    if (text.trim().length < 3) {
      toast.error('Опишите проблему подробнее')
      return
    }
    setSending(true)
    try {
      await api.post('/support', { text: `[${TOPICS.find((t) => t.id === topic)?.label}] ${text.trim()}` })
      setText('')
      toast.success('Сообщение отправлено')
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Не удалось отправить')
    } finally {
      setSending(false)
    }
  }

  return (
    <>
      <Card hero>
        <div className="stack stack--sm">
          <div className="hero__eyebrow">Поддержка</div>
          <h1 className="hero__title">Мы на связи</h1>
          <p className="hero__subtitle">{info?.message ?? 'Опишите проблему — поможем быстро'}</p>
        </div>
      </Card>

      {info?.url && (
        <Card>
          <div className="stack stack--sm">
            <div className="row" style={{ gap: 10 }}>
              <span style={{ fontSize: 24 }}>💬</span>
              <div className="grow">
                <div className="strong">Написать в Telegram</div>
                <div className="small muted">@{info.username?.replace('@', '')} · отвечаем быстрее всего</div>
              </div>
            </div>
            <Button block onClick={() => openTelegramLink(info.url!)}>
              Открыть чат
            </Button>
          </div>
        </Card>
      )}

      <Card>
        <SectionTitle title="Описать проблему" />
        <div className="stack">
          <div className="field">
            <span className="field__label">Тема</span>
            <div className="tabs">
              {TOPICS.map((item) => (
                <button
                  key={item.id}
                  className={['tabs__item', topic === item.id && 'tabs__item--active'].filter(Boolean).join(' ')}
                  onClick={() => setTopic(item.id)}
                >
                  {item.icon} {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="support-text">
              Что произошло?
            </label>
            <textarea
              id="support-text"
              className="textarea"
              placeholder="Например: на Android подключается, но через минуту отваливается"
              value={text}
              maxLength={4000}
              onChange={(event) => setText(event.target.value)}
            />
            <span className="tiny muted">{text.length} / 4000</span>
          </div>

          <Button block loading={sending} onClick={() => void send()}>
            Отправить
          </Button>
        </div>
      </Card>

      <Card flat>
        <div className="tiny muted">
          Перед обращением попробуйте «Обновить подключение» в разделе «Мой VPN» — это решает
          большинство проблем с подключением.
        </div>
      </Card>
    </>
  )
}
