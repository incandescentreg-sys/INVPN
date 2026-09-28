import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { haptic } from '../lib/telegram'

type ToastTone = 'neutral' | 'success' | 'error'

interface Toast {
  id: number
  text: string
  tone: ToastTone
}

interface ToastApi {
  show: (text: string, tone?: ToastTone) => void
  success: (text: string) => void
  error: (text: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

let counter = 0

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const show = useCallback((text: string, tone: ToastTone = 'neutral') => {
    const id = ++counter
    setToasts((current) => [...current, { id, text, tone }])
    haptic(tone === 'error' ? 'error' : tone === 'success' ? 'success' : 'light')
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id))
    }, 2800)
  }, [])

  const value = useMemo<ToastApi>(
    () => ({
      show,
      success: (text: string) => show(text, 'success'),
      error: (text: string) => show(text, 'error'),
    }),
    [show],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      {toasts.length > 0 && (
        <div className="toasts" role="status" aria-live="polite">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={[
                'toast',
                toast.tone === 'error' && 'toast--error',
                toast.tone === 'success' && 'toast--success',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              {toast.text}
            </div>
          ))}
        </div>
      )}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside <ToastProvider>')
  return context
}
