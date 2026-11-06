import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, ChevronDown, ChevronUp, ChevronRight, Search, X, ChevronsUpDown, Info, PieChart, Download, Columns3 } from 'lucide-react'
import { dashboardApi, accountsApi, productsApi, type PeriodKey, type PnLSummary, type DashboardProductRow, type ProductDetail } from '../api/client'
import { useFinancialVault } from '../context/FinancialVaultContext'
import { useFinancialDisplayMode } from '../context/FinancialDisplayModeContext'
import { computeFinancials, decryptCost, encryptCost, skuCostAad, skuCostHistoryAad } from '../crypto/financialVault'
import { waitForBrowserIdle, yieldToBrowser } from '../utils/browserYield'
import { EmptyDashboard } from '../components/EmptyDashboard'
import {
  f, pct, neg, sumMoney, profitMoney, costMoney, grossToNet23, num,
  visibleUnitCost, netCostFromVisible, vatMoney, signedVatMoney,
} from '../utils/money'

// ── Formatting ────────────────────────────────────────────────────────────────
// Money/VAT formatters are shared — see utils/money (behavior preserved 1:1,
// including the Dashboard default of rendering zero amounts as '—').
type FinancialProductRow = DashboardProductRow & { cost_per_unit?: string }
type DecryptProgress = { label: string; done: number; total: number } | null
type FinancialSummaryCache = { cacheKey: string; value: PnLSummary }
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const
const EMPTY_PRODUCTS: DashboardProductRow[] = []
const profitLabel = (showNet: boolean) => showNet ? 'Zysk netto' : 'Zysk brutto'
const profitPerUnitLabel = (showNet: boolean) => showNet ? 'Zysk netto / szt.' : 'Zysk brutto / szt.'

const neutralAllegroCost = (netCost: string | number | null | undefined) => num(netCost)
const neutralAllegroAdjustment = (grossAdjustment: string | number | null | undefined) => grossToNet23(grossAdjustment)
const ADS_IMP_INFO = 'Koszt Allegro Ads z zaimportowanego pliku statystyk ofert. To jest podstawowe źródło przypisania kosztu reklamy do konkretnych ofert/SKU.'
const ADS_NSP_INFO = 'Korekta Allegro Ads z billing API (NSP), która wyrównuje import IMP do kosztu widocznego w API. Wartość dodatnia oznacza brakujący koszt z API względem importu; wartość ujemna oznacza, że import jest wyższy niż NSP.'

function toLocalIsoDate(dateValue: Date) {
  const d = new Date(dateValue)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}

function formatShortDate(dateIso: string) {
  return new Date(`${dateIso}T12:00:00`).toLocaleDateString('pl-PL', { day: 'numeric', month: 'short' })
}

// ── Period config ─────────────────────────────────────────────────────────────
const PERIODS: { key: PeriodKey; label: string; color: string; bg: string; border: string; ring: string }[] = [
  { key: 'today',          label: 'Dzisiaj',           color: 'text-finance-blue',  bg: 'bg-white',          border: 'border-slate-200',       ring: 'ring-blue-200' },
  { key: 'yesterday',      label: 'Wczoraj',           color: 'text-sky-700',       bg: 'bg-white',          border: 'border-slate-200',       ring: 'ring-sky-200' },
  { key: 'current_month',  label: 'Bieżący miesiąc',   color: 'text-finance-green', bg: 'bg-white',          border: 'border-slate-200',       ring: 'ring-emerald-200' },
  { key: 'previous_month', label: 'Poprzedni miesiąc', color: 'text-emerald-700',   bg: 'bg-white',          border: 'border-slate-200',       ring: 'ring-emerald-200' },
  { key: 'last_7d',        label: 'Ostatnie 7 dni',    color: 'text-cyan-700',      bg: 'bg-white',          border: 'border-slate-200',       ring: 'ring-cyan-200' },
  { key: 'last_14d',       label: 'Ostatnie 14 dni',   color: 'text-violet-700',    bg: 'bg-white',          border: 'border-slate-200',       ring: 'ring-violet-200' },
  { key: 'last_30d',       label: 'Ostatnie 30 dni',   color: 'text-amber-700',     bg: 'bg-white',          border: 'border-slate-200',       ring: 'ring-amber-200' },
  { key: 'last_90d',       label: 'Ostatnie 90 dni',   color: 'text-rose-700',      bg: 'bg-white',          border: 'border-slate-200',       ring: 'ring-rose-200' },
]

type TileView = 'default' | 'rolling' | 'custom'

const TILE_VIEW_PERIODS: Record<Exclude<TileView, 'custom'>, PeriodKey[]> = {
  default: ['today', 'yesterday', 'current_month', 'previous_month'],
  rolling: ['last_7d', 'last_14d', 'last_30d', 'last_90d'],
}

async function decryptProductRows(
  rows: DashboardProductRow[],
  key: CryptoKey,
  isVatPayer: boolean,
  onProgress?: (done: number, total: number) => void,
  shouldCancel?: () => boolean,
): Promise<FinancialProductRow[]> {
  const next: FinancialProductRow[] = []
  const total = rows.length
  onProgress?.(0, total)
  for (let i = 0; i < rows.length; i += 1) {
    if (shouldCancel?.()) return next
    const p = rows[i]
    const rawUnitCost = await decryptCost(key, p.encrypted_cost)
    const costMultiplier = Number(p.cost_multiplier ?? 1)
    const unitCost = rawUnitCost == null ? null : rawUnitCost * (Number.isFinite(costMultiplier) && costMultiplier > 0 ? costMultiplier : 1)
    if (shouldCancel?.()) return next
    const unitCostForMode = unitCost == null ? null : visibleUnitCost(unitCost, p.vat_rate, isVatPayer)
    const revenue = isVatPayer ? Number(p.revenue_net) : Number(p.revenue_gross)
    const totalAllegro = neutralAllegroCost(p.total_allegro_net)
    const priceAdjust = neutralAllegroAdjustment(p.price_adjust_cost)
    const campaignBonus = neutralAllegroAdjustment(p.campaign_bonus)
    const refundCommission = neutralAllegroAdjustment(p.refund_commission)
    const commissionRefunds = neutralAllegroAdjustment(p.commission_refunds_amount)
    const metrics = computeFinancials({
      revenue,
      units: p.units_sold,
      costUnits: Number(p.cogs_units ?? p.units_sold),
      unitCost: unitCostForMode,
      totalAllegro,
      priceAdjust,
      campaignBonus,
      refundCommission,
      commissionRefunds,
    })
    next.push({
      ...p,
      cost_per_unit: unitCostForMode == null ? undefined : String(unitCostForMode),
      cogs: metrics.cogs == null ? null : String(metrics.cogs),
      profit_net: metrics.profit == null ? null : String(metrics.profit),
      profit_per_unit: metrics.profitPerUnit == null ? null : String(metrics.profitPerUnit),
      margin_pct: metrics.marginPct == null ? null : String(metrics.marginPct),
      roi_pct: metrics.roiPct == null ? null : String(metrics.roiPct),
    })
    if ((i + 1) % 10 === 0 || i + 1 === total) onProgress?.(i + 1, total)
    if ((i + 1) % 5 === 0) await yieldToBrowser()
  }
  return next
}

async function buildFinancialSummary(
  summary: PnLSummary,
  rows: DashboardProductRow[],
  key: CryptoKey,
  isVatPayer: boolean,
  onProgress?: (done: number, total: number) => void,
  shouldCancel?: () => boolean,
): Promise<PnLSummary> {
  const financialRows = await decryptProductRows(rows, key, isVatPayer, onProgress, shouldCancel)
  const cogs = financialRows.reduce((sum, r) => sum + Number(r.cogs ?? 0), 0)
  const profit = financialRows.reduce((sum, r) => sum + Number(r.profit_net ?? 0), 0)
  const revenue = isVatPayer ? Number(summary.revenue_net) : Number(summary.revenue_gross)
  const totalAllegro = neutralAllegroCost(summary.total_allegro_net)
  return {
    ...summary,
    cogs: String(cogs),
    profit_net: String(profit),
    margin_pct: revenue > 0 ? String((profit / revenue) * 100) : null,
    roi_pct: cogs > 0 ? String((profit / cogs) * 100) : null,
    kp_ratio: revenue > 0 ? String((cogs / revenue) * 100) : null,
    kcap_ratio: revenue > 0 ? String(((cogs + totalAllegro) / revenue) * 100) : null,
  }
}

function financialSummaryCacheKey(
  period: string,
  summary: PnLSummary,
  accountId: number | undefined,
  currency: string,
  search: string,
  isVatPayer: boolean,
) {
  return [
    period,
    accountId ?? 'all',
    currency,
    search || '',
    isVatPayer ? 'net' : 'gross',
    summary.date_from,
    summary.date_to,
    summary.revenue_gross,
    summary.revenue_net,
    summary.total_allegro,
    summary.total_allegro_net,
    summary.price_adjust_cost,
    summary.campaign_bonus,
    summary.refund_commission,
    summary.commission_refunds_amount,
    summary.returns_goods_value,
    summary.comparison_delta_value,
    summary.comparison_delta_pct,
  ].map(value => value ?? '').join('|')
}

function mergeLatestComparison(financial: PnLSummary | undefined, latest: PnLSummary | undefined) {
  if (!financial) return undefined
  if (!latest) return financial
  if (!latest.comparison_label && latest.comparison_delta_pct == null && latest.comparison_delta_pct_net == null) {
    return financial
  }
  return {
    ...financial,
    comparison_label: latest.comparison_label,
    comparison_revenue_gross: latest.comparison_revenue_gross,
    comparison_revenue_net: latest.comparison_revenue_net,
    comparison_delta_value: latest.comparison_delta_value,
    comparison_delta_value_net: latest.comparison_delta_value_net,
    comparison_delta_pct: latest.comparison_delta_pct,
    comparison_delta_pct_net: latest.comparison_delta_pct_net,
  }
}

function DecryptProgressBar({ progress }: { progress: DecryptProgress }) {
  if (!progress) return null
  const pctDone = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 100
  return (
    <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5">
      <div className="flex items-center justify-between text-xs mb-1.5">
        <span className="text-blue-800">{progress.label}</span>
        <span className="text-blue-700 tabular-nums">{pctDone}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-blue-100">
        <div className="h-full bg-finance-blue transition-all duration-150" style={{ width: `${pctDone}%` }} />
      </div>
    </div>
  )
}

