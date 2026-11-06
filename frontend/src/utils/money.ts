// Shared money / VAT formatting helpers extracted from the Orders and Dashboard pages.
// Every function preserves the exact behavior of the previous per-page copies —
// including the differing zero rendering (dash vs "0,00 zł"), currency suffix and
// sign handling. Do not "unify" semantics here without checking both pages.

export type MoneyInput = string | number | null | undefined
export type MoneySign = 'plain' | 'plus' | 'minus'
export type ZeroMode = 'dash' | 'zero'

export const VAT_SUFFIX_PLN = 'zł'

// Raw pl-PL number formatting without null/NaN guards.
export function formatNumber(value: number, dec = 2): string {
  return value.toLocaleString('pl-PL', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

// Number formatting with '—' fallback for null/undefined/NaN.
export function f(v: MoneyInput, dec = 2): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return isNaN(n) ? '—' : formatNumber(n, dec)
}

// Lenient coercion used by the money math helpers (null/undefined → 0).
export function num(v: MoneyInput): number {
  return Number(v ?? 0)
}

// Percent formatting: any falsy input renders as '—' (note: '0' stays truthy).
export function pct(v: MoneyInput): string {
  return v ? `${f(v)}%` : '—'
}

export function sumMoney(...values: Array<string | null | undefined>): number {
  return values.reduce((sum, value) => sum + Number(value ?? 0), 0)
}

export function grossToNet23(v: MoneyInput): number {
  const value = num(v)
  return value === 0 ? 0 : value / 1.23
}

export function grossToNetByRate(gross: MoneyInput, vatRate: MoneyInput): number {
  const value = num(gross)
  const rate = num(vatRate)
  return value === 0 ? 0 : value / (1 + rate / 100)
}

export function vatMultiplier(vatRate: MoneyInput): number {
  const rate = num(vatRate)
  return 1 + (Number.isFinite(rate) ? rate : 0) / 100
}

export function visibleUnitCost(netCost: number, vatRate: MoneyInput, showNet: boolean): number {
  return showNet ? netCost : netCost * vatMultiplier(vatRate)
}

// Parses a user-typed ("12,34") visible cost back to net. Returns null when not finite.
export function netCostFromVisible(value: string, vatRate: MoneyInput, showNet: boolean): number | null {
  const parsed = Number(value.replace(',', '.'))
  if (!Number.isFinite(parsed)) return null
  return showNet ? parsed : parsed / vatMultiplier(vatRate)
}

export type MoneyOpts = {
  sign?: MoneySign
  minus?: string   // minus character for sign 'minus' (Orders cost column uses U+2212)
  suffix?: string  // currency suffix, default 'zł'
  zero?: ZeroMode  // zero rendering, default 'dash'
}

// Core money formatter behind pln/fCurrency/neg/pos/profitMoney/costMoney/costPln.
export function money(v: MoneyInput, opts?: MoneyOpts): string {
  const suffix = opts?.suffix ?? VAT_SUFFIX_PLN
  if (v === null || v === undefined || Number(v) === 0) {
    return opts?.zero === 'zero' ? `0,00 ${suffix}` : '—'
  }
  const body = `${f(v)} ${suffix}`
  const sign = opts?.sign ?? 'plain'
  if (sign === 'plus') return `+${body}`
  if (sign === 'minus') return `${opts?.minus ?? '-'}${body}`
  return body
}

export const pln = (v: MoneyInput, zero: ZeroMode = 'dash') => money(v, { zero })
export const fCurrency = (v: MoneyInput, currency: string) => money(v, { suffix: currency })
export const neg = (v: MoneyInput) => money(v, { sign: 'minus' })
export const pos = (v: MoneyInput) => money(v, { sign: 'plus' })
export const profitMoney = (v: MoneyInput, currency = VAT_SUFFIX_PLN) => money(v, { suffix: currency })
export const costMoney = (v: MoneyInput, currency = VAT_SUFFIX_PLN) => money(v, { sign: 'minus', suffix: currency })
export const costPln = (v: MoneyInput) => money(v, { sign: 'minus', minus: '−' })

export type VatMoneyOpts = {
  net?: MoneyInput
  isVatPayer?: boolean
  sign?: MoneySign
  zero?: ZeroMode  // zero rendering; Dashboard pages default to 'dash', Orders overrides to 'zero'
  suffix?: string
}

export type VatMoneyResult = { text: string; title: string | undefined; value: number }

export function vatMoney(gross: MoneyInput, opts?: VatMoneyOpts): VatMoneyResult {
  const suffix = opts?.suffix ?? VAT_SUFFIX_PLN
  const grossValue = num(gross)
  const netValue = opts?.net != null ? num(opts.net) : grossToNet23(gross)
  const visibleValue = opts?.isVatPayer ? netValue : grossValue
  const zeroMode = opts?.zero ?? 'dash'
  const sign = opts?.sign ?? 'plain'
  const zeroText = zeroMode === 'zero' ? `0,00 ${suffix}` : '—'
  let text = zeroText
  if (visibleValue !== 0) {
    const body = `${f(visibleValue)} ${suffix}`
    text = sign === 'plus' ? `+${body}` : sign === 'minus' ? `-${body}` : body
  }
  const title = opts?.isVatPayer && grossValue !== 0 ? `Brutto: ${f(grossValue)} ${suffix}` : undefined
  return { text, title, value: visibleValue }
}

// Refund-style rendering: negative values become '+', zero/positive become '-'.
export function signedVatMoney(
  gross: MoneyInput,
  opts?: { isVatPayer?: boolean; suffix?: string },
): VatMoneyResult {
  const value = num(gross)
  if (value < 0) return vatMoney(Math.abs(value), { isVatPayer: opts?.isVatPayer, sign: 'plus', suffix: opts?.suffix })
  return vatMoney(value, { isVatPayer: opts?.isVatPayer, sign: 'minus', suffix: opts?.suffix })
}
