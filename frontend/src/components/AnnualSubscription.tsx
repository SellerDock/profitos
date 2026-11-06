import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { billingApi, type SubscriptionStatus } from '../api/client'
import { supportEmail } from '../config/brand'
import { pendingSubscriptionLabel } from '../utils/subscription'

export default function AnnualSubscription({ data }: { data: SubscriptionStatus }) {
  const queryClient = useQueryClient()
  const [tier, setTier] = useState('')
  const [accepted, setAccepted] = useState(false)
  const pending = data.usage?.pending_subscription
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['billing-subscription'] })
  const request = useMutation({ mutationFn: () => billingApi.requestSubscription(tier, data.terms_version), onSuccess: refresh })
  const cancel = useMutation({ mutationFn: (id: number) => billingApi.cancelSubscription(id), onSuccess: refresh })
  const detail = (request.error as { response?: { status?: number; data?: { detail?: string } } } | null)?.response?.data?.detail
  const errors: Record<string, string> = { subscription_pending: 'Masz już zamówienie w toku.', subscription_active: 'Ten pakiet jest już aktywny lub nie jest wyższy od aktywnego.', subscription_renewed: 'Odnowienie pakietu zostało już zamówione.', 'Nieaktualna wersja regulaminu': 'Regulamin uległ zmianie. Odśwież stronę i zaakceptuj aktualną wersję.' }
  return <section className="apos-panel min-w-0 p-5 space-y-4">
    <h3 className="font-semibold text-slate-950">Zamów pakiet roczny</h3>
    {pending ? <div className="space-y-3 text-sm"><p>{pendingSubscriptionLabel(pending)} – {data.pricing.find(item => item.code === pending.tier_code)?.label ?? pending.tier_code}</p>{pending.status === 'pending_invoice' && <button className="apos-button" disabled={cancel.isPending} onClick={() => cancel.mutate(pending.id)}>Anuluj zamówienie</button>}{cancel.isError && <p className="text-red-600">Nie udało się anulować zamówienia.</p>}</div> : <>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">{data.pricing.filter(item => item.billing_period === 'year' && !item.is_custom).map(item => <label key={item.code} className="min-w-0 cursor-pointer rounded border border-slate-200 p-3 text-sm"><input type="radio" name="annual-tier" checked={tier === item.code} onChange={() => setTier(item.code)} /> <span className="font-semibold">{item.label}</span><span className="mt-1 block">{item.price_pln.toLocaleString('pl-PL')} zł netto / rok</span></label>)}</div>
      <p className="break-words text-sm text-slate-600">Powyżej 25 000 – napisz do nas{supportEmail() && <>: <a className="text-finance-blue underline" href={`mailto:${supportEmail()}`}>{supportEmail()}</a></>}</p>
      <label className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>Akceptuję <Link className="text-finance-blue underline" to="/terms">regulamin</Link>.</span></label>
      <button className="apos-button-primary" disabled={!tier || !accepted || request.isPending} onClick={() => request.mutate()}>Zamów pakiet – faktura z terminem 7 dni</button>
      {request.isError && <p className="text-sm text-red-600">{detail === 'billing_profile_incomplete' ? <>Uzupełnij <Link className="underline" to="/settings?tab=billing">dane do faktury</Link> przed zamówieniem.</> : errors[detail ?? ''] ?? 'Nie udało się zamówić pakietu. Sprawdź wybrany pakiet i spróbuj ponownie.'}</p>}
    </>}
  </section>
}