// ── Summary tile ──────────────────────────────────────────────────────────────
function SummaryTile({
  cfg, data, selected, onClick, currency, isVatPayer,
}: {
  cfg: typeof PERIODS[0]; data: PnLSummary | undefined; selected: boolean; onClick: () => void; currency: string; isVatPayer: boolean
}) {
  const loading = !data
  const profit = Number(data?.profit_net ?? 0)
  const profitColor = profit > 0 ? 'text-finance-green' : profit < 0 ? 'text-finance-red' : 'text-slate-500'
  const cur = (gross: string | null | undefined, net?: string | null | undefined) =>
    vatMoney(gross, { net, isVatPayer, suffix: currency }).text
  const negCur = (gross: string | null | undefined, net?: string | null | undefined) =>
    vatMoney(gross, { net, isVatPayer, sign: 'minus', suffix: currency }).text
  const comparePct = Number((isVatPayer ? data?.comparison_delta_pct_net : data?.comparison_delta_pct) ?? 0)
  const compareColor = comparePct > 0 ? 'text-finance-green' : comparePct < 0 ? 'text-finance-red' : 'text-slate-500'
  const comparisonTitle = data?.comparison_label
    ? `${data.comparison_label}: ${
        vatMoney(
          data.comparison_delta_value,
          { net: data.comparison_delta_value_net, isVatPayer, suffix: currency },
        ).text
      }`
    : undefined

  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-w-0 rounded-lg border p-4 text-left transition-all select-none
        ${cfg.bg} ${cfg.border}
        ${selected ? `ring-2 ${cfg.ring} shadow-panel` : 'shadow-sm hover:border-slate-300 hover:shadow-panel'}`}
    >
      <div className="flex items-center justify-between mb-3">
        <span className={`text-[11px] font-semibold uppercase tracking-wide ${cfg.color}`}>{cfg.label}</span>
        {data?.comparison_label ? (
          <span className={`text-[11px] font-semibold tabular-nums ${compareColor}`} title={comparisonTitle}>
            {comparePct > 0 ? '+' : ''}{pct(isVatPayer ? data.comparison_delta_pct_net : data.comparison_delta_pct)}
          </span>
        ) : selected
          ? <ChevronUp size={14} className="text-slate-400" />
          : <span className="text-slate-400 text-[11px]">Więcej</span>}
      </div>

      {loading ? (
        <div className="space-y-2 animate-pulse">
          {[...Array(5)].map((_, i) => <div key={i} className="h-3 bg-slate-700 rounded" />)}
        </div>
      ) : (
        <>
          {/* Całkowita Sprzedaż */}
          <div className="mb-3">
            <p className="text-slate-500 text-xs mb-0.5">Całkowita sprzedaż</p>
            <p
              className="text-slate-950 text-xl font-bold tabular-nums"
              title={vatMoney(data!.revenue_gross, { isVatPayer, suffix: currency }).title}
            >
              {cur(data!.revenue_gross, data!.revenue_net)}
            </p>
            <p className="text-slate-500 text-xs">{data!.orders_count} zamówień · {data!.units_sold} szt.</p>
            {data?.comparison_label && (
              <p
                className={`mt-1 text-[11px] ${compareColor}`}
                title={comparisonTitle}
              >
                Sprzedaż {comparePct > 0 ? '+' : ''}{pct(isVatPayer ? data.comparison_delta_pct_net : data.comparison_delta_pct)}
                <span className="text-slate-400"> · {data.comparison_label}</span>
              </p>
            )}
          </div>
          {/* Mini grid */}
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
            <div>
              <p className="text-slate-500">Zwroty</p>
              <p
                className="text-slate-400"
                title={vatMoney(data!.returns_revenue, { isVatPayer, suffix: currency }).title}
              >
                {negCur(data!.returns_revenue, data!.returns_revenue_net)}
              </p>
            </div>
            <div>
              <p className="text-slate-500">Koszt reklam</p>
              <p
                className="text-finance-red"
                title={vatMoney(data!.ads_cost, { isVatPayer, suffix: currency }).title}
              >
                {negCur(data!.ads_cost)}
              </p>
            </div>
            <div>
              <p className="text-slate-500">{profitLabel(isVatPayer)}</p>
              <p className={`font-semibold ${profitColor}`}>{profitMoney(data!.profit_net, currency)}</p>
            </div>
            <div>
              <p className="text-slate-500">Marża</p>
              <p className={`font-semibold ${profitColor}`}>{pct(data!.margin_pct)}</p>
            </div>
          </div>
        </>
      )}
    </button>
  )
}

// ── Accordion row ─────────────────────────────────────────────────────────────
type SubItem = { label: string; value: string; code?: string; title?: string; info?: string }
type RowKind = 'pos' | 'neg' | 'info'

const KIND_COLOR: Record<RowKind, string> = {
  pos: 'text-finance-green',
  neg: 'text-finance-red',
  info: 'text-slate-500',
}

function AccordionRow({ label, value, kind, subs, title }: {
  label: ReactNode; value: string; kind: RowKind; subs?: SubItem[]; title?: string
}) {
  const [open, setOpen] = useState(false)
  const isZero = value === '—'
  const valColor = isZero ? 'text-slate-400' : KIND_COLOR[kind]

  if (!subs) {
    return (
      <div className="flex justify-between items-center gap-2 text-xs py-1 pl-4">
        <span className={`min-w-0 ${isZero ? 'text-slate-400' : 'text-slate-600'}`}>{label}</span>
        <span className={`shrink-0 font-mono tabular-nums ${valColor}`} title={title}>{value}</span>
      </div>
    )
  }

  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex justify-between items-center gap-2 rounded-md px-2 py-1 text-xs group hover:bg-white"
      >
        <span className="flex min-w-0 items-center gap-1 text-left">
          <ChevronRight
            size={11}
            className={`flex-shrink-0 transition-transform duration-150 text-slate-400 group-hover:text-slate-700
              ${open ? 'rotate-90' : ''}`}
          />
          <span className={`min-w-0 ${isZero ? 'text-slate-400' : 'text-slate-700'} group-hover:text-slate-950 transition-colors`}>
            {label}
          </span>
        </span>
        <span className={`shrink-0 font-mono tabular-nums ${valColor}`} title={title}>{value}</span>
      </button>

      {open && (
        <div className="ml-5 mt-0.5 mb-1 border-l border-slate-200 pl-3 space-y-0.5">
          {subs.map(s => {
            const subZero = s.value === '—'
            return (
              <div key={s.label} className="flex justify-between items-center gap-2 text-xs">
                <span className={`min-w-0 ${subZero ? 'text-slate-300' : 'text-slate-500'}`}>
                  {s.label}
                  {s.code && <span className="text-slate-300 ml-1 font-mono text-[10px]">({s.code})</span>}
                  {s.info && (
                    <span className="ml-1 inline-flex align-[-2px] text-slate-300 hover:text-slate-500" title={s.info}>
                      <Info size={10} />
                    </span>
                  )}
                </span>
                <span
                  className={`shrink-0 font-mono tabular-nums ${subZero ? 'text-slate-300' : KIND_COLOR[kind]}`}
                  title={s.title}
                >
                  {s.value}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Expanded detail panel ─────────────────────────────────────────────────────
function DetailPanel({ data, color, isVatPayer }: { data: PnLSummary; color: string; isVatPayer: boolean }) {
  const requiredCosts = sumMoney(data.commission_cost)
  const deliveryCosts = sumMoney(data.smart_shipping_cost)
  const smartForecastCosts = sumMoney(data.smart_forecast_cost)
  const actualSmartCosts = Math.max(0, deliveryCosts - smartForecastCosts)
  const promotionCosts = sumMoney(
    data.featuring_commission_cost,
    data.featuring_cost,
    data.campaign_commission_cost,
    data.ads_cost,
    data.coins_cost,
  )
  const allegroRebates = sumMoney(data.price_adjust_cost, data.campaign_bonus, data.refund_commission, data.commission_refunds_amount)
  const accountCosts = sumMoney(data.protect_cost, data.local_cost, data.subscription_cost)
  const buyerShippingCosts = sumMoney(data.foreign_shipping_cost, data.shipping_passthrough_cost)
  const neutralCancelledInfo = sumMoney(data.neutral_cancelled_value)

  return (
    <div className="apos-panel mt-4 p-5">
      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">

        {/* P&L breakdown with accordion */}
        <div>
          <p className={`text-xs font-semibold uppercase tracking-wide mb-3 ${color}`}>
            Rozkład wyniku — {data.period_label}
            <span className="ml-2 font-normal normal-case text-slate-400 tracking-normal" title="Koszty zamówień (wysyłka, prowizje, monety, wyrównania) atrybuowane do daty zakupu. Subskrypcje, kampanie i opłaty konta — do daty obciążenia.">
              <Info size={11} className="inline mb-0.5 text-slate-400" />
            </span>
          </p>
          <div className="space-y-1 rounded-lg border border-slate-200 bg-slate-50/70 p-3">

            {/* 1. Sprzedaż */}
            <AccordionRow
              label={isVatPayer ? 'Sprzedaż netto' : 'Sprzedaż brutto'}
              value={vatMoney(data.revenue_gross, { net: data.revenue_net, isVatPayer }).text}
              title={vatMoney(data.revenue_gross, { isVatPayer }).title}
              kind="pos"
              subs={[
                { label: 'Sprzedaż', value: vatMoney(data.sales_gross_value, { net: data.sales_net_value, isVatPayer, sign: 'plus' }).text, title: vatMoney(data.sales_gross_value, { isVatPayer }).title },
                { label: 'Zwroty', value: vatMoney(data.returns_goods_value, { net: data.returns_goods_value_net, isVatPayer, sign: 'minus' }).text, title: vatMoney(data.returns_goods_value, { isVatPayer }).title },
                { label: 'Przychody od klienta za dostawę', value: vatMoney(data.buyer_shipping_revenue, { net: data.buyer_shipping_revenue_net, isVatPayer, sign: 'plus' }).text, title: vatMoney(data.buyer_shipping_revenue, { isVatPayer }).title },
              ]}
            />

            {/* 2. Obowiązkowe */}
            <AccordionRow
              label="Obowiązkowe"
              value={vatMoney(String(requiredCosts), { isVatPayer, sign: 'minus' }).text}
              title={vatMoney(String(requiredCosts), { isVatPayer }).title}
              kind="neg"
              subs={[
                { label: 'Prowizja od sprzedaży', value: vatMoney(data.commission_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.commission_cost, { isVatPayer }).title, code: 'SUC' },
              ]}
            />

            {/* 3. Koszty Allegro Smart */}
            <AccordionRow
              label="Koszty Allegro Smart"
              value={vatMoney(String(deliveryCosts), { isVatPayer, sign: 'minus' }).text}
              title={vatMoney(String(deliveryCosts), { isVatPayer }).title}
              kind="neg"
              subs={[
                { label: 'Smart Prognoza', value: vatMoney(String(smartForecastCosts), { isVatPayer, sign: 'minus' }).text, title: vatMoney(String(smartForecastCosts), { isVatPayer }).title, code: 'SMART' },
                { label: 'Dopłata do Allegro Smart', value: vatMoney(String(actualSmartCosts), { isVatPayer, sign: 'minus' }).text, title: vatMoney(String(actualSmartCosts), { isVatPayer }).title, code: 'Delivery Smart' },
              ]}
            />

            {/* 4. Reklama i promowanie */}
            <AccordionRow
              label="Reklama i promowanie"
              value={vatMoney(String(promotionCosts), { isVatPayer, sign: 'minus' }).text}
              title={vatMoney(String(promotionCosts), { isVatPayer }).title}
              kind="neg"
              subs={[
                { label: 'Prowizja od sprzedaży oferty wyróżnionej', value: vatMoney(data.featuring_commission_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.featuring_commission_cost, { isVatPayer }).title, code: 'FSF' },
                { label: 'Opłata za wyróżnienie', value: vatMoney(data.featuring_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.featuring_cost, { isVatPayer }).title, code: 'FEA' },
                { label: 'Prowizja kampanii', value: vatMoney(data.campaign_commission_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.campaign_commission_cost, { isVatPayer }).title, code: 'BRG' },
                {
                  label: 'Allegro Ads IMP',
                  value: vatMoney(data.ads_imported_cost, { isVatPayer, sign: 'minus' }).text,
                  title: vatMoney(data.ads_imported_cost, { isVatPayer }).title,
                  code: 'IMP',
                  info: ADS_IMP_INFO,
                },
                {
                  label: 'Allegro Ads NSP',
                  value: signedVatMoney(data.ads_nsp_adjustment_cost, { isVatPayer }).text,
                  title: signedVatMoney(data.ads_nsp_adjustment_cost, { isVatPayer }).title,
                  code: 'NSP',
                  info: ADS_NSP_INFO,
                },
                { label: 'Monety', value: vatMoney(data.coins_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.coins_cost, { isVatPayer }).title, code: 'CPF/RCP' },
              ]}
            />

            {/* 5. Rabaty od Allegro */}
            <AccordionRow
              label="Rabaty od Allegro"
              value={vatMoney(String(allegroRebates), { isVatPayer, sign: 'plus' }).text}
              title={vatMoney(String(allegroRebates), { isVatPayer }).title}
              kind="pos"
              subs={[
                { label: 'Allegro Ceny', value: vatMoney(data.price_adjust_cost, { isVatPayer, sign: 'plus' }).text, title: vatMoney(data.price_adjust_cost, { isVatPayer }).title, code: 'PS1/PSA' },
                { label: 'Bonus kampanii', value: vatMoney(data.campaign_bonus, { isVatPayer, sign: 'plus' }).text, title: vatMoney(data.campaign_bonus, { isVatPayer }).title, code: 'CB2' },
                { label: 'Zwrot prowizji', value: vatMoney(data.refund_commission, { isVatPayer, sign: 'plus' }).text, title: vatMoney(data.refund_commission, { isVatPayer }).title, code: 'REF' },
                { label: 'Zwrot prowizji po zwrocie', value: vatMoney(data.commission_refunds_amount, { isVatPayer, sign: 'plus' }).text, title: vatMoney(data.commission_refunds_amount, { isVatPayer }).title, code: 'SUC/FSF' },
              ]}
            />

            {/* 6. Zwroty */}
            <AccordionRow
              label="Zwroty"
              value={vatMoney(data.returns_goods_value, { net: data.returns_goods_value_net, isVatPayer, sign: 'minus' }).text}
              title={vatMoney(data.returns_goods_value, { isVatPayer }).title}
              kind="info"
              subs={[
                { label: 'Przyznane zgłoszenia', value: data.returns_count > 0 ? String(data.returns_count) : '—' },
                { label: 'Przyznane sztuki', value: data.returns_units > 0 ? String(data.returns_units) : '—' },
                { label: 'W trakcie zgłoszenia', value: data.returns_pending_count > 0 ? String(data.returns_pending_count) : '—' },
                { label: 'W trakcie sztuki', value: data.returns_pending_units > 0 ? String(data.returns_pending_units) : '—' },
                { label: 'Odrzucone zgłoszenia', value: data.returns_rejected_count > 0 ? String(data.returns_rejected_count) : '—' },
                { label: 'Odrzucone sztuki', value: data.returns_rejected_units > 0 ? String(data.returns_rejected_units) : '—' },
              ]}
            />

            {/* 7. Fulfillment */}
            <AccordionRow
              label="Fulfillment"
              value={vatMoney(data.fulfillment, { isVatPayer, sign: 'minus' }).text}
              title={vatMoney(data.fulfillment, { isVatPayer }).title}
              kind="neg"
              subs={[
                { label: 'Opłata podstawowa', value: vatMoney(data.fulfillment_base_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.fulfillment_base_cost, { isVatPayer }).title, code: 'OFA' },
                { label: 'Magazynowanie', value: vatMoney(data.fulfillment_storage_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.fulfillment_storage_cost, { isVatPayer }).title, code: 'OF1/OFB/OFC/OFD/OFQ/OFR/OFS/OFU/OFZ' },
                { label: 'Obsługa zwrotów', value: vatMoney(data.fulfillment_returns_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.fulfillment_returns_cost, { isVatPayer }).title, code: 'OFE/OFF/OFI' },
                { label: 'Subskrypcja', value: vatMoney(data.fulfillment_subscription_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.fulfillment_subscription_cost, { isVatPayer }).title, code: 'OFM' },
                { label: 'Opłaty dodatkowe', value: vatMoney(data.fulfillment_other_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.fulfillment_other_cost, { isVatPayer }).title, code: 'SHIPMENT_SURCHARGE/pozostałe OF*' },
              ]}
            />

            {/* 8. Opłaty konta */}
            <AccordionRow
              label="Opłaty konta"
              value={vatMoney(String(accountCosts), { isVatPayer, sign: 'minus' }).text}
              title={vatMoney(String(accountCosts), { isVatPayer }).title}
              kind="neg"
              subs={[
                { label: 'Allegro Protect', value: vatMoney(data.protect_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.protect_cost, { isVatPayer }).title, code: 'INS' },
                { label: 'Dopłata lokalna', value: vatMoney(data.local_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.local_cost, { isVatPayer }).title, code: 'ALC/ALS/ALK/ALI/ALL/ALP' },
                { label: 'Abonament', value: vatMoney(data.subscription_cost, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.subscription_cost, { isVatPayer }).title, code: 'SB*/SH*/ST*/ILF/ABO' },
              ]}
            />

            {/* COGS — no subs */}
            <AccordionRow label="Koszt sprzedanych produktów" value={neg(data.cogs)} kind="neg" />

            {/* 9. Neutralne anulacje — visually distinct */}
            <div className="mt-2 pt-2 border-t border-slate-200">
              <AccordionRow
                label="Neutralne anulacje / nieopłacone"
                value={vatMoney(String(neutralCancelledInfo), { isVatPayer, sign: 'minus' }).text}
                title={vatMoney(String(neutralCancelledInfo), { isVatPayer }).title}
                kind="info"
                subs={[
                  { label: 'Anulowane zamówienia', value: data.neutral_cancelled_orders_count > 0 ? String(data.neutral_cancelled_orders_count) : '—' },
                  { label: 'Sztuki', value: data.neutral_cancelled_units > 0 ? String(data.neutral_cancelled_units) : '—' },
                  { label: 'Wartość zamówień', value: vatMoney(data.neutral_cancelled_value, { isVatPayer, sign: 'minus' }).text, title: vatMoney(data.neutral_cancelled_value, { isVatPayer }).title },
                ]}
              />
              <p className="text-[10px] text-slate-400 pl-4 mt-0.5 italic">
                Wartości kontrolne — nie wliczane do przychodu, kosztów ani zwrotów klasycznych.
              </p>
            </div>

            {/* 10. Koszty ponoszone przez kupującego — visually distinct */}
            <div className="mt-2 pt-2 border-t border-slate-200">
              <AccordionRow
                label="Koszty dostaw rozliczane przez Allegro"
                value={neg(String(buyerShippingCosts))}
                kind="info"
                subs={[
                  { label: 'Dostawy klienta rozliczane przez Allegro', value: neg(data.shipping_passthrough_cost), code: 'HB4/HLB/…' },
                  { label: 'Dostawy zagraniczne rozliczane przez Allegro', value: neg(data.foreign_shipping_cost), code: 'HB1/HB8' },
                ]}
              />
              <p className="text-[10px] text-slate-400 pl-4 mt-0.5 italic">
                Wartości informacyjne — nie wliczane do zysku; nie obejmują kosztów dostaw rozliczanych poza Allegro.
              </p>
            </div>

            {/* Profit total */}
            <div className="border-t border-slate-300 mt-2 pt-3 flex justify-between items-center gap-2">
              <span className="min-w-0 text-slate-950 text-sm font-semibold">{profitLabel(isVatPayer)}</span>
              <span className={`shrink-0 font-mono font-bold text-sm ${Number(data.profit_net) >= 0 ? 'text-finance-green' : 'text-finance-red'}`}>
                {f(data.profit_net)} zł
              </span>
            </div>
          </div>
        </div>

        {/* KPIs */}
        <div>
          <p className={`text-xs font-semibold uppercase tracking-wide mb-3 ${color}`}>Wskaźniki</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {([
              ['Marża', pct(data.margin_pct)],
              ['ROI', pct(data.roi_pct)],
              ['Zamówienia', String(data.orders_count)],
              ['Sztuki', String(data.units_sold)],
            ] as [string, string][]).map(([label, val]) => (
              <div key={label} className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm">
                <p className="text-slate-500 text-xs">{label}</p>
                <p className="text-slate-950 font-semibold text-sm">{val}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Charts ───────────────────────────────────────────────────────────────────
type ChartSummaryPoint = {
  key: string
  label: string
  summary?: PnLSummary
}

const visibleRevenue = (summary: PnLSummary, isVatPayer: boolean) =>
  isVatPayer ? num(summary.revenue_net) : num(summary.revenue_gross)

const visibleCost = (gross: string | number | null | undefined, isVatPayer: boolean) =>
  grossToNet23(gross)

const compactMoney = (value: number, currency: string) => {
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${f(value / 1_000_000, 1)} mln ${currency}`
  if (abs >= 10_000) return `${f(value / 1_000, 0)} tys. ${currency}`
  if (abs >= 1_000) return `${f(value / 1_000, 1)} tys. ${currency}`
  return `${f(value, 0)} ${currency}`
}

