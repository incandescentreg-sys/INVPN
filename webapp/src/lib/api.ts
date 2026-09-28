/** API client: one place that knows the base URL, auth header and error shape. */

import { getInitData } from './telegram'

const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, '') ?? ''

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get isAuth(): boolean {
    return this.status === 401
  }

  get isForbidden(): boolean {
    return this.status === 403
  }
}

let accessToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** Skip the Authorization header (used by the auth endpoints). */
  anonymous?: boolean
  timeoutMs?: number
}

const DEFAULT_TIMEOUT = 20_000

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, anonymous, timeoutMs = DEFAULT_TIMEOUT, headers, ...rest } = options

  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)

  const finalHeaders: Record<string, string> = {
    Accept: 'application/json',
    ...((headers as Record<string, string>) ?? {}),
  }
  if (body !== undefined) finalHeaders['Content-Type'] = 'application/json'
  if (!anonymous && accessToken) finalHeaders['Authorization'] = `Bearer ${accessToken}`
  // The API also accepts raw initData, which keeps the very first request
  // (before the token exists) working.
  if (!anonymous && !accessToken) {
    const initData = getInitData()
    if (initData) finalHeaders['X-Telegram-Init-Data'] = initData
  }

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...rest,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })

    if (response.status === 204) return undefined as T

    const isJson = response.headers.get('content-type')?.includes('application/json')
    const payload = isJson ? await response.json().catch(() => null) : null

    if (!response.ok) {
      const message =
        (payload && (payload.detail || payload.error)) || `Ошибка ${response.status}`
      if (response.status === 401) onUnauthorized?.()
      throw new ApiError(String(message), response.status, payload?.code ?? 'error')
    }

    return payload as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if ((error as Error).name === 'AbortError') {
      throw new ApiError('Сервер не отвечает. Проверьте соединение.', 0, 'timeout')
    }
    throw new ApiError('Нет связи с сервером', 0, 'network')
  } finally {
    window.clearTimeout(timer)
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export const API_BASE = BASE_URL
