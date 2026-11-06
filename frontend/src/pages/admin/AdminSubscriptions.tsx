import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminApi, type AdminSubscription } from '../../api/client'

const statuses: Record<string, string> = { pending_invoice: 'Czeka na fakturę', invoiced: 'Czeka na płatność', active: 'Aktywny', expired: 'Wygasły', cancelled: 'Anulowany' }
function today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
export default function AdminSubscriptions() {
  const [status, setStatus] = useState('')
  const [dates, setDates] = useState<Record<number, string>>({})
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['admin-subscriptions', status], queryFn: () => adminApi.subscriptions(status) })
  const action = useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => client.invalidateQueries({ queryKey: ['admin-subscriptions'] }) })
  const detail = (action.error as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail
  const button = 'rounded border border-slate-600 px-2 py-1 text-xs hover:bg-slate-800 disabled:opacity-50'
  function manual(row: AdminSubscription) { const number = window.prompt('Podaj numer faktury', row.invoice_number ?? ''); if (number?.trim()) action.mutate(() => adminApi.manualSubscriptionInvoice(row.id, number.trim())) }
  return <section className="min-w-0 space-y-4"><h2 className="text-lg font-semibold text-white">Zamówienia pakietów</h2>
    <label className="text-sm text-slate-300">Status <select value={status} onChange={e => setStatus(e.target.value)} className="ml-2 rounded border border-slate-600 bg-slate-900 p-2"> <option value="">Wszystkie</option>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    {query.isError && <p className="text-red-300">Nie udało się pobrać zamówień.</p>}
    {action.isError && <p className="break-words rounded bg-red-950 p-3 text-sm text-red-200">{typeof detail === 'string' ? (detail === 'billing_profile_incomplete' ? 'Niekompletne dane do faktury.' : detail) : 'Nie udało się wykonać operacji.'}</p>}
    <div className="overflow-x-auto rounded border border-slate-700"><table className="min-w-[55rem] w-full text-left text-sm text-slate-200"><thead className="bg-slate-800 text-xs uppercase text-slate-400"><tr>{['Konto', 'Pakiet', 'Status', 'Faktura', 'Zamówiono', 'Akcje'].map(v => <th key={v} className="p-3">{v}</th>)}</tr></thead><tbody className="divide-y divide-slate-800 bg-slate-900">
      {query.isLoading && <tr><td colSpan={6} className="p-3">Ładowanie...</td></tr>}{query.data?.items.length === 0 && <tr><td colSpan={6} className="p-3">Brak zamówień.</td></tr>}
      {query.data?.items.map(row => <tr key={row.id}><td className="p-3">{row.company_name || `Konto ${row.tenant_id}`}<div className="text-xs text-slate-400">{row.nip}</div></td><td className="p-3">{row.tier_code}<div>{row.price_pln} zł netto</div></td><td className="p-3">{statuses[row.status] ?? row.status}</td><td className="p-3">{row.invoice_number || '–'}</td><td className="p-3">{row.requested_at?.slice(0, 10) || '–'}</td><td className="p-3"><div className="flex flex-wrap items-center gap-2">
        {row.status === 'pending_invoice' && <><button disabled={action.isPending} className={button} onClick={() => { if (window.confirm('Wystawić fakturę w iFirmie?')) action.mutate(() => adminApi.invoiceSubscription(row.id)) }}>Wystaw fakturę w iFirmie</button><button disabled={action.isPending} className={button} onClick={() => manual(row)}>Wpisz numer ręcznie</button></>}
        {row.status === 'invoiced' && <>{!row.invoice_number && <button disabled={action.isPending} className={button} onClick={() => manual(row)}>Wpisz numer ręcznie</button>}<input aria-label="Data płatności" type="date" value={dates[row.id] ?? today()} onChange={e => setDates({ ...dates, [row.id]: e.target.value })} className="rounded border border-slate-600 bg-slate-950 p-1" /><button disabled={action.isPending || dates[row.id] === ''} className={button} onClick={() => action.mutate(() => adminApi.markSubscriptionPaid(row.id, dates[row.id] ?? today()))}>Oznacz opłacone</button></>}
        {(row.status === 'pending_invoice' || row.status === 'invoiced') && <button disabled={action.isPending} className={button} onClick={() => { if (window.confirm('Anulować zamówienie?')) action.mutate(() => adminApi.cancelSubscription(row.id)) }}>Anuluj</button>}
      </div></td></tr>)}
    </tbody></table></div>
  </section>
}
