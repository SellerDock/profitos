import { Fragment, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Package, User, CheckCircle2, AlertCircle, Lock } from 'lucide-react'
import { ordersApi, type RecentOrder, type OrderLineItem } from '../api/client'
import { useBillingLabels } from '../utils/billingLabels'
import { useFinancialVault } from '../context/FinancialVaultContext'
import { useFinancialDisplayMode } from '../context/FinancialDisplayModeContext'
import { decryptCost } from '../crypto/financialVault'
import { yieldToBrowser } from '../utils/browserYield'
import {
  f, num as n, pln as plnFmt, costPln, grossToNet23, grossToNetByRate,
  visibleUnitCost, vatMoney as vatMoneyFmt,
  type MoneyInput, type VatMoneyOpts,
} from '../utils/money'

// ── Formatters ────────────────────────────────────────────────────────────────
// Shared implementations live in utils/money — the wrappers below keep the
// Orders-specific zero rendering ('0,00 zł' instead of Dashboard's '—').
const pln = (v: string | null | undefined) => plnFmt(v, 'zero')
const vatMoney = (gross: MoneyInput, opts?: VatMoneyOpts) => vatMoneyFmt(gross, { zero: 'zero', ...opts })

function fDate(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('pl-PL', { day: '2-digit', month: '2-digit', year: '2-digit' })
    + ' ' + d.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })
}

function profitClass(v: string | null | undefined): string {
  const n = Number(v)
  if (isNaN(n) || n === 0) return 'text-slate-400'
  return n > 0 ? 'text-emerald-400' : 'text-red-400'
}

const profitLabel = (showNet: boolean) => showNet ? 'Zysk netto' : 'Zysk brutto'