function PeriodComparisonChart({
  points,
  isVatPayer,
  currency,
}: {
  points: ChartSummaryPoint[]
  isVatPayer: boolean
  currency: string
}) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)
  const rows = points
    .filter(point => point.summary)
    .map(point => {
      const summary = point.summary!
      return {
        ...point,
        revenue: visibleRevenue(summary, isVatPayer),
        profit: num(summary.profit_net),
        margin: num(summary.margin_pct),
      }
    })

  const width = 540
  const height = 218
  const plot = { left: 44, top: 18, width: 456, height: 132 }
  const revenueMax = Math.max(0, ...rows.map(row => row.revenue), 1)
  const revenueMin = Math.min(0, ...rows.map(row => row.revenue))
  const revenueSpan = Math.max(revenueMax - revenueMin, 1)
  const profitMin = Math.min(0, ...rows.map(row => row.profit))
  const profitMax = Math.max(0, ...rows.map(row => row.profit))
  const profitSpan = Math.max(profitMax - profitMin, 1)
  const x = (index: number) => plot.left + (rows.length <= 1 ? plot.width / 2 : (index / (rows.length - 1)) * plot.width)
  const yRevenue = (value: number) => plot.top + plot.height - ((value - revenueMin) / revenueSpan) * plot.height
  const yProfit = (value: number) => plot.top + plot.height - ((value - profitMin) / profitSpan) * plot.height
  const pathFor = (field: 'revenue') =>
    rows.map((row, index) => `${index === 0 ? 'M' : 'L'} ${x(index).toFixed(1)} ${yRevenue(row[field]).toFixed(1)}`).join(' ')
  const profitZeroY = yProfit(0)
  const step = rows.length <= 1 ? plot.width : plot.width / (rows.length - 1)
  const profitBarWidth = Math.max(3, Math.min(34, step - 1, Math.max(8, step * 0.56)))
  const showPointLabel = (index: number) => rows.length <= 10 || index === 0 || index === rows.length - 1 || index % 5 === 0
  // On narrow screens (~390px) all labels of a ≤10-point chart overlap — keep first/last and every other one.
  const hideLabelOnMobile = (index: number) =>
    rows.length > 6 && rows.length <= 10 && index % 2 === 1 && index !== rows.length - 1
  const showCards = rows.length <= 10
  const hoveredRow = rows.find(row => row.key === hoveredKey)
  const hoveredIndex = hoveredRow ? rows.findIndex(row => row.key === hoveredRow.key) : -1
  const tooltipX = hoveredIndex >= 0 ? Math.min(width - 176, Math.max(8, x(hoveredIndex) - 82)) : 0
  const tooltipY = hoveredRow ? Math.max(8, Math.min(yRevenue(hoveredRow.revenue), yProfit(hoveredRow.profit)) - 72) : 0

  return (
    <section className="apos-panel overflow-hidden p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Activity size={15} className="text-finance-blue" />
            <h3 className="text-sm font-semibold text-slate-950">Porównanie okresów</h3>
          </div>
          <p className="mt-1 text-xs text-slate-500">Ostatnie 30 dni z realnych danych sprzedaży i kosztów.</p>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <span className="inline-flex items-center gap-1 text-slate-500"><i className="h-2 w-2 rounded-full bg-finance-blue" />Sprzedaż</span>
          <span className="inline-flex items-center gap-1 text-slate-500"><i className="h-2 w-2 rounded-sm bg-finance-green" />Zysk (osobna skala)</span>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="flex h-52 items-center justify-center rounded-lg border border-dashed border-slate-200 text-sm text-slate-400">
          Brak danych do wykresu.
        </div>
      ) : (
        <>
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="h-56 w-full"
            role="img"
            aria-label="Porównanie sprzedaży i zysku netto"
            onMouseLeave={() => setHoveredKey(null)}
          >
            {[0, 1, 2, 3].map(i => {
              const gy = plot.top + (plot.height / 3) * i
              return <line key={i} x1={plot.left} x2={plot.left + plot.width} y1={gy} y2={gy} stroke="#e2e8f0" strokeWidth="1" />
            })}
            {profitMin < 0 && profitMax > 0 && (
              <line x1={plot.left} x2={plot.left + plot.width} y1={profitZeroY} y2={profitZeroY} stroke="#94a3b8" strokeDasharray="4 5" />
            )}
            {rows.map((row, index) => {
              const profitY = yProfit(row.profit)
              const barTop = Math.min(profitY, profitZeroY)
              const barHeight = Math.max(Math.abs(profitZeroY - profitY), 2)
              return (
                <rect
                  key={`${row.key}-profit`}
                  x={x(index) - profitBarWidth / 2}
                  y={barTop}
                  width={profitBarWidth}
                  height={barHeight}
                  rx="4"
                  fill={row.profit >= 0 ? '#059669' : '#dc2626'}
                  opacity="0.86"
                />
              )
            })}
            <path d={pathFor('revenue')} fill="none" stroke="#2563eb" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
            {rows.map((row, index) => (
              <g key={row.key}>
                <circle cx={x(index)} cy={yRevenue(row.revenue)} r="4" fill="#2563eb" />
                {showPointLabel(index) && (
                  <g className={hideLabelOnMobile(index) ? 'max-sm:hidden' : undefined}>
                    <text x={x(index)} y="178" textAnchor="middle" className="fill-slate-500 text-[10px] font-medium">{row.label}</text>
                    <text x={x(index)} y="196" textAnchor="middle" className="fill-slate-900 text-[10px] font-semibold">
                      {compactMoney(row.revenue, currency)}
                    </text>
                  </g>
                )}
              </g>
            ))}
            {hoveredRow && hoveredIndex >= 0 && (
              <g pointerEvents="none">
                <line
                  x1={x(hoveredIndex)}
                  x2={x(hoveredIndex)}
                  y1={plot.top}
                  y2={plot.top + plot.height}
                  stroke="#94a3b8"
                  strokeDasharray="3 4"
                />
                <circle cx={x(hoveredIndex)} cy={yRevenue(hoveredRow.revenue)} r="5.5" fill="#2563eb" stroke="white" strokeWidth="2" />
                <circle cx={x(hoveredIndex)} cy={yProfit(hoveredRow.profit)} r="5.5" fill={hoveredRow.profit >= 0 ? '#059669' : '#dc2626'} stroke="white" strokeWidth="2" />
                <rect x={tooltipX} y={tooltipY} width="164" height="64" rx="8" fill="#0f172a" opacity="0.96" />
                <text x={tooltipX + 10} y={tooltipY + 16} className="fill-white text-[10px] font-semibold">{hoveredRow.label}</text>
                <text x={tooltipX + 10} y={tooltipY + 29} className="fill-blue-200 text-[10px]">
                  Sprzedaż: {compactMoney(hoveredRow.revenue, currency)}
                </text>
                <text x={tooltipX + 10} y={tooltipY + 42} className={hoveredRow.profit >= 0 ? 'fill-emerald-200 text-[10px]' : 'fill-red-200 text-[10px]'}>
                  Zysk: {compactMoney(hoveredRow.profit, currency)}
                </text>
                <text x={tooltipX + 10} y={tooltipY + 55} className={hoveredRow.profit >= 0 ? 'fill-emerald-200 text-[10px]' : 'fill-red-200 text-[10px]'}>
                  Marża {pct(String(hoveredRow.margin))}
                </text>
              </g>
            )}
            {rows.map((row, index) => (
              <rect
                key={`${row.key}-hit`}
                x={x(index) - step / 2}
                y={0}
                width={step}
                height={height}
                fill="transparent"
                className="cursor-crosshair"
                onMouseEnter={() => setHoveredKey(row.key)}
                onMouseMove={() => setHoveredKey(row.key)}
                onFocus={() => setHoveredKey(row.key)}
              >
                <title>{`${row.label}: sprzedaż ${compactMoney(row.revenue, currency)}, zysk ${compactMoney(row.profit, currency)}, marża ${pct(String(row.margin))}`}</title>
              </rect>
            ))}
            <text x="0" y={plot.top + 4} className="fill-slate-400 text-[10px]">{compactMoney(revenueMax, currency)}</text>
            <text x={plot.left + plot.width + 8} y={plot.top + 4} className="fill-finance-green text-[10px]">
              {compactMoney(profitMax, currency)}
            </text>
            {profitMin < 0 && (
              <text x={plot.left + plot.width + 8} y={plot.top + plot.height} className="fill-finance-red text-[10px]">
                {compactMoney(profitMin, currency)}
              </text>
            )}
          </svg>

          {showCards ? (
            <div className="grid gap-2 md:grid-cols-5">
              {rows.map(row => (
                <div
                  key={row.key}
                  className="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-left"
                >
                  <p className="text-[11px] font-medium text-slate-500">{row.label}</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums text-slate-950">{compactMoney(row.profit, currency)}</p>
                  <p className={`text-[11px] ${row.margin >= 0 ? 'text-finance-green' : 'text-finance-red'}`}>Marża {pct(String(row.margin))}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-[11px] text-slate-500">
              <span>{rows[0]?.label} - {rows[rows.length - 1]?.label}</span>
              <span className="tabular-nums">Każdy punkt = 1 dzień</span>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function CostStructureChart({
  summary,
  isVatPayer,
  currency,
}: {
  summary: PnLSummary
  isVatPayer: boolean
  currency: string
}) {
  const categories = [
    { label: 'Towar', value: Math.max(0, num(summary.cogs)), color: '#f59e0b' },
    {
      label: 'Prowizje',
      value: Math.max(0, visibleCost(sumMoney(summary.commission_cost, summary.featuring_commission_cost, summary.campaign_commission_cost), isVatPayer)),
      color: '#ef4444',
    },
    { label: 'Reklamy', value: Math.max(0, visibleCost(summary.ads_cost, isVatPayer)), color: '#2563eb' },
    { label: 'Smart i fulfillment', value: Math.max(0, visibleCost(sumMoney(summary.smart_shipping_cost, summary.fulfillment), isVatPayer)), color: '#7c3aed' },
    {
      label: 'Pozostałe',
      value: Math.max(0, visibleCost(sumMoney(summary.featuring_cost, summary.coins_cost, summary.protect_cost, summary.local_cost, summary.subscription_cost), isVatPayer)),
      color: '#64748b',
    },
  ].filter(item => item.value > 0.005)
  const total = categories.reduce((sum, item) => sum + item.value, 0)
  const radius = 54
  const circumference = 2 * Math.PI * radius
  let offset = 0

  return (
    <section className="apos-panel p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <PieChart size={15} className="text-finance-amber" />
            <h3 className="text-sm font-semibold text-slate-950">Struktura kosztów</h3>
          </div>
          <p className="mt-1 text-xs text-slate-500">Aktywny okres: {summary.period_label}</p>
        </div>
        <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-500">
          {compactMoney(total, currency)}
        </span>
      </div>

      {total <= 0 ? (
        <div className="flex h-52 items-center justify-center rounded-lg border border-dashed border-slate-200 text-sm text-slate-400">
          Brak kosztów do pokazania.
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-[170px_1fr] md:items-center">
          <div className="relative mx-auto h-40 w-40">
            <svg viewBox="0 0 140 140" className="h-40 w-40 -rotate-90">
              <circle cx="70" cy="70" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="16" />
              {categories.map(item => {
                const length = (item.value / total) * circumference
                const dashOffset = offset
                offset += length
                return (
                  <circle
                    key={item.label}
                    cx="70"
                    cy="70"
                    r={radius}
                    fill="none"
                    stroke={item.color}
                    strokeWidth="16"
                    strokeDasharray={`${length} ${circumference - length}`}
                    strokeDashoffset={-dashOffset}
                  />
                )
              })}
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="text-[11px] font-medium text-slate-500">Koszty</span>
              <span className="text-sm font-bold text-slate-950">{compactMoney(total, currency)}</span>
            </div>
          </div>

          <div className="space-y-2">
            {categories.map(item => {
              const share = total > 0 ? (item.value / total) * 100 : 0
              return (
                <div key={item.label} className="grid grid-cols-[92px_1fr_74px] items-center gap-2 text-xs">
                  <span className="flex min-w-0 items-center gap-2 text-slate-600">
                    <i className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="truncate" title={item.label}>{item.label}</span>
                  </span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                    <span className="block h-full rounded-full" style={{ width: `${share}%`, backgroundColor: item.color }} />
                  </span>
                  <span className="text-right font-mono tabular-nums text-slate-500">{f(share, 1)}%</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}

// ── Product detail side panel ─────────────────────────────────────────────────
// ── P&L Modal helpers ─────────────────────────────────────────────────────────
/** Flat P&L row — plain line or indented sub-item */
function PnLLine({ label, code, val, cl, sub = false, title, info }: {
  label: string; code?: string; val: string; cl: string; sub?: boolean; title?: string; info?: string
}) {
  return (
    <div className={`flex items-baseline justify-between py-[3px] ${sub ? 'pl-5' : ''}`}>
      <span className={`text-xs leading-relaxed min-w-0 break-words ${sub ? 'text-slate-500' : 'text-slate-300'}`}>
        {sub && <span className="text-slate-700 mr-1 select-none">└</span>}
        {label}
        {code && <span className="text-[10px] font-mono text-slate-700 ml-1.5">{code}</span>}
        {info && (
          <span className="ml-1 inline-flex align-[-2px] text-slate-600 hover:text-slate-400" title={info}>
            <Info size={10} />
          </span>
        )}
      </span>
      <span className={`text-xs font-mono tabular-nums ml-4 shrink-0 ${cl}`} title={title}>{val}</span>
    </div>
  )
}

/** Accordion section with optional sub-items */
function PnLSection({ label, code, val, cl, children, title }: {
  label: string; code?: string; val: string; cl: string; children: React.ReactNode; title?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-baseline justify-between py-[3px] group"
      >
        <span className="text-xs text-slate-300 group-hover:text-white transition-colors flex items-center gap-1 min-w-0">
          <ChevronRight
            size={10}
            className={`shrink-0 text-slate-600 group-hover:text-slate-400 transition-transform duration-150 ${open ? 'rotate-90' : ''}`}
          />
          {label}
          {code && <span className="text-[10px] font-mono text-slate-700">{code}</span>}
        </span>
        <span className={`text-xs font-mono tabular-nums ml-4 shrink-0 ${cl}`} title={title}>{val}</span>
      </button>
      {open && (
        <div className="ml-2 border-l border-slate-700/40 pl-2 mt-0.5 mb-0.5">
          {children}
        </div>
      )}
    </div>
  )
}

// colour helpers for modal P&L
const nc = (v: string | null) => !v || Number(v) === 0 ? 'text-slate-600' : 'text-red-400/90'
const pc = (v: string | null) => !v || Number(v) === 0 ? 'text-slate-600' : 'text-emerald-400/90'
const mv = (v: string | null) => !v || Number(v) === 0
  ? '0,00 zł'
  : `${f(v)} zł`
const plusVal = (v: string | null) => !v || Number(v) === 0
  ? '0,00 zł'
  : `+${f(v)} zł`
const minusVal = (v: string | null) => !v || Number(v) === 0
  ? '0,00 zł'
  : `-${f(v)} zł`

// ── Product Detail Modal ──────────────────────────────────────────────────────
function ProductDetailModal({
  sku_key, period, accountId, currency, isVatPayer, dateFrom, dateTo, onClose,
}: {
  sku_key: string; period: PeriodKey; accountId?: number; currency?: string; isVatPayer: boolean
  dateFrom?: string; dateTo?: string; onClose: () => void
}) {
  const queryClient = useQueryClient()
  const { data: rawDetail, isLoading, isError } = useQuery({
    queryKey: ['product-detail', sku_key, period, accountId, currency, dateFrom, dateTo],
    queryFn: () => dashboardApi.productDetail(sku_key, period, accountId, currency, dateFrom, dateTo),
  })
  const vault = useFinancialVault()
  const [detail, setDetail] = useState<(ProductDetail & { cost_per_unit?: string; profit_per_unit?: string | null }) | null>(null)
  const [costInput, setCostInput] = useState('')
  const [costMessage, setCostMessage] = useState<string | null>(null)

  const saveMissingCostMutation = useMutation({
    mutationFn: async ({ product, visibleCost }: { product: ProductDetail; visibleCost: string }) => {
      if (!vault.key) throw new Error('vault_locked')
      const netCost = netCostFromVisible(visibleCost, product.vat_rate, isVatPayer)
      if (netCost == null || netCost <= 0) throw new Error('invalid_cost')
      const keyVersion = vault.status?.key_version ?? 1
      const today = new Date().toISOString().slice(0, 10)
      const encrypted = await encryptCost(vault.key, netCost, skuCostAad(product.sku_id, keyVersion), keyVersion)
      const historyEncrypted = await encryptCost(vault.key, netCost, skuCostHistoryAad(product.sku_id, today, keyVersion), keyVersion)
      return productsApi.patch(product.sku_id, {
        encrypted_cost: encrypted,
        history_encrypted_cost: historyEncrypted,
      })
    },
    onSuccess: () => {
      setCostInput('')
      setCostMessage('Zapisano koszt.')
      queryClient.invalidateQueries({ queryKey: ['product-detail'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-products'] })
      queryClient.invalidateQueries({ queryKey: ['products-manage'] })
    },
    onError: (error) => {
      setCostMessage(error instanceof Error && error.message === 'vault_locked'
        ? 'Odblokuj sejf kosztów, żeby zapisać.'
        : 'Nie udało się zapisać kosztu.')
    },
  })

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!rawDetail) {
        setDetail(null)
        return
      }
      if (!vault.key) {
        setDetail(rawDetail)
        return
      }
      const rawUnitCost = await decryptCost(vault.key, rawDetail.encrypted_cost)
      const costMultiplier = Number(rawDetail.cost_multiplier ?? 1)
      const unitCost = rawUnitCost == null ? null : rawUnitCost * (Number.isFinite(costMultiplier) && costMultiplier > 0 ? costMultiplier : 1)
      const unitCostForMode = unitCost == null ? null : visibleUnitCost(unitCost, rawDetail.vat_rate, isVatPayer)
      const totalAllegro = neutralAllegroCost(rawDetail.total_allegro_net)
      const metrics = computeFinancials({
        revenue: isVatPayer ? Number(rawDetail.revenue_net) : Number(rawDetail.revenue_gross),
        units: rawDetail.units_sold,
        costUnits: Number(rawDetail.cogs_units ?? rawDetail.units_sold),
        unitCost: unitCostForMode,
        totalAllegro,
        priceAdjust: neutralAllegroAdjustment(rawDetail.price_adjust_cost ?? 0),
        campaignBonus: neutralAllegroAdjustment(rawDetail.campaign_bonus ?? 0),
        refundCommission: neutralAllegroAdjustment(rawDetail.refund_commission ?? 0),
        commissionRefunds: neutralAllegroAdjustment(rawDetail.commission_refunds_amount ?? 0),
      })
      if (!cancelled) setDetail({
        ...rawDetail,
        cost_per_unit: unitCostForMode == null ? undefined : String(unitCostForMode),
        cogs: metrics.cogs == null ? null : String(metrics.cogs),
        profit_net: metrics.profit == null ? null : String(metrics.profit),
        margin_pct: metrics.marginPct == null ? null : String(metrics.marginPct),
        roi_pct: metrics.roiPct == null ? null : String(metrics.roiPct),
        profit_per_unit: metrics.profitPerUnit == null ? null : String(metrics.profitPerUnit),
      })
    }
    run().catch(() => setDetail(rawDetail ?? null))
    return () => { cancelled = true }
  }, [isVatPayer, rawDetail, vault.key])

  const d = detail ?? rawDetail
  const profitCl = !d?.profit_net ? 'text-slate-400'
    : Number(d.profit_net) >= 0 ? 'text-emerald-400' : 'text-red-400'
  const showMissingCostForm = Boolean(rawDetail && !rawDetail.encrypted_cost)

  const handleSaveMissingCost = (event: FormEvent) => {
    event.preventDefault()
    if (!rawDetail || saveMissingCostMutation.isPending) return
    setCostMessage(null)
    saveMissingCostMutation.mutate({ product: rawDetail, visibleCost: costInput })
  }

  // derived aggregates
  const requiredCostsModal = d ? sumMoney(d.commission_cost) : 0
  const deliveryCostsModal = d ? sumMoney(d.smart_shipping_cost) : 0
  const smartForecastCostsModal = d ? sumMoney(d.smart_forecast_cost) : 0
  const actualSmartCostsModal = Math.max(0, deliveryCostsModal - smartForecastCostsModal)
  const promotionCostsModal = d ? sumMoney(
    d.featuring_commission_cost,
    d.featuring_cost,
    d.campaign_commission_cost,
    d.ads_cost,
    d.coins_cost,
  ) : 0
  const allegroRebatesModal = d ? sumMoney(d.price_adjust_cost, d.campaign_bonus, d.refund_commission, d.commission_refunds_amount) : 0
  const accountCostsModal = d ? sumMoney(d.protect_cost, d.local_cost, d.subscription_cost) : 0
  const classicReturnsModal = d ? sumMoney(d.returns_goods_value) : 0

  const kpiItems = d ? [
    { label: isVatPayer ? 'Sprzedaż netto' : 'Sprzedaż brutto', val: vatMoney(d.revenue_gross, { net: d.revenue_net, isVatPayer }).text, title: vatMoney(d.revenue_gross, { isVatPayer }).title, cl: 'text-white' },
    { label: 'Sztuki',          val: String(d.units_sold),        cl: 'text-white' },
    { label: 'Marża',           val: pct(d.margin_pct),           cl: profitCl },
    { label: profitLabel(isVatPayer), val: d.profit_net ? `${f(d.profit_net)} zł` : '—', cl: profitCl },
  ] : []

  return (
    <div
      className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-0 sm:p-4"
      onClick={onClose}
    >
      <div
        className="relative bg-slate-900 border-0 border-slate-700/80 rounded-none w-full h-full max-w-xl flex flex-col shadow-2xl sm:border sm:rounded-2xl sm:h-auto sm:max-h-[90vh]"
        onClick={e => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-slate-700/60 shrink-0">
          <div className="min-w-0 pr-4">
            {d ? (
              <>
                <p className="text-white font-bold text-base leading-snug break-words">{d.name}</p>
                <p className="text-slate-500 text-xs mt-0.5">
                  <span className="font-mono text-slate-400">{d.sku_key}</span>
                  {d.ean && <span className="ml-2 text-slate-600 font-mono">{d.ean}</span>}
                  <span className="mx-2 text-slate-700">·</span>
                  {d.period_label}
                </p>
              </>
            ) : (
              <p className="font-mono text-slate-400 text-sm">{sku_key}</p>
            )}
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors shrink-0 mt-0.5">
            <X size={18} />
          </button>
        </div>

        {/* ── Scrollable body ── */}
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
          {isLoading && (
            <div className="p-6 space-y-2 animate-pulse">
              {[...Array(10)].map((_, i) => (
                <div key={i} className="h-3 bg-slate-800 rounded" style={{ width: `${60 + (i % 4) * 10}%` }} />
              ))}
            </div>
          )}
          {isError && (
            <p className="p-6 text-red-400 text-sm">Nie udało się załadować danych dla tego SKU.</p>
          )}

          {d && (
            <>
              {/* ── KPI tiles ── */}
              <div className="grid grid-cols-2 gap-3 px-4 py-4 border-b border-slate-700/40 sm:grid-cols-4 sm:px-6">
                {kpiItems.map(({ label, val, cl, title }) => (
                  <div key={label} className="bg-slate-800/80 rounded-xl px-3 py-2.5 text-center">
                    <p className="text-slate-500 text-[11px] mb-0.5">{label}</p>
                    <p className={`font-bold text-sm tabular-nums ${cl}`} title={title}>{val}</p>
                  </div>
                ))}
              </div>

              {/* ── P&L breakdown ── */}
              <div className="px-4 py-4 sm:px-6">

                {/* 1. Sprzedaż */}
                <PnLSection
                  label={isVatPayer ? 'Sprzedaż netto' : 'Sprzedaż brutto'}
                  val={vatMoney(d.revenue_gross, { net: d.revenue_net, isVatPayer, sign: 'plus' }).text}
                  title={vatMoney(d.revenue_gross, { isVatPayer }).title}
                  cl={pc(d.revenue_gross)}
                >
                  <PnLLine label="Sprzedaż" val={vatMoney(d.sales_gross_value, { net: d.sales_net_value, isVatPayer, sign: 'plus' }).text} title={vatMoney(d.sales_gross_value, { isVatPayer }).title} cl={pc(d.sales_gross_value)} sub />
                  <PnLLine label="Zwroty" val={vatMoney(d.returns_goods_value, { net: d.returns_goods_value_net, isVatPayer, sign: 'minus' }).text} title={vatMoney(d.returns_goods_value, { isVatPayer }).title} cl="text-slate-400" sub />
                </PnLSection>
                <PnLLine label="Sprzedane sztuki" val={`${d.units_sold} szt.`} cl={d.units_sold > 0 ? 'text-slate-300' : 'text-slate-600'} />

                <div className="my-2 border-t border-slate-800" />

                {/* 2. Obowiązkowe */}
                <PnLSection
                  label="Obowiązkowe"
                  val={vatMoney(String(requiredCostsModal), { isVatPayer, sign: 'minus' }).text}
                  title={vatMoney(String(requiredCostsModal), { isVatPayer }).title}
                  cl={requiredCostsModal !== 0 ? 'text-red-400/90' : 'text-slate-600'}
                >
                  <PnLLine label="Prowizja od sprzedaży" code="SUC" val={vatMoney(d.commission_cost, { isVatPayer, sign: 'minus' }).text} title={vatMoney(d.commission_cost, { isVatPayer }).title} cl={nc(d.commission_cost)} sub />
                </PnLSection>

                {/* 3. Koszty Allegro Smart */}
                <PnLSection
                  label="Koszty Allegro Smart"
                  val={vatMoney(String(deliveryCostsModal), { isVatPayer, sign: 'minus' }).text}
                  title={vatMoney(String(deliveryCostsModal), { isVatPayer }).title}
                  cl={deliveryCostsModal !== 0 ? 'text-red-400/90' : 'text-slate-600'}
                >
                  <PnLLine label="Smart Prognoza" code="SMART" val={vatMoney(String(smartForecastCostsModal), { isVatPayer, sign: 'minus' }).text} title={vatMoney(String(smartForecastCostsModal), { isVatPayer }).title} cl={smartForecastCostsModal !== 0 ? 'text-red-400/90' : 'text-slate-600'} sub />
                  <PnLLine label="Dopłata do Allegro Smart" code="Delivery Smart" val={vatMoney(String(actualSmartCostsModal), { isVatPayer, sign: 'minus' }).text} title={vatMoney(String(actualSmartCostsModal), { isVatPayer }).title} cl={actualSmartCostsModal !== 0 ? 'text-red-400/90' : 'text-slate-600'} sub />
                </PnLSection>

                {/* 4. Reklama i promowanie */}
                <PnLSection
                  label="Reklama i promowanie"
                  val={vatMoney(String(promotionCostsModal), { isVatPayer, sign: 'minus' }).text}
                  title={vatMoney(String(promotionCostsModal), { isVatPayer }).title}
                  cl={promotionCostsModal !== 0 ? 'text-red-400/90' : 'text-slate-600'}
                >
                  <PnLLine label="Prowizja od sprzedaży oferty wyróżnionej" code="FSF" val={vatMoney(d.featuring_commission_cost, { isVatPayer, sign: 'minus' }).text} title={vatMoney(d.featuring_commission_cost, { isVatPayer }).title} cl={nc(d.featuring_commission_cost)} sub />
                  <PnLLine label="Opłata za wyróżnienie" code="FEA" val={vatMoney(d.featuring_cost, { isVatPayer, sign: 'minus' }).text} title={vatMoney(d.featuring_cost, { isVatPayer }).title} cl={nc(d.featuring_cost)} sub />
                  <PnLLine label="Prowizja kampanii" code="BRG" val={vatMoney(d.campaign_commission_cost, { isVatPayer, sign: 'minus' }).text} title={vatMoney(d.campaign_commission_cost, { isVatPayer }).title} cl={nc(d.campaign_commission_cost)} sub />
                  <PnLLine label="Allegro Ads IMP" code="IMP" val={vatMoney(d.ads_imported_cost, { isVatPayer, sign: 'minus' }).text} title={vatMoney(d.ads_imported_cost, { isVatPayer }).title} cl={nc(d.ads_imported_cost)} info={ADS_IMP_INFO} sub />
                  <PnLLine label="Allegro Ads NSP" code="NSP" val={signedVatMoney(d.ads_nsp_adjustment_cost, { isVatPayer }).text} title={signedVatMoney(d.ads_nsp_adjustment_cost, { isVatPayer }).title} cl={Number(d.ads_nsp_adjustment_cost) < 0 ? pc(String(Math.abs(Number(d.ads_nsp_adjustment_cost)))) : nc(d.ads_nsp_adjustment_cost)} info={ADS_NSP_INFO} sub />
                  <PnLLine label="Monety" code="CPF/RCP" val={vatMoney(d.coins_cost, { isVatPayer, sign: 'minus' }).text} title={vatMoney(d.coins_cost, { isVatPayer }).title} cl={nc(d.coins_cost)} sub />
                </PnLSection>

                {/* 5. Rabaty od Allegro */}
                <PnLSection
                  label="Rabaty od Allegro"
                  val={vatMoney(String(allegroRebatesModal), { isVatPayer, sign: 'plus' }).text}
                  cl={allegroRebatesModal !== 0 ? 'text-emerald-400/90' : 'text-slate-600'}
                >
                  <PnLLine label="Allegro Ceny" code="PS1/PSA" val={vatMoney(d.price_adjust_cost, { isVatPayer, sign: 'plus' }).text} cl={pc(d.price_adjust_cost)} sub />
                  <PnLLine label="Bonus kampanii" code="CB2" val={vatMoney(d.campaign_bonus, { isVatPayer, sign: 'plus' }).text} cl={pc(d.campaign_bonus)} sub />
                  <PnLLine label="Zwrot prowizji" code="REF" val={vatMoney(d.refund_commission, { isVatPayer, sign: 'plus' }).text} cl={pc(d.refund_commission)} sub />
                  <PnLLine label="Zwrot prowizji po zwrocie" code="SUC/FSF" val={vatMoney(d.commission_refunds_amount, { isVatPayer, sign: 'plus' }).text} cl={pc(d.commission_refunds_amount)} sub />
                </PnLSection>

                {/* 6. Zwroty */}
                <PnLSection
                  label="Zwroty"
                  val={vatMoney(d.returns_goods_value, { net: d.returns_goods_value_net, isVatPayer, sign: 'minus' }).text}
                  cl={classicReturnsModal !== 0 ? 'text-slate-400' : 'text-slate-600'}
                >
                  <PnLLine label="Przyznane zgłoszenia" val={d.returns_count > 0 ? String(d.returns_count) : '0'} cl={d.returns_count > 0 ? 'text-slate-400' : 'text-slate-600'} sub />
                  <PnLLine label="Przyznane sztuki" val={d.returns_units > 0 ? `${d.returns_units} szt.` : '0 szt.'} cl={d.returns_units > 0 ? 'text-slate-400' : 'text-slate-600'} sub />
                  <PnLLine label="W trakcie zgłoszenia" val={d.returns_pending_count > 0 ? String(d.returns_pending_count) : '0'} cl={d.returns_pending_count > 0 ? 'text-slate-400' : 'text-slate-600'} sub />
                  <PnLLine label="W trakcie sztuki" val={d.returns_pending_units > 0 ? `${d.returns_pending_units} szt.` : '0 szt.'} cl={d.returns_pending_units > 0 ? 'text-slate-400' : 'text-slate-600'} sub />
                  <PnLLine label="Odrzucone zgłoszenia" val={d.returns_rejected_count > 0 ? String(d.returns_rejected_count) : '0'} cl={d.returns_rejected_count > 0 ? 'text-slate-400' : 'text-slate-600'} sub />
                  <PnLLine label="Odrzucone sztuki" val={d.returns_rejected_units > 0 ? `${d.returns_rejected_units} szt.` : '0 szt.'} cl={d.returns_rejected_units > 0 ? 'text-slate-400' : 'text-slate-600'} sub />
                </PnLSection>

                {/* 7. Fulfillment */}
                <PnLSection
                  label="Fulfillment"
                  val={minusVal(d.fulfillment)}
                  cl={nc(d.fulfillment)}
                >
                  <PnLLine label="Opłata podstawowa" code="OFA" val={minusVal(d.fulfillment_base_cost)} cl={nc(d.fulfillment_base_cost)} sub />
                  <PnLLine label="Magazynowanie" code="OF1/OFB/OFC/OFD/OFQ/OFR/OFS/OFU/OFZ" val={minusVal(d.fulfillment_storage_cost)} cl={nc(d.fulfillment_storage_cost)} sub />
                  <PnLLine label="Obsługa zwrotów" code="OFE/OFF/OFI" val={minusVal(d.fulfillment_returns_cost)} cl={nc(d.fulfillment_returns_cost)} sub />
                  <PnLLine label="Subskrypcja" code="OFM" val={minusVal(d.fulfillment_subscription_cost)} cl={nc(d.fulfillment_subscription_cost)} sub />
                  <PnLLine label="Opłaty dodatkowe" code="SHIPMENT_SURCHARGE/pozostałe OF*" val={minusVal(d.fulfillment_other_cost)} cl={nc(d.fulfillment_other_cost)} sub />
                </PnLSection>

                {/* 8. Opłaty konta */}
                <PnLSection
                  label="Opłaty konta"
                  val={minusVal(String(accountCostsModal))}
                  cl={accountCostsModal !== 0 ? 'text-red-400/90' : 'text-slate-600'}
                >
                  <PnLLine label="Allegro Protect" code="INS" val={minusVal(d.protect_cost)} cl={nc(d.protect_cost)} sub />
                  <PnLLine label="Dopłata lokalna" code="ALC/ALS/ALK/ALI/ALL/ALP" val={minusVal(d.local_cost)} cl={nc(d.local_cost)} sub />
                  <PnLLine label="Abonament" code="SB*/SH*/ST*/ILF/ABO" val={minusVal(d.subscription_cost)} cl={nc(d.subscription_cost)} sub />
                </PnLSection>

                {/* COGS */}
                <PnLLine label="Koszt sprzedanych produktów" val={minusVal(d.cogs)} cl={nc(d.cogs)} />

                {/* 9. Koszty ponoszone przez kupującego — visually distinct */}
                <div className="mt-3 pt-2 border-t border-slate-700/50">
                  <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Koszty dostaw rozliczane przez Allegro</p>
                  <PnLLine
                    label="Dostawy klienta rozliczane przez Allegro"
                    code="HB4/HLB/…"
                    val={minusVal(d.shipping_passthrough_cost)}
                    cl="text-slate-500"
                  />
                  <PnLLine
                    label="Dostawy zagraniczne rozliczane przez Allegro"
                    code="HB1/HB8"
                    val={minusVal(d.foreign_shipping_cost)}
                    cl="text-slate-500"
                  />
                  <p className="text-[10px] text-slate-600 italic mt-0.5">
                    Wartości informacyjne — nie wliczane do zysku; nie obejmują kosztów dostaw rozliczanych poza Allegro.
                  </p>
                </div>

                {/* Result line */}
                <div className="mt-3 border-t border-slate-600 pt-3 space-y-1">
                  <div className="flex justify-between items-baseline">
                    <span className="text-sm font-bold text-white">{profitLabel(isVatPayer)}</span>
                    <span className={`text-sm font-bold tabular-nums font-mono ${profitCl}`}>{f(d.profit_net)} zł</span>
                  </div>
                  <div className="flex justify-between items-baseline">
                    <span className="text-xs text-slate-500">Marża</span>
                    <span className={`text-xs tabular-nums font-mono ${profitCl}`}>{pct(d.margin_pct)}</span>
                  </div>
                  <div className="flex justify-between items-baseline">
                    <span className="text-xs text-slate-500">ROI</span>
                    <span className={`text-xs tabular-nums font-mono ${profitCl}`}>{pct(d.roi_pct)}</span>
                  </div>
                </div>

                {/* Product info footer */}
                <div className="mt-4 grid grid-cols-1 gap-3 border-t border-slate-800 pt-3 text-xs sm:grid-cols-3">
                  {[
                    ['Cena sprzedaży', `${f(d.sell_price)} zł`],
                    ['Koszt zakupu',   (d as any).cost_per_unit ? `${f((d as any).cost_per_unit)} zł` : '—'],
                    ['Zysk / szt.',    (d as any).profit_per_unit ? `${f((d as any).profit_per_unit)} zł` : '—'],
                  ].map(([label, val]) => (
                    <div key={label}>
                      <p className="text-slate-600 mb-0.5">{label}</p>
                      <p className="text-slate-300">{val}</p>
                    </div>
                  ))}
                </div>

                {showMissingCostForm && (
                  <form
                    onSubmit={handleSaveMissingCost}
                    className="mt-3 flex flex-col gap-2 rounded-lg border border-amber-400/20 bg-amber-400/5 p-3 text-xs sm:flex-row sm:items-end"
                  >
                    <label className="min-w-0 flex-1">
                      <span className="mb-1 block text-slate-400">
                        {isVatPayer ? 'Koszt zakupu netto' : 'Koszt zakupu brutto'}
                      </span>
                      <input
                        value={costInput}
                        onChange={e => setCostInput(e.target.value)}
                        inputMode="decimal"
                        placeholder="0,00"
                        disabled={!vault.key || saveMissingCostMutation.isPending}
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-2 font-mono text-sm text-white outline-none transition focus:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
                      />
                    </label>
                    <button
                      type="submit"
                      disabled={!vault.key || !costInput.trim() || saveMissingCostMutation.isPending}
                      className="rounded-md bg-emerald-500 px-3 py-2 font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                    >
                      {saveMissingCostMutation.isPending ? 'Zapisywanie...' : 'Zapisz'}
                    </button>
                    <p className="text-slate-500 sm:max-w-[140px]">
                      {costMessage ?? (!vault.key ? 'Odblokuj sejf kosztów.' : 'Brak kosztu zakupu.')}
                    </p>
                  </form>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Row presentation ──────────────────────────────────────────────────────────
function marginColor(v: string | null) {
  if (!v) return 'text-slate-500'
  const n = Number(v)
  return n < 0 ? 'text-finance-red' : n < 20 ? 'text-finance-amber' : 'text-finance-green'
}
function rowStripe(rowIndex: number) {
  return rowIndex % 2 === 0 ? 'apos-row-even' : 'apos-row-odd'
}

// ── Mobile product card ───────────────────────────────────────────────────────
function DashboardProductCard({ p, isVatPayer, onClick }: {
  p: FinancialProductRow
  isVatPayer: boolean
  onClick: () => void
}) {
  return (
    <div
      onClick={onClick}
      className="cursor-pointer rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition-colors hover:border-slate-300"
    >
      <div className="min-w-0">
        <p className="truncate font-mono text-[11px] font-semibold text-slate-500">{p.sku_key}</p>
        <p className="truncate text-xs font-medium text-slate-900" title={p.name}>{p.name}</p>
        <div className="mt-0.5 flex flex-wrap items-center gap-2">
          {Number(p.sell_price) > 0 && <span className="text-slate-500 text-xs">{f(p.sell_price)} zł</span>}
          {Number(p.cost_per_unit) > 0 && <span className="text-slate-400 text-xs">CZ: {f(p.cost_per_unit)} zł</span>}
          {p.ean && <span className="text-slate-300 text-xs font-mono">{p.ean}</span>}
        </div>
      </div>

      <div className="mt-3 border-t border-slate-100 pt-3">
        <p className="text-[11px] text-slate-500">{profitLabel(isVatPayer)}</p>
        <p className={`text-xl font-bold tabular-nums ${Number(p.profit_net) >= 0 ? 'text-finance-green' : 'text-finance-red'}`}>
          {f(p.profit_net)} zł
        </p>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
        <div>
          <p className="text-[11px] text-slate-500">Przychód</p>
          <p
            className="text-sm font-medium text-slate-700 tabular-nums"
            title={vatMoney(p.revenue_gross, { isVatPayer }).title}
          >
            {vatMoney(p.revenue_gross, { net: p.revenue_net, isVatPayer }).text}
          </p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500">Marża</p>
          <p className={`text-sm font-semibold tabular-nums ${marginColor(p.margin_pct)}`}>{pct(p.margin_pct)}</p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500">Sprzedane</p>
          <p className="text-sm font-medium text-slate-700 tabular-nums">{p.units_sold}</p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500">Koszty Allegro</p>
          <p
            className="text-sm font-medium text-finance-red tabular-nums"
            title={`Kwota brutto z Allegro: ${f(p.total_allegro)} zł`}
          >
            {costMoney(p.total_allegro_net)}
          </p>
        </div>
      </div>

      <details className="group mt-3" onClick={e => e.stopPropagation()}>
        <summary className="flex cursor-pointer list-none items-center justify-between rounded-md border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600">
          <span>Szczegóły</span>
          <ChevronRight size={14} className="text-slate-400 transition-transform group-open:rotate-90" />
        </summary>
        <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
          <div>
            <p className="text-[11px] text-slate-500">Zwroty</p>
            <p className="text-sm font-medium text-slate-500 tabular-nums">{p.returns_units || '—'}</p>
          </div>
          <div>
            <p className="text-[11px] text-slate-500">Ads</p>
            <p
              className="text-sm font-medium text-finance-amber tabular-nums"
              title={vatMoney(p.ads_cost, { isVatPayer }).title}
            >
              {vatMoney(p.ads_cost, { isVatPayer, sign: 'minus' }).text}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-slate-500">COGS</p>
            <p className="text-sm font-medium text-finance-amber tabular-nums">
              {Number(p.cogs) > 0 ? `-${f(p.cogs)} zł` : '—'}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-slate-500">{profitPerUnitLabel(isVatPayer)}</p>
            <p className="text-sm font-medium text-slate-500 tabular-nums">
              {p.profit_per_unit ? `${f(p.profit_per_unit)} zł` : '—'}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-slate-500">ROI</p>
            <p className={`text-sm font-medium tabular-nums ${marginColor(p.roi_pct)}`}>{pct(p.roi_pct)}</p>
          </div>
        </div>
      </details>
    </div>
  )
}

// ── Sorting ───────────────────────────────────────────────────────────────────
type SortDir = 'asc' | 'desc'
type SortKey = 'name' | 'units_sold' | 'returns_units' | 'revenue_gross' | 'total_allegro'
             | 'ads_cost' | 'cogs' | 'profit_net' | 'profit_per_unit' | 'margin_pct' | 'roi_pct'

function sortProducts(rows: FinancialProductRow[], key: SortKey, dir: SortDir) {
  return [...rows].sort((a, b) => {
    if (key === 'name') {
      const cmp = a.name.localeCompare(b.name, 'pl')
      return dir === 'asc' ? cmp : -cmp
    }
    const av = key === 'units_sold' ? a.units_sold
             : key === 'returns_units' ? a.returns_units
             : Number(a[key] ?? 0)
    const bv = key === 'units_sold' ? b.units_sold
             : key === 'returns_units' ? b.returns_units
             : Number(b[key] ?? 0)
    return dir === 'asc' ? av - bv : bv - av
  })
}

type ColDef = { label: string; key: SortKey | null; align: 'left' | 'right' }
const COLS: ColDef[] = [
  { label: 'PRODUKT',        key: 'name',           align: 'left'  },
  { label: 'SZTUKI',         key: 'units_sold',      align: 'right' },
  { label: 'ZWROTY',         key: 'returns_units',   align: 'right' },
  { label: 'SPRZEDAŻ',       key: 'revenue_gross',   align: 'right' },
  { label: 'KOSZTY ALLEGRO', key: 'total_allegro',   align: 'right' },
  { label: 'REKLAMY',        key: 'ads_cost',        align: 'right' },
  { label: 'KOSZT TOW.',     key: 'cogs',            align: 'right' },
  { label: 'ZYSK NETTO',     key: 'profit_net',      align: 'right' },
  { label: 'ZYSK/SZT',       key: 'profit_per_unit', align: 'right' },
  { label: 'MARŻA',          key: 'margin_pct',      align: 'right' },
  { label: 'ROI',            key: 'roi_pct',         align: 'right' },
]

function productColumns(showNet: boolean): ColDef[] {
  return COLS.map(col => {
    if (col.key === 'profit_net') return { ...col, label: profitLabel(showNet).toUpperCase() }
    if (col.key === 'profit_per_unit') return { ...col, label: profitPerUnitLabel(showNet).replace(' / ', '/').toUpperCase() }
    return col
  })
}

type PdfColumnKey =
  | 'name'
  | 'sku_key'
  | 'ean'
  | 'sell_price'
  | 'cost_per_unit'
  | 'units_sold'
  | 'returns_units'
  | 'revenue'
  | 'total_allegro'
  | 'ads_cost'
  | 'cogs'
  | 'profit_net'
  | 'profit_per_unit'
  | 'margin_pct'
  | 'roi_pct'

type PdfColumn = {
  key: PdfColumnKey
  label: (showNet: boolean) => string
  align: 'left' | 'right'
  value: (row: FinancialProductRow, showNet: boolean) => string
}

const PDF_COLUMNS: PdfColumn[] = [
  { key: 'name', label: () => 'Nazwa', align: 'left', value: row => row.name || '—' },
  { key: 'sku_key', label: () => 'SKU', align: 'left', value: row => row.sku_key || '—' },
  { key: 'ean', label: () => 'EAN', align: 'left', value: row => row.ean || '—' },
  { key: 'sell_price', label: () => 'Cena', align: 'right', value: row => Number(row.sell_price) > 0 ? `${f(row.sell_price)} zł` : '—' },
  { key: 'cost_per_unit', label: showNet => showNet ? 'Koszt netto / szt.' : 'Koszt brutto / szt.', align: 'right', value: row => Number(row.cost_per_unit) > 0 ? `${f(row.cost_per_unit)} zł` : '—' },
  { key: 'units_sold', label: () => 'Sztuki', align: 'right', value: row => String(row.units_sold) },
  { key: 'returns_units', label: () => 'Zwroty', align: 'right', value: row => row.returns_units ? String(row.returns_units) : '—' },
  { key: 'revenue', label: showNet => showNet ? 'Sprzedaż netto' : 'Sprzedaż brutto', align: 'right', value: (row, showNet) => vatMoney(row.revenue_gross, { net: row.revenue_net, isVatPayer: showNet }).text },
  { key: 'total_allegro', label: () => 'Koszty Allegro', align: 'right', value: row => costMoney(row.total_allegro_net) },
  { key: 'ads_cost', label: () => 'Reklamy', align: 'right', value: (row, showNet) => vatMoney(row.ads_cost, { isVatPayer: showNet, sign: 'minus' }).text },
  { key: 'cogs', label: () => 'Koszt tow.', align: 'right', value: row => Number(row.cogs) > 0 ? `-${f(row.cogs)} zł` : '—' },
  { key: 'profit_net', label: showNet => profitLabel(showNet), align: 'right', value: row => row.profit_net ? `${f(row.profit_net)} zł` : '—' },
  { key: 'profit_per_unit', label: showNet => profitPerUnitLabel(showNet), align: 'right', value: row => row.profit_per_unit ? `${f(row.profit_per_unit)} zł` : '—' },
  { key: 'margin_pct', label: () => 'Marża', align: 'right', value: row => pct(row.margin_pct) },
  { key: 'roi_pct', label: () => 'ROI', align: 'right', value: row => pct(row.roi_pct) },
]

const DEFAULT_PDF_COLUMNS: PdfColumnKey[] = ['name', 'units_sold', 'profit_per_unit']

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function printProductsPdf({
  rows,
  columns,
  title,
  subtitle,
  isVatPayer,
}: {
  rows: FinancialProductRow[]
  columns: PdfColumn[]
  title: string
  subtitle: string
  isVatPayer: boolean
}) {
  const popup = window.open('', '_blank', 'width=1080,height=760')
  if (!popup) return
  const generatedAt = new Date().toLocaleString('pl-PL')
  const tableHead = columns
    .map(col => `<th class="${col.align === 'right' ? 'num' : ''}">${escapeHtml(col.label(isVatPayer))}</th>`)
    .join('')
  const tableRows = rows
    .map(row => `<tr>${columns.map(col => `<td class="${col.align === 'right' ? 'num' : ''}">${escapeHtml(col.value(row, isVatPayer))}</td>`).join('')}</tr>`)
    .join('')
  popup.document.write(`<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(title)}</title>
  <style>
    @page { size: A4 landscape; margin: 12mm; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #0f172a; font-family: Arial, Helvetica, sans-serif; font-size: 11px; }
    header { margin-bottom: 14px; }
    h1 { margin: 0 0 4px; font-size: 18px; line-height: 1.2; }
    .meta { color: #475569; font-size: 10px; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    th { border-bottom: 1px solid #0f172a; padding: 6px 5px; text-align: left; font-size: 9px; text-transform: uppercase; color: #334155; }
    td { border-bottom: 1px solid #e2e8f0; padding: 5px; vertical-align: top; overflow-wrap: anywhere; }
    .num { text-align: right; white-space: nowrap; }
    tr:nth-child(even) td { background: #f8fafc; }
  </style>
</head>
<body>
  <header>
    <h1>${escapeHtml(title)}</h1>
    <div class="meta">${escapeHtml(subtitle)} · Wygenerowano: ${escapeHtml(generatedAt)} · SKU: ${rows.length}</div>
  </header>
  <table>
    <thead><tr>${tableHead}</tr></thead>
    <tbody>${tableRows || `<tr><td colspan="${columns.length}">Brak danych.</td></tr>`}</tbody>
  </table>
  <script>
    window.addEventListener('load', () => {
      window.focus();
      window.print();
    });
  </script>
</body>
</html>`)
  popup.document.close()
}

function SortTh({ col, sortKey, sortDir, onSort }: {
  col: ColDef; sortKey: SortKey; sortDir: SortDir; onSort: (k: SortKey) => void
}) {
  const active = col.key && sortKey === col.key
  return (
    <th
      onClick={() => col.key && onSort(col.key)}
      className={`px-3 py-2.5 font-semibold whitespace-nowrap select-none
        ${col.key ? 'cursor-pointer hover:text-slate-900' : ''}
        ${col.align === 'left' ? 'text-left' : 'text-right'}
        ${active ? 'text-slate-950' : 'text-slate-500'}`}
    >
      <span className={`inline-flex items-center gap-0.5 ${col.align === 'right' ? 'flex-row-reverse' : ''}`}>
        {col.label}
        {col.key && (
          active
            ? (sortDir === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />)
            : <ChevronsUpDown size={10} className="text-slate-400" />
        )}
      </span>
    </th>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const dateDaysAgoIso = (daysAgo: number) => {
  const d = new Date()
  d.setHours(12, 0, 0, 0)
  d.setDate(d.getDate() - daysAgo)
  return toLocalIsoDate(d)
}

const CUSTOM_CFG = {
  key: 'custom' as PeriodKey,
  label: 'Wybrany zakres',
  color: 'text-finance-blue',
  bg: 'bg-white',
  border: 'border-slate-200',
  ring: 'ring-blue-200',
}

// ── Main component ────────────────────────────────────────────────────────────
export default function Dashboard() {
  const vault = useFinancialVault()
  const financialDisplay = useFinancialDisplayMode()
  const [selectedPeriod, setSelectedPeriod] = useState<PeriodKey>('current_month')
  const [tileView, setTileView] = useState<TileView>('default')
  const [customFrom, setCustomFrom]   = useState('')
  const [customTo,   setCustomTo]     = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch]           = useState('')
  const [selectedAccount, setSelectedAccount] = useState<number | undefined>()
  const selectedCurrency = 'PLN'
  const [selectedSku,     setSelectedSku]     = useState<string | null>(null)
  const [sortCol, setSortCol] = useState<SortKey>('profit_net')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [displayProducts, setDisplayProducts] = useState<FinancialProductRow[]>([])
  const [pdfColumnKeys, setPdfColumnKeys] = useState<PdfColumnKey[]>(DEFAULT_PDF_COLUMNS)
  const [financialSummaries, setFinancialSummaries] = useState<Partial<Record<PeriodKey, PnLSummary>>>({})
  const [financialDailyChartSummaries, setFinancialDailyChartSummaries] = useState<Record<string, PnLSummary>>({})
  const [financialCustomSummary, setFinancialCustomSummary] = useState<PnLSummary | undefined>()
  const [summaryProgress, setSummaryProgress] = useState<DecryptProgress>(null)
  const [tableProgress, setTableProgress] = useState<DecryptProgress>(null)
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(20)
  const [page, setPage] = useState(1)
  const decryptedProductsCacheRef = useRef<Record<string, FinancialProductRow[]>>({})
  const financialSummariesRef = useRef<Partial<Record<PeriodKey, FinancialSummaryCache>>>({})
  const financialDailyChartSummariesRef = useRef<Record<string, FinancialSummaryCache>>({})

  const publishFinancialSummaries = () => {
    const next: Partial<Record<PeriodKey, PnLSummary>> = {}
    for (const [period, cached] of Object.entries(financialSummariesRef.current)) {
      if (cached) next[period as PeriodKey] = cached.value
    }
    setFinancialSummaries(next)
  }

  const publishFinancialDailyChartSummaries = () => {
    const next: Record<string, PnLSummary> = {}
    for (const [period, cached] of Object.entries(financialDailyChartSummariesRef.current)) {
      if (cached) next[period] = cached.value
    }
    setFinancialDailyChartSummaries(next)
  }

  const isCustom = selectedPeriod === 'custom' && Boolean(customFrom && customTo)
  const activeCfg = isCustom ? CUSTOM_CFG : (PERIODS.find(p => p.key === selectedPeriod) ?? PERIODS[2])
  const visiblePeriods = tileView === 'custom'
    ? []
    : PERIODS.filter(period => TILE_VIEW_PERIODS[tileView].includes(period.key))
  const dailyChartRanges = useMemo(() => (
    Array.from({ length: 30 }, (_, index) => 29 - index).map(daysAgo => ({
      key: `day_${daysAgo}`,
      label: daysAgo === 0 ? 'Dzisiaj' : formatShortDate(dateDaysAgoIso(daysAgo)),
      date: dateDaysAgoIso(daysAgo),
    }))
  ), [])
  const dailyChartRangeKey = dailyChartRanges.map(r => r.date).join('|')

  const handleSort = (key: SortKey) => {
    if (sortCol === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(key); setSortDir('desc') }
  }

  const handleSearchSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSearch(searchInput.trim())
  }

  const handleSearchClear = () => {
    setSearchInput('')
    setSearch('')
  }

  const togglePdfColumn = (key: PdfColumnKey) => {
    setPdfColumnKeys(prev => (
      prev.includes(key)
        ? prev.filter(item => item !== key)
        : [...prev, key]
    ))
  }

  const applyCustomRange = (from: string, to: string) => {
    if (from && to) {
      setSelectedPeriod('custom')
    }
  }

  const handleCustomFromChange = (value: string) => {
    setCustomFrom(value)
    if (customTo && value > customTo) {
      setCustomTo(value)
      applyCustomRange(value, value)
      return
    }
    applyCustomRange(value, customTo)
  }

  const handleCustomToChange = (value: string) => {
    setCustomTo(value)
    applyCustomRange(customFrom, value)
  }

  const clearCustomRange = () => {
    setCustomFrom('')
    setCustomTo('')
    setSelectedPeriod('custom')
  }

  const handleTileViewChange = (view: TileView) => {
    setTileView(view)
    setSelectedPeriod(view === 'default' ? 'current_month' : view === 'rolling' ? 'last_30d' : 'custom')
  }

  const { data: accounts = [], isLoading: loadingAccounts } = useQuery({ queryKey: ['accounts'], queryFn: accountsApi.list })
  const isVatPayer = financialDisplay.showNet
  const productCols = useMemo(() => productColumns(isVatPayer), [isVatPayer])

  const { data: summaries } = useQuery({
    queryKey: ['dashboard-summaries', selectedAccount, selectedCurrency, search, visiblePeriods.map(period => period.key)],
    queryFn: () => dashboardApi.summaryAll(
      selectedAccount, selectedCurrency, search || undefined, visiblePeriods.map(period => period.key),
    ),
    enabled: visiblePeriods.length > 0,
    refetchInterval: 60_000,
  })
  const { data: summaryComparisons } = useQuery({
    queryKey: ['dashboard-summary-comparisons', selectedAccount, selectedCurrency, search, visiblePeriods.map(period => period.key)],
    queryFn: () => dashboardApi.summaryComparisons(
      selectedAccount, selectedCurrency, search || undefined, visiblePeriods.map(period => period.key),
    ),
    enabled: !!summaries,
    refetchInterval: 60_000,
  })

  const { data: customSummary } = useQuery({
    queryKey: ['dashboard-summary-custom', customFrom, customTo, selectedAccount, selectedCurrency, search],
    queryFn: () => dashboardApi.summaryCustom(customFrom, customTo, selectedAccount, selectedCurrency, search || undefined),
    enabled: isCustom && !!customFrom && !!customTo,
  })

  const { data: dailyChartSummaries } = useQuery({
    queryKey: ['dashboard-daily-chart-summaries', dailyChartRangeKey, selectedAccount, selectedCurrency, search],
    queryFn: async () => {
      const first = dailyChartRanges[0]?.date
      const last = dailyChartRanges[dailyChartRanges.length - 1]?.date
      if (!first || !last) return {}
      const byDate = await dashboardApi.summaryDaily(first, last, selectedAccount, selectedCurrency, search || undefined)
      return Object.fromEntries(
        dailyChartRanges.map(range => [range.key, byDate[range.date]] as const).filter(([, summary]) => Boolean(summary)),
      ) as Record<string, PnLSummary>
    },
    refetchInterval: 60_000,
  })

  const { data: productsData, isLoading: loadingProducts } = useQuery({
    queryKey: ['dashboard-products', selectedPeriod, selectedAccount, search, selectedCurrency, customFrom, customTo],
    queryFn: () => dashboardApi.products(
      selectedPeriod, selectedAccount, search || undefined, selectedCurrency,
      isCustom ? customFrom : undefined,
      isCustom ? customTo   : undefined,
    ),
    enabled: selectedPeriod !== 'custom' || isCustom,
    refetchInterval: 60_000,
  })
  const products = productsData ?? EMPTY_PRODUCTS

  const activeSummary = isCustom ? customSummary : summaries?.[selectedPeriod]
  const mergedSummaries = useMemo(() => {
    if (!summaries) return undefined
    const merged: Record<string, PnLSummary> = {}
    for (const [key, summary] of Object.entries(summaries)) {
      const compare = summaryComparisons?.[key]
      if (!compare) {
        merged[key] = summary
        continue
      }
      const currentGross = Number(summary.revenue_gross ?? 0)
      const currentNet = Number(summary.revenue_net ?? 0)
      const compareGross = Number(compare.comparison_revenue_gross ?? 0)
      const compareNet = Number(compare.comparison_revenue_net ?? 0)
      const deltaGross = currentGross - compareGross
      const deltaNet = currentNet - compareNet
      const deltaPctGross = compareGross ? (deltaGross / compareGross) * 100 : null
      const deltaPctNet = compareNet ? (deltaNet / compareNet) * 100 : null
      merged[key] = {
        ...summary,
        comparison_label: compare.comparison_label,
        comparison_revenue_gross: compare.comparison_revenue_gross,
        comparison_revenue_net: compare.comparison_revenue_net,
        comparison_delta_value: deltaGross.toFixed(2),
        comparison_delta_value_net: deltaNet.toFixed(2),
        comparison_delta_pct: deltaPctGross == null ? null : deltaPctGross.toFixed(2),
        comparison_delta_pct_net: deltaPctNet == null ? null : deltaPctNet.toFixed(2),
      }
    }
    return merged
  }, [summaries, summaryComparisons])
  const productsRevision = useMemo(
    () => products.map(p => `${p.sku_key}:${p.units_sold}:${p.cogs_units ?? ''}:${p.revenue_gross}:${p.total_allegro}:${p.encrypted_cost?.ciphertext ?? ''}:${p.cost_multiplier ?? 1}`).join(';'),
    [products],
  )
  const productsCacheKey = [
    selectedPeriod,
    selectedAccount ?? 'all',
    selectedCurrency,
    isVatPayer ? 'net' : 'gross',
    search || '',
    isCustom ? customFrom : '',
    isCustom ? customTo : '',
    productsRevision,
  ].join('|')

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!productsData) {
        setDisplayProducts([])
        setTableProgress(null)
        return
      }
      if (!vault.key) {
        setDisplayProducts(products)
        setTableProgress(null)
        return
      }
      const cached = decryptedProductsCacheRef.current[productsCacheKey]
      if (cached) {
        setDisplayProducts(cached)
        setTableProgress(null)
        return
      }
      const rows = await decryptProductRows(products, vault.key, isVatPayer, (done, total) => {
        if (!cancelled) setTableProgress({ label: 'Odszyfrowuję tabelę produktów', done, total })
      }, () => cancelled)
      if (cancelled) return
      decryptedProductsCacheRef.current[productsCacheKey] = rows
      if (!cancelled) setDisplayProducts(rows)
      if (!cancelled) setTableProgress(null)
    }
    run().catch(() => {
      setDisplayProducts(products)
      setTableProgress(null)
    })
    return () => {
      cancelled = true
    }
  }, [isVatPayer, products, productsCacheKey, productsData, vault.key])

  useEffect(() => {
    decryptedProductsCacheRef.current = {}
  }, [isVatPayer, search, selectedAccount, selectedCurrency, vault.key])

  useEffect(() => {
    financialSummariesRef.current = {}
    setFinancialSummaries({})
    financialDailyChartSummariesRef.current = {}
    setFinancialDailyChartSummaries({})
    setSummaryProgress(null)
  }, [isVatPayer, selectedAccount, selectedCurrency, search, vault.key])

  useEffect(() => {
    let cancelled = false
    async function decryptSummary(period: PeriodKey, showProgress: boolean) {
      if (!vault.key || !summaries || period === 'custom') return
      const cfg = PERIODS.find(p => p.key === period)
      const summary = (mergedSummaries?.[period] ?? summaries[period])
      if (!cfg || !summary) return
      const cacheKey = financialSummaryCacheKey(period, summary, selectedAccount, selectedCurrency, search, isVatPayer)
      const cached = financialSummariesRef.current[period]
      if (cached?.cacheKey === cacheKey) return

      if (showProgress && !cached?.value) setSummaryProgress({ label: `Odszyfrowuję kafelek: ${cfg.label}`, done: 0, total: 1 })
      const rows = await dashboardApi.products(period, selectedAccount, search || undefined, selectedCurrency)
      if (cancelled) return
      const decrypted = await buildFinancialSummary(summary, rows, vault.key, isVatPayer, (done, total) => {
        if (!cancelled && showProgress && !cached?.value) setSummaryProgress({ label: `Odszyfrowuję kafelek: ${cfg.label}`, done, total })
      }, () => cancelled)
      if (cancelled) return
      financialSummariesRef.current = { ...financialSummariesRef.current, [period]: { cacheKey, value: decrypted } }
      publishFinancialSummaries()
      if (showProgress && !cached?.value) setSummaryProgress(null)
    }

    decryptSummary(selectedPeriod, true).catch(() => {
      if (!cancelled) setSummaryProgress(null)
    })
    return () => { cancelled = true }
  }, [isVatPayer, mergedSummaries, selectedAccount, selectedCurrency, selectedPeriod, search, summaries, vault.key])

  useEffect(() => {
    if (!vault.key || !summaries || isCustom) return
    let cancelled = false
    const availableSummaries = summaries
    const activeKey = vault.key
    const timeout = window.setTimeout(() => {
      async function runIdlePrefetch() {
        for (const cfg of PERIODS) {
          if (cancelled || cfg.key === selectedPeriod) continue
          await waitForBrowserIdle(1000)
          if (cancelled) return
          const summary = mergedSummaries?.[cfg.key] ?? availableSummaries[cfg.key]
          if (!summary) continue
          const cacheKey = financialSummaryCacheKey(cfg.key, summary, selectedAccount, selectedCurrency, search, isVatPayer)
          if (financialSummariesRef.current[cfg.key]?.cacheKey === cacheKey) continue
          const rows = await dashboardApi.products(cfg.key, selectedAccount, search || undefined, selectedCurrency)
          if (cancelled) return
          const decrypted = await buildFinancialSummary(summary, rows, activeKey, isVatPayer, undefined, () => cancelled)
          if (cancelled) return
          financialSummariesRef.current = { ...financialSummariesRef.current, [cfg.key]: { cacheKey, value: decrypted } }
          publishFinancialSummaries()
          await yieldToBrowser()
        }
      }
      runIdlePrefetch().catch(() => undefined)
    }, 2500)
    return () => {
      cancelled = true
      window.clearTimeout(timeout)
    }
  }, [isCustom, isVatPayer, mergedSummaries, selectedAccount, selectedCurrency, selectedPeriod, search, summaries, vault.key])

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!vault.key || !isCustom || !customSummary) {
        setFinancialCustomSummary(undefined)
        return
      }
      const rows = await dashboardApi.products(
        'custom', selectedAccount, search || undefined, selectedCurrency, customFrom, customTo,
      )
      if (cancelled) return
      const summary = await buildFinancialSummary(customSummary, rows, vault.key, isVatPayer, (done, total) => {
        if (!cancelled) setSummaryProgress({ label: 'Odszyfrowuję zakres niestandardowy', done, total })
      }, () => cancelled)
      if (!cancelled) {
        setFinancialCustomSummary(summary)
        setSummaryProgress(null)
      }
    }
    run().catch(() => {
      setFinancialCustomSummary(undefined)
      setSummaryProgress(null)
    })
    return () => { cancelled = true }
  }, [customFrom, customSummary, customTo, isCustom, isVatPayer, search, selectedAccount, selectedCurrency, vault.key])

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!vault.key || !dailyChartSummaries) {
        if (!vault.key) setFinancialDailyChartSummaries({})
        return
      }
      const activeKey = vault.key
      for (const range of dailyChartRanges) {
        const summary = dailyChartSummaries[range.key]
        if (!summary) continue
        const cacheKey = financialSummaryCacheKey(range.key, summary, selectedAccount, selectedCurrency, search, isVatPayer)
        if (financialDailyChartSummariesRef.current[range.key]?.cacheKey === cacheKey) continue
        const rows = await dashboardApi.products(
          'custom', selectedAccount, search || undefined, selectedCurrency, range.date, range.date,
        )
        if (cancelled) return
        const decrypted = await buildFinancialSummary(summary, rows, activeKey, isVatPayer, undefined, () => cancelled)
        if (cancelled) return
        financialDailyChartSummariesRef.current = {
          ...financialDailyChartSummariesRef.current,
          [range.key]: { cacheKey, value: decrypted },
        }
        publishFinancialDailyChartSummaries()
        await yieldToBrowser()
      }
    }
    run().catch(() => {
      if (!cancelled && !vault.key) setFinancialDailyChartSummaries({})
    })
    return () => { cancelled = true }
  }, [dailyChartRangeKey, dailyChartRanges, dailyChartSummaries, isVatPayer, search, selectedAccount, selectedCurrency, vault.key])

  const latestActiveSummary = isCustom ? customSummary : mergedSummaries?.[selectedPeriod] ?? activeSummary
  const financialActiveSummary = isCustom
    ? (financialCustomSummary ?? customSummary)
    : (mergeLatestComparison(financialSummaries[selectedPeriod], latestActiveSummary) ?? latestActiveSummary)
  const chartSummaries = useMemo<ChartSummaryPoint[]>(() => (
    dailyChartRanges.map(range => ({
      key: range.key,
      label: range.label,
      summary: financialDailyChartSummaries[range.key] ?? dailyChartSummaries?.[range.key],
    }))
  ), [dailyChartRanges, dailyChartSummaries, financialDailyChartSummaries])
  const sortedProducts = useMemo(
    () => sortProducts(displayProducts, sortCol, sortDir),
    [displayProducts, sortCol, sortDir],
  )
  const selectedPdfColumns = useMemo(
    () => PDF_COLUMNS.filter(col => pdfColumnKeys.includes(col.key)),
    [pdfColumnKeys],
  )
  const totalPages = Math.max(1, Math.ceil(sortedProducts.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const pageStart = sortedProducts.length === 0 ? 0 : (currentPage - 1) * pageSize + 1
  const pageEnd = Math.min(currentPage * pageSize, sortedProducts.length)
  const pagedProducts = sortedProducts.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const combinedProgress = summaryProgress ?? tableProgress
  const showProductLoadingRows = loadingProducts && displayProducts.length === 0
  useEffect(() => {
    setPage(1)
  }, [pageSize, products.length, search, selectedAccount, selectedCurrency, selectedPeriod, customFrom, customTo, sortCol, sortDir])

  const handlePrintProductsPdf = () => {
    const periodLabel = isCustom && customSummary ? customSummary.period_label : activeCfg.label
    const accountLabel = selectedAccount
      ? accounts.find(account => account.id === selectedAccount)?.name ?? `Konto #${selectedAccount}`
      : 'Wszystkie konta'
    const searchLabel = search ? ` · Szukaj: ${search}` : ''
    printProductsPdf({
      rows: sortedProducts,
      columns: selectedPdfColumns,
      title: `Produkty - ${periodLabel}`,
      subtitle: `${accountLabel}${searchLabel}`,
      isVatPayer,
    })
  }

  if (!loadingAccounts && accounts.length === 0) {
    return <EmptyDashboard />
  }

  return (
    <div className="space-y-5">
      {/* Filters */}
      <div className="apos-panel flex flex-col gap-3 p-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-slate-950">Panel</h2>
          <p className="text-xs text-slate-500">Sprzedaż, zwroty, koszty Allegro i marża SKU w jednym widoku.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
        <form onSubmit={handleSearchSubmit} className="flex w-full min-w-[240px] flex-1 gap-2 lg:w-96 lg:flex-none">
        <div className="relative min-w-0 flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            className="apos-control w-full pl-8 pr-8"
            placeholder="Nazwa, SKU, EAN lub ID oferty..."
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
          />
          {searchInput && (
            <button
              type="button"
              onClick={handleSearchClear}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-900 transition-colors"
            >
              <X size={13} />
            </button>
          )}
        </div>
        <button type="submit" className="apos-button shrink-0 px-3 text-sm">Szukaj</button>
        </form>
        <div className="grid w-full grid-cols-[auto_1fr_1fr] items-center gap-2 lg:contents">
        <span className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm">
          PLN
        </span>
        <select
          className="apos-control w-full min-w-0 lg:w-auto"
          value={selectedAccount ?? ''}
          onChange={e => setSelectedAccount(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">Wszystkie konta</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <select
          className="apos-control w-full min-w-0 lg:w-auto"
          value={tileView}
          onChange={e => handleTileViewChange(e.target.value as TileView)}
          aria-label="Widok kafelków"
        >
          <option value="default">Dzisiaj i miesiące</option>
          <option value="rolling">Ostatnie dni</option>
          <option value="custom">Wybrany zakres</option>
        </select>
        </div>
        </div>
      </div>

      <DecryptProgressBar progress={combinedProgress} />

      {/* Custom date range */}
      {tileView === 'custom' && (
        <div className="rounded-lg border border-blue-300 bg-blue-50/60 px-4 py-3 shadow-sm transition-all">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Wybrany zakres</p>
              <p className="mt-0.5 text-xs text-slate-500">
                Po wybraniu obu dat panel przełączy się na jeden kafelek z tym zakresem.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex min-w-0 flex-1 items-center gap-2 lg:flex-none">
                <label className="text-slate-500 text-xs whitespace-nowrap">Od</label>
                <input
                  type="date"
                  value={customFrom}
                  onChange={e => handleCustomFromChange(e.target.value)}
                  className="apos-control w-full min-w-0 py-1.5 lg:w-auto"
                />
              </div>
              <div className="flex min-w-0 flex-1 items-center gap-2 lg:flex-none">
                <label className="text-slate-500 text-xs whitespace-nowrap">Do</label>
                <input
                  type="date"
                  value={customTo}
                  min={customFrom || undefined}
                  onChange={e => handleCustomToChange(e.target.value)}
                  className="apos-control w-full min-w-0 py-1.5 lg:w-auto"
                />
              </div>
              <button type="button" onClick={clearCustomRange} className="apos-button w-full py-1.5 text-xs lg:w-auto">
                Wyczyść
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Period tiles */}
      <div className={`grid gap-3 ${tileView === 'custom' ? 'md:grid-cols-1 xl:grid-cols-1' : 'md:grid-cols-2 xl:grid-cols-4'}`}>
        {tileView === 'custom' ? (isCustom ? (
          <SummaryTile
            cfg={{ ...CUSTOM_CFG, label: customSummary?.period_label ?? CUSTOM_CFG.label }}
            data={financialCustomSummary ?? customSummary}
            selected
            onClick={() => undefined}
            currency={selectedCurrency}
            isVatPayer={isVatPayer}
          />
        ) : (
          <div className="rounded-lg border border-dashed border-blue-300 bg-blue-50/60 p-4 text-sm text-slate-600">
            Wybierz datę „Od” i „Do”, aby wyświetlić kafelek dla wybranego zakresu.
          </div>
        )) : (
          visiblePeriods.map(cfg => (
              <SummaryTile
                key={cfg.key}
                cfg={cfg}
                data={
                  mergeLatestComparison(financialSummaries[cfg.key], mergedSummaries?.[cfg.key] ?? summaries?.[cfg.key])
                  ?? mergedSummaries?.[cfg.key]
                  ?? summaries?.[cfg.key]
                }
                selected={selectedPeriod === cfg.key}
                onClick={() => setSelectedPeriod(cfg.key)}
                currency={selectedCurrency}
                isVatPayer={isVatPayer}
              />
            ))
        )}
      </div>

      {/* Charts */}
      <div className="grid gap-4 xl:grid-cols-[1.18fr_0.82fr]">
        <PeriodComparisonChart
          points={chartSummaries}
          currency={selectedCurrency}
          isVatPayer={isVatPayer}
        />
        {financialActiveSummary && (
          <CostStructureChart
            summary={financialActiveSummary}
            currency={selectedCurrency}
            isVatPayer={isVatPayer}
          />
        )}
      </div>

      {/* Expanded P&L detail */}
      {financialActiveSummary && <DetailPanel data={financialActiveSummary} color={activeCfg.color} isVatPayer={isVatPayer} />}

      {/* Products table */}
      <div>
        <div className="mb-2 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <h3 className="text-slate-950 font-semibold">
            Produkty —{' '}
            {isCustom && customSummary ? customSummary.period_label : activeCfg.label}
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-500">
              {pageStart}-{pageEnd} z {sortedProducts.length} SKU
            </span>
            <details className="relative">
              <summary className="apos-button flex cursor-pointer list-none items-center gap-1.5 px-2 py-1 text-xs">
                <Columns3 size={13} />
                Kolumny PDF
              </summary>
              <div className="absolute right-0 z-20 mt-2 w-60 rounded-lg border border-slate-200 bg-white p-2 shadow-xl">
                <div className="max-h-72 space-y-1 overflow-y-auto">
                  {PDF_COLUMNS.map(col => (
                    <label key={col.key} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50">
                      <input
                        type="checkbox"
                        checked={pdfColumnKeys.includes(col.key)}
                        onChange={() => togglePdfColumn(col.key)}
                        className="h-3.5 w-3.5 rounded border-slate-300 text-blue-600"
                      />
                      <span>{col.label(isVatPayer)}</span>
                    </label>
                  ))}
                </div>
              </div>
            </details>
            <button
              type="button"
              onClick={handlePrintProductsPdf}
              disabled={selectedPdfColumns.length === 0 || sortedProducts.length === 0}
              className="apos-button flex items-center gap-1.5 px-2 py-1 text-xs"
            >
              <Download size={13} />
              Pobierz PDF
            </button>
            <select
              value={pageSize}
              onChange={e => setPageSize(Number(e.target.value) as (typeof PAGE_SIZE_OPTIONS)[number])}
              className="apos-control px-2 py-1 text-xs"
            >
              {PAGE_SIZE_OPTIONS.map(size => <option key={size} value={size}>{size}/str.</option>)}
            </select>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={currentPage <= 1}
                className="apos-button px-2 py-1 text-xs"
              >
                Poprzednia
              </button>
              <span className="min-w-12 text-center text-xs text-slate-500 tabular-nums">
                {currentPage}/{totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage >= totalPages}
                className="apos-button px-2 py-1 text-xs"
              >
                Następna
              </button>
            </div>
          </div>
        </div>

        <div className="hidden lg:block apos-table-wrap overflow-x-auto">
          <table className="apos-table apos-table-min-dashboard">
            <thead>
              <tr>
                {productCols.map(col => (
                  <SortTh key={col.label} col={col} sortKey={sortCol} sortDir={sortDir} onSort={handleSort} />
                ))}
              </tr>
            </thead>
            <tbody>
              {showProductLoadingRows ? (
                [...Array(5)].map((_, i) => (
                  <tr key={i}>
                    {productCols.map((_, j) => <td key={j}><div className="h-3 bg-slate-200 rounded animate-pulse" /></td>)}
                  </tr>
                ))
              ) : sortedProducts.length === 0 ? (
                <tr><td colSpan={productCols.length} className="px-4 py-10 text-center text-slate-500">
                  Brak sprzedaży w wybranym okresie.
                </td></tr>
              ) : pagedProducts.map((p: FinancialProductRow, rowIndex: number) => (
                <tr key={p.sku_key} onClick={() => setSelectedSku(p.sku_key)} className={`cursor-pointer ${rowStripe(rowIndex)}`}>
                  <td className="min-w-[210px]">
                    <p className="font-mono text-[11px] font-semibold text-slate-500">{p.sku_key}</p>
                    <p className="max-w-[240px] truncate text-xs font-medium text-slate-900" title={p.name}>{p.name}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      {Number(p.sell_price) > 0 && <span className="text-slate-500 text-xs">{f(p.sell_price)} zł</span>}
                      {Number(p.cost_per_unit) > 0 && <span className="text-slate-400 text-xs">CZ: {f(p.cost_per_unit)} zł</span>}
                      {p.ean && <span className="text-slate-300 text-xs font-mono">{p.ean}</span>}
                    </div>
                  </td>
                  <td className="text-right text-slate-700">{p.units_sold}</td>
                  <td className="text-right text-slate-500">{p.returns_units || '—'}</td>
                  <td
                    className="text-right text-slate-700 whitespace-nowrap"
                    title={vatMoney(p.revenue_gross, { isVatPayer }).title}
                  >
                    {vatMoney(p.revenue_gross, { net: p.revenue_net, isVatPayer }).text}
                  </td>
                  <td
                    className="text-right text-finance-red whitespace-nowrap"
                    title={`Kwota brutto z Allegro: ${f(p.total_allegro)} zł`}
                  >
                    {costMoney(p.total_allegro_net)}
                  </td>
                  <td
                    className="text-right text-finance-amber whitespace-nowrap"
                    title={vatMoney(p.ads_cost, { isVatPayer }).title}
                  >
                    {vatMoney(p.ads_cost, { isVatPayer, sign: 'minus' }).text}
                  </td>
                  <td className="text-right text-finance-amber whitespace-nowrap">
                    {Number(p.cogs) > 0 ? `-${f(p.cogs)} zł` : '—'}
                  </td>
                  <td className="text-right whitespace-nowrap font-semibold">
                    <span className={Number(p.profit_net) >= 0 ? 'text-finance-green' : 'text-finance-red'}>
                      {f(p.profit_net)} zł
                    </span>
                  </td>
                  <td className="text-right text-slate-500 whitespace-nowrap">
                    {p.profit_per_unit ? `${f(p.profit_per_unit)} zł` : '—'}
                  </td>
                  <td className="text-right">
                    <span className={`font-semibold ${marginColor(p.margin_pct)}`}>{pct(p.margin_pct)}</span>
                  </td>
                  <td className="text-right">
                    <span className={marginColor(p.roi_pct)}>{pct(p.roi_pct)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Product cards (mobile) */}
        <div className="space-y-3 lg:hidden">
          {showProductLoadingRows ? (
            [...Array(3)].map((_, i) => (
              <div key={i} className="animate-pulse space-y-3 rounded-lg border border-slate-200 bg-white p-4">
                <div className="h-3 w-2/5 rounded bg-slate-200" />
                <div className="h-3 w-3/4 rounded bg-slate-200" />
                <div className="h-6 w-1/2 rounded bg-slate-200" />
                <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                  <div className="h-3 rounded bg-slate-200" />
                  <div className="h-3 rounded bg-slate-200" />
                </div>
              </div>
            ))
          ) : sortedProducts.length === 0 ? (
            <div className="rounded-lg border border-slate-200 bg-white px-4 py-10 text-center text-slate-500">
              Brak sprzedaży w wybranym okresie.
            </div>
          ) : pagedProducts.map((p: FinancialProductRow) => (
            <DashboardProductCard
              key={p.sku_key}
              p={p}
              isVatPayer={isVatPayer}
              onClick={() => setSelectedSku(p.sku_key)}
            />
          ))}
        </div>
      </div>

      {selectedSku && (
        <ProductDetailModal
          sku_key={selectedSku}
          period={selectedPeriod}
          accountId={selectedAccount}
          currency={selectedCurrency}
          isVatPayer={isVatPayer}
          dateFrom={isCustom ? customFrom : undefined}
          dateTo={isCustom ? customTo : undefined}
          onClose={() => setSelectedSku(null)}
        />
      )}
    </div>
  )
}
