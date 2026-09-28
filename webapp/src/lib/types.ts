/** API types mirroring the backend Pydantic schemas. */

export type SubscriptionStatus = 'pending' | 'active' | 'expired' | 'suspended' | 'cancelled'
export type ClientStatus = 'pending' | 'active' | 'disabled' | 'error'
export type PaymentStatus =
  | 'pending'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'refunded'
  | 'partially_refunded'
export type HealthStatus = 'up' | 'degraded' | 'down' | 'unknown'

export interface User {
  id: string
  telegram_id: number
  username: string | null
  first_name: string | null
  last_name: string | null
  display_name: string
  is_admin: boolean
  is_banned: boolean
  created_at: string
}

export interface AuthResponse {
  user: User
  token: { access_token: string; token_type: string; expires_in: number }
  is_new: boolean
  is_admin: boolean
}

export interface Plan {
  id: string
  code: string
  title: string
  description: string | null
  days: number
  price_kopeks: number
  currency: string
  features: string[]
  badge: string | null
  is_popular: boolean
  is_active: boolean
  sort_order: number
  server_id: string | null
}

export interface Subscription {
  id: string
  status: SubscriptionStatus
  plan_id: string
  plan_title: string
  plan_days: number
  days_left: number
  total_days: number
  progress_percent: number
  started_at: string | null
  expires_at: string | null
  price_paid_kopeks: number | null
  is_expired: boolean
  server_id: string | null
  server_name: string | null
  device_limit: number
  created_at: string
}

export interface SubscriptionSummary {
  id: string
  status: SubscriptionStatus
  plan_title: string
  plan_days: number
  price_kopeks: number | null
  started_at: string | null
  expires_at: string | null
  days_left: number
  progress_percent: number
  is_expired: boolean
  server_id: string | null
  server_name: string | null
}

export interface Payment {
  id: string
  provider: string
  provider_payment_id: string | null
  amount_kopeks: number
  currency: string
  description: string | null
  status: PaymentStatus
  confirmation_url: string | null
  paid_at: string | null
  refunded_kopeks: number
  subscription_id: string | null
  plan_id: string | null
  created_at: string
}

export interface PaymentStatusResponse {
  payment: Payment
  subscription_activated: boolean
  message: string | null
}

export interface CreatePaymentResponse {
  payment: Payment
  confirmation_url: string | null
  redirect_url: string | null
  already_paid: boolean
}

export interface VpnClient {
  id: string
  uuid: string
  email: string
  label: string | null
  status: ClientStatus
  is_primary: boolean
  server_id: string
  server_name: string | null
  created_at: string
  last_synced_at: string | null
  disabled_reason: string | null
}

export interface ClientLinks {
  client_id: string
  label: string
  link: string
  base64_link: string
  qr_payload: string
  deep_links: Record<string, string>
  host: string
  port: number
  server_name: string
  protocol: string
  flow: string
}

export interface VpnClientWithLinks extends VpnClient {
  links: ClientLinks | null
}

export interface VpnState {
  has_access: boolean
  subscription: SubscriptionSummary | null
  primary_client: VpnClientWithLinks | null
  clients: VpnClient[]
  device_limit: { limit: number; used: number; remaining: number | null }
  server: {
    id: string
    name: string
    host: string
    port: number
    healthy: boolean
  } | null
  sync_pending: boolean
  instructions_url: string | null
}

export interface Notification {
  id: string
  kind: string
  title: string
  body: string
  payload: Record<string, unknown> | null
  is_read: boolean
  created_at: string
}

export interface ClientApp {
  id: string
  name: string
  platforms: string[]
  store_url: string | null
  howto: string[]
}

export interface Instructions {
  apps: ClientApp[]
  notes: string[]
  faq: { q: string; a: string }[]
}

export interface SupportInfo {
  username: string | null
  url: string | null
  message: string
}

export interface ProfileResponse {
  user: User
  subscription: SubscriptionSummary | null
  support_username: string | null
}

// ---------------------------------------------------------------- admin ----
export interface AdminStats {
  users: { total: number; new_24h: number; new_7d: number }
  subscriptions: { active: number; expired: number; expiring_soon: number }
  payments: {
    revenue_kopeks: number
    successful: number
    revenue_30d_kopeks: number
    successful_30d: number
    pending: number
    by_day: { date: string; total_kopeks: number; count: number }[]
  }
  vpn: {
    clients_active: number
    clients_total: number
    servers: {
      id: string
      name: string
      active: boolean
      health: HealthStatus
      last_error: string | null
      last_checked_at: string | null
    }[]
  }
}

export interface Page<T> {
  items: T[]
  total?: number
  limit: number
  offset: number
}

export interface AdminServer {
  id: string
  name: string
  is_active: boolean
  weight: number
  max_clients: number
  host: string
  ssh_port: number
  ssh_user: string
  public_host: string
  public_port: number
  xray_config_path: string
  xray_service_name: string
  reality_public_key: string | null
  reality_short_id: string | null
  reality_target: string
  reality_server_names: string
  reality_fingerprint: string
  last_check_status: HealthStatus
  last_check_error: string | null
  last_checked_at: string | null
  xray_synced_at: string | null
  note: string | null
  clients_total?: number
  clients_active?: number
}