// ── Expanded row content ──────────────────────────────────────────────────────
function OrderDetail({ order, isVatPayer }: { order: RecentOrder; isVatPayer: boolean }) {
  const labels = useBillingLabels()

  return (
    <div className="bg-slate-900/40 border-t border-slate-800">
      <div className="p-4 space-y-4">
        {/* Line items */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2 flex items-center gap-1.5">
            <Package size={12} />
            Produkty w zamówieniu ({order.items.length})
          </h4>
          <div className="rounded-lg border border-slate-800 overflow-x-auto">
            <table className="w-full min-w-[48rem] text-xs">
              <thead className="bg-slate-800/60 text-slate-500 uppercase tracking-wide">
                <tr>
                  <th className="text-left  px-3 py-2 font-medium">Produkt / SKU</th>
                  <th className="text-right px-3 py-2 font-medium">Ilość</th>
                  <th className="text-right px-3 py-2 font-medium">Cena/szt</th>
                  <th className="text-right px-3 py-2 font-medium">{isVatPayer ? 'Przychód netto' : 'Przychód'}</th>
                  <th className="text-right px-3 py-2 font-medium">Koszt zak./szt</th>
                  <th className="text-right px-3 py-2 font-medium">COGS</th>
                </tr>
              </thead>
              <tbody>
                {order.items.map(it => (
                  <tr key={it.line_item_id} className="border-t border-slate-800/60">
                    <td className="px-3 py-2">
                      <div className="text-slate-200 leading-tight">{it.sku_name}</div>
                      <div className="text-slate-500 text-[11px]">
                        {it.sku || '—'} {it.offer_id && <span className="ml-1 text-slate-600">· oferta {it.offer_id}</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-300">{it.quantity}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-400" title={vatMoney(it.unit_price, { isVatPayer }).title}>
                      {vatMoney(it.unit_price, { net: grossToNetByRate(it.unit_price, it.vat_rate), isVatPayer }).text}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-white font-medium" title={vatMoney(it.revenue, { isVatPayer }).title}>
                      {vatMoney(it.revenue, { net: grossToNetByRate(it.revenue, it.vat_rate), isVatPayer }).text}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-400">
                      {(it as any).cost_per_unit ? pln((it as any).cost_per_unit) : <span className="inline-flex items-center justify-end gap-1 text-slate-500"><Lock size={10} />—</span>}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-amber-300/90">{it.cogs ? `−${pln(it.cogs).replace(/^-/, '')}` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Costs breakdown + summary */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Costs */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2 flex items-center gap-1.5">
              Koszty Allegro dla zamówienia
              <span className="text-slate-600 font-normal normal-case">
                ({order.exact_match_count}/{order.entries_count} dopasowane dokładnie)
              </span>
            </h4>
            {order.costs.length === 0 ? (
              <div className="rounded-lg border border-slate-800 p-4 text-center text-slate-500 text-xs">
                Brak dopasowanych pozycji billingu
              </div>
            ) : (
              <div className="rounded-lg border border-slate-800 overflow-x-auto">
                <table className="w-full min-w-[32rem] text-xs">
                  <tbody>
                    {order.costs.map(c => {
                      const n = Number(c.amount)
                      const isRefund = n > 0
                      return (
                        <tr key={c.type} className="border-t border-slate-800/60 first:border-t-0">
                          <td className="px-3 py-1.5 text-slate-300">
                            <span className="font-mono text-[10px] text-slate-500 mr-2">{c.type}</span>
                            {labels(c.type) || c.type_name}
                          </td>
                          <td className={`px-3 py-1.5 text-right tabular-nums font-medium ${isRefund ? 'text-emerald-400/90' : 'text-red-400/90'}`}>
                            {isRefund ? '+' : '−'}{pln(String(Math.abs(n)))}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Order P&L summary */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">Podsumowanie wyniku</h4>
            <div className="rounded-lg border border-slate-800 overflow-hidden text-xs">
              <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-800/60">
                <span className="text-slate-400">{isVatPayer ? 'Przychód netto' : 'Przychód brutto'}</span>
                <span className="text-white font-medium tabular-nums" title={vatMoney(order.revenue, { isVatPayer }).title}>
                  {vatMoney(order.revenue, { net: (order as any).revenue_net, isVatPayer }).text}
                </span>
              </div>
              <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-800/60">
                <span className="text-slate-400">Koszt zakupu (COGS)</span>
                <span className="text-amber-300/90 tabular-nums">−{pln(order.cogs)}</span>
              </div>
              <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-800/60">
                <span className="text-slate-400">Koszty Allegro</span>
                <span className="text-red-400/90 tabular-nums" title={vatMoney(order.costs_total, { isVatPayer }).title}>
                  {vatMoney(order.costs_total, { net: (order as any).costs_total_net, isVatPayer, sign: 'minus' }).text}
                </span>
              </div>
              <div className="flex items-center justify-between px-3 py-2 bg-slate-800/40">
                <span className="text-slate-200 font-semibold">{profitLabel(isVatPayer)}</span>
                <span className={`font-bold tabular-nums ${profitClass(order.profit_net)}`}>{pln(order.profit_net)}</span>
              </div>
              {order.margin_pct !== null && (
                <div className="flex items-center justify-between px-3 py-1.5 text-slate-500">
                  <span>Marża</span>
                  <span className="tabular-nums">{f(order.margin_pct, 2)}%</span>
                </div>
              )}
            </div>

            {/* Match-quality hint */}
            {order.entries_count > 0 && order.exact_match_count < order.entries_count && (
              <div className="mt-2 flex items-start gap-1.5 text-[11px] text-amber-500/80">
                <AlertCircle size={12} className="mt-0.5 shrink-0" />
                <span>
                  Część kosztów dopasowana heurystycznie (na podstawie oferty i daty). Po kolejnej
                  synchronizacji dokładność poprawi się dla nowych zamówień.
                </span>
              </div>
            )}
            {order.entries_count > 0 && order.exact_match_count === order.entries_count && (
              <div className="mt-2 flex items-center gap-1.5 text-[11px] text-emerald-500/80">
                <CheckCircle2 size={12} className="shrink-0" />
                Wszystkie pozycje dopasowane dokładnie (po order_id)
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Mobile card view ────────────────────────────────────────────────────────────
function OrderLineItemCard({ item, isVatPayer }: { item: OrderLineItem; isVatPayer: boolean }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
      <div className="text-slate-200 text-xs leading-tight">{item.sku_name}</div>
      <div className="text-slate-500 text-[11px] mb-2">
        {item.sku || '—'} {item.offer_id && <span className="ml-1 text-slate-600">· oferta {item.offer_id}</span>}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-[11px]">
        <div>
          <p className="text-slate-500">Ilość</p>
          <p className="text-slate-300 tabular-nums">{item.quantity}</p>
        </div>
        <div>
          <p className="text-slate-500">Cena/szt</p>
          <p className="text-slate-400 tabular-nums" title={vatMoney(item.unit_price, { isVatPayer }).title}>
            {vatMoney(item.unit_price, { net: grossToNetByRate(item.unit_price, item.vat_rate), isVatPayer }).text}
          </p>
        </div>
        <div>
          <p className="text-slate-500">{isVatPayer ? 'Przychód netto' : 'Przychód'}</p>
          <p className="text-white font-medium tabular-nums" title={vatMoney(item.revenue, { isVatPayer }).title}>
            {vatMoney(item.revenue, { net: grossToNetByRate(item.revenue, item.vat_rate), isVatPayer }).text}
          </p>
        </div>
        <div>
          <p className="text-slate-500">Koszt zak./szt</p>
          <p className="text-slate-400 tabular-nums">
            {(item as any).cost_per_unit ? pln((item as any).cost_per_unit) : <span className="inline-flex items-center gap-1 text-slate-500"><Lock size={10} />—</span>}
          </p>
        </div>
        <div>
          <p className="text-slate-500">COGS</p>
          <p className="text-amber-300/90 tabular-nums">{item.cogs ? `−${pln(item.cogs).replace(/^-/, '')}` : '—'}</p>
        </div>
      </div>
    </div>
  )
}

function OrderCard({ order, isVatPayer }: { order: RecentOrder; isVatPayer: boolean }) {
  const totalUnits = order.items.reduce((s, i) => s + i.quantity, 0)
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
      <div className="min-w-0">
        <div className="font-mono text-xs text-slate-300 truncate">{order.order_id}</div>
        <div className="text-[11px] text-slate-500">{fDate(order.bought_at)}</div>
        <div className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-400">
          <User size={10} className="text-slate-500 shrink-0" />
          <span className="truncate">{order.buyer_login || '—'}</span>
          <span className="text-slate-600">·</span>
          <span className="truncate">{order.account_name || `#${order.account_id}`}</span>
        </div>
      </div>

      <div className="mt-3 flex items-end justify-between gap-3 border-t border-slate-800 pt-3">
        <div>
          <p className="text-[11px] text-slate-500">{profitLabel(isVatPayer)}</p>
          <p className={`text-xl font-bold tabular-nums ${profitClass(order.profit_net)}`}>{pln(order.profit_net)}</p>
        </div>
        <div className="text-right">
          <p className="text-[11px] text-slate-500">Marża</p>
          <p className={`text-sm font-semibold tabular-nums ${profitClass(order.profit_net)}`}>
            {order.margin_pct !== null ? `${f(order.margin_pct, 1)}%` : '—'}
          </p>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <div>
          <p className="text-[11px] text-slate-500">{isVatPayer ? 'Przychód netto' : 'Przychód'}</p>
          <p className="text-sm font-medium text-white tabular-nums" title={vatMoney(order.revenue, { isVatPayer }).title}>
            {vatMoney(order.revenue, { net: (order as any).revenue_net, isVatPayer }).text}
          </p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500">COGS</p>
          <p className="text-sm font-medium text-amber-300/90 tabular-nums">{Number(order.cogs) > 0 ? `−${pln(order.cogs)}` : '—'}</p>
        </div>
      </div>

      <details className="group mt-3">
        <summary className="flex cursor-pointer list-none items-center justify-between rounded-md border border-slate-800 px-3 py-2 text-xs font-medium text-slate-300">
          <span>Szczegóły</span>
          <ChevronRight size={14} className="text-slate-500 transition-transform group-open:rotate-90" />
        </summary>
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-3 gap-3 text-[11px]">
            <div>
              <p className="text-slate-500">Szt</p>
              <p className="text-slate-300 tabular-nums">{totalUnits}</p>
            </div>
            <div>
              <p className="text-slate-500">Koszty Allegro</p>
              <p className="text-red-400/90 tabular-nums" title={vatMoney(order.costs_total, { isVatPayer }).title}>
                {vatMoney(order.costs_total, { net: (order as any).costs_total_net, isVatPayer, sign: 'minus' }).text}
              </p>
            </div>
            <div>
              <p className="text-slate-500">Koszt Smart</p>
              <p className="text-orange-400/80 tabular-nums" title={vatMoney(order.smart_cost, { isVatPayer }).title}>
                {vatMoney(order.smart_cost, { net: (order as any).smart_cost_net, isVatPayer, sign: 'minus' }).text}
              </p>
            </div>
          </div>

          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              <Package size={12} />
              Produkty w zamówieniu ({order.items.length})
            </h4>
            <div className="space-y-2">
              {order.items.map(item => (
                <OrderLineItemCard key={item.line_item_id} item={item} isVatPayer={isVatPayer} />
              ))}
            </div>
          </div>
        </div>
      </details>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function Orders() {
  const vault = useFinancialVault()
  const financialDisplay = useFinancialDisplayMode()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [limit, setLimit] = useState(100)
  const [smartOnly, setSmartOnly] = useState(false)
  const [displayOrders, setDisplayOrders] = useState<RecentOrder[]>([])

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ['orders-recent', limit, smartOnly],
    queryFn: () => ordersApi.recent(limit, undefined, smartOnly),
  })
  const isVatPayer = financialDisplay.showNet

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!vault.key) {
        setDisplayOrders(orders)
        return
      }
      const next: RecentOrder[] = []
      for (let orderIndex = 0; orderIndex < orders.length; orderIndex += 1) {
        if (cancelled) return
        const order = orders[orderIndex]
        let cogs = 0
        const revenueNet = Number(order.revenue_net ?? order.revenue)
        const items = []
        for (let itemIndex = 0; itemIndex < order.items.length; itemIndex += 1) {
          if (cancelled) return
          const item = order.items[itemIndex]
          const unitCost = item.sku_id == null
            ? null
            : await decryptCost(vault.key!, item.encrypted_cost)
          const unitCostForMode = unitCost == null ? null : visibleUnitCost(unitCost, item.vat_rate, isVatPayer)
          const itemCogs = unitCostForMode == null ? null : unitCostForMode * item.quantity
          if (itemCogs != null) cogs += itemCogs
          items.push({
            ...item,
            cost_per_unit: unitCostForMode == null ? undefined : String(unitCostForMode),
            cogs: itemCogs == null ? null : String(itemCogs),
          } as any)
        }
        const revenueBase = isVatPayer ? revenueNet : Number(order.revenue)
        // Allegro billing amounts are gross; the net/gross switch decides what is shown,
        // so profit never mixes a gross revenue with a net cost (see Dashboard's vatMoney).
        const costsTotalNet = grossToNet23(order.costs_total)
        const smartCostNet = grossToNet23(order.smart_cost)
        const costsTotalBase = isVatPayer ? costsTotalNet : Number(order.costs_total)
        const profit = revenueBase - cogs - costsTotalBase
        const margin = revenueBase > 0 ? (profit / revenueBase) * 100 : null
        next.push({
          ...order,
          items,
          revenue_net: String(revenueNet),
          costs_total_net: String(costsTotalNet),
          smart_cost_net: String(smartCostNet),
          cogs: String(cogs),
          profit_net: String(profit),
          margin_pct: margin == null ? null : String(margin),
        })
        if ((orderIndex + 1) % 5 === 0) await yieldToBrowser()
      }
      if (!cancelled) setDisplayOrders(next)
    }
    run().catch(() => setDisplayOrders(orders))
    return () => { cancelled = true }
  }, [isVatPayer, orders, vault.key])

  function toggle(id: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  // Totals
  const totals = displayOrders.reduce((acc, o) => ({
    revenue:     acc.revenue     + (isVatPayer ? n((o as any).revenue_net) : Number(o.revenue)),
    cogs:        acc.cogs        + Number(o.cogs),
    costs_total: acc.costs_total + (isVatPayer ? n((o as any).costs_total_net) : Number(o.costs_total)),
    smart_cost:  acc.smart_cost  + (isVatPayer ? n((o as any).smart_cost_net) : Number(o.smart_cost ?? 0)),
    profit_net:  acc.profit_net  + Number(o.profit_net),
  }), { revenue: 0, cogs: 0, costs_total: 0, smart_cost: 0, profit_net: 0 })

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Zamówienia</h2>
          <p className="text-slate-400 text-sm mt-0.5">
            {smartOnly ? 'Ostatnie zamówienia z kosztami Smart' : 'Ostatnie zamówienia'}: {displayOrders.length}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <label className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={smartOnly}
              onChange={e => setSmartOnly(e.target.checked)}
              className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-emerald-500"
            />
            <span>Tylko z kosztami Smart</span>
          </label>
          <select
            value={limit}
            onChange={e => setLimit(parseInt(e.target.value, 10))}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
          >
            <option value={50}>Ostatnie 50</option>
            <option value={100}>Ostatnie 100</option>
            <option value={200}>Ostatnie 200</option>
            <option value={500}>Ostatnie 500</option>
          </select>
        </div>
      </div>

      {/* Aggregate tiles */}
      {displayOrders.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4">
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
            <p className="text-slate-400 text-xs">{isVatPayer ? 'Przychód netto' : 'Przychód'}</p>
            <p className="text-white text-xl font-bold tabular-nums mt-1">{pln(String(totals.revenue))}</p>
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
            <p className="text-slate-400 text-xs">Koszt zakupu</p>
            <p className="text-amber-300/90 text-xl font-bold tabular-nums mt-1">−{pln(String(totals.cogs))}</p>
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
            <p className="text-slate-400 text-xs">Koszty Allegro</p>
            <p className="text-red-400/90 text-xl font-bold tabular-nums mt-1">{costPln(totals.costs_total)}</p>
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
            <p className="text-slate-400 text-xs">{profitLabel(isVatPayer)}</p>
            <p className={`text-xl font-bold tabular-nums mt-1 ${profitClass(String(totals.profit_net))}`}>
              {pln(String(totals.profit_net))}
            </p>
          </div>
        </div>
      )}

      {/* Table (desktop) */}
      <div className="hidden lg:block apos-scroll-table-dark">
        <table className="w-full min-w-[70rem] text-sm">
          <thead className="bg-slate-800/80 border-b border-slate-700/60 text-slate-400 text-xs uppercase tracking-wide">
            <tr>
              <th className="w-8"></th>
              <th className="text-left  px-3 py-2 font-semibold">Zamówienie</th>
              <th className="text-left  px-3 py-2 font-semibold">Kupujący</th>
              <th className="text-left  px-3 py-2 font-semibold">Konto</th>
              <th className="text-right px-3 py-2 font-semibold">Szt</th>
              <th className="text-right px-3 py-2 font-semibold">Przychód</th>
              <th className="text-right px-3 py-2 font-semibold">COGS</th>
              <th className="text-right px-3 py-2 font-semibold">Koszty Allegro</th>
              <th className="text-right px-3 py-2 font-semibold">Koszt Smart</th>
              <th className="text-right px-3 py-2 font-semibold">{profitLabel(isVatPayer)}</th>
              <th className="text-right px-3 py-2 font-semibold">Marża</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              [...Array(8)].map((_, i) => (
                <tr key={i} className="border-b border-slate-800 animate-pulse">
                  {[...Array(10)].map((_, j) => (
                    <td key={j} className="px-3 py-3"><div className="h-3 bg-slate-700 rounded w-3/4" /></td>
                  ))}
                </tr>
              ))
            ) : orders.length === 0 ? (
              <tr>
                <td colSpan={11} className="px-3 py-10 text-center text-slate-500">
                  Brak zamówień.
                </td>
              </tr>
            ) : displayOrders.map(o => {
              const isOpen = expanded.has(o.order_id)
              const totalUnits = o.items.reduce((s, i) => s + i.quantity, 0)
              return (
                <Fragment key={o.order_id}>
                  <tr
                    onClick={() => toggle(o.order_id)}
                    className={`border-b border-slate-800/60 cursor-pointer transition-colors
                      ${isOpen ? 'bg-slate-800/50' : 'hover:bg-slate-800/30'}`}
                  >
                    <td className="pl-3 py-2.5">
                      <ChevronRight
                        size={14}
                        className={`text-slate-500 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                      />
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="font-mono text-xs text-slate-300">{o.order_id}</div>
                      <div className="text-[11px] text-slate-500">{fDate(o.bought_at)}</div>
                    </td>
                    <td className="px-3 py-2.5 text-slate-300">
                      <div className="flex items-center gap-1.5 text-xs">
                        <User size={10} className="text-slate-500" />
                        {o.buyer_login || '—'}
                      </div>
                      {o.status && <div className="text-[10px] text-slate-500 mt-0.5">{o.status}</div>}
                    </td>
                    <td className="px-3 py-2.5 text-slate-400 text-xs">{o.account_name || `#${o.account_id}`}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-slate-300">{totalUnits}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-white font-medium" title={vatMoney(o.revenue, { isVatPayer }).title}>
                      {vatMoney(o.revenue, { net: (o as any).revenue_net, isVatPayer }).text}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-amber-300/90">{Number(o.cogs) > 0 ? `−${pln(o.cogs)}` : '—'}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-red-400/90" title={vatMoney(o.costs_total, { isVatPayer }).title}>
                      {vatMoney(o.costs_total, { net: (o as any).costs_total_net, isVatPayer, sign: 'minus' }).text}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-orange-400/80" title={vatMoney(o.smart_cost, { isVatPayer }).title}>
                      {vatMoney(o.smart_cost, { net: (o as any).smart_cost_net, isVatPayer, sign: 'minus' }).text}
                    </td>
                    <td className={`px-3 py-2.5 text-right tabular-nums font-semibold ${profitClass(o.profit_net)}`}>{pln(o.profit_net)}</td>
                    <td className={`px-3 py-2.5 text-right tabular-nums ${profitClass(o.profit_net)}`}>
                      {o.margin_pct !== null ? `${f(o.margin_pct, 1)}%` : '—'}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={11} className="p-0"><OrderDetail order={o} isVatPayer={isVatPayer} /></td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Cards (mobile) */}
      <div className="space-y-3 lg:hidden">
        {isLoading ? (
          [...Array(4)].map((_, i) => (
            <div key={i} className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4 animate-pulse space-y-3">
              <div className="h-3 bg-slate-700 rounded w-2/5" />
              <div className="h-3 bg-slate-700 rounded w-1/3" />
              <div className="h-7 bg-slate-700 rounded w-1/2" />
            </div>
          ))
        ) : orders.length === 0 ? (
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-10 text-center text-slate-500">
            Brak zamówień.
          </div>
        ) : displayOrders.map(o => (
          <OrderCard key={o.order_id} order={o} isVatPayer={isVatPayer} />
        ))}
      </div>

      <p className="text-xs text-slate-500">
        Koszty Allegro są dopasowane do zamówień poprzez <code className="text-slate-400">order_id</code> (dokładne)
        lub — dla danych historycznych — heurystycznie poprzez ofertę i datę (±30 dni, greedy closest-match).
      </p>
    </div>
  )
}
