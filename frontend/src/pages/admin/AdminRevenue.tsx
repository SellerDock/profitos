import { useQuery } from '@tanstack/react-query'
import { Coins, ReceiptText } from 'lucide-react'
import { adminApi, type AdminRevenueSummary, type AdminRevenueTenant } from '../../api/client'

function money(value: string | number) {
  return Number(value).toLocaleString('pl-PL', {
    style: 'currency',
    currency: 'PLN',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function monthLabel(value: string) {
  return new Intl.DateTimeFormat('pl-PL', { month: 'long', year: 'numeric' }).format(new Date(`${value}T00:00:00`))
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat('pl-PL', { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00`))
}

function SummaryCard({
  title,
  summary,
  currentMonth,
  previousMonth,
}: {
  title: string
  summary: AdminRevenueSummary
  currentMonth: string
  previousMonth: string
}) {
  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
        <Coins size={16} className="text-emerald-300" />
        {title}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">{monthLabel(currentMonth)}</div>
          <div className="mt-1 text-2xl font-bold text-white">{money(summary.current_month_estimate_net)}</div>
          <div className="mt-1 text-xs text-slate-400">{summary.current_month_orders} zamówień</div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">{monthLabel(previousMonth)}</div>
          <div className="mt-1 text-2xl font-bold text-white">{money(summary.previous_month_estimate_net)}</div>
          <div className="mt-1 text-xs text-slate-400">{summary.previous_month_orders} zamówień</div>
        </div>
      </div>
      <div className="mt-3 text-xs text-slate-500">
        {summary.customers_count} kont, {summary.billable_customers_count} po trialu lub z naliczeniem w okresie.
      </div>
    </div>
  )
}

function RevenueCell({
  tenant,
  month,
}: {
  tenant: AdminRevenueTenant
  month: 'current' | 'previous'
}) {
  const amount = month === 'current' ? tenant.current_month_estimate_net : tenant.previous_month_estimate_net
  const orders = month === 'current' ? tenant.current_month_orders : tenant.previous_month_orders
  const tier = month === 'current' ? tenant.current_month_tier : tenant.previous_month_tier
  const billableDays = month === 'current' ? tenant.current_month_billable_days : tenant.previous_month_billable_days
  const monthDays = month === 'current' ? tenant.current_month_days : tenant.previous_month_days
  return (
    <div>
      <div className="font-semibold text-white">{money(amount)}</div>
      <div className="mt-1 text-xs text-slate-400">{orders} zam. · {tier.label} · {tier.is_custom ? 'wycena indywidualna' : `${tier.price_pln} zł netto${tier.billing_period === 'year' ? ' / rok' : ''}`}</div>
      <div className="text-xs text-slate-500">{billableDays}/{monthDays} dni naliczanych</div>
    </div>
  )
}

export default function AdminRevenue() {
  const { data, isLoading } = useQuery({ queryKey: ['admin-revenue'], queryFn: adminApi.revenue })

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-white">Przychody orientacyjne</h2>
        <p className="mt-1 text-sm text-slate-400">
          Szacunek netto według cennika, liczby zamówień w miesiącu i końca 30-dniowego triala.
          Konto operatora nie jest liczone jako klient.
        </p>
      </div>

      {isLoading && <div className="rounded border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300">Ładowanie...</div>}

      {data && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <SummaryCard
              title="Wszyscy klienci"
              summary={data.totals.all_customers}
              currentMonth={data.current_month}
              previousMonth={data.previous_month}
            />
            <SummaryCard
              title="Klienci aktywni"
              summary={data.totals.active_customers}
              currentMonth={data.current_month}
              previousMonth={data.previous_month}
            />
          </div>

          <div className="rounded border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
            To jest prognoza operacyjna, nie księgowość. Klient aktywny to konto, które po trialu zaakceptowało
            regulamin i kliknęło przejście na pakiet płatny.
          </div>

          <div className="overflow-x-auto rounded border border-slate-700">
            <table className="min-w-full divide-y divide-slate-700 text-sm">
              <thead className="bg-slate-800 text-left text-xs uppercase text-slate-400">
                <tr>
                  <th className="px-3 py-2">Konto</th>
                  <th className="px-3 py-2">Trial</th>
                  <th className="px-3 py-2">FV</th>
                  <th className="px-3 py-2">{monthLabel(data.current_month)}</th>
                  <th className="px-3 py-2">{monthLabel(data.previous_month)}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-900 text-slate-200">
                {data.items.length === 0 && (
                  <tr><td className="px-3 py-4 text-slate-400" colSpan={5}>Brak klientów poza kontem operatora.</td></tr>
                )}
                {data.items.map(tenant => (
                  <tr key={tenant.tenant_id}>
                    <td className="px-3 py-3">
                      <div className="font-medium text-white">{tenant.name}</div>
                      <div className="text-xs text-slate-500">{tenant.slug}</div>
                      {!tenant.is_active && <div className="mt-1 text-xs text-red-300">konto nieaktywne</div>}
                    </td>
                    <td className="px-3 py-3">
                      <div className="text-white">do {dateLabel(tenant.trial_ends_at)}</div>
                      <div className={tenant.trial_active ? 'text-xs text-emerald-300' : 'text-xs text-slate-500'}>
                        {tenant.trial_active ? 'trial aktywny' : 'po trialu'}
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs ${tenant.paid_plan_accepted ? 'bg-emerald-500/15 text-emerald-200' : 'bg-slate-700 text-slate-300'}`}>
                        <ReceiptText size={13} />
                        {tenant.paid_plan_accepted ? 'aktywny' : 'bez akceptacji'}
                      </span>
                    </td>
                    <td className="px-3 py-3"><RevenueCell tenant={tenant} month="current" /></td>
                    <td className="px-3 py-3"><RevenueCell tenant={tenant} month="previous" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
