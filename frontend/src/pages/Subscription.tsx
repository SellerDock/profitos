import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, CreditCard, FileText, Lock } from 'lucide-react'
import { billingApi } from '../api/client'

function monthLabel(iso: string): string {
  return new Date(iso).toLocaleDateString('pl-PL', { month: 'long', year: 'numeric' })
}

function pln(value: number): string {
  return value.toLocaleString('pl-PL', { style: 'currency', currency: 'PLN', maximumFractionDigits: 0 })
}

export default function Subscription() {
  const queryClient = useQueryClient()
  const [termsAccepted, setTermsAccepted] = useState(false)
  const { data, isLoading, error } = useQuery({
    queryKey: ['billing-subscription'],
    queryFn: billingApi.subscription,
  })
  const acceptPlan = useMutation({
    mutationFn: () => billingApi.acceptPaidPlan({
      terms_accepted: termsAccepted,
      terms_version: data?.terms_version ?? '',
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['billing-subscription'] }),
  })

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Rozliczenia</p>
        <h2 className="mt-1 text-2xl font-bold text-slate-950">Plan i faktury</h2>
      </div>

      {isLoading && <div className="apos-panel p-5 text-sm text-slate-500">Ładowanie rozliczeń...</div>}
      {error && <div className="apos-panel p-5 text-sm text-red-500">Nie udało się pobrać rozliczeń.</div>}

      {data && (
        <>
          <section className="grid gap-4 md:grid-cols-3">
            <div className="apos-panel p-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</p>
              <div className="mt-3 flex items-center gap-2">
                {data.trial_active ? <CheckCircle2 size={18} className="text-emerald-500" /> : <CreditCard size={18} className="text-finance-blue" />}
                <p className="text-lg font-semibold text-slate-950">
                  {data.trial_active ? 'Okres próbny' : data.paid_plan_accepted ? data.current_tier.label : 'Wymagana decyzja'}
                </p>
              </div>
              <p className="mt-2 text-sm text-slate-500">
                {data.trial_active
                  ? `Trial trwa do ${new Date(data.trial_ends_at).toLocaleDateString('pl-PL')}.`
                  : data.paid_plan_accepted
                    ? `Aktualny próg: ${pln(data.current_tier.price_pln)} / miesiąc.`
                    : 'Zaakceptuj regulamin, żeby kontynuować synchronizację po trialu.'}
              </p>
            </div>

            <div className="apos-panel p-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Bieżący miesiąc</p>
              <p className="mt-3 text-3xl font-bold text-slate-950">{data.current_month_orders}</p>
              <p className="mt-1 text-sm text-slate-500">zamówień · {monthLabel(data.current_month)}</p>
            </div>

            <div className="apos-panel p-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Poprzedni miesiąc</p>
              <p className="mt-3 text-3xl font-bold text-slate-950">{data.previous_month_orders}</p>
              <p className="mt-1 text-sm text-slate-500">zamówień · {monthLabel(data.previous_month)}</p>
            </div>
          </section>

          <section className="apos-panel p-5">
            <h3 className="mb-3 flex items-center gap-2 font-semibold text-slate-950">
              {data.paid_plan_accepted ? <CheckCircle2 size={16} className="text-emerald-500" /> : <AlertTriangle size={16} className="text-amber-500" />}
              Pakiet płatny po trialu
            </h3>
            {data.paid_plan_accepted ? (
              <p className="text-sm leading-6 text-slate-600">
                Pakiet płatny jest aktywny. Nowe synchronizacje Allegro pozostają włączone po zakończeniu triala,
                a rozliczenie liczymy według cennika i liczby zamówień.
              </p>
            ) : (
              <div className="space-y-4">
                <p className="text-sm leading-6 text-slate-600">
                  Możesz zaakceptować pakiet już teraz. Opłaty naliczamy dopiero po zakończeniu triala,
                  zgodnie z cennikiem netto widocznym niżej.
                </p>
                {data.imports_paused && (
                  <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    Trial już się zakończył, więc nowe synchronizacje Allegro są wstrzymane do czasu akceptacji pakietu płatnego.
                  </div>
                )}
                <label className="flex cursor-pointer items-start gap-3 text-sm leading-6 text-slate-700">
                  <input
                    type="checkbox"
                    checked={termsAccepted}
                    onChange={event => setTermsAccepted(event.target.checked)}
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-finance-blue focus:ring-finance-blue"
                  />
                  <span>
                    Akceptuję <Link to="/terms" className="font-medium text-finance-blue hover:underline">regulamin ProfitOS.pl</Link>
                    {' '}i przechodzę na pakiet płatny po zakończeniu triala.
                  </span>
                </label>
                <button
                  type="button"
                  onClick={() => acceptPlan.mutate()}
                  disabled={!termsAccepted || acceptPlan.isPending}
                  className="apos-button-primary"
                >
                  {acceptPlan.isPending ? 'Zapisywanie...' : 'Przechodzę na pakiet płatny'}
                </button>
                {acceptPlan.isError && <p className="text-sm text-red-500">Nie udało się zapisać akceptacji. Spróbuj ponownie.</p>}
              </div>
            )}
          </section>

          <section className="apos-panel p-5">
            <h3 className="mb-4 flex items-center gap-2 font-semibold text-slate-950">
              <CreditCard size={16} />
              Cennik
            </h3>
            <div className="grid gap-3 md:grid-cols-5">
              {data.pricing.map(tier => (
                <div
                  key={tier.code}
                  className={`rounded-lg border p-4 ${
                    tier.code === data.current_tier.code
                      ? 'border-finance-blue bg-blue-50'
                      : 'border-slate-200 bg-white'
                  }`}
                >
                  <p className="text-sm font-semibold text-slate-950">{tier.label}</p>
                  <p className="mt-3 text-2xl font-bold text-slate-950">{pln(tier.price_pln)}</p>
                  <p className="mt-1 text-xs text-slate-500">miesięcznie</p>
                </div>
              ))}
            </div>
            <p className="mt-4 flex items-center gap-2 text-xs text-slate-500">
              <Lock size={13} />
              Po okresie próbnym rozliczenie będzie liczone według liczby zamówień z poprzedniego miesiąca.
            </p>
          </section>

          <section className="apos-panel p-5">
            <h3 className="mb-4 flex items-center gap-2 font-semibold text-slate-950">
              <FileText size={16} />
              Faktury
            </h3>
            {data.invoices.length === 0 ? (
              <p className="text-sm text-slate-500">Nie ma jeszcze wystawionych faktur.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[42rem] text-sm">
                  <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="py-2">Numer</th>
                      <th className="py-2">Okres</th>
                      <th className="py-2">Kwota</th>
                      <th className="py-2">Status</th>
                      <th className="py-2 text-right">Plik</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.invoices.map(invoice => (
                      <tr key={invoice.id} className="border-t border-slate-200">
                        <td className="py-3 font-medium text-slate-950">{invoice.number}</td>
                        <td className="py-3 text-slate-600">{monthLabel(invoice.period_month)}</td>
                        <td className="py-3 text-slate-600">{invoice.amount_gross} {invoice.currency}</td>
                        <td className="py-3 text-slate-600">{invoice.status}</td>
                        <td className="py-3 text-right">
                          {invoice.pdf_url ? (
                            <a className="apos-button" href={invoice.pdf_url} target="_blank" rel="noopener">Pobierz</a>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
