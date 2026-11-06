import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Trash2, X } from 'lucide-react'
import { adminApi, type AdminTenant } from '../../api/client'

function monthLabel(value: string) {
  return new Intl.DateTimeFormat('pl-PL', { month: 'short', year: 'numeric' }).format(new Date(`${value}T00:00:00`))
}

export default function AdminTenants() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['admin-tenants'], queryFn: adminApi.tenants })
  const [deleteTarget, setDeleteTarget] = useState<AdminTenant | null>(null)
  const [deleteSlug, setDeleteSlug] = useState('')
  const [deleteConfirmed, setDeleteConfirmed] = useState(false)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  async function setActive(id: number, active: boolean) {
    if (active) await adminApi.reactivateTenant(id)
    else await adminApi.deactivateTenant(id)
    await queryClient.invalidateQueries({ queryKey: ['admin-tenants'] })
  }

  function openDelete(tenant: AdminTenant) {
    setDeleteTarget(tenant)
    setDeleteSlug('')
    setDeleteConfirmed(false)
    setDeleteError(null)
  }

  async function hardDelete() {
    if (!deleteTarget || deleteSlug !== deleteTarget.slug || !deleteConfirmed || deleteBusy) return
    setDeleteBusy(true)
    setDeleteError(null)
    try {
      await adminApi.hardDeleteTenant(deleteTarget.id, deleteSlug)
      setDeleteTarget(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-tenants'] })
    } catch (error: any) {
      setDeleteError(error?.response?.data?.detail || 'Nie udało się usunąć konta.')
    } finally {
      setDeleteBusy(false)
    }
  }

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-white">Konta firmowe</h2>
      <div className="overflow-x-auto rounded border border-slate-700">
        <table className="min-w-full divide-y divide-slate-700 text-sm">
          <thead className="bg-slate-800 text-left text-xs uppercase text-slate-400">
            <tr>
              <th className="px-3 py-2">Nazwa</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Schemat</th>
              <th className="px-3 py-2">Pula / pakiet</th>
              <th className="px-3 py-2">Użytkownicy</th>
              <th className="px-3 py-2">Konta Allegro</th>
              <th className="px-3 py-2">SKU</th>
              <th className="px-3 py-2">Zamówienia</th>
              <th className="px-3 py-2">Aktywność</th>
              <th className="px-3 py-2">Akcje</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900 text-slate-200">
            {isLoading && <tr><td className="px-3 py-4" colSpan={10}>Ładowanie...</td></tr>}
            {!isLoading && data?.items.length === 0 && <tr><td className="px-3 py-4" colSpan={10}>Brak kont.</td></tr>}
            {data?.items.map(tenant => (
              <tr key={tenant.id}>
                <td className="px-3 py-2">
                  <div className="font-medium text-white">{tenant.name}</div>
                  <div className="text-xs text-slate-500">{tenant.slug}</div>
                </td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-1 text-xs ${tenant.is_active ? 'bg-emerald-500/15 text-emerald-200' : 'bg-red-500/15 text-red-200'}`}>
                    {tenant.is_active ? 'aktywny' : 'nieaktywny'}
                  </span>
                </td>
                <td className="px-3 py-2">{tenant.billing_scheme === 'pool_v2' ? 'Pula' : tenant.billing_scheme === 'legacy_trial' ? 'Trial' : '–'}</td>
                <td className="px-3 py-2">{tenant.billing_scheme === 'pool_v2' ? <><div>Wykorzystano: {tenant.pool_used ?? '–'}, pozostało: {tenant.pool_remaining ?? '–'}</div><div>{tenant.active_tier ?? 'Darmowy'}{tenant.period_end ? ` do ${tenant.period_end}` : ''}</div></> : '–'}</td>
                <td className="px-3 py-2">{tenant.users_count}</td>
                <td className="px-3 py-2">{tenant.accounts_count}</td>
                <td className="px-3 py-2">{tenant.sku_count}</td>
                <td className="px-3 py-2">
                  <div className="font-medium text-white">{tenant.current_month_orders}</div>
                  <div className="text-[11px] text-slate-500">{monthLabel(tenant.current_month)}</div>
                  <div className="mt-1 text-slate-300">{tenant.previous_month_orders}</div>
                  <div className="text-[11px] text-slate-500">{monthLabel(tenant.previous_month)}</div>
                </td>
                <td className="px-3 py-2">{tenant.last_activity_at?.slice(0, 16).replace('T', ' ') || '–'}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => void setActive(tenant.id, !tenant.is_active)}
                      className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
                    >
                      {tenant.is_active ? 'Dezaktywuj' : 'Reaktywuj'}
                    </button>
                    {tenant.id !== 1 && (
                      <button
                        onClick={() => openDelete(tenant)}
                        className="inline-flex items-center gap-1 rounded border border-red-500/50 px-2 py-1 text-xs text-red-200 hover:bg-red-500/10"
                      >
                        <Trash2 size={13} />
                        Usuń trwale
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <div className="w-full max-w-lg rounded border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-white">Usuń trwale konto</h3>
                <p className="mt-1 text-sm leading-6 text-slate-400">
                  Ta operacja usuwa konto klienta i dane operacyjne z bazy. Nie da się jej cofnąć
                  bez odtwarzania backupu.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
                title="Zamknij"
              >
                <X size={18} />
              </button>
            </div>

            <div className="space-y-4">
              <div className="rounded border border-slate-700 bg-slate-950 p-3 text-sm text-slate-300">
                <div className="font-medium text-white">{deleteTarget.name}</div>
                <div className="mt-1 font-mono text-xs text-slate-500">{deleteTarget.slug}</div>
              </div>
              <label className="block">
                <span className="mb-1 block text-sm text-slate-300">Wpisz slug konta</span>
                <input
                  value={deleteSlug}
                  onChange={event => setDeleteSlug(event.target.value)}
                  className="w-full rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-red-400"
                  autoFocus
                />
              </label>
              <label className="flex cursor-pointer items-start gap-3 text-sm leading-6 text-slate-300">
                <input
                  type="checkbox"
                  checked={deleteConfirmed}
                  onChange={event => setDeleteConfirmed(event.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-slate-600 text-red-500 focus:ring-red-500"
                />
                <span>Rozumiem, że dane zostaną nieodwracalnie usunięte.</span>
              </label>
              {deleteError && <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">{deleteError}</p>}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDeleteTarget(null)}
                  className="rounded border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
                >
                  Anuluj
                </button>
                <button
                  type="button"
                  onClick={() => void hardDelete()}
                  disabled={deleteBusy || deleteSlug !== deleteTarget.slug || !deleteConfirmed}
                  className="rounded bg-red-600 px-3 py-2 text-sm font-semibold text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {deleteBusy ? 'Usuwanie...' : 'Usuń trwale'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
