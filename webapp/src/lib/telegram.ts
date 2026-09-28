/**
 * Telegram Mini App SDK wrapper.
 *
 * Declared locally instead of pulling `telegram-web-app` typings: we only use a
 * small, stable slice of the API and this keeps the dependency tree minimal.
 * When the app runs in a normal browser (dev, preview) every call degrades to a
 * no-op so the UI stays usable for local development.
 */

export interface TelegramThemeParams {
  bg_color?: string
  text_color?: string
  hint_color?: string
  link_color?: string
  button_color?: string
  button_text_color?: string
  secondary_bg_color?: string
  header_bg_color?: string
  accent_text_color?: string
  section_bg_color?: string
  destructive_text_color?: string
  bg_color_dark?: string
  text_color_dark?: string
  hint_color_dark?: string
  link_color_dark?: string
  button_color_dark?: string
  button_text_color_dark?: string
  secondary_bg_color_dark?: string
  section_bg_color_dark?: string
}

export interface TelegramWebAppUser {
  id: number
  first_name?: string
  last_name?: string
  username?: string
  language_code?: string
  is_premium?: boolean
}

export interface TelegramWebApp {
  initData: string
  version: string
  platform: string
  colorScheme: 'light' | 'dark'
  themeParams: TelegramThemeParams
  isExpanded: boolean
  viewportHeight: number
  viewportStableHeight: number
  isClosingConfirmationEnabled: boolean
  ready(): void
  expand(): void
  close(): void
  disableVerticalSwipes?(): void
  requestFullscreen?(): void
  setHeaderColor?(color: string): void
  setBackgroundColor?(color: string): void
  enableClosingConfirmation?(): void
  disableClosingConfirmation?(): void
  onEvent(event: string, handler: () => void): void
  offEvent(event: string, handler: () => void): void
  openLink(url: string, options?: { try_instant_view?: boolean }): void
  openTelegramLink(url: string): void
  showAlert?(message: string, cb?: () => void): void
  showConfirm?(message: string, cb?: (ok: boolean) => void): void
  HapticFeedback?: {
    impactOccurred(style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'): void
    notificationOccurred(type: 'error' | 'success' | 'warning'): void
    selectionChanged(): void
  }
  BackButton?: {
    isVisible: boolean
    show(): void
    hide(): void
    onClick(cb: () => void): void
    offClick(cb: () => void): void
  }
  MainButton?: {
    text: string
    isVisible: boolean
    show(): void
    hide(): void
    setText(text: string): void
    onClick(cb: () => void): void
    offClick(cb: () => void): void
    enable(): void
    disable(): void
    showProgress(leaveActive?: boolean): void
    hideProgress(): void
  }
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp }
  }
}

export const tg: TelegramWebApp | undefined = typeof window !== 'undefined'
  ? window.Telegram?.WebApp
  : undefined

export const isTelegram = Boolean(tg?.initData)

/** Init data is what we hand to the backend for authentication. */
export function getInitData(): string {
  return tg?.initData ?? ''
}

export function getPlatform(): string {
  return tg?.platform ?? 'web'
}

export function haptic(type: 'light' | 'medium' | 'heavy' | 'success' | 'error' | 'warning' | 'select' = 'light') {
  const h = tg?.HapticFeedback
  if (!h) return
  try {
    if (type === 'success' || type === 'error' || type === 'warning') {
      h.notificationOccurred(type)
    } else if (type === 'select') {
      h.selectionChanged()
    } else {
      h.impactOccurred(type)
    }
  } catch {
    /* haptics are best-effort */
  }
}

/** Show the Telegram back button while a modal/screen is pushed. */
export function useBackButton(visible: boolean, onClick?: () => void) {
  if (!tg?.BackButton) return
  const handler = onClick ?? (() => window.history.back())
  try {
    if (visible) {
      tg.BackButton.onClick(handler)
      tg.BackButton.show()
    } else {
      tg.BackButton.offClick(handler)
      tg.BackButton.hide()
    }
  } catch {
    /* ignore */
  }
}

export function openLink(url: string) {
  if (tg?.openLink) tg.openLink(url)
  else window.open(url, '_blank', 'noopener,noreferrer')
}

export function openTelegramLink(url: string) {
  if (tg?.openTelegramLink) tg.openTelegramLink(url)
  else openLink(url)
}

export function closeApp() {
  tg?.close?.()
}

/**
 * Paint Telegram's theme into CSS custom properties.
 * Telegram provides dark/light variants; we pick the set matching colorScheme.
 */
export function applyTheme() {
  const root = document.documentElement
  const params = tg?.themeParams
  if (!params) {
    root.dataset.theme = tg?.colorScheme ?? 'auto'
    return
  }

  const dark = tg?.colorScheme === 'dark'
  const pick = (key: keyof TelegramThemeParams): string | undefined => {
    const value = params[key]
    return typeof value === 'string' && value ? value : undefined
  }

  const map: Record<string, string> = {
    '--tg-bg': pick('bg_color') ?? (dark ? '#0f1720' : '#ffffff'),
    '--tg-text': pick('text_color') ?? (dark ? '#f5f7fa' : '#0f1720'),
    '--tg-hint': pick('hint_color') ?? (dark ? '#8b98a8' : '#707579'),
    '--tg-link': pick('link_color') ?? '#2AABEE',
    '--tg-button': pick('button_color') ?? (dark ? '#3E82AD' : '#2AABEE'),
    '--tg-button-text': pick('button_text_color') ?? '#ffffff',
    '--tg-secondary-bg': pick('secondary_bg_color') ?? (dark ? '#18212c' : '#f2f4f7'),
    '--tg-section-bg': pick('section_bg_color') ?? (dark ? '#141b23' : '#ffffff'),
    '--tg-header-bg': pick('header_bg_color') ?? (dark ? '#0f1720' : '#ffffff'),
    '--tg-accent-text': pick('accent_text_color') ?? (dark ? '#6ab3f3' : '#3a7ca5'),
    '--tg-destructive': pick('destructive_text_color') ?? '#e5484d',
  }

  for (const [key, value] of Object.entries(map)) {
    root.style.setProperty(key, value)
  }
  root.dataset.theme = tg?.colorScheme ?? 'auto'
  root.style.colorScheme = tg?.colorScheme ?? 'light dark'
}

/** Called once at startup: expand, disable swipe-to-close, paint the theme. */
export function initTelegram() {
  if (!tg) {
    document.documentElement.dataset.theme = 'auto'
    return
  }
  try {
    tg.ready()
    tg.expand()
    tg.disableVerticalSwipes?.()
    applyTheme()
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', tg.themeParams.bg_color ?? '#ffffff')
    tg.setHeaderColor?.(tg.themeParams.bg_color ?? '#ffffff')
    tg.setBackgroundColor?.(tg.themeParams.bg_color ?? '#ffffff')
    tg.onEvent('themeChanged', applyTheme)
  } catch {
    /* never let SDK quirks break the app */
  }
}
