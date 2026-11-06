import { FormEvent, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, X } from 'lucide-react'
import { adminApi, type AdminWaitlistEntry } from '../../api/client'

type Status = 'pending' | 'approved' | 'rejected'

export default function AdminWaitlist() {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<Status>('pending')
  const [approving, setApproving] = useState<AdminWaitlistEntry | null>(null)
  const [tenantName, setTenantName] = useState('')
  const [activationUrl, setActivationUrl] = useState('')
  const [activationEmailSent, setActivationEmailSent] = useState(false)
  const [activationEmailError, setActivationEmailError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: ['admin-waitlist', status],
    queryFn: () => adminApi.waitlist(status),
  })

  function openApprove(entry: AdminWaitlistEntry) {
    setApproving(entry)
    setTenantName(entry.company || entry.email.split('@')[0])
    setActivationUrl('')
    setActivationEmailSent(false)
    setActivationEmailError(null)
    setError(null)
  }

  async function approve(event: FormEvent) {
    event.preventDefault()
    if (!approving || !tenantName.trim()) return
    setBusy(true)
    setError(null)
    try {
      const result = await adminApi.approveWaitlist(approving.id, { tenant_name: tenantName.trim() })
      setActivationUrl(result.activation_url)
      setActivationEmailSent(result.activation_email_sent)
      setActivationEmailError(result.activation_email_error || null)
      await queryClient.invalidateQueries({ queryKey: ['admin-waitlist'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-tenants'] })
    } catch {
      setError('Nie udało się zatwierdzić zgłoszenia.')
    } finally {
      setBusy(false)
    }
  }

  async function reject(entry: AdminWaitlistEntry) {
    const reason = window.prompt('Powód odrzucenia')
    if (!reason) return
    await adminApi.rejectWaitlist(entry.id, { reason })
    await queryClient.invalidateQueries({ queryKey: ['admin-waitlist'] })
  }

  async function copyUrl() {
    await navigator.clipboard.writeText(activationUrl)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-white">Zgłoszenia kont</h2>
        <select
          value={status}
          onChange={event => setStatus(event.target.value as Status)}
          className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
        >
          <option value="pending">Oczekujące</option>
          <option value="approved">Zatwierdzone</option>
          <option value="rejected">Odrzucone</option>
        </select>
      </div>
      <div className="overflow-x-auto rounded border border-slate-700">
        <table className="min-w-full divide-y divide-slate-700 text-sm">
          <thead className="bg-slate-800 text-left text-xs uppercase text-slate-400">
            <tr>
              <th className="px-3 py-2">Email</th>
              <th className="px-3 py-2">Firma</th>
              <th className="px-3 py-2">Zamówienia</th>
              <th className="px-3 py-2">Utworzono</th>
              <th className="px-3 py-2">Akcje</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900 text-slate-200">
            {isLoading && <tr><td className="px-3 py-4" colSpan={5}>Ładowanie...</td></tr>}
            {!isLoading && data?.items.length === 0 && <tr><td className="px-3 py-4" colSpan={5}>Brak zgłoszeń.</td></tr>}
            {data?.items.map(entry => (
              <tr key={entry.id}>
                <td className="px-3 py-2 font-medium text-white">{entry.email}</td>
                <td className="px-3 py-2">{entry.company || '—'}</td>
                <td className="px-3 py-2">{entry.monthly_orders || '—'}</td>
                <td className="px-3 py-2">{entry.created_at?.slice(0, 10) || '—'}</td>
                <td className="px-3 py-2">
                  {entry.status === 'pending' ? (
                    <div className="flex gap-2">
                      <button onClick={() => openApprove(entry)} className="rounded bg-emerald-600 px-2 py-1 text-xs text-white hover:bg-emerald-500">Zatwierdź</button>
                      <button onClick={() => void reject(entry)} className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800">Odrzuć</button>
                    </div>
                  ) : entry.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {approving && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4">
          <div className="w-full max-w-lg rounded-lg border border-slate-700 bg-slate-900 p-5 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-white">Zatwierdź zgłoszenie</h3>
              <button onClick={() => setApproving(null)} className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"><X size={18} /></button>
            </div>
            {activationUrl ? (
              <div className="space-y-3">
                <p className="text-sm text-emerald-200">Dostęp został utworzony. To jedyny moment, kiedy widzisz raw token.</p>
                {activationEmailSent ? (
                  <p className="rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100">
                    Mail aktywacyjny został wysłany do użytkownika. Link poniżej zostaje jako kopia awaryjna.
                  </p>
                ) : (
                  <p className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                    Mail nie został wysłany automatycznie. Skopiuj link i wyślij go użytkownikowi ręcznie.
                    {activationEmailError && <span className="mt-1 block text-amber-200/80">Powód: {activationEmailError}</span>}
                  </p>
                )}
                <div className="rounded bg-slate-950 p-3 font-mono text-xs text-slate-100 break-all">{activationUrl}</div>
                <button onClick={() => void copyUrl()} className="inline-flex items-center gap-2 rounded bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-500">
                  {copied ? <Check size={16} /> : <Copy size={16} />}
                  {copied ? 'Skopiowano' : 'Kopiuj link'}
                </button>
              </div>
            ) : (
              <form onSubmit={approve} className="space-y-4">
                <p className="text-sm text-slate-300">Email: <span className="text-white">{approving.email}</span></p>
                <label className="block">
                  <span className="mb-1 block text-sm text-slate-300">Nazwa konta firmowego</span>
                  <input
                    required
                    value={tenantName}
                    onChange={event => setTenantName(event.target.value)}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-indigo-500"
                  />
                </label>
                {error && <p className="text-sm text-red-300">{error}</p>}
                <button disabled={busy} className="rounded bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60">
                  {busy ? 'Tworzenie...' : 'Utwórz konto i link'}
                </button>
              </form>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
