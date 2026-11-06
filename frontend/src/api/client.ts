import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { appUrl } from '../config/brand'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const api = axios.create({
  baseURL: apiBaseUrl,
  withCredentials: true,
  headers: { 'X-Requested-With': 'XMLHttpRequest' },
})

api.interceptors.request.use(config => {
  return config
})

interface RetriableRequestConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

export const refreshSession = () => api.post('/auth/refresh')

// Shared in-flight refresh promise so concurrent 401s trigger a single /auth/refresh call.
let refreshing: Promise<unknown> | null = null

api.interceptors.response.use(
  response => response,
  async (error: AxiosError) => {
    const status = error?.response?.status
    const config = error.config as RetriableRequestConfig | undefined
    const url = String(config?.url || '')
    const publicPaths = ['/', '/login', '/admiiii123', '/register', '/security', '/privacy', '/terms', '/regulamin', '/activate', '/pobierz']
    const isPublicPath = publicPaths.includes(window.location.pathname)
    const isRefreshCall = url.includes('/auth/refresh')
    const isLoginCall = url.includes('/auth/login')
    const isMeCall = url.includes('/auth/me')

    if (
      status === 401 &&
      config &&
      !config._retried &&
      !isRefreshCall &&
      !isLoginCall &&
      !isMeCall &&
      !isPublicPath
    ) {
      config._retried = true
      try {
        if (!refreshing) {
          refreshing = refreshSession().finally(() => {
            refreshing = null
          })
        }
        await refreshing
        return api(config)
      } catch {
        // refresh failed – fall through to the redirect below
      }
    }

    if (status === 401 && !isMeCall && !isPublicPath) {
      const loginPath = window.location.pathname.startsWith('/admin') ? '/admiiii123' : '/login'
      window.location.href = appUrl(`${loginPath}?next=${encodeURIComponent(window.location.pathname)}`)
    }
    return Promise.reject(error)
  },
)

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${apiBaseUrl}${normalizedPath}`
}

// ── Accounts ──────────────────────────────────────────────────────────────────
export interface Account {
  id: number; name: string; allegro_client_id: string
  color: string; created_at: string
  token_expires_at: string | null; is_connected: boolean
}
export interface AccountCreate {
  name: string; allegro_client_id: string; allegro_client_secret: string; color: string
}
export const accountsApi = {
  list: () => api.get<Account[]>('/accounts/').then(r => r.data),
  create: (data: AccountCreate) => api.post<Account>('/accounts/', data).then(r => r.data),
  delete: (id: number) => api.delete(`/accounts/${id}`),
}

export interface AppSettings {
  is_vat_payer: boolean
}

export const appSettingsApi = {
  get: () => api.get<AppSettings>('/app-settings/').then(r => r.data),
  update: (data: AppSettings) => api.put<AppSettings>('/app-settings/', data).then(r => r.data),
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
export type PeriodKey =
  | 'today'
  | 'yesterday'
  | 'last_7d'
  | 'last_14d'
  | 'last_30d'
  | 'last_90d'
  | 'current_month'
  | 'last_month'
  | 'previous_month'
  | 'ytd'
  | 'custom'

export interface EncryptedValue {
  ciphertext: string
  nonce: string
  key_version: number
  aad_context: string
}

export interface FinancialVaultStatus {
  configured: boolean
  id?: number
  scope?: string
  kdf?: 'argon2id'
  salt?: string
  memory_cost?: number
  time_cost?: number
  parallelism?: number
  verify_nonce?: string
  verify_ciphertext?: string
  key_version?: number
  encrypted_costs?: number
  encrypted_history?: number
}

export interface FinancialVaultSetup {
  salt: string
  memory_cost: number
  time_cost: number
  parallelism: number
  verify_nonce: string
  verify_ciphertext: string
}

export const financialVaultApi = {
  status: () => api.get<FinancialVaultStatus>('/financial-vault/status').then(r => r.data),
  setup: (data: FinancialVaultSetup) =>
    api.post<FinancialVaultStatus>('/financial-vault/setup', data).then(r => r.data),
}

export interface CryptoProof {
  verifiable: {
    cryptoVersion: string
    sourceRepo: string
    sourceCommit: string
    releaseUrl: string
    bundleSha256: string
    bundleSri: string
    bundleUrl: string
    algorithm: string
    kdf: string
    argon2idParams: {
      memoryCost: number
      timeCost: number
      parallelism: number
    }
    decryptToolUrl: string
    decryptToolSha256: string
  }
  operatorStatement: {
    text: string
    note: string
  }
}

export interface EncryptedCostExport {
  envelope: {
    v: 1
    alg: 'AES-256-GCM'
    kdf: 'argon2id'
    kdfParams: {
      memoryCost: number
      timeCost: number
      parallelism: number
    }
    salt: string
    iv: string
    ct: string
    aad: string
    keyVersion: number
  }
  sku: {
    id: number
    sku_key: string
    name: string
  }
  note: string
}

export const securityApi = {
  cryptoProof: () => api.get<CryptoProof>('/security/crypto-proof').then(r => r.data),
  encryptedCostExport: (skuMasterId: number) =>
    api.get<EncryptedCostExport>(`/security/encrypted-cost-export/${skuMasterId}`).then(r => r.data),
}

// ── Android app download ─────────────────────────────────────────────────────
export interface AppManifest {
  version: string
  filename: string
  size_bytes: number
  sha256: string
  min_android: string
  released_at: string
  notes: string
}

export const appDownloadApi = {
  manifest: () => api.get<AppManifest>('/app/manifest').then(r => r.data),
  downloadUrl: () => buildApiUrl('/app/download'),
}

export interface AuthUser {
  id: number
  email: string
  is_operator: boolean
  tenant_id: number | null
  totp_enrolled: boolean
}

export type LoginResponse =
  | { status: 'ok'; user: AuthUser }
  | { status: 'totp_required' }
  | {
      status: 'totp_enroll_required'
      provisioning_uri: string
      secret: string
      qr_svg: string
      issuer: string
      account_name: string
    }

export type TotpSetupResponse = Extract<LoginResponse, { status: 'totp_enroll_required' }>

export interface WaitlistPayload {
  email: string
  company?: string
  phone?: string
  monthly_orders?: string
  message?: string
  website?: string
  privacy_accepted?: boolean
}

export interface ActivationStatus {
  status: 'valid'
  email: string
  tenant_name: string
  provisioning_uri?: string
  secret?: string
  qr_svg?: string
  expires_at: string
}

export const authApi = {
  me: () => api.get<AuthUser>('/auth/me').then(r => r.data),
  login: (data: { email: string; password: string; totp?: string; remember_device?: boolean }) =>
    api.post<LoginResponse>('/auth/login', data).then(r => r.data),
  enrollTotp: (data: { totp: string }) =>
    api.post<{ status: 'ok'; user: AuthUser }>('/auth/totp/enroll', data).then(r => r.data),
  setupTotp: () => api.post<TotpSetupResponse>('/auth/totp/setup').then(r => r.data),
  disableTotp: (data: { password: string }) =>
    api.post<{ status: 'ok' }>('/auth/totp/disable', data).then(r => r.data),
  logout: () => api.post('/auth/logout'),
  waitlist: (data: WaitlistPayload) =>
    api.post<{ status: 'ok'; activation_email_sent?: boolean }>('/auth/waitlist', data).then(r => r.data),
  activationStatus: (token: string) =>
    api.get<ActivationStatus>(`/auth/activate/${encodeURIComponent(token)}`).then(r => r.data),
  activate: (data: { token: string; password: string; totp?: string; privacy_accepted: boolean }) =>
    api.post<{ status: 'ok' }>('/auth/activate', data).then(r => r.data),
}

export interface DeviceSession {
  id: number
  device_label: string | null
  user_agent: string | null
  app_version: string | null
  ip_created: string | null
  created_at: string
  last_used_at: string | null
  status: string
}

export const devicesApi = {
  list: () => api.get<{ devices: DeviceSession[] }>('/auth/devices').then(r => r.data.devices),
  revoke: (id: number) => api.delete(`/auth/devices/${id}`),
}

export const supportApi = {
  createTicket: (data: { message: string; attachment?: File | null }) => {
    const form = new FormData()
    form.append('message', data.message)
    if (data.attachment) {
      form.append('attachment', data.attachment)
    }
    return api.post<{ status: 'ok' }>('/support/ticket', form).then(r => r.data)
  },
}

export interface AdminWaitlistEntry {
  id: number
  email: string
  company: string | null
  phone: string | null
  monthly_orders: string | null
  message: string | null
  created_at: string | null
  approved_at: string | null
  status: 'pending' | 'approved' | 'rejected'
  notes: string | null
}

export interface AdminTenant {
  id: number
  name: string
  slug: string
  is_active: boolean
  created_at: string | null
  users_count: number
  accounts_count: number
  sku_count: number
  orders_count: number
  current_month: string
  previous_month: string
  current_month_orders: number
  previous_month_orders: number
  last_activity_at: string | null
  billing_scheme: 'legacy_trial' | 'pool_v2' | null
  pool_used: number | null
  pool_remaining: number | null
  active_tier: string | null
  period_end: string | null
}

export interface AdminPricingTier {
  code: string
  label: string
  max_orders: number | null
  price_pln: number
  billing_period: 'year' | 'free'
  is_custom?: boolean
}

export interface AdminRevenueSummary {
  customers_count: number
  billable_customers_count: number
  current_month_orders: number
  previous_month_orders: number
  current_month_estimate_net: string
  previous_month_estimate_net: string
}

export interface AdminRevenueTenant {
  tenant_id: number
  name: string
  slug: string
  is_active: boolean
  created_at: string | null
  trial_ends_at: string | null
  trial_active: boolean | null
  billing_scheme: 'legacy_trial' | 'pool_v2' | null
  annual_subscription_revenue_net: string
  monthly_subscription_revenue_net: string
  paid_plan_accepted: boolean
  current_month_orders: number
  previous_month_orders: number
  current_month_tier: AdminPricingTier
  previous_month_tier: AdminPricingTier
  current_month_estimate_net: string
  previous_month_estimate_net: string
  current_month_billable_days: number
  previous_month_billable_days: number
  current_month_days: number
  previous_month_days: number
}

export interface AdminRevenue {
  annual_subscription_revenue_net: string
  monthly_subscription_revenue_net: string
  current_month: string
  previous_month: string
  pricing_net: boolean
  operator_tenant_excluded: boolean
  paid_invoice_statuses: string[]
  totals: {
    all_customers: AdminRevenueSummary
    active_customers: AdminRevenueSummary
  }
  items: AdminRevenueTenant[]
}

export interface AdminSubscription {
  id: number; tenant_id: number; company_name: string | null; nip: string | null
  tier_code: string; price_pln: number; status: string; invoice_number: string | null
  ifirma_invoice_id: string | null; requested_at: string | null; invoiced_at: string | null
  paid_at: string | null; period_start: string | null; period_end: string | null; cancelled_at: string | null
}

export interface SystemHealth {
  status: 'ok' | 'degraded'
  db_ok: boolean
  tenants_count: number
  users_count: number
  active_sessions: number
  pending_activations: number
  pending_waitlist: number
  last_sync_at: string | null
  checked_at: string
}

export const adminApi = {
  waitlist: (status?: 'pending' | 'approved' | 'rejected') =>
    api.get<{ items: AdminWaitlistEntry[]; total: number }>('/admin/waitlist', { params: { status } }).then(r => r.data),
  approveWaitlist: (entryId: number, data: { tenant_name: string }) =>
    api.post<{
      activation_url: string
      activation_email_sent: boolean
      activation_email_error?: string
      expires_at: string
      tenant_id: number
      tenant_slug: string
    }>(
      `/admin/waitlist/${entryId}/approve`,
      data,
    ).then(r => r.data),
  rejectWaitlist: (entryId: number, data: { reason: string }) =>
    api.post<{ status: 'rejected' }>(`/admin/waitlist/${entryId}/reject`, data).then(r => r.data),
  tenants: () => api.get<{ items: AdminTenant[] }>('/admin/tenants').then(r => r.data),
  subscriptions: (status?: string) => api.get<{ items: AdminSubscription[] }>('/admin/subscriptions', { params: { status: status || undefined } }).then(r => r.data),
  invoiceSubscription: (id: number) => api.post(`/admin/subscriptions/${id}/invoice`).then(r => r.data),
  manualSubscriptionInvoice: (id: number, invoice_number: string) => api.post(`/admin/subscriptions/${id}/manual-invoice`, { invoice_number }).then(r => r.data),
  markSubscriptionPaid: (id: number, paid_on: string) => api.post(`/admin/subscriptions/${id}/mark-paid`, { paid_on }).then(r => r.data),
  cancelSubscription: (id: number) => api.post(`/admin/subscriptions/${id}/cancel`).then(r => r.data),
  revenue: () => api.get<AdminRevenue>('/admin/revenue').then(r => r.data),
  deactivateTenant: (tenantId: number) => api.post<{ status: string }>(`/admin/tenants/${tenantId}/deactivate`).then(r => r.data),
  reactivateTenant: (tenantId: number) => api.post<{ status: string }>(`/admin/tenants/${tenantId}/reactivate`).then(r => r.data),
  hardDeleteTenant: (tenantId: number, slug: string) =>
    api.delete(`/admin/tenants/${tenantId}`, { params: { confirm: true, slug } }),
  systemHealth: () => api.get<SystemHealth>('/admin/system-health').then(r => r.data),
}

export interface PnLSummary {
  period_label: string; date_from: string; date_to: string
  revenue_gross: string; revenue_net: string; sales_gross_value: string; sales_net_value: string
  buyer_shipping_revenue: string; buyer_shipping_revenue_net: string; units_sold: number; orders_count: number
  comparison_label?: string
  comparison_revenue_gross?: string
  comparison_revenue_net?: string
  comparison_delta_value?: string
  comparison_delta_value_net?: string
  comparison_delta_pct?: string | null
  comparison_delta_pct_net?: string | null
  // Allegro costs (positive magnitudes)
  commission_cost: string             // SUC
  featuring_commission_cost: string   // FSF
  ads_cost: string                    // Allegro Ads total
  ads_imported_cost: string           // Allegro Ads IMP
  ads_nsp_adjustment_cost: string     // NSP reconciliation, can be negative
  smart_shipping_cost: string         // Allegro Delivery codes – buyer paid nothing
  smart_forecast_cost: string         // synthetic SMART forecast included in smart_shipping_cost
  shipping_passthrough_cost: string   // HB4/HLB/… where buyer paid delivery – not in profit
  foreign_shipping_cost: string       // HB1/HB8 – buyer passthrough, NOT in profit
  featuring_cost: string              // FEA
  coins_cost: string                  // CPF/RCP – net of coin refunds
  campaign_commission_cost: string    // BRG
  campaign_bonus: string              // CB2
  price_adjust_cost: string           // PS1/PSA – positive rebate
  protect_cost: string                // INS
  local_cost: string                  // ALC/ALS/ALK/ALI/ALL/ALP
  subscription_cost: string           // SB*/SH*/ST*/ILF/ABO
  refund_commission: string           // REF – positive
  fulfillment_base_cost: string       // OFA
  fulfillment_storage_cost: string    // OF1/OFB/OFC/OFD/OFQ/OFR/OFS/OFU/OFZ
  fulfillment_returns_cost: string    // OFE/OFF/OFI
  fulfillment_subscription_cost: string // OFM
  fulfillment_other_cost: string      // SHIPMENT_SURCHARGE + remaining OF*
  fulfillment: string                 // all fulfillment codes
  total_allegro: string               // sum excluding foreign_shipping_cost and shipping_passthrough
  total_allegro_net: string
  ads_cost_source: 'imported' | 'billing' | 'mixed'
  returns_revenue: string
  returns_revenue_net: string
  returns_count: number
  returns_units: number
  returns_goods_value: string
  returns_goods_value_net: string
  returns_refund_value: string
  returns_pending_count: number
  returns_pending_units: number
  returns_rejected_count: number
  returns_rejected_units: number
  neutral_cancelled_orders_count: number
  neutral_cancelled_units: number
  neutral_cancelled_value: string
  commission_refunds_amount: string   // informational: sum of positive SUC/FSF entries
  cogs: string | null; profit_net: string | null
  margin_pct: string | null; roi_pct: string | null
  kp_ratio?: string | null; kcap_ratio?: string | null
}

export interface SummaryComparison {
  comparison_label: string
  comparison_revenue_gross: string
  comparison_revenue_net: string
}

export interface DashboardProductRow {
  sku_id: number; sku_key: string; name: string; sell_price: string; encrypted_cost: EncryptedValue | null; ean: string | null
  cost_multiplier?: string
  vat_rate: string
  units_sold: number; cogs_units?: string; returns_units: number; returns_pending_units: number; returns_rejected_units: number; revenue_gross: string; revenue_net: string
  commission_cost: string; featuring_commission_cost: string
  ads_cost: string; ads_imported_cost: string; ads_nsp_adjustment_cost: string; smart_shipping_cost: string; smart_forecast_cost: string; shipping_passthrough_cost: string
  foreign_shipping_cost: string
  featuring_cost: string; coins_cost: string; campaign_commission_cost: string; campaign_bonus: string; price_adjust_cost: string
  protect_cost: string; local_cost: string; subscription_cost: string
  refund_commission: string; commission_refunds_amount: string; fulfillment: string
  total_allegro: string; total_allegro_net: string; cogs: string | null
  profit_net: string | null; profit_per_unit: string | null
  margin_pct: string | null; roi_pct: string | null
}

export interface ProductDetail {
  sku_id: number; sku_key: string; name: string; sell_price: string; encrypted_cost: EncryptedValue | null; cost_multiplier?: string; ean: string | null; vat_rate: string
  period_label: string; date_from: string; date_to: string
  // Revenue
  revenue_gross: string; revenue_net: string; sales_gross_value: string; sales_net_value: string; units_sold: number; cogs_units?: string
  // Allegro costs (positive magnitudes)
  commission_cost: string             // SUC
  featuring_commission_cost: string   // FSF
  ads_cost: string                    // Allegro Ads total
  ads_imported_cost: string           // Allegro Ads IMP
  ads_nsp_adjustment_cost: string     // NSP reconciliation, can be negative
  smart_shipping_cost: string         // Allegro Delivery codes – buyer paid nothing (proportional)
  smart_forecast_cost: string         // synthetic SMART forecast included above (proportional)
  shipping_passthrough_cost: string   // HB4/HLB/… where buyer paid delivery – not in profit (proportional)
  foreign_shipping_cost: string       // HB1/HB8 – buyer passthrough, NOT in profit
  featuring_cost: string              // FEA (proportional)
  coins_cost: string                  // CPF/RCP – net of coin refunds
  campaign_commission_cost: string    // BRG
  campaign_bonus: string              // CB2
  price_adjust_cost: string           // PS1/PSA – positive rebate
  protect_cost: string                // INS (proportional)
  local_cost: string                  // ALC/ALS/ALK/ALI/ALL/ALP (proportional)
  subscription_cost: string           // SB*/SH*/ST*/ILF/ABO (proportional)
  refund_commission: string           // REF – positive
  fulfillment_base_cost: string       // OFA (proportional)
  fulfillment_storage_cost: string    // OF1/OFB/OFC/OFD/OFQ/OFR/OFS/OFU/OFZ (proportional)
  fulfillment_returns_cost: string    // OFE/OFF/OFI (proportional)
  fulfillment_subscription_cost: string // OFM (proportional)
  fulfillment_other_cost: string      // SHIPMENT_SURCHARGE + remaining OF* (proportional)
  fulfillment: string                 // all fulfillment codes
  total_allegro_net: string
  // Returns / placeholders
  returns_revenue: string; returns_revenue_net: string; returns_goods_value: string; returns_goods_value_net: string; returns_count: number; returns_units: number; returns_refund_value: string
  returns_pending_count: number; returns_pending_units: number; returns_rejected_count: number; returns_rejected_units: number
  commission_refunds_amount: string; transaction_fee: string
  // COGS
  cogs: string | null
  // Results
  profit_net: string | null; margin_pct: string | null; roi_pct: string | null
  kp_ratio?: string | null; kcap_ratio?: string | null
}

// ── Billing / Subscription ───────────────────────────────────────────────────
export interface BillingProfile {
  company_name: string | null
  nip: string | null
  regon: string | null
  krs: string | null
  street: string | null
  postal_code: string | null
  city: string | null
  country: string
  invoice_email: string | null
  vat_status: string | null
  fetched_from_vat_api_at?: string | null
  updated_at?: string | null
}

export interface PricingTier {
  code: string
  label: string
  max_orders: number | null
  price_pln: number
  billing_period: 'year' | 'free'
  is_custom?: boolean
}

export interface TenantInvoice {
  id: number
  number: string
  period_month: string
  issue_date: string | null
  due_date: string | null
  amount_net: string
  amount_gross: string
  currency: string
  status: string
  pdf_url: string | null
}

export interface SubscriptionUsage {
  scheme: 'legacy_trial' | 'pool_v2'; pool_total: number; pool_used: number; pool_remaining: number
  pool_active: boolean; month: string; month_orders: number; monthly_limit: number | null
  over_limit: boolean
  active_subscription: { tier_code: string; period_start: string; period_end: string } | null
  pending_subscription: { id: number; tier_code: string; status: 'pending_invoice' | 'invoiced'; invoice_number: string | null } | null
  upgrade_suggested: boolean; suggested_tier_code: string | null
}

export interface SubscriptionStatus {
  billing_scheme: 'legacy_trial' | 'pool_v2' | null
  usage: SubscriptionUsage | null
  trial_started_at: string | null
  trial_ends_at: string | null
  trial_active: boolean | null
  terms_version: string
  paid_plan_accepted: boolean
  imports_paused: boolean
  current_month: string
  current_month_orders: number
  previous_month: string
  previous_month_orders: number
  current_tier: PricingTier
  pricing: PricingTier[]
  invoices: TenantInvoice[]
}

export const billingApi = {
  profile: () => api.get<BillingProfile>('/billing/profile').then(r => r.data),
  updateProfile: (data: BillingProfile) => api.put<BillingProfile>('/billing/profile', data).then(r => r.data),
  vatLookup: (nip: string) => api.get<BillingProfile>(`/billing/vat-lookup/${encodeURIComponent(nip)}`).then(r => r.data),
  subscription: () => api.get<SubscriptionStatus>('/billing/subscription').then(r => r.data),
  requestSubscription: (tier_code: string, terms_version: string) => api.post<{ id: number; status: string; tier_code: string; price_pln: number }>('/billing/subscription/request', { tier_code, terms_version }).then(r => r.data),
  cancelSubscription: (id: number) => api.post(`/billing/subscription/${id}/cancel`).then(r => r.data),
  acceptPaidPlan: (data: { terms_accepted: boolean; terms_version: string }) =>
    api.post<{ paid_plan_accepted: boolean; terms_version: string; accepted_at: string | null }>(
      '/billing/paid-plan/accept',
      data,
    ).then(r => r.data),
}

export const dashboardApi = {
  summaryAll: (accountId?: number, currency = 'PLN', search?: string, periods?: PeriodKey[]) =>
    api.get<Record<string, PnLSummary>>('/dashboard/summary/all', {
      params: {
        ...(accountId ? { account_id: accountId } : {}),
        currency,
        ...(search ? { search } : {}),
        ...(periods?.length ? { periods: periods.join(',') } : {}),
      }
    }).then(r => r.data),
  summaryComparisons: (accountId?: number, currency = 'PLN', search?: string, periods?: PeriodKey[]) =>
    api.get<Record<string, SummaryComparison>>('/dashboard/summary/comparisons', {
      params: {
        ...(accountId ? { account_id: accountId } : {}),
        currency,
        ...(search ? { search } : {}),
        ...(periods?.length ? { periods: periods.join(',') } : {}),
      }
    }).then(r => r.data),
  summaryCustom: (dateFrom: string, dateTo: string, accountId?: number, currency = 'PLN', search?: string) =>
    api.get<PnLSummary>('/dashboard/summary', {
      params: {
        period: 'custom',
        date_from: dateFrom,
        date_to: dateTo,
        currency,
        ...(accountId ? { account_id: accountId } : {}),
        ...(search ? { search } : {}),
      }
    }).then(r => r.data),
  summaryDaily: (dateFrom: string, dateTo: string, accountId?: number, currency = 'PLN', search?: string) =>
    api.get<Record<string, PnLSummary>>('/dashboard/summary/daily', {
      params: {
        date_from: dateFrom,
        date_to: dateTo,
        currency,
        ...(accountId ? { account_id: accountId } : {}),
        ...(search ? { search } : {}),
      }
    }).then(r => r.data),
  products: (period: PeriodKey, accountId?: number, search?: string, currency = 'PLN', dateFrom?: string, dateTo?: string) =>
    api.get<DashboardProductRow[]>('/dashboard/products', {
      params: {
        period,
        currency,
        ...(accountId ? { account_id: accountId } : {}),
        ...(search ? { search } : {}),
        ...(dateFrom ? { date_from: dateFrom } : {}),
        ...(dateTo ? { date_to: dateTo } : {}),
      }
    }).then(r => r.data),
  productDetail: (skuKey: string, period: PeriodKey, accountId?: number, currency = 'PLN', dateFrom?: string, dateTo?: string) =>
    api.get<ProductDetail>('/dashboard/product-detail', {
      params: {
        sku_key: skuKey,
        period,
        currency,
        ...(accountId ? { account_id: accountId } : {}),
        ...(dateFrom ? { date_from: dateFrom } : {}),
        ...(dateTo ? { date_to: dateTo } : {}),
      }
    }).then(r => r.data),
}

// ── Products / SKU management ─────────────────────────────────────────────────
export interface CostHistoryEntry {
  id: number; encrypted_cost: EncryptedValue | null; valid_from: string; valid_to: string | null; note: string | null
}
export interface ProductManageRow {
  id: number; sku_key: string; name: string
  encrypted_cost: EncryptedValue | null; vat_rate: string; target_margin_pct: string
  offer_ids?: string[]; eans?: string[]
  cost_history: CostHistoryEntry[]
}
export interface SkuPatch {
  encrypted_cost?: EncryptedValue; history_encrypted_cost?: EncryptedValue
  vat_rate?: string; target_margin_pct?: string; name?: string
}
export interface CostHistoryCreate {
  encrypted_cost: EncryptedValue; current_encrypted_cost: EncryptedValue
  valid_from: string; valid_to?: string; note?: string
}
export interface ImportCostsResult {
  updated: number; not_found: string[]
}

export const productsApi = {
  list: (accountId?: unknown) => {
    const id = typeof accountId === 'number' ? accountId : undefined
    return api.get<ProductManageRow[]>('/products/', { params: id ? { account_id: id } : undefined }).then(r => r.data)
  },
  patch: (id: number, data: SkuPatch) =>
    api.patch<ProductManageRow>(`/products/${id}`, data).then(r => r.data),
  addCostHistory: (id: number, data: CostHistoryCreate) =>
    api.post<ProductManageRow>(`/products/${id}/cost-history`, data).then(r => r.data),
  deleteCostHistory: (skuId: number, histId: number, currentEncryptedCost?: EncryptedValue) =>
    api.delete(`/products/${skuId}/cost-history/${histId}`, {
      data: currentEncryptedCost ? { current_encrypted_cost: currentEncryptedCost } : undefined,
    }),
  importCosts: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<ImportCostsResult>('/products/import-costs', fd).then(r => r.data)
  },
  autoImport: (accountId: number) =>
    api.post<{ added: number; skipped: number; no_sku: number }>(
      `/sku/auto-import/${accountId}`
    ).then(r => r.data),
}

// ── Stock ─────────────────────────────────────────────────────────────────────
export interface StockRow {
  sku_id: number; sku_key: string; name: string
  quantity: number; updated_at: string | null; updated_by: string; sync_from_allegro: boolean
  sold_15d: number; sold_30d: number; sold_90d: number
  avg_daily: number; days_left: number | null
}
export interface StockSettings { threshold_critical: number; threshold_warning: number }
export interface StockUpdatePayload { quantity: number; sync_from_allegro?: boolean }
export interface StockUpdateResult { sku_id: number; quantity: number; updated_by: string; updated_at: string; sync_from_allegro: boolean }
export interface StockAutoImportResult { added: number; imported: number; accounts: number }
export const stockApi = {
  list: (accountId?: unknown) => {
    const id = typeof accountId === 'number' ? accountId : undefined
    return api.get<StockRow[]>('/stock/', { params: id ? { account_id: id } : undefined }).then(r => r.data)
  },
  getSettings: () => api.get<StockSettings>('/stock/settings').then(r => r.data),
  updateSettings: (data: StockSettings) => api.put<StockSettings>('/stock/settings', data).then(r => r.data),
  update: async (skuId: number, data: StockUpdatePayload): Promise<StockUpdateResult> => {
    const r = await api.put<StockUpdateResult>(`/stock/${skuId}`, data); return r.data
  },
  autoImport: async (): Promise<StockAutoImportResult> => {
    const r = await api.post<StockAutoImportResult>('/stock/auto-import'); return r.data
  },
}

// ── Orders (per-order P&L diagnostic) ─────────────────────────────────────────
export interface OrderLineItem {
  line_item_id: string; sku: string | null; sku_id: number | null; sku_name: string
  offer_id: string | null; quantity: number
  vat_rate: string
  unit_price: string; revenue: string
  encrypted_cost: EncryptedValue | null; cogs: string | null
}
export interface OrderCostBreakdown { type: string; type_name: string; amount: string }
export interface RecentOrder {
  order_id: string; bought_at: string | null; buyer_login: string | null
  status: string | null; account_id: number; account_name: string | null
  items: OrderLineItem[]
  revenue: string; cogs: string | null; costs_total: string; smart_cost: string
  revenue_net: string; costs_total_net?: string; smart_cost_net?: string
  profit_net: string | null; margin_pct: string | null
  costs: OrderCostBreakdown[]
  entries_count: number; exact_match_count: number
}
export const ordersApi = {
  recent: (limit = 100, accountId?: number, smartOnly = false) =>
    api.get<RecentOrder[]>('/orders/recent', {
      params: {
        limit,
        account_id: accountId,
        ...(smartOnly ? { smart_only: true } : {}),
      },
    }).then(r => r.data),
}

// ── Import ────────────────────────────────────────────────────────────────────
export interface SyncResult {
  account_id: number; account_name: string
  orders_count: number; billing_count: number; offers_count: number
  days_fetched: number; synced_at: string; error: string | null
}
export interface LastSync {
  synced_at: string | null; days_fetched: number | null
  orders_count: number; billing_count: number; offers_count: number; error: string | null
}
export interface AccountSyncStatus {
  account_id: number; account_name: string; color: string
  is_connected: boolean; last_sync: LastSync | null
}
export const importApi = {
  sync: (accountId: number, days = 90) =>
    api.post<SyncResult>(`/import/sync/${accountId}?days=${days}`).then(r => r.data),
  status: () => api.get<AccountSyncStatus[]>('/import/status').then(r => r.data),
}

// ── Ads Import ────────────────────────────────────────────────────────────────
export interface AdsImportResult {
  rows_parsed: number
  rows_imported: number
  rows_skipped: number
  unmatched_offers: string[]
  date_range: { from: string; to: string } | null
  total_cost: string
}
export interface AdsImportListEntry {
  imported_filename: string
  imported_at: string | null
  date_from: string
  date_to: string
  rows_count: number
  total_cost: string
}
export interface AdsDeleteResult {
  deleted: number
  date_from: string
  date_to: string
}
// ── SKU Multiplier Patterns ───────────────────────────────────────────────────
export interface SkuMultiplierPattern {
  id: number
  pattern_regex: string
  multiplier: string
  description: string | null
  priority: number
  enabled: boolean
  created_at: string
  updated_at: string
}
export interface PatternCreate {
  pattern_regex: string
  multiplier: number
  description?: string
  priority?: number
  enabled?: boolean
}
export interface PatternUpdate {
  pattern_regex?: string
  multiplier?: number
  description?: string | null
  priority?: number
  enabled?: boolean
}
export interface TestPatternRequest {
  pattern_regex: string
  sample_offer_names: string[]
}
export interface TestPatternResultItem {
  offer_name: string
  matched: boolean
  captured_group: string | null
}
export interface ReapplyResult {
  updated_count: number
  unchanged_count: number
}
export interface UnmatchedOffer {
  offer_id: string
  name: string
  sku: string | null
}
export const skuMappingApi = {
  list: () => api.get<SkuMultiplierPattern[]>('/sku-mapping/patterns').then(r => r.data),
  create: (data: PatternCreate) =>
    api.post<SkuMultiplierPattern>('/sku-mapping/patterns', data).then(r => r.data),
  update: (id: number, data: PatternUpdate) =>
    api.patch<SkuMultiplierPattern>(`/sku-mapping/patterns/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/sku-mapping/patterns/${id}`),
  test: (data: TestPatternRequest) =>
    api.post<TestPatternResultItem[]>('/sku-mapping/test', data).then(r => r.data),
  reapply: () => api.post<ReapplyResult>('/sku-mapping/reapply').then(r => r.data),
  unmatchedOffers: (limit = 5) =>
    api.get<UnmatchedOffer[]>('/sku-mapping/unmatched-offers', { params: { limit } }).then(r => r.data),
}

export const adsImportApi = {
  upload: (accountId: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<AdsImportResult>(`/ads-import/${accountId}`, fd).then(r => r.data)
  },
  list: (accountId: number) =>
    api.get<AdsImportListEntry[]>(`/ads-import/${accountId}/list`).then(r => r.data),
  delete: (accountId: number, dateFrom: string, dateTo: string) =>
    api.delete<AdsDeleteResult>(`/ads-import/${accountId}`, {
      params: { date_from: dateFrom, date_to: dateTo },
    }).then(r => r.data),
}
